#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Isolated synthetic ABBA comparison. Does not contact or change the live API."""
import argparse
import contextlib
import hashlib
import io
import json
from pathlib import Path
import statistics
import sys
import time
import wave


CASES = {
    "baseline": {},
    "non_streaming_true": {"non_streaming_mode": True},
    "subtalker_greedy": {"subtalker_dosample": False},
    "predictor_hidden_off": {"predictor_hidden_states": False},
    "combo": {"non_streaming_mode": True, "subtalker_dosample": False,
              "predictor_hidden_states": False},
}
TEXTS = {
    "short": "我在这里，慢慢来就好。",
    "medium": "先休息一下吧。我在这里，慢慢来就好。",
    "long": "今天的事情已经整理好了。先休息一下吧，我会把重点记清楚，等你回来以后，再陪你一步一步完成。",
}


@contextlib.contextmanager
def temporary_method(obj, name, replacement):
    """Restore the original instance/class lookup even after cancellation."""
    had_own = name in vars(obj)
    previous_own = vars(obj).get(name)
    setattr(obj, name, replacement)
    try:
        yield
    finally:
        if had_own:
            setattr(obj, name, previous_own)
        else:
            delattr(obj, name)


@contextlib.contextmanager
def instrument(engine, options, synchronize):
    """Coarse GPU boundaries; predictor subcalls use CPU time without extra syncs."""
    wrapper = engine.model
    core = wrapper.model
    predictor = core.talker.code_predictor
    stats = {"codec_seconds": 0.0, "decode_seconds": 0.0,
             "tokenize_seconds": 0.0, "predictor_calls": 0,
             "predictor_host_seconds": 0.0, "predictor_hidden_states": []}

    def timed(original, field, sync):
        def call(*args, **kwargs):
            if sync:
                synchronize()
            start = time.perf_counter()
            try:
                return original(*args, **kwargs)
            finally:
                if sync:
                    synchronize()
                stats[field] += time.perf_counter() - start
        return call

    original_custom = wrapper.generate_custom_voice
    def custom(*args, **kwargs):
        for key in ("non_streaming_mode", "subtalker_dosample"):
            if key in options:
                kwargs[key] = options[key]
        return original_custom(*args, **kwargs)

    original_predictor = predictor.generate
    def predict(*args, **kwargs):
        if "predictor_hidden_states" in options:
            kwargs["output_hidden_states"] = options["predictor_hidden_states"]
        stats["predictor_calls"] += 1
        hidden = kwargs.get("output_hidden_states")
        if hidden not in stats["predictor_hidden_states"]:
            stats["predictor_hidden_states"].append(hidden)
        start = time.perf_counter()
        try:
            return original_predictor(*args, **kwargs)
        finally:
            stats["predictor_host_seconds"] += time.perf_counter() - start

    with contextlib.ExitStack() as stack:
        for obj, name, method in (
            (wrapper, "generate_custom_voice", custom),
            (core, "generate", timed(core.generate, "codec_seconds", True)),
            (core.speech_tokenizer, "decode", timed(core.speech_tokenizer.decode, "decode_seconds", True)),
            (wrapper, "_tokenize_texts", timed(wrapper._tokenize_texts, "tokenize_seconds", False)),
            (predictor, "generate", predict),
        ):
            stack.enter_context(temporary_method(obj, name, method))
        yield stats


def describe_module(module):
    parameter = next(module.parameters())
    return {"device": str(parameter.device), "dtype": str(parameter.dtype),
            "attention": getattr(module.config, "_attn_implementation", None),
            "use_cache": getattr(module.config, "use_cache", None)}


def summarize(rows):
    result = {}
    for candidate in CASES:
        selected = [row for row in rows if not row["warmup"] and row["case"] == candidate]
        if not selected:
            continue
        durations = [row["wall_seconds"] for row in selected]
        rtfs = [row["rtf"] for row in selected]
        result[candidate] = {"n": len(selected), "median_wall_seconds": statistics.median(durations),
            "min_wall_seconds": min(durations), "max_wall_seconds": max(durations),
            "median_rtf": statistics.median(rtfs),
            "distinct_audio_hashes": len({row["audio_sha256"] for row in selected})}
    pairs = {}
    for candidate in CASES:
        if candidate == "baseline":
            continue
        base = [row["wall_seconds"] for row in rows if not row["warmup"] and row["comparison"] == candidate and row["case"] == "baseline"]
        trial = [row["wall_seconds"] for row in rows if not row["warmup"] and row["case"] == candidate]
        if base and trial:
            a, b = statistics.median(base), statistics.median(trial)
            pairs[candidate] = {"baseline_median_seconds": a, "candidate_median_seconds": b,
                                "candidate_over_baseline": b / a, "speedup": a / b}
    return {"cases": result, "paired": pairs}


def comparison_sequence(candidate, round_index):
    return (("baseline", candidate, candidate, "baseline") if round_index % 2 == 0
            else (candidate, "baseline", "baseline", candidate))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--deps", action="append", default=[], type=Path)
    parser.add_argument("--styles", type=Path, default=Path(__file__).parent / "styles.json")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--voice", choices=["phoenix-soft", "phoenix-drowsy", "phoenix-focused"], default="phoenix-soft")
    parser.add_argument("--text-case", choices=list(TEXTS), default="medium")
    parser.add_argument("--rounds", type=int, choices=range(1, 6), default=1,
                        help="ABBA rounds per candidate; one round gives two measured candidate runs")
    parser.add_argument("--candidates", nargs="+", choices=[key for key in CASES if key != "baseline"],
                        default=[key for key in CASES if key != "baseline"])
    parser.add_argument("--profile-kernels", action="store_true", help="One extra diagnostic baseline; excluded from comparisons")
    args = parser.parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    output = args.out.resolve()
    if output == repo_root or repo_root in output.parents:
        parser.error("Write private benchmark output outside the public repository")
    if (output / "report.json").exists():
        parser.error("Use a fresh output directory; existing benchmark reports are preserved")
    output.mkdir(parents=True, exist_ok=True)
    samples = output / "samples"
    samples.mkdir(exist_ok=True)
    for directory in reversed(args.deps):
        sys.path.insert(0, str(directory.resolve(strict=True)))
    from offline import install_offline_policy
    network = install_offline_policy()
    from engine import TTSEngine
    with contextlib.redirect_stdout(sys.stderr):
        engine = TTSEngine(args.model_dir, args.styles)
    torch = engine.torch
    core = engine.model.model
    report = {"schema_version": 1, "ok": False, "status": "running",
        "synthetic_only": True, "text_case": args.text_case, "text": TEXTS[args.text_case],
        "voice": args.voice, "speaker": engine.config["speaker"], "cases": CASES,
        "protocol": "One baseline warmup, then each candidate warmup; A-B-B-A and B-A-A-B blocks alternate across rounds in one process",
        "rounds": args.rounds, "live_service_changed": False, "network": network,
        "environment": {"torch": torch.__version__, "cuda": torch.version.cuda,
            "device": torch.cuda.get_device_name(0), "cpu_threads": torch.get_num_threads(),
            "interop_threads": torch.get_num_interop_threads(),
            "talker": describe_module(core.talker),
            "predictor": describe_module(core.talker.code_predictor),
            "tokenizer": describe_module(core.speech_tokenizer.model),
            "flash_sdp_enabled": torch.backends.cuda.flash_sdp_enabled(),
            "memory_efficient_sdp_enabled": torch.backends.cuda.mem_efficient_sdp_enabled(),
            "math_sdp_enabled": torch.backends.cuda.math_sdp_enabled()},
        "limitations": [
            "This loads a second model instance; the existing API, LLM, vision and rendering may compete for GPU/host memory.",
            "ABBA compares candidates against nearby baseline runs under the same background, not an exclusive-GPU ceiling.",
            "This direct-engine comparison excludes HTTP queue wait, MP3 encoding and the live server's socket-cancellation checks; use a separate end-to-end probe for those.",
            "Coarse phase boundaries synchronize CUDA; nested predictor time is host elapsed time, not isolated GPU compute time.",
            "All audio is generated in batches; first audio is available only after generation finishes.",
            "No automatic quality rating or default selection is made. Listen to saved synthetic samples before choosing.",
        ], "runs": [], "errors": []}
    saved_cases = set()
    def persist():
        report["summary"] = summarize(report["runs"])
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    def run(case, comparison, warmup=False):
        number = len(report["runs"]) + 1
        print(f"synthetic run {number}: {case} ({'warmup' if warmup else 'measured'})", file=sys.stderr, flush=True)
        began = time.perf_counter()
        with contextlib.redirect_stdout(sys.stderr), instrument(engine, CASES[case], lambda: torch.cuda.synchronize(0)) as stages:
            audio, metrics = engine.synthesize(TEXTS[args.text_case], args.voice)
        wall = time.perf_counter() - began
        with wave.open(io.BytesIO(audio), "rb") as reader:
            duration = reader.getnframes() / reader.getframerate()
            if reader.getnchannels() != 1 or duration <= 0:
                raise RuntimeError("Candidate produced invalid audio")
        row = {"number": number, "case": case, "comparison": comparison, "warmup": warmup,
            "wall_seconds": wall, "first_audio_seconds": wall, "audio_seconds": duration,
            "rtf": wall / duration, "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "metrics": metrics, "stages": stages,
            "cuda_allocated_bytes": torch.cuda.memory_allocated(0),
            "cuda_reserved_bytes": torch.cuda.memory_reserved(0)}
        if not warmup and case not in saved_cases:
            filename = case + ".wav"
            (samples / filename).write_bytes(audio)
            row["sample_file"] = "samples/" + filename
            saved_cases.add(case)
        report["runs"].append(row)
        persist()
        return row
    persist()
    try:
        run("baseline", "initial", True)
        for candidate in args.candidates:
            run(candidate, candidate, True)
            for round_index in range(args.rounds):
                for case in comparison_sequence(candidate, round_index):
                    run(case, candidate)
        if args.profile_kernels:
            from torch.profiler import ProfilerActivity, profile
            with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA], record_shapes=False,
                         profile_memory=False, with_stack=False) as prof:
                with contextlib.redirect_stdout(sys.stderr):
                    engine.synthesize(TEXTS[args.text_case], args.voice)
                torch.cuda.synchronize(0)
            report["attention_kernel_profile"] = [
                {"name": item.key, "count": item.count,
                 "self_device_time_us": getattr(item, "self_device_time_total", None)}
                for item in prof.key_averages() if any(word in item.key.lower() for word in ("attention", "sdpa", "flash"))]
        report.update(ok=True, status="complete")
    except Exception as error:
        report["errors"].append({"type": type(error).__name__, "message": str(error)[:300]})
        report["status"] = "failed"
    finally:
        persist()
    print(json.dumps({"ok": report["ok"], "status": report["status"], "report": str(output / "report.json"),
                      "measured_runs": sum(not row["warmup"] for row in report["runs"]),
                      "summary": report["summary"]}, ensure_ascii=False))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

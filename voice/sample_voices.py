#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate three fixed synthetic samples and record actual batch latency/RTF."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-dir", required=True, type=Path)
    parser.add_argument("--deps", action="append", default=[], type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--styles", type=Path, default=Path(__file__).parent / "styles.json")
    args = parser.parse_args()
    for directory in reversed(args.deps):
        sys.path.insert(0, str(directory.resolve()))
    from offline import install_offline_policy
    network = install_offline_policy()
    from engine import TTSEngine
    args.out.mkdir(parents=True, exist_ok=True)
    report = {"ok": False, "testedAt": datetime.now(timezone.utc).isoformat(), "model": "Qwen3-TTS-12Hz-1.7B-CustomVoice",
              "speaker": "Serena", "attention": "sdpa", "samples": [], "network": network,
              "latency_definition": "Batch API: first audio available after full waveform generation; no 97ms streaming claim.",
              "provenance": "Fixed original test text and generic style descriptions. No actor reference audio or voice cloning."}
    try:
        engine = TTSEngine(args.model_dir, args.styles)
        report["model_load_seconds"] = round(engine.load_seconds, 4)
        report["optional_generic_audio_loader_disabled"] = engine.generic_audio_loader_disabled
        report["torch"] = engine.torch.__version__
        report["cuda"] = engine.torch.version.cuda
        report["device"] = engine.torch.cuda.get_device_name(0)
        for alias, style in engine.config["voices"].items():
            audio, metrics = engine.synthesize(style["sample_text"], alias)
            filename = alias + ".wav"
            (args.out / filename).write_bytes(audio)
            report["samples"].append({**metrics, "file": filename, "text": style["sample_text"]})
            (args.out / "sample-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"sample_ready": filename, **metrics}, ensure_ascii=False), flush=True)
        report["ok"] = len(report["samples"]) == 3 and network["blocked_attempts"] == 0
    except Exception as error:
        report["error_type"] = type(error).__name__
        raise
    finally:
        (args.out / "sample-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

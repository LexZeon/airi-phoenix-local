# SPDX-License-Identifier: MIT
"""No GPU/model import: prove reversible instrumentation and candidate isolation."""
import importlib.util
from pathlib import Path
import types
import unittest

spec = importlib.util.spec_from_file_location("bench_candidates", Path(__file__).parents[1] / "bench_candidates.py")
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)


class Predictor:
    def generate(self, **kwargs):
        return kwargs


class CandidateTests(unittest.TestCase):
    def engine(self):
        predictor = Predictor()
        core = types.SimpleNamespace(talker=types.SimpleNamespace(code_predictor=predictor))
        core.generate = lambda: predictor.generate(output_hidden_states=True)
        core.speech_tokenizer = types.SimpleNamespace(decode=lambda: "decoded")
        wrapper = types.SimpleNamespace(model=core, _tokenize_texts=lambda text: text)
        wrapper.generate_custom_voice = lambda **kwargs: (kwargs, core.generate(), core.speech_tokenizer.decode())
        return types.SimpleNamespace(model=wrapper)

    def test_candidate_parameters_and_restore(self):
        engine = self.engine()
        original = engine.model.generate_custom_voice
        with bench.instrument(engine, bench.CASES["combo"], lambda: None) as stats:
            kwargs, predicted, _ = engine.model.generate_custom_voice(non_streaming_mode=False)
        self.assertIs(engine.model.generate_custom_voice, original)
        self.assertEqual(kwargs, {"non_streaming_mode": True, "subtalker_dosample": False})
        self.assertFalse(predicted["output_hidden_states"])
        self.assertEqual(stats["predictor_calls"], 1)
        self.assertNotIn("generate", vars(engine.model.model.talker.code_predictor))

    def test_exception_restores_every_method(self):
        engine = self.engine()
        original = engine.model.model.generate
        with self.assertRaisesRegex(RuntimeError, "synthetic"):
            with bench.instrument(engine, bench.CASES["subtalker_greedy"], lambda: None):
                raise RuntimeError("synthetic")
        self.assertIs(engine.model.model.generate, original)
        self.assertNotIn("generate", vars(engine.model.model.talker.code_predictor))

    def test_baseline_retains_existing_flags(self):
        engine = self.engine()
        with bench.instrument(engine, bench.CASES["baseline"], lambda: None):
            kwargs, predicted, _ = engine.model.generate_custom_voice(non_streaming_mode=False)
        self.assertEqual(kwargs, {"non_streaming_mode": False})
        self.assertTrue(predicted["output_hidden_states"])

    def test_summary_excludes_warmup_and_pairs_controls(self):
        rows = [{"case": case, "comparison": "combo", "warmup": warm, "wall_seconds": seconds,
                 "rtf": seconds / 4, "audio_sha256": "same"}
                for case, warm, seconds in [("baseline", True, 100), ("baseline", False, 8),
                    ("combo", False, 4), ("combo", False, 4), ("baseline", False, 8)]]
        summary = bench.summarize(rows)
        self.assertEqual(summary["paired"]["combo"]["speedup"], 2)
        self.assertEqual(summary["cases"]["baseline"]["n"], 2)

    def test_successive_rounds_counterbalance_order(self):
        self.assertEqual(bench.comparison_sequence("combo", 0), ("baseline", "combo", "combo", "baseline"))
        self.assertEqual(bench.comparison_sequence("combo", 1), ("combo", "baseline", "baseline", "combo"))


if __name__ == "__main__":
    unittest.main()

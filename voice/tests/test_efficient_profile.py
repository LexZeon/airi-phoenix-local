# SPDX-License-Identifier: MIT
"""Exercise the real engine request lock/restoration using a CPU-only fake model."""
import contextlib
import importlib.util
import json
from pathlib import Path
import threading
import types
import unittest

import numpy as np

root = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("voice_engine", root / "engine.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Predictor:
    def __init__(self):
        self.flags = []
        self.on_generate = None

    def generate(self, **kwargs):
        self.flags.append(kwargs["output_hidden_states"])
        if self.on_generate:
            self.on_generate(kwargs)
        return kwargs


class EfficientProfileTests(unittest.TestCase):
    def engine(self):
        engine = module.TTSEngine.__new__(module.TTSEngine)
        engine.config = json.loads((root / "styles.json").read_text(encoding="utf-8-sig"))
        engine.lock = threading.Lock()
        engine.metrics = {"tts_requests": 0, "tts_failures": 0}
        engine.torch = types.SimpleNamespace(manual_seed=lambda _: None, inference_mode=contextlib.nullcontext)
        predictor = Predictor()
        talker = types.SimpleNamespace(code_predictor=predictor,
            register_forward_pre_hook=lambda callback: types.SimpleNamespace(remove=lambda: None))
        instructions = []
        def custom(**kwargs):
            instructions.append(kwargs["instruct"])
            predictor.generate(output_hidden_states=True)
            return [np.array([0.2, -0.2, 0.1], dtype=np.float32)], 24000
        engine.model = types.SimpleNamespace(model=types.SimpleNamespace(talker=talker), generate_custom_voice=custom)
        return engine, predictor, instructions

    def test_optional_alias_preserves_soft_instructions_and_waveform(self):
        engine, predictor, instructions = self.engine()
        baseline, a = engine.synthesize("Synthetic text", "phoenix-soft")
        efficient, b = engine.synthesize("Synthetic text", "phoenix-soft-efficient")
        after, c = engine.synthesize("Synthetic text", "phoenix-soft")
        self.assertEqual(predictor.flags, [True, False, True])
        self.assertEqual(instructions[0], instructions[1])
        self.assertEqual(baseline, efficient)
        self.assertEqual(after, baseline)
        self.assertEqual([a["profile"], b["profile"], c["profile"]], ["default", "predictor-hidden-off", "default"])
        self.assertEqual(engine.config["default_voice"], "phoenix-soft")
        self.assertNotIn("generate", vars(predictor))

    def test_failure_restores_predictor_and_releases_gpu_slot(self):
        for failure in (ConnectionAbortedError, TimeoutError, RuntimeError):
            with self.subTest(failure=failure.__name__):
                engine, predictor, _ = self.engine()
                predictor.on_generate = lambda _: (_ for _ in ()).throw(failure("synthetic failure"))
                with self.assertRaises(failure):
                    engine.synthesize("Synthetic text", "phoenix-soft-efficient")
                self.assertFalse(engine.lock.locked())
                self.assertNotIn("generate", vars(predictor))
                self.assertEqual(engine.metrics["tts_failures"], 1)
                predictor.on_generate = None
                engine.synthesize("Synthetic text", "phoenix-soft")
                self.assertTrue(predictor.flags[-1])

    def test_parallel_requests_do_not_share_the_optional_override(self):
        engine, predictor, _ = self.engine()
        entered, release = threading.Event(), threading.Event()
        errors = []
        def hold(kwargs):
            if kwargs["output_hidden_states"] is False:
                entered.set()
                if not release.wait(2):
                    raise RuntimeError("test synchronization failed")
        predictor.on_generate = hold
        def request(voice):
            try:
                engine.synthesize("Synthetic text", voice)
            except Exception as error:
                errors.append(error)
        first = threading.Thread(target=request, args=("phoenix-soft-efficient",))
        second = threading.Thread(target=request, args=("phoenix-soft",))
        first.start()
        self.assertTrue(entered.wait(1))
        second.start()
        release.set()
        first.join(2); second.join(2)
        self.assertFalse(first.is_alive() or second.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(predictor.flags, [False, True])
        self.assertFalse(engine.lock.locked())
        self.assertNotIn("generate", vars(predictor))

    def test_override_requires_generation_lock(self):
        engine, _, _ = self.engine()
        with self.assertRaisesRegex(RuntimeError, "lock is required"):
            with engine.predictor_output_mode(False):
                pass


if __name__ == "__main__":
    unittest.main()

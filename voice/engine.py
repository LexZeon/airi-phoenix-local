# SPDX-License-Identifier: MIT
"""Local CustomVoice inference; no reference audio, cloning, or remote URLs."""

import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import threading
import time
import wave


class TTSEngine:
    def __init__(self, model_dir, style_file):
        import torch
        import transformers.utils.import_utils as import_utils
        # CustomVoice accepts text only. Transformers' generic audio loader is
        # unused and otherwise imports optional SoXR (no Windows ARM wheel).
        self.generic_audio_loader_disabled = importlib.util.find_spec("soxr") is None
        if self.generic_audio_loader_disabled:
            import_utils._librosa_available = False
        with contextlib.redirect_stdout(sys.stderr):
            from qwen_tts import Qwen3TTSModel
        self.torch = torch
        self.config = json.loads(Path(style_file).read_text(encoding="utf-8-sig"))
        self.lock = threading.Lock()
        self.ready = False
        self.metrics = {"tts_requests": 0, "tts_failures": 0, "last_generation_seconds": None, "last_audio_seconds": None, "last_rtf": None}
        began = time.monotonic()
        self.model = Qwen3TTSModel.from_pretrained(
            str(Path(model_dir).resolve(strict=True)), device_map="cuda:0",
            dtype=torch.bfloat16, attn_implementation="sdpa", local_files_only=True,
        )
        self.load_seconds = time.monotonic() - began
        self.ready = True

    @contextlib.contextmanager
    def generation_slot(self, cancelled, queue_timeout, generation_timeout):
        queued_at = time.monotonic()
        while not self.lock.acquire(timeout=0.25):
            if cancelled and cancelled():
                raise ConnectionAbortedError("Client cancelled while waiting for local speech")
            if time.monotonic() - queued_at >= queue_timeout:
                raise TimeoutError("Local speech queue wait exceeded its time limit")
        hook = None
        deadline = time.monotonic() + generation_timeout

        def check_cancelled(_module=None, _inputs=None):
            if cancelled and cancelled():
                raise ConnectionAbortedError("Client cancelled local speech")
            if time.monotonic() >= deadline:
                raise TimeoutError("Local speech generation exceeded its time limit")

        try:
            check_cancelled()
            # The upstream outer wrapper discards generic stopping_criteria.
            # An official PyTorch forward pre-hook checks every talker step,
            # without editing package files or changing model weights.
            hook = self.model.model.talker.register_forward_pre_hook(check_cancelled)
            yield
            check_cancelled()
        finally:
            if hook is not None:
                hook.remove()
            self.lock.release()

    def synthesize(self, text, voice=None, speed=1.0, *, cancelled=None,
                   queue_timeout=120, generation_timeout=120):
        import numpy as np
        if not isinstance(text, str) or not text.strip() or len(text) > self.config["max_input_characters"]:
            raise ValueError("input must be nonempty text within the configured character limit")
        selected = voice or self.config["default_voice"]
        if selected not in self.config["voices"]:
            raise ValueError("Unknown voice alias")
        if isinstance(speed, bool) or not isinstance(speed, (int, float)) or not 0.75 <= speed <= 1.25:
            raise ValueError("speed must be between 0.75 and 1.25")
        instructions = self.config["voices"][selected]["instructions"]
        if speed != 1:
            instructions += f" 目标语速约为平常的百分之{round(speed * 100)}，保持自然音高。"
        with self.generation_slot(cancelled, queue_timeout, generation_timeout):
            began = time.monotonic()
            self.torch.manual_seed(self.config["seed"])
            try:
                with self.torch.inference_mode():
                    wavs, sample_rate = self.model.generate_custom_voice(
                        text=text.strip(), language=self.config["language"], speaker=self.config["speaker"],
                        instruct=instructions, max_new_tokens=self.config["max_new_tokens"],
                        non_streaming_mode=False,
                    )
                audio = np.asarray(wavs[0], dtype=np.float32).reshape(-1)
                if audio.size == 0 or not np.isfinite(audio).all():
                    raise RuntimeError("Invalid generated waveform")
                pcm = np.rint(np.clip(audio, -1, 1) * 32767).astype("<i2")
                output = io.BytesIO()
                with wave.open(output, "wb") as wave_file:
                    wave_file.setnchannels(1)
                    wave_file.setsampwidth(2)
                    wave_file.setframerate(int(sample_rate))
                    wave_file.writeframes(pcm.tobytes())
                elapsed = time.monotonic() - began
                duration = audio.size / sample_rate
                self.metrics.update(tts_requests=self.metrics["tts_requests"] + 1,
                                    last_generation_seconds=round(elapsed, 4), last_audio_seconds=round(duration, 4),
                                    last_rtf=round(elapsed / duration, 4))
                return output.getvalue(), {"voice": selected, "sample_rate": int(sample_rate),
                    "audio_seconds": round(duration, 4), "generation_seconds": round(elapsed, 4),
                    "first_audio_seconds": round(elapsed, 4), "rtf": round(elapsed / duration, 4),
                    "peak": round(float(np.max(np.abs(audio))), 5), "rms": round(float(np.sqrt(np.mean(audio ** 2))), 5)}
            except Exception:
                self.metrics["tts_failures"] += 1
                raise

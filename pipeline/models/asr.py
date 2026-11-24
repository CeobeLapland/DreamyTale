"""Local speech-to-text for the voice interaction path.

The competition ships one WAV per action; the reader also sends live
microphone audio (webm/ogg). Both are decoded here to mono 16 kHz float32 and
handed to faster-whisper. The model runs on CUDA when the runtime DLLs can be
found and falls back to CPU int8 otherwise.

No business code imports `faster_whisper` directly: switching ASR means
editing `config/models.yaml`, not the pipeline or the backend.
"""

from __future__ import annotations

import os
import time
import wave
from pathlib import Path
from threading import Lock
from typing import Any

import numpy as np

from .base import ASRResult


def _cuda_dll_dirs() -> list[Path]:
    """Directories that hold cuBLAS / cuDNN on this machine.

    LM Studio bundles the CUDA 12 runtime; ctranslate2 ships its own cuDNN 9.
    Both have to be on the DLL search path before ctranslate2 touches the GPU.
    """
    candidates: list[Path] = []
    configured = os.environ.get("DREAMYTALE_CUDA_DLL_DIRS", "")
    candidates.extend(Path(item) for item in configured.split(os.pathsep) if item)
    try:
        import ctranslate2

        candidates.append(Path(ctranslate2.__file__).resolve().parent)
    except Exception:  # noqa: BLE001 - optional dependency
        pass
    vendor = Path.home() / ".lmstudio" / "extensions" / "backends" / "vendor"
    if vendor.is_dir():
        candidates.extend(sorted(vendor.glob("win-llama-cuda12-*")))
    return [path for path in candidates if path.is_dir()]


def _decode_wav(path: Path, sampling_rate: int) -> np.ndarray:
    """Minimal PCM WAV reader, used when PyAV cannot open the file."""
    with wave.open(str(path), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        raw = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"unsupported WAV sample width: {width * 8} bit")
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    if rate != sampling_rate and samples.size:
        duration = samples.size / rate
        target = max(1, int(duration * sampling_rate))
        samples = np.interp(
            np.linspace(0, duration, target, endpoint=False),
            np.linspace(0, duration, samples.size, endpoint=False),
            samples,
        ).astype(np.float32)
    return samples


def decode_audio(path: Path, sampling_rate: int = 16000) -> np.ndarray:
    """Decode any supported audio file to mono float32 at `sampling_rate`."""
    try:
        import av
    except Exception:  # noqa: BLE001 - fall back to the WAV reader
        if path.suffix.lower() == ".wav":
            return _decode_wav(path, sampling_rate)
        raise

    try:
        with av.open(str(path)) as container:
            stream = container.streams.audio[0]
            resampler = av.AudioResampler(
                format="fltp",
                layout="mono",
                rate=sampling_rate,
            )
            chunks = []
            for frame in container.decode(stream):
                # Drop timestamps: we only need the samples in order.
                frame.pts = None
                for resampled in resampler.resample(frame):
                    chunks.append(resampled.to_ndarray().reshape(-1))
            for resampled in resampler.resample(None):
                chunks.append(resampled.to_ndarray().reshape(-1))
    except Exception:
        if path.suffix.lower() == ".wav":
            return _decode_wav(path, sampling_rate)
        raise

    if not chunks:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(chunks).astype(np.float32)


class FasterWhisperASR:
    """faster-whisper provider with lazy loading and a CPU fallback."""

    name = "faster_whisper"

    def __init__(
        self,
        model: str = "",
        device: str = "auto",
        compute_type: str = "auto",
        cpu_threads: int = 4,
        beam_size: int = 5,
        vad_filter: bool = False,
        language: str = "auto",
        cuda_dll_dirs: list[str] | None = None,
    ) -> None:
        self.model = model
        self.device = device
        self.compute_type = compute_type
        self.cpu_threads = cpu_threads
        self.beam_size = beam_size
        self.vad_filter = vad_filter
        self.language = language
        self.cuda_dll_dirs = cuda_dll_dirs or []
        self.detail = ""
        self._model: Any = None
        self._device = ""
        self._lock = Lock()
        self._dll_handles: list[Any] = []

    def available(self) -> bool:
        try:
            import faster_whisper  # noqa: F401
        except Exception as exc:  # noqa: BLE001
            self.detail = f"faster-whisper not installed: {type(exc).__name__}"
            return False
        if not self.model:
            self.detail = "asr.faster_whisper.model is not configured"
            return False
        if _looks_like_path(self.model) and not Path(self.model).exists():
            self.detail = f"ASR model not found: {self.model}"
            return False
        return True

    def _prepare_dlls(self) -> None:
        directories = [Path(item) for item in self.cuda_dll_dirs if Path(item).is_dir()]
        directories.extend(_cuda_dll_dirs())
        seen: set[str] = set()
        for directory in directories:
            key = str(directory).lower()
            if key in seen:
                continue
            seen.add(key)
            os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    self._dll_handles.append(os.add_dll_directory(str(directory)))
                except OSError:
                    pass

    def _load(self) -> Any:
        with self._lock:
            if self._model is not None:
                return self._model

            from faster_whisper import WhisperModel

            self._prepare_dlls()
            wanted = (self.device or "auto").lower()
            attempts: list[tuple[str, str]] = []
            if wanted in {"auto", "cuda"}:
                attempts.append(("cuda", "float16"))
            if wanted in {"auto", "cpu"}:
                attempts.append(("cpu", self.compute_type if self.compute_type != "auto" else "int8"))

            errors: list[str] = []
            for device, compute_type in attempts:
                try:
                    model = WhisperModel(
                        self.model,
                        device=device,
                        compute_type=compute_type,
                        cpu_threads=self.cpu_threads,
                    )
                    # Construction succeeds even when cuBLAS is missing; the
                    # first encode is what fails, so warm up before accepting.
                    list(
                        model.transcribe(
                            np.zeros(16000, dtype=np.float32),
                            language="zh",
                            beam_size=1,
                            vad_filter=False,
                        )[0]
                    )
                    self._model = model
                    self._device = device
                    self.detail = "" if device == "cuda" else (
                        "CUDA unavailable; running on CPU int8"
                    )
                    return self._model
                except Exception as exc:  # noqa: BLE001 - try the next device
                    errors.append(f"{device}: {type(exc).__name__}: {exc}")

            self.detail = "ASR model could not be loaded: " + " | ".join(errors)
            raise RuntimeError(self.detail)

    def transcribe(
        self,
        audio_path: Path,
        *,
        language: str | None = None,
        initial_prompt: str | None = None,
    ) -> ASRResult:
        model = self._load()
        started = time.perf_counter()
        audio = decode_audio(audio_path)
        duration_ms = int(len(audio) / 16000 * 1000)
        if len(audio) < 1600:  # under 100 ms: treat as silence, not a command
            return ASRResult(text="", duration_ms=duration_ms, latency_ms=0)

        hint = language or self.language
        if hint in {"", "auto", "None"}:
            hint = None

        with self._lock:
            segments, info = model.transcribe(
                audio,
                language=hint,
                initial_prompt=initial_prompt or None,
                beam_size=self.beam_size,
                vad_filter=self.vad_filter,
                condition_on_previous_text=False,
                temperature=0.0,
            )
            text = "".join(segment.text for segment in segments).strip()

        return ASRResult(
            text=text,
            language=getattr(info, "language", None),
            language_probability=getattr(info, "language_probability", None),
            duration_ms=duration_ms,
            latency_ms=int((time.perf_counter() - started) * 1000),
        )


class NullASR:
    name = "null"

    def __init__(self, detail: str = "no ASR provider configured") -> None:
        self.detail = detail

    def available(self) -> bool:
        return False

    def transcribe(self, *_args: Any, **_kwargs: Any) -> ASRResult:
        raise RuntimeError(self.detail)


def _looks_like_path(value: str) -> bool:
    return any(token in value for token in ("/", "\\", ":")) or value.startswith(".")

"""Viaim-first Mandarin speech-to-text with a local fallback."""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from threading import Lock

MAX_AUDIO_BYTES = 10 * 1024 * 1024

_model = None
_model_lock = Lock()
log = logging.getLogger("devils-committee")


class InvalidAudio(ValueError):
    """The uploaded payload cannot be decoded as speech audio."""


def _get_model():
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel

            model_name = os.getenv("WHISPER_MODEL", "base")
            download_root = Path(os.getenv("WHISPER_MODEL_DIR", "./var/models"))
            download_root.mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(
                model_name,
                device="cpu",
                compute_type="int8",
                download_root=str(download_root),
            )
    return _model


def _viaim_configured() -> bool:
    return bool(
        os.getenv("VIAIM_AI_OPEN_APP_KEY", "").strip()
        and os.getenv("VIAIM_AI_OPEN_APP_SECRET", "").strip()
    )


def _decode_pcm16_mono_16khz(payload: bytes) -> bytes:
    """Decode browser WebM/Ogg audio into Viaim's required PCM format."""

    try:
        import av

        chunks: list[bytes] = []
        with av.open(io.BytesIO(payload), mode="r") as container:
            stream = next(
                (item for item in container.streams if item.type == "audio"),
                None,
            )
            if stream is None:
                raise InvalidAudio("audio stream is missing")
            resampler = av.AudioResampler(
                format="s16",
                layout="mono",
                rate=16000,
            )
            for frame in container.decode(stream):
                converted = resampler.resample(frame)
                frames = converted if isinstance(converted, list) else [converted]
                for item in frames:
                    if item is None:
                        continue
                    size = item.samples * 2
                    chunks.append(bytes(item.planes[0])[:size])
        pcm = b"".join(chunks)
        if not pcm:
            raise InvalidAudio("audio payload has no samples")
        return pcm
    except InvalidAudio:
        raise
    except Exception as exc:
        raise InvalidAudio("audio cannot be decoded") from exc


def _transcribe_viaim(payload: bytes) -> str:
    from viaim_ai_open import ViaimAIOpen

    pcm = _decode_pcm16_mono_16khz(payload)
    with ViaimAIOpen() as client:
        result = client.text_stream.transcribe(pcm)
    text = str(getattr(result, "text", "")).strip()
    if not text:
        raise InvalidAudio("no speech recognized")
    return text


def _transcribe_local(payload: bytes) -> str:
    try:
        segments, _ = _get_model().transcribe(
            io.BytesIO(payload),
            language="zh",
            beam_size=5,
            vad_filter=True,
            initial_prompt="A股股票代码由六位数字组成，可能包含SH或SZ。请准确转写普通话和数字。",
        )
        return "".join(segment.text for segment in segments).strip()
    except InvalidAudio:
        raise
    except Exception as exc:
        raise InvalidAudio("audio cannot be decoded") from exc


def transcribe_audio(payload: bytes) -> str:
    if len(payload) < 100:
        raise InvalidAudio("audio payload is empty")
    if len(payload) > MAX_AUDIO_BYTES:
        raise InvalidAudio("audio payload is too large")
    if _viaim_configured():
        try:
            return _transcribe_viaim(payload)
        except Exception as exc:
            log.warning(
                "Viaim transcription unavailable; using local fallback: %s",
                type(exc).__name__,
            )
    return _transcribe_local(payload)

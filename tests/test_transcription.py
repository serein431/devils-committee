import io
import wave

from backend import transcription


def _wav_payload() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(16000)
        target.writeframes(b"\x00\x00" * 1600)
    return output.getvalue()


def test_browser_audio_is_converted_to_viaim_pcm():
    pcm = transcription._decode_pcm16_mono_16khz(_wav_payload())

    assert len(pcm) == 3200


def test_viaim_is_preferred_when_credentials_exist(monkeypatch):
    monkeypatch.setenv("VIAIM_AI_OPEN_APP_KEY", "app_test")
    monkeypatch.setenv("VIAIM_AI_OPEN_APP_SECRET", "secret_test")
    monkeypatch.setattr(
        transcription,
        "_transcribe_viaim",
        lambda payload: "研究 300750",
    )
    monkeypatch.setattr(
        transcription,
        "_transcribe_local",
        lambda payload: (_ for _ in ()).throw(AssertionError("unexpected fallback")),
    )

    assert transcription.transcribe_audio(b"audio" * 30) == "研究 300750"


def test_local_transcription_is_used_when_viaim_fails(monkeypatch):
    monkeypatch.setenv("VIAIM_AI_OPEN_APP_KEY", "app_test")
    monkeypatch.setenv("VIAIM_AI_OPEN_APP_SECRET", "secret_test")
    monkeypatch.setattr(
        transcription,
        "_transcribe_viaim",
        lambda payload: (_ for _ in ()).throw(RuntimeError("service unavailable")),
    )
    monkeypatch.setattr(
        transcription,
        "_transcribe_local",
        lambda payload: "本地识别结果",
    )

    assert transcription.transcribe_audio(b"audio" * 30) == "本地识别结果"

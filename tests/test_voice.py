from types import SimpleNamespace
import sys

import pytest

from core import voice


def test_failed_custom_voice_tries_installed_windows_voice(monkeypatch):
    monkeypatch.setattr(voice.platform, 'system', lambda: 'Windows')
    monkeypatch.setattr(voice, '_silma_is_ready', lambda: True)
    def failed(_): raise RuntimeError('fixture voice failure')
    monkeypatch.setattr(voice, '_speak_with_silma', failed)
    calls = []
    monkeypatch.setattr(voice.subprocess, 'run', lambda *args, **kwargs: calls.append(kwargs) or SimpleNamespace(returncode=0))
    assert voice.speak_arabic('اختبار') is True
    assert len(calls) == 1


@pytest.fixture(autouse=True)
def isolate_voice_unit_tests_from_installed_models(monkeypatch, tmp_path):
    # Do not launch real synthesis from unit tests.
    monkeypatch.setattr(voice, "SILMA_MODEL_PATH", tmp_path / "no-silma.pt")
    monkeypatch.setattr(voice, "SILMA_REFERENCE_PATH", tmp_path / "no-reference.wav")
    monkeypatch.setattr(voice, "SILMA_PYTHON_PATH", tmp_path / "no-python.exe")
    monkeypatch.setattr(voice, "SILMA_WORKER_PATH", tmp_path / "no-worker.py")


def test_transcribe_pcm_uses_the_existing_local_model_only(tmp_path, monkeypatch):
    model_dir = tmp_path / "speech-tiny"
    model_dir.mkdir()
    (model_dir / "model.bin").write_bytes(b"model")
    calls = {}

    class Audio:
        def astype(self, _kind):
            return self

        def __truediv__(self, _value):
            return "normalized-audio"

    class FakeModel:
        def __init__(self, path, **kwargs):
            calls["model"] = (path, kwargs)

        def transcribe(self, audio, **kwargs):
            calls["transcribe"] = (audio, kwargs)
            return iter((SimpleNamespace(text=" اكتبي إعلان ميكب "),)), SimpleNamespace(language="ar")

    monkeypatch.setitem(
        sys.modules,
        "numpy",
        SimpleNamespace(
            frombuffer=lambda data, dtype: Audio(), int16="int16", float32="float32"
        ),
    )
    monkeypatch.setitem(sys.modules, "faster_whisper", SimpleNamespace(WhisperModel=FakeModel))

    result = voice.transcribe_pcm(b"voice bytes", model_path=model_dir)

    assert result == {"text": "اكتبي إعلان ميكب", "language": "ar", "requires_review": True}
    assert calls["model"][1] == {
        "device": "cpu", "compute_type": "int8", "local_files_only": True,
    }
    assert calls["transcribe"][0] == "normalized-audio"
    assert calls["transcribe"][1] == {
        "language": "ar",
        "beam_size": 5,
        "vad_filter": False,
        "condition_on_previous_text": False,
    }


def test_transcribe_pcm_does_not_download_a_missing_model(tmp_path):
    with pytest.raises(ValueError, match="will not download"):
        voice.transcribe_pcm(b"audio", model_path=tmp_path / "missing-model")


def test_transcription_rejects_latin_gibberish_as_unrecognized_arabic():
    assert not voice._has_arabic_script("Samanikoyas, Samanik.")
    assert voice._has_arabic_script("اكتبي إعلانًا")


def test_microphone_capture_is_bounded_and_windows_only(monkeypatch):
    monkeypatch.setattr(voice.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="Windows only"):
        voice.record_microphone_pcm()

    monkeypatch.setattr(voice.platform, "system", lambda: "Windows")
    with pytest.raises(ValueError, match="from 1 to 12"):
        voice.record_microphone_pcm(seconds=13)


def test_speech_output_uses_installed_arabic_voice_without_passing_text_in_command(
    monkeypatch, tmp_path,
):
    monkeypatch.setattr(voice.platform, "system", lambda: "Windows")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(voice.subprocess, "run", fake_run)
    text = "أهلًا يا بودا"

    assert voice.speak_arabic(text) is True
    assert text not in " ".join(captured["command"])
    assert captured["input"] == text.encode("utf-8")
    assert "Language -like 'ar-EG*'" in captured["command"][-1]
    assert "Windows.Media.SpeechSynthesis.SpeechSynthesizer" in captured["command"][-1]
    assert "Insert 350 ms of PCM silence" in captured["command"][-1]
    assert "$paddedAudio" in captured["command"][-1]


def test_speech_prefers_user_voice_clone_when_installed(monkeypatch):
    monkeypatch.setattr(voice.platform, "system", lambda: "Windows")
    captured = {}
    monkeypatch.setattr(voice, "_silma_is_ready", lambda: True)
    monkeypatch.setattr(
        voice, "_speak_with_silma", lambda text: captured.setdefault("text", text)
    )
    assert voice.speak_arabic("أهلًا يا بوده") is True
    assert captured["text"] == "أهلًا يا بوده"


def test_windows_fallback_never_selects_a_non_egyptian_arabic_voice(monkeypatch):
    monkeypatch.setattr(voice.platform, "system", lambda: "Windows")
    monkeypatch.setattr(voice.subprocess, "run", lambda *_a, **_k: SimpleNamespace(returncode=3))
    assert voice.speak_arabic("مرحبًا") is False
    assert "Language -like 'ar-EG*'" in voice._SPEECH_SCRIPT
    assert "Language -like 'ar-*'" not in voice._SPEECH_SCRIPT


def test_speech_output_gracefully_reports_missing_arabic_voice(monkeypatch):
    monkeypatch.setattr(voice.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        voice.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=3)
    )

    assert voice.speak_arabic("مرحبًا") is False

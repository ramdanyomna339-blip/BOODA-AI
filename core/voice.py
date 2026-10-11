"""Opt-in, local microphone transcription and Windows Arabic speech output."""

import ctypes
import json
import os
import platform
import queue
import subprocess
import sys
import tempfile
import threading
import time
import atexit
from pathlib import Path


SPEECH_MODEL_PATH = Path(".local-ai-runtime/models/speech-tiny")
SAMPLE_RATE = 16_000
MAX_RECORD_SECONDS = 12
VOICE_LOAD_TIMEOUT_SECONDS = 120
VOICE_GENERATION_TIMEOUT_SECONDS = 120
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SILMA_MODEL_PATH = PROJECT_ROOT / ".local-ai-runtime/models/tts/model.pt"
SILMA_REFERENCE_PATH = PROJECT_ROOT / ".local-ai-runtime/models/tts/user-reference.wav"
SILMA_PYTHON_PATH = PROJECT_ROOT / ".silma-venv/Scripts/python.exe"
SILMA_WORKER_PATH = Path(__file__).with_name("silma_voice_worker.py")
SILMA_CACHE_PATH = PROJECT_ROOT / ".local-ai-runtime/models/tts/silma-cache"
SILMA_LOG_PATH = PROJECT_ROOT / ".local-ai-runtime/models/tts/silma-worker.log"
_SILMA_PROCESS = None
_SILMA_LOG = None
_SILMA_READER_QUEUE = None
_SILMA_LOCK = threading.Lock()


class _WaveFormat(ctypes.Structure):
    _fields_ = [
        ("format_tag", ctypes.c_ushort),
        ("channels", ctypes.c_ushort),
        ("samples_per_sec", ctypes.c_uint),
        ("avg_bytes_per_sec", ctypes.c_uint),
        ("block_align", ctypes.c_ushort),
        ("bits_per_sample", ctypes.c_ushort),
        ("extra_size", ctypes.c_ushort),
    ]


class _WaveHeader(ctypes.Structure):
    _fields_ = [
        ("data", ctypes.c_void_p),
        ("buffer_length", ctypes.c_uint),
        ("bytes_recorded", ctypes.c_uint),
        ("user", ctypes.c_size_t),
        ("flags", ctypes.c_uint),
        ("loops", ctypes.c_uint),
        ("next", ctypes.c_void_p),
        ("reserved", ctypes.c_size_t),
    ]


def _check_wave_result(result, action):
    if result != 0:
        raise RuntimeError(f"Windows microphone {action} failed (code {result}).")


def _has_arabic_script(text):
    return any("\u0600" <= char <= "\u06ff" for char in text)


def record_microphone_pcm(*, seconds=8):
    """Record one bounded utterance into memory; never writes a recording file."""
    if platform.system() != "Windows":
        raise RuntimeError("Microphone capture is currently available on Windows only.")
    if type(seconds) is not int or not 1 <= seconds <= MAX_RECORD_SECONDS:
        raise ValueError(f"Choose a recording length from 1 to {MAX_RECORD_SECONDS} seconds.")

    winmm = ctypes.WinDLL("winmm")
    fmt = _WaveFormat(1, 1, SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16, 0)
    byte_count = seconds * SAMPLE_RATE * 2
    audio_buffer = ctypes.create_string_buffer(byte_count)
    header = _WaveHeader(
        ctypes.cast(audio_buffer, ctypes.c_void_p), byte_count, 0, 0, 0, 0, None, 0
    )
    handle = ctypes.c_void_p()
    prepared = False
    started = False
    _check_wave_result(
        winmm.waveInOpen(ctypes.byref(handle), 0xFFFFFFFF, ctypes.byref(fmt), 0, 0, 0),
        "open",
    )
    try:
        _check_wave_result(
            winmm.waveInPrepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header)),
            "prepare",
        )
        prepared = True
        _check_wave_result(
            winmm.waveInAddBuffer(handle, ctypes.byref(header), ctypes.sizeof(header)),
            "buffer setup",
        )
        _check_wave_result(winmm.waveInStart(handle), "start")
        started = True
        deadline = time.monotonic() + seconds + 5
        while not header.flags & 1:  # WHDR_DONE
            if time.monotonic() >= deadline:
                raise TimeoutError("Microphone recording did not finish in time.")
            time.sleep(0.05)
        if header.bytes_recorded < SAMPLE_RATE:
            raise ValueError("No clear microphone audio was captured; try again closer to the mic.")
        return ctypes.string_at(header.data, header.bytes_recorded)
    finally:
        if started:
            winmm.waveInStop(handle)
        if prepared:
            winmm.waveInUnprepareHeader(handle, ctypes.byref(header), ctypes.sizeof(header))
        winmm.waveInClose(handle)


def transcribe_pcm(pcm_data, *, model_path=SPEECH_MODEL_PATH):
    """Transcribe mono 16 kHz PCM locally with the already-downloaded Whisper model."""
    model_dir = Path(model_path)
    if not model_dir.is_dir() or not (model_dir / "model.bin").is_file():
        raise ValueError(
            "The local speech model is missing. Booda will not download a model automatically."
        )
    if not pcm_data:
        raise ValueError("No microphone audio was captured.")
    try:
        import numpy as np
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "Local speech libraries are not available. Start Booda with start_desktop.ps1."
        ) from error

    audio = np.frombuffer(pcm_data, dtype=np.int16).astype(np.float32) / 32768.0
    model = WhisperModel(
        str(model_dir), device="cpu", compute_type="int8", local_files_only=True
    )
    # Short Egyptian Arabic utterances are often misdetected as English when
    # Whisper auto-detects language. Force Arabic and avoid VAD dropping a quiet
    # first/last word in this short microphone clip.
    segments, info = model.transcribe(
        audio,
        language="ar",
        beam_size=5,
        vad_filter=False,
        condition_on_previous_text=False,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text or not _has_arabic_script(text):
        raise ValueError(
            "Booda could not recognize Arabic speech reliably. Check the selected Windows microphone, "
            "then speak a short, clear Arabic sentence and try again."
        )
    return {"text": text, "language": info.language, "requires_review": True}


def transcribe_microphone(*, seconds=12, model_path=SPEECH_MODEL_PATH):
    print(f"سجّلي طلبك الآن؛ مدة التسجيل حتى {seconds} ثوانٍ. الصوت يظل في الذاكرة ولا يُحفظ كملف.")
    return transcribe_pcm(record_microphone_pcm(seconds=seconds), model_path=model_path)


_SPEECH_SCRIPT = r'''
Add-Type -AssemblyName System.Runtime.WindowsRuntime
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$voice = [Windows.Media.SpeechSynthesis.SpeechSynthesizer,Windows.Media.SpeechSynthesis,ContentType=WindowsRuntime]::AllVoices | Where-Object { $_.Language -like 'ar-EG*' } | Select-Object -First 1
if ($null -eq $voice) { exit 3 }
$synth.Voice = $voice
$stream = [Console]::OpenStandardInput()
$memory = New-Object System.IO.MemoryStream
$buffer = New-Object byte[] 4096
while (($count = $stream.Read($buffer, 0, $buffer.Length)) -gt 0) { $memory.Write($buffer, 0, $count) }
$text = [System.Text.Encoding]::UTF8.GetString($memory.ToArray())
$operation = $synth.SynthesizeTextToStreamAsync($text)
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object { $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and $_.GetParameters().Count -eq 1 } | Select-Object -First 1
$speechTask = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream]).Invoke($null, @($operation))
$speechStream = $speechTask.GetAwaiter().GetResult()
$reader = New-Object Windows.Storage.Streams.DataReader($speechStream.GetInputStreamAt(0))
$load = $reader.LoadAsync([uint32]$speechStream.Size)
$loadTask = $asTask.MakeGenericMethod([uint32]).Invoke($null, @($load))
$null = $loadTask.GetAwaiter().GetResult()
$audio = New-Object byte[] ([int]$speechStream.Size)
$reader.ReadBytes($audio)
# Windows can clip the first phoneme while the output device wakes up.
# Insert 350 ms of PCM silence at the beginning of the in-memory WAV.
$dataMarker = -1
for ($i = 12; $i -le ($audio.Length - 8); $i++) {
    if ([System.Text.Encoding]::ASCII.GetString($audio, $i, 4) -eq 'data') {
        $dataMarker = $i
        break
    }
}
if ($dataMarker -lt 0) { throw 'Speech stream did not contain a WAV data chunk.' }
$dataStart = $dataMarker + 8
$dataLength = [BitConverter]::ToInt32($audio, $dataMarker + 4)
$sampleRate = [BitConverter]::ToInt32($audio, 24)
$blockAlign = [BitConverter]::ToUInt16($audio, 32)
$silenceLength = [int]([Math]::Round($sampleRate * $blockAlign * 0.35))
$paddedAudio = New-Object byte[] ($audio.Length + $silenceLength)
[Array]::Copy($audio, 0, $paddedAudio, 0, $dataStart)
[Array]::Copy($audio, $dataStart, $paddedAudio, $dataStart + $silenceLength, $dataLength)
[Array]::Copy([BitConverter]::GetBytes([int]($paddedAudio.Length - 8)), 0, $paddedAudio, 4, 4)
[Array]::Copy([BitConverter]::GetBytes([int]($dataLength + $silenceLength)), 0, $paddedAudio, $dataMarker + 4, 4)
$audioMemory = New-Object System.IO.MemoryStream(,$paddedAudio)
$player = New-Object System.Media.SoundPlayer($audioMemory)
$player.PlaySync()
$player.Dispose()
$audioMemory.Dispose()
$reader.Dispose()
$speechStream.Dispose()
$synth.Dispose()
'''.strip()


def speak_arabic(text, *, dialect_memory=None):
    """Speak with the user's local voice clone, falling back to Windows ar-EG."""
    if platform.system() != "Windows":
        return False
    if not isinstance(text, str) or not text.strip():
        return True
    from core.dialect_learning import apply_dialect_corrections
    text = apply_dialect_corrections(text, dialect_memory)

    if _silma_is_ready():
        try:
            _speak_with_silma(text)
            return True
        except (RuntimeError, OSError):
            print("تعذر الصوت المحلي المخصص؛ بحاول الصوت المصري المثبت في Windows.")
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SPEECH_SCRIPT],
            input=text.encode("utf-8"),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=90,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"Windows speech output failed: {error}") from error
    if result.returncode == 3:
        return False
    if result.returncode != 0:
        raise RuntimeError("Windows could not speak this reply.")
    return True


def _silma_is_ready():
    return all(Path(path).is_file() for path in (
        SILMA_MODEL_PATH, SILMA_REFERENCE_PATH, SILMA_PYTHON_PATH, SILMA_WORKER_PATH
    ))


def _read_silma_worker(process, messages):
    try:
        for line in process.stdout:
            try:
                messages.put(json.loads(line))
            except (json.JSONDecodeError, TypeError):
                continue
    finally:
        messages.put({"ok": False, "error": "The local voice worker stopped."})


def _start_silma_worker():
    global _SILMA_PROCESS, _SILMA_LOG, _SILMA_READER_QUEUE
    if _SILMA_PROCESS is not None and _SILMA_PROCESS.poll() is None:
        return
    print("بجهّز الصوت المستنسخ محليًا لأول مرة؛ ممكن ياخد شوية وقت.")
    SILMA_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SILMA_LOG = open(SILMA_LOG_PATH, "a", encoding="utf-8")
    worker_env = os.environ.copy()
    worker_env.update({
        "BOODA_SILMA_MODEL_PATH": str(SILMA_MODEL_PATH),
        "BOODA_SILMA_VOCAB_PATH": str(SILMA_MODEL_PATH.with_name("vocab.txt")),
        "BOODA_SILMA_CACHE_PATH": str(SILMA_CACHE_PATH),
        "HF_HOME": str(SILMA_CACHE_PATH),
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "PYTHONIOENCODING": "utf-8",
    })
    _SILMA_PROCESS = subprocess.Popen(
        [str(SILMA_PYTHON_PATH), "-u", str(SILMA_WORKER_PATH)],
        cwd=str(PROJECT_ROOT),
        env=worker_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=_SILMA_LOG,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )
    _SILMA_READER_QUEUE = queue.Queue()
    threading.Thread(
        target=_read_silma_worker,
        args=(_SILMA_PROCESS, _SILMA_READER_QUEUE),
        daemon=True,
    ).start()
    try:
        ready = _SILMA_READER_QUEUE.get(timeout=VOICE_LOAD_TIMEOUT_SECONDS)
    except queue.Empty as error:
        _stop_silma_worker()
        raise RuntimeError("Loading the local voice model took too long.") from error
    if not ready.get("ready"):
        _stop_silma_worker()
        raise RuntimeError(ready.get("error", "The local voice model did not start."))


def _speak_with_silma(text):
    if platform.system() != "Windows":
        return False
    try:
        import winsound
    except ImportError as error:
        raise RuntimeError("Windows audio playback is unavailable.") from error
    with _SILMA_LOCK:
        _start_silma_worker()
        fd, output_path = tempfile.mkstemp(prefix="booda-voice-", suffix=".wav")
        import os
        os.close(fd)
        Path(output_path).unlink(missing_ok=True)
        try:
            _SILMA_PROCESS.stdin.write(json.dumps({
                "text": text,
                "output_path": output_path,
                "reference_path": str(SILMA_REFERENCE_PATH),
                "cache_path": str(SILMA_CACHE_PATH),
                "model_path": str(SILMA_MODEL_PATH),
            }, ensure_ascii=False) + "\n")
            _SILMA_PROCESS.stdin.flush()
            try:
                response = _SILMA_READER_QUEUE.get(timeout=VOICE_GENERATION_TIMEOUT_SECONDS)
            except queue.Empty as error:
                _stop_silma_worker()
                raise RuntimeError("Generating the cloned voice took too long.") from error
            if not response.get("ok"):
                _stop_silma_worker()
                raise RuntimeError(response.get("error", "Voice generation failed."))
            audio_path = Path(response.get("output_path", output_path))
            winsound.PlaySound(str(audio_path), winsound.SND_FILENAME)
        finally:
            Path(output_path).unlink(missing_ok=True)
    return True


def _stop_silma_worker():
    global _SILMA_PROCESS, _SILMA_LOG, _SILMA_READER_QUEUE
    process, log_file = _SILMA_PROCESS, _SILMA_LOG
    _SILMA_PROCESS = _SILMA_LOG = _SILMA_READER_QUEUE = None
    if process is not None and process.poll() is None:
        try:
            process.stdin.close()
            process.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            process.terminate()
    if log_file is not None:
        log_file.close()


atexit.register(_stop_silma_worker)

"""Synthesize the already-configured local voice to a file, without playback or downloads."""
import json
from pathlib import Path
import shutil
import sys
import types
import wave
from uuid import uuid4
from core import voice


def run():
    from core.console import configure_utf8_console
    configure_utf8_console()
    folder = Path(__file__).resolve().parents[1]/'outputs/voice_offline_checks'/uuid4().hex
    folder.mkdir(parents=True)
    sample = folder/'sample.wav'
    report = {'network_allowed':False, 'microphone_used':False, 'played':False, 'passed':False}
    original = sys.modules.get('winsound')
    def save(path, flags):
        shutil.copyfile(path, sample)
    sys.modules['winsound'] = types.SimpleNamespace(PlaySound=save, SND_FILENAME=0)
    try:
        if not voice._silma_is_ready(): raise RuntimeError('Configured voice files are missing.')
        voice._speak_with_silma('أهلًا، أنا بوده. جاهز أساعدك خطوة بخطوة، ونراجع النتيجة مع بعض.')
        with wave.open(str(sample),'rb') as audio:
            report.update(seconds=audio.getnframes()/audio.getframerate(), sample_rate=audio.getframerate(), channels=audio.getnchannels())
        report['passed'] = report['seconds'] > 0 and sample.stat().st_size > 1000
        report['quality'] = 'audible quality requires user listening; waveform validity is not a quality score'
    except Exception as error:
        report['error_type'] = type(error).__name__
    finally:
        voice._stop_silma_worker()
        if original is None: sys.modules.pop('winsound',None)
        else: sys.modules['winsound'] = original
    path = folder/'report.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('REPORT='+str(path),flush=True)
    if not report['passed']: raise RuntimeError('Offline voice check failed; inspect report.')


if __name__ == '__main__': run()

"""Explicit offline poster and silent slideshow exports, not generative design."""
from pathlib import Path
import math
from fractions import Fraction
from uuid import uuid4
from xml.sax.saxutils import escape
import json
from hashlib import sha256


def output_folder(root, kind, workspace_scope=None):
    scope = workspace_scope or {}
    if not isinstance(scope, dict) or set(scope) - {'client_id','project_id'} or any(
        not isinstance(value,str) or not value.strip() or len(value)>100 for value in scope.values()):
        raise ValueError('نطاق العميل أو المشروع غير صالح.')
    identity = sha256(json.dumps(scope,sort_keys=True).encode()).hexdigest()[:20] if scope else 'general'
    folder = Path(root)/'outputs'/kind/identity
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def catalog(result, workspace_scope):
    result['workspace_scope'] = dict(workspace_scope or {})
    Path(result['path']).with_suffix('.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def list_media_outputs(root, workspace_scope=None):
    items = []
    for kind in ('local_designs','local_videos'):
        folder = output_folder(root,kind,workspace_scope)
        for path in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:30]:
            try:
                data = json.loads(path.read_text(encoding='utf-8'))
                output = Path(data['path']).resolve()
                if data.get('workspace_scope') == (workspace_scope or {}) and output.parent == folder.resolve() and output.is_file():
                    items.append(data)
            except (ValueError,OSError,KeyError,TypeError):
                continue
    return items


def create_poster(*, title, subtitle='', width=1080, height=1080, background='#152238', root='.', workspace_scope=None):
    import re
    if not isinstance(title, str) or not title.strip() or len(title) > 100:
        raise ValueError('اكتب عنوانًا من 1 إلى 100 حرف.')
    if not isinstance(subtitle, str) or len(subtitle) > 200:
        raise ValueError('النص الفرعي أطول من الحد.')
    if re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', title + subtitle):
        raise ValueError('النص يحتوي رموز تحكم غير صالحة للتصميم.')
    if any(type(value) is not int or not 320 <= value <= 2160 for value in (width, height)):
        raise ValueError('الأبعاد يجب أن تكون بين 320 و2160.')
    if not re.fullmatch(r'#[0-9a-fA-F]{6}', background):
        raise ValueError('اللون يجب أن يكون بصيغة #112233.')
    font_size = min(64, max(16, int(width / max(len(title), 12) * 1.25)))
    lines = [subtitle[i:i+35] for i in range(0, len(subtitle), 35)]
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">'
        f'<rect width="100%" height="100%" fill="{background}"/>'
        f'<rect x="{width*.12}" y="{height*.24}" width="{width*.76}" height="6" fill="#F7C873"/>'
        f'<text x="{width/2}" y="{height*.4}" fill="white" text-anchor="middle" font-family="Segoe UI,Arial" font-size="{font_size}" direction="rtl">{escape(title)}</text>'
        + ''.join(f'<text x="{width/2}" y="{height*.54+i*height*.055}" fill="#E2E8F0" text-anchor="middle" font-family="Segoe UI,Arial" font-size="{max(14,font_size//2)}" direction="rtl">{escape(line)}</text>' for i,line in enumerate(lines)) + '</svg>')
    folder = output_folder(root,'local_designs',workspace_scope)
    path = folder / (uuid4().hex + '.svg')
    path.write_text(svg, encoding='utf-8')
    return catalog({'path': str(path.resolve()), 'width': width, 'height': height, 'format': 'svg',
        'scope': 'fixed template; review text fit before publishing', 'generated_by_model': False}, workspace_scope)


def create_slideshow(images, *, seconds_per_image=2, root='.', workspace_scope=None):
    import av
    from PIL import Image, ImageOps
    if not isinstance(images, list) or not 1 <= len(images) <= 20:
        raise ValueError('اختر من 1 إلى 20 صورة.')
    if type(seconds_per_image) not in (int, float) or not math.isfinite(seconds_per_image) or not 0.5 <= seconds_per_image <= 5:
        raise ValueError('مدة الصورة بين نصف ثانية و5 ثوان.')
    # Decode all inputs before creating an output; never accepts URLs.
    frames = []
    for item in images:
        path = Path(item)
        if not path.is_file() or path.suffix.lower() not in {'.png', '.jpg', '.jpeg', '.webp'} or path.stat().st_size > 20_000_000:
            raise ValueError('صور محلية PNG/JPEG/WebP حتى 20MB فقط.')
        with Image.open(path) as image:
            if image.width * image.height > 20_000_000:
                raise ValueError('الصورة أكبر من الحد.')
            frames.append(ImageOps.pad(ImageOps.exif_transpose(image).convert('RGB'), (720, 1280), color='black'))
    folder = output_folder(root,'local_videos',workspace_scope)
    destination = folder / (uuid4().hex + '.mp4')
    fps, count = 12, 0
    try:
        with av.open(str(destination), 'w') as output:
            stream = output.add_stream('libx264', rate=fps)
            stream.width, stream.height, stream.pix_fmt = 720, 1280, 'yuv420p'
            stream.options = {'preset': 'ultrafast', 'crf': '25'}
            for image in frames:
                for _ in range(round(seconds_per_image * fps)):
                    frame = av.VideoFrame.from_image(image)
                    frame.pts, frame.time_base = count, Fraction(1, fps)
                    count += 1
                    for packet in stream.encode(frame): output.mux(packet)
            for packet in stream.encode(None): output.mux(packet)
        with av.open(str(destination)) as check:
            decoded = sum(1 for _ in check.decode(video=0))
        if decoded != count:
            raise RuntimeError('عدد إطارات الفيديو لا يطابق المطلوب.')
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return catalog({'path': str(destination.resolve()), 'frames': count, 'seconds': count/fps,
            'width': 720, 'height': 1280, 'audio': False, 'scope': 'silent image slideshow, not full editing'}, workspace_scope)

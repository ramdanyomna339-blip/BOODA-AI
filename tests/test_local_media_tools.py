import pytest
from PIL import Image
from xml.etree import ElementTree
from core.local_media_tools import create_poster, create_slideshow
from core.local_media_tools import list_media_outputs


def test_poster_preserves_arabic_and_cannot_inject_svg(tmp_path):
    result = create_poster(title='عرض <script>مميز</script>', subtitle='خصم & تفاصيل', root=tmp_path)
    tree = ElementTree.parse(result['path'])
    assert len(tree.findall('.//{http://www.w3.org/2000/svg}script')) == 0
    assert 'عرض <script>مميز</script>' in ''.join(tree.getroot().itertext())
    assert tree.getroot().attrib['width'] == '1080'


def test_slideshow_encodes_decodable_frames_and_refuses_missing_inputs(tmp_path):
    paths = []
    for color in ('red', 'blue'):
        path = tmp_path / (color + '.png')
        Image.new('RGB', (120, 80), color).save(path)
        paths.append(path)
    result = create_slideshow(paths, seconds_per_image=.5, root=tmp_path)
    assert result['frames'] == 12 and result['seconds'] == 1 and result['audio'] is False
    with pytest.raises(ValueError): create_slideshow([tmp_path/'missing.png'], root=tmp_path)
    with pytest.raises(ValueError): create_slideshow(paths, seconds_per_image=float('nan'), root=tmp_path)


def test_output_catalog_is_scoped_and_cannot_return_external_paths(tmp_path):
    import json
    from pathlib import Path
    a = create_poster(title='عميل أ', root=tmp_path, workspace_scope={'client_id':'a'})
    create_poster(title='عميل ب', root=tmp_path, workspace_scope={'client_id':'b'})
    assert [item['path'] for item in list_media_outputs(tmp_path,{'client_id':'a'})] == [a['path']]
    assert list_media_outputs(tmp_path) == []
    altered = dict(a,path=str(tmp_path/'outside.txt'))
    (tmp_path/'outside.txt').write_text('private')
    Path(a['path']).with_suffix('.json').write_text(json.dumps(altered))
    assert list_media_outputs(tmp_path,{'client_id':'a'}) == []
    with pytest.raises(ValueError): create_poster(title='x',root=tmp_path,workspace_scope={'path':'../'})

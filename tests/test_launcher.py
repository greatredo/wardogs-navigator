"""The navigation host remains usable without optional component files."""
import json
from wardogs_nav.launcher import pilot_component


def test_component_missing_broken_incompatible_and_source(tmp_path):
    assert pilot_component(tmp_path, False)[0] is None
    folder = tmp_path / 'pilot'
    folder.mkdir()
    (folder / 'component.json').write_text('{', encoding='utf-8')
    assert '损坏' in pilot_component(tmp_path, False)[1]
    (folder / 'component.json').write_text(json.dumps(dict(id='wardogs-pilot', host_api=2)), encoding='utf-8')
    assert '不兼容' in pilot_component(tmp_path, False)[1]
    (folder / 'component.json').write_text(json.dumps(dict(id='wardogs-pilot', host_api=1)), encoding='utf-8')
    assert '不完整' in pilot_component(tmp_path, False)[1]
    (folder / 'main.py').touch()
    (folder / 'wardogs_pilot').mkdir()
    for name in ('app.py', 'core.py', 'windows_bridge.ps1'):
        (folder / 'wardogs_pilot' / name).touch()
    assert pilot_component(tmp_path, False)[0][1] == str(folder / 'main.py')


def test_frozen_component_partial_runtime_remains_unavailable(tmp_path):
    folder = tmp_path / 'components/pilot'
    folder.mkdir(parents=True)
    (folder / 'component.json').write_text(json.dumps(dict(id='wardogs-pilot', host_api=1)), encoding='utf-8')
    (folder / 'WardogsPilot.exe').touch()
    (folder / '_internal').mkdir()
    assert pilot_component(tmp_path, True)[0] is None
    for name in ('PySide6/Qt6Core.dll', 'wardogs_pilot/windows_bridge.ps1',
                 'assets/audio/airplane-announcement.mp3', 'python313.dll'):
        file = folder / '_internal' / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    assert pilot_component(tmp_path, True)[0][0] == str(folder / 'WardogsPilot.exe')

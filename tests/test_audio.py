"""Speech failures must stay outside the UI; fallback must speak actual built-ins."""
from pathlib import Path
import sys
import time
import wave
import pytest
from PySide6.QtCore import QCoreApplication
from PySide6.QtWidgets import QApplication
from wardogs_audio.bridge import WindowsBridge
from wardogs_audio.pack import DefaultVoicePack, number_words
from wardogs_audio.speech import SpeechService
from wardogs_audio.navigation import NavigationSpeech
from wardogs_audio.player import FilePlayer
from wardogs_nav.model import default_settings, NOTE_TYPES, MODIFIERS
from wardogs_nav.navigation import Cue, cue_text, Navigator
from wardogs_nav.routing import Route

@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def wait_for(app, predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    app.processEvents()
    assert predicate(), 'Timed out waiting for audio callback'


@pytest.mark.parametrize('value,zh,en', [
    ('0', '零', 'zero'), ('12', '十二', 'twelve'), ('110', '一百一十', 'one hundred ten'),
    ('1010', '一千零一十', 'one thousand ten'), ('10001', '一万零一', 'ten thousand one'),
    ('-55.3', '负五十五点三', 'minus fifty five point three'),
])
def test_number_grammar(value, zh, en):
    assert number_words(value, 'zh-CN') == zh
    assert number_words(value, 'en-US') == en


def test_default_pack_covers_navigation_wrc_and_numbers(tmp_path):
    pack = DefaultVoicePack()
    phrases = [('沿当前道路行驶1230米', 'zh-CN'), ('前方2.5公里，路口向右前方', 'zh-CN'),
               ('行驶方向相反，请在安全位置掉头', 'zh-CN'), ('路线已更新', 'zh-CN'),
               ('已到达，请安全掉头，开始返程', 'zh-CN'),
               ('一百米，左三，收紧，接，右六。五十米，急刹车，接，左直角，别切。', 'zh-CN')]
    for mode in ('normal', 'wrc'):
        for kind in NOTE_TYPES:
            for grade in range(1, 7):
                phrases.append((cue_text(Cue('x', 0, kind, grade, modifiers=list(MODIFIERS)), mode, spoken=True), 'zh-CN'))
    for text, lang in phrases:
        assert pack.segments(text, lang), text
    for lang, text in [('zh-CN', '沿当前道路行驶1230米')]:
        path = tmp_path / (lang + '.wav')
        pack.render(text, lang, path)
        with wave.open(str(path), 'rb') as audio:
            assert audio.getparams()[:3] == (1, 2, 24000)
            assert 1000 < audio.getnframes() < 24000 * 60


def test_unknown_custom_text_never_plays_a_partial_or_different_instruction(tmp_path):
    target = tmp_path / 'no-partial.wav'
    with pytest.raises(ValueError, match='自定义文字'):
        DefaultVoicePack().render('前方100米，桥梁已经塌陷', 'zh-CN', target)
    assert not target.exists()


def subprocess_bridge(code):
    return WindowsBridge(command=[sys.executable, '-u', '-c', code])


def test_child_exit_is_reported_without_terminating_caller():
    bridge = subprocess_bridge('import sys,os;sys.stdin.readline();os._exit(23)')
    with pytest.raises(RuntimeError, match='已退出'):
        bridge.call('voices')
    assert bridge.closed and bridge.process is None


def test_hung_child_is_terminated_on_timeout():
    bridge = subprocess_bridge('import sys,time;sys.stdin.readline();time.sleep(60)')
    bridge.start()
    process = bridge.process
    started = time.monotonic()
    with pytest.raises(RuntimeError, match='超时'):
        bridge.call('voices', timeout=.1)
    assert process.poll() is not None
    assert time.monotonic() - started < 4


def test_service_falls_back_after_child_crash_and_remembers_failed_voice(app, tmp_path):
    made = []
    def factory():
        made.append(True)
        return subprocess_bridge('import sys,os;sys.stdin.readline();os._exit(23)')
    service = SpeechService(bridge_factory=factory)
    ready, errors, status = [], [], []
    service.ready.connect(lambda *args: ready.append(args))
    service.failed.connect(lambda *args: errors.append(args))
    service.status.connect(status.append)
    try:
        for generation in range(2):
            assert service.synthesize('路口右转', 'zh-CN', '', 0, tmp_path/f'{generation}.wav', generation)
            wait_for(app, lambda: len(ready) == generation + 1 and not service.busy)
            assert ready[-1][1:] == (generation, 'local')
        assert not errors and len(made) == 1
        assert any('切换默认' in s for s in status)
    finally:
        service.close()
        app.processEvents()


def test_local_mode_never_constructs_a_system_voice_host(app, tmp_path):
    def forbidden():
        raise AssertionError('Local mode must not touch SAPI')
    service = SpeechService(bridge_factory=forbidden)
    results = []
    service.ready.connect(lambda *args: results.append(args))
    try:
        service.synthesize('路口左转', 'zh-CN', '', 0, tmp_path/'local.wav', 1, 'local')
        wait_for(app, lambda: bool(results))
        assert results[0][2] == 'local'
    finally:
        service.close()


def test_cancel_terminates_inflight_child_and_discards_late_result(app, tmp_path):
    service = SpeechService(bridge_factory=lambda: subprocess_bridge('import sys,time;sys.stdin.readline();time.sleep(60)'))
    results = []
    service.ready.connect(lambda *args: results.append(args))
    try:
        service.synthesize('路口左转', 'zh-CN', '', 0, tmp_path/'cancel.wav', 1)
        wait_for(app, lambda: service.bridge and service.bridge.process is not None)
        process = service.bridge.process
        service.cancel()
        wait_for(app, lambda: not service.busy)
        assert process.poll() is not None and results == []
        service.synthesize('路口右转', 'zh-CN', '', 0, tmp_path/'next.wav', 2, 'local')
        wait_for(app, lambda: bool(results))
        assert results[0][1:] == (2, 'local')
    finally:
        service.close()


def test_enumeration_crash_is_async_and_nonfatal(app):
    service = SpeechService(bridge_factory=lambda: subprocess_bridge('import sys,os;sys.stdin.readline();os._exit(23)'))
    voices = []
    service.voices_ready.connect(voices.append)
    try:
        service.load_voices()
        wait_for(app, lambda: bool(voices))
        assert voices == [[]]
    finally:
        service.close()


def test_navigation_stop_releases_pending_cues_and_does_not_replay_passed_turn(app, tmp_path, monkeypatch):
    from wardogs_nav.app import MainWindow
    monkeypatch.setenv('WARDOGS_NAV_DATA', str(tmp_path))
    window = MainWindow(start_worker=False)
    try:
        # Hold synthesis pending to exercise the real UI's cancellation receipts.
        monkeypatch.setattr(window.tts.service, 'synthesize', lambda *a, **kw: True)
        settings = default_settings();settings.update(lead_m=120, lead_s=0, arrival_m=5)
        route = Route([[0,0],[500,0]], ['major'], ['road'], 500, [0,0], 0)
        route.junctions = [dict(at=200, delta=90)]
        nav = window.navigator
        nav.start(route, [], settings, 1)
        data = nav.update([100,0], 0)
        ids = data['speech_ids']
        window.speak(data['speech'], (nav, nav.route, nav.lap, ids))
        assert ids <= nav.pending and not nav.spoken
        nav.lost();window.tts.stop()
        assert not nav.pending and not nav.spoken
        assert nav.update([100,0], 1)['speech'] == data['speech']
        nav.pending.clear()
        after = nav.update([250,0], 2)
        assert '右转' not in (after['speech'] or '')
    finally:
        window.close()
        app.processEvents()


def test_completed_navigation_receipt_prevents_repeat(app, tmp_path, monkeypatch):
    from wardogs_nav.app import MainWindow
    monkeypatch.setenv('WARDOGS_NAV_DATA', str(tmp_path))
    window = MainWindow(start_worker=False)
    try:
        monkeypatch.setattr(window.tts.service, 'synthesize', lambda *a, **kw: True)
        route = Route([[0,0],[500,0]], ['major'], ['road'], 500, [0,0], 0)
        nav = window.navigator;nav.start(route, [], default_settings(), 1)
        data = nav.update([0,0], 0)
        window.speak(data['speech'], (nav, route, nav.lap, data['speech_ids']))
        window.tts._complete()
        assert data['speech_ids'] <= nav.spoken and not nav.pending
        nav.lost();window.tts.stop()
        assert nav.update([0,0], 1)['speech'] is None
        assert isinstance(window.tts.player, FilePlayer)
    finally:
        window.close()
        app.processEvents()

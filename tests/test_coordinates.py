import time
from copy import deepcopy
import numpy as np
import pytest
from test_bigmap import app,window,mini,large,until
from wardogs_nav.coordinates import parse_coordinates,format_coordinates,game_to_map,map_to_game,coordinate_system
from wardogs_nav.coordinate_reader import CoordinateFix,CoordinateReader,crosshair
from wardogs_nav.model import default_settings
from wardogs_nav.vision import Fix,MapViewFix
from wardogs_nav.worker import CaptureWorker


@pytest.mark.parametrize('text',['x87.18, y33.31','X:87.18 Y=33.31','（x87.18，y33.31）','87.18/33.31'])
def test_game_coordinate_input(text):
    assert parse_coordinates(text)==[87.18,33.31]
    assert format_coordinates(parse_coordinates(text))=='x87.18, y33.31'


@pytest.mark.parametrize('text',['x87.18','x87.18 y33.31 x90 y40','xB7.18, y33.31','x87.18, yNaN','87,18/33,31','inf/2'])
def test_incomplete_or_ambiguous_input_is_not_guessed(text):
    with pytest.raises(ValueError):parse_coordinates(text)


@pytest.mark.parametrize('map_id',['ozeti','bakurani','zestafona'])
def test_map_coordinate_orientation_and_round_trip(map_id):
    _,b=coordinate_system(map_id)
    game=[(b['minX']+b['maxX'])/2,(b['minY']+b['maxY'])/2]
    point=game_to_map(map_id,game)
    assert map_to_game(map_id,point)==pytest.approx(game)
    assert game_to_map(map_id,[game[0]+1,game[1]])[0]>point[0]
    assert game_to_map(map_id,[game[0],game[1]+1])[1]<point[1]
    with pytest.raises(ValueError):game_to_map(map_id,[0,0])


def test_real_bakurani_sample_matches_independent_terrain_registration():
    assert game_to_map('bakurani',[87.02,33.58])==pytest.approx([1181.8588046,1783.6851249],abs=.3)


def coordinate_view(window,point=(300,100),cursor=(400,200),**changes):
    coordinate=CoordinateFix(map_to_game(window.project['map'],point),list(point),cursor)
    return large(window,valid=False,matrix=None,coordinate=coordinate,**changes)


def test_coordinate_only_hotkey_uses_new_frame_and_waits_for_vehicle(window,monkeypatch):
    coordinate_view(window,point=(200,100))
    assert window.game_map_active() and window.big_view is None and not window.big_overlay.isVisible()
    assert window.last_accepted is None and not window.fix_live
    monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:(400,200))
    window.on_map_hotkey('navigate');actions=window.worker.take_actions()
    assert actions and window.project['destination'] is None
    view=coordinate_view(window)
    window.on_big_map(view,None,actions)
    assert window.project['destination']==[300,100] and window.project['start'] is None
    assert window.pending_start and not window.navigator.active
    assert window.hud.data['text']=='目标已设置'
    mini(window)
    assert window.project['start']==[100,100] and window.navigator.active
    assert window.coordinate_view is None and not window.global_hotkeys.active


def test_coordinate_action_waits_when_mouse_moved(window,monkeypatch):
    coordinate_view(window);monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:(400,200))
    window.on_map_hotkey('destination');actions=window.worker.take_actions()
    before=deepcopy(window.project)
    view=coordinate_view(window,cursor=(460,220))
    window.on_big_map(view,None,actions)
    assert window.project==before and window.worker.map_action
    assert '保持十字位置' in window.big_status.text()


@pytest.mark.parametrize('invalid',['age','session','map','region','foreground','mini'])
def test_coordinate_context_cannot_reuse_old_target(window,monkeypatch,invalid):
    view=coordinate_view(window);before=deepcopy(window.project);queries=[]
    if invalid=='age':view.captured_at-=3
    elif invalid=='session':window.worker.reset_view()
    elif invalid=='map':view.map_id='bakurani'
    elif invalid=='region':view.region=dict(view.region,left=99)
    elif invalid=='foreground':monkeypatch.setattr('wardogs_nav.hotkeys.foreground_window',lambda:999)
    else:window.worker.mode='mini'
    monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:queries.append(1) or (400,200))
    window.on_map_hotkey('destination')
    assert not queries and window.project==before


def test_input_works_before_any_fix_and_invalid_input_preserves_trip(window):
    point=[300,100];window.worker.capture=False
    game=map_to_game(window.project['map'],point)
    window.coordinate_input.setText(f'x{game[0]}, y{game[1]}');window.apply_coordinates()
    assert window.project['destination']==pytest.approx(point) and window.project['start'] is None
    assert format_coordinates(game) in window.destination_label.text()
    before=deepcopy(window.project)
    window.coordinate_input.setText('x0, y0');window.apply_coordinates()
    assert window.project==before and '超出' in window.coordinate_feedback.text()


def test_native_reader_does_not_start_for_blank_or_without_crosshair():
    reader=CoordinateReader()
    try:
        assert reader.read(np.zeros((800,800,3),np.uint8),'ozeti',0) is None
        assert reader.bridge is None
        assert crosshair(np.zeros((800,800,3),np.uint8),(200,200,80,20),(100,100,80,20)) is None
    finally:reader.cleanup()


def test_worker_coordinate_fallback_stops_when_minimap_recovers(app,monkeypatch):
    settings=default_settings();settings['bigmap']['enabled']=True;settings['interval_ms']=200
    worker=CaptureWorker(settings);mode=['mini'];calls={'ocr':0,'big':0,'foreground':0};frames=[];small=[]
    class Source:
        def grab(self,region):return np.zeros((80,80,4),np.uint8)
        def close(self):pass
    class Matcher:
        last=None
        def locate(self,*args):return Fix(valid=mode[0]=='mini')
        def locate_map(self,*args):calls['big']+=1;return MapViewFix(valid=False)
    def read(*args):calls['ocr']+=1;return CoordinateFix([87,33],[200,100],(20,30))
    def foreground():calls['foreground']+=1;return 123
    monkeypatch.setattr('mss.MSS',Source);monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Matcher())
    monkeypatch.setattr(worker.coordinates,'read',read);monkeypatch.setattr('wardogs_nav.worker.foreground_window',foreground)
    worker.result.connect(lambda *args:small.append(args));worker.map_result.connect(lambda *args:frames.append(args))
    worker.capture=True;worker.start()
    try:
        until(app,lambda:len(small)>=2);assert not any(calls.values())
        mode[0]='big';worker.request_action('destination',(20,30),123)
        until(app,lambda:bool(frames))
        assert frames[-1][0].coordinate and not frames[-1][0].valid and frames[-1][2]
        mode[0]='mini';worker.wake.set();until(app,lambda:small[-1][0].valid)
        counts=dict(calls);n=len(small);until(app,lambda:len(small)>n+1)
        assert counts==calls
    finally:worker.shutdown()

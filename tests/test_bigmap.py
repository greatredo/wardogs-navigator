import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import threading
import time
import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from wardogs_nav.app import MainWindow
from wardogs_nav.bigmap import BigMapOverlay
from wardogs_nav.hotkeys import parse_hotkey
from wardogs_nav.maps import map_asset
from wardogs_nav.model import default_settings,load_settings,atomic_json
from wardogs_nav.vision import Fix,MapViewFix,Locator,read_image,feature_mask
from wardogs_nav.worker import CaptureWorker


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path/'data'))
    monkeypatch.setattr('wardogs_nav.hotkeys.foreground_window',lambda:123)
    w=MainWindow(start_worker=False);w.settings['voice']=False
    w.project.update(roads=[dict(id='line',name='路',kind='major',points=[[100,100],[200,100],[300,100]],confirmed=True)],
                     start=None,destination=None,waypoints=[],avoid=[],notes=[],destinations=[],meters_per_pixel=1,roundtrip=True)
    w.settings['bigmap']['enabled']=True;w.worker.capture=True
    w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def mini(window,x=100):
    window.worker.mode='mini'
    window.on_fix(Fix(x=x,y=100,scale=.5,confidence=1,valid=True,map_id=window.project['map'],generation=window.worker.context[1]),np.zeros((80,80,3),np.uint8),True)


def large(window,**kwargs):
    window.worker.mode='big'
    view=MapViewFix(matrix=np.array([[.5,0,0],[0,.5,0]]),frame_size=(800,800),valid=True,
        map_id=window.project['map'],generation=window.worker.context[1],session=window.worker.session,
        region=dict(window.settings['bigmap_capture']),captured_at=time.monotonic(),foreground=123)
    for key,value in kwargs.items():setattr(view,key,value)
    window.on_big_map(view,None)
    return view


def until(app,predicate,timeout=8):
    deadline=time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:app.processEvents();time.sleep(.005)
    app.processEvents();assert predicate()


def test_view_transform_physical_pixels_negative_monitor_origin():
    mat=np.array([[.2,-.004,880],[.004,.2,830]])
    view=MapViewFix(matrix=mat,valid=True,frame_size=(1000,800),region=dict(left=-1600,top=180,width=1000,height=800))
    expected=mat@[450,300,1]
    assert view.screen_to_map((-1150,480))==pytest.approx(expected)
    assert view.project([expected])[0]==pytest.approx((450,300))
    assert view.screen_to_map((-600,480)) is None
    assert view.screen_to_map((-1601,480)) is None


def test_locator_pan_zoom_independent_from_vehicle():
    locator=Locator.from_assets('zestafona');image=read_image(map_asset('zestafona','image'))
    vehicle=Fix(x=150,y=180,scale=.4,valid=True);locator.last=vehicle
    for x,y,size in [(850,780,260),(895,815,170),(930,850,80)]:
        frame=cv2.resize(image[y:y+size,x:x+size],(850,850))
        result=locator.locate_map(frame)
        assert result.valid,result.reason
        expected=[x+size*.5,y+size*.5]
        assert result.matrix@[425,425,1]==pytest.approx(expected,abs=.8)
        assert locator.last is vehicle
    assert not locator.locate_map(np.zeros((850,850,3),np.uint8)).valid


def test_worker_has_zero_bigmap_work_when_mini_valid_then_recovers(app,monkeypatch):
    settings=default_settings();settings['bigmap']['enabled']=True;settings['interval_ms']=200
    settings['capture']=dict(left=0,top=0,width=80,height=80)
    settings['bigmap_capture']=dict(left=100,top=100,width=160,height=160)
    worker=CaptureWorker(settings);mode=['mini'];calls=dict(mini=0,big=0,foreground=0)
    class Source:
        def grab(self,region):
            key='mini' if region['width']==80 else 'big';calls[key]+=1
            return np.zeros((region['height'],region['width'],4),np.uint8)
        def close(self):pass
    class Matcher:
        last=None
        def locate(self,*args):return Fix(valid=mode[0]=='mini')
        def locate_map(self,*args):return MapViewFix(matrix=np.eye(2,3),valid=mode[0]=='big',frame_size=(160,160))
    def foreground():calls['foreground']+=1;return 123
    monkeypatch.setattr('mss.MSS',Source);monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Matcher())
    monkeypatch.setattr('wardogs_nav.worker.foreground_window',foreground)
    small=[];big=[];worker.result.connect(lambda *args:small.append(args));worker.map_result.connect(lambda *args:big.append(args))
    worker.capture=True;worker.start()
    try:
        until(app,lambda:len(small)>=3)
        assert calls['big']==calls['foreground']==0 and not big
        mode[0]='big';worker.wake.set();until(app,lambda:bool(big))
        assert big[-1][0].valid and calls['big']>0
        mode[0]='lost';worker.wake.set();until(app,lambda:not big[-1][0].valid)
        mode[0]='mini';worker.wake.set();until(app,lambda:small[-1][0].valid)
        count=(calls['big'],calls['foreground']);n=len(small)
        until(app,lambda:len(small)>n+1)
        assert (calls['big'],calls['foreground'])==count
    finally:worker.shutdown()


@pytest.mark.parametrize('change',['stop','region','map'])
def test_inflight_bigmap_discarded_on_context_change(app,monkeypatch,change):
    settings=default_settings();settings['bigmap']['enabled']=True
    worker=CaptureWorker(settings);entered=threading.Event();release=threading.Event();results=[]
    class Source:
        def grab(self,region):return np.zeros((80,80,4),np.uint8)
        def close(self):pass
    class Matcher:
        last=None
        def locate(self,*args):return Fix()
        def locate_map(self,*args):entered.set();release.wait(8);return MapViewFix(valid=True)
    monkeypatch.setattr('mss.MSS',Source);monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Matcher())
    monkeypatch.setattr('wardogs_nav.worker.foreground_window',lambda:123)
    worker.map_result.connect(lambda *args:results.append(args));worker.capture=True;worker.start()
    try:
        until(app,entered.is_set)
        if change=='stop':worker.capture=False;worker.reset_view()
        elif change=='region':settings['bigmap_capture']['left']=400;worker.reset_view();worker.capture=False
        else:worker.request_map('bakurani')
        release.set();worker.shutdown();app.processEvents();assert not results
    finally:release.set();worker.shutdown()


def test_mini_stops_mouse_and_hotkeys_before_any_cursor_read(window,monkeypatch):
    mini(window);large(window)
    assert window.cursor_timer.isActive()
    queried=[];monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:queried.append(1) or (200,200))
    mini(window)
    window.poll_map_cursor();window.on_map_hotkey('navigate')
    assert not queried and not window.cursor_timer.isActive() and not window.global_hotkeys.active
    assert not window.big_overlay.isVisible() and window.worker.map_action is None


@pytest.mark.parametrize('invalid',['capture','foreground','region','generation'])
def test_invalid_view_cannot_use_cursor_or_change_trip(window,monkeypatch,invalid):
    mini(window);view=large(window);before=deepcopy(window.project)
    if invalid=='capture':window.worker.capture=False
    elif invalid=='foreground':monkeypatch.setattr('wardogs_nav.hotkeys.foreground_window',lambda:999)
    elif invalid=='region':window.worker.reset_view()
    else:window.worker.request_map('bakurani')
    calls=[];monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:calls.append(1))
    window.poll_map_cursor();window.on_map_hotkey('navigate')
    assert not calls and window.project==before and not window.big_overlay.isVisible()


def test_hotkey_waits_for_new_transform(window,monkeypatch):
    mini(window);large(window)
    monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:(400,200))
    window.on_map_hotkey('navigate');action=window.worker.map_action
    assert window.project['destination'] is None and action
    view=large(window,matrix=np.array([[.5,0,100],[0,.5,0]]))
    window.on_big_map(view,None,[action])
    assert window.project['destination']==pytest.approx([300,100])
    assert window.project['start']==[100,100] and window.pending_start
    assert not window.navigator.active
    mini(window,110)
    assert window.navigator.active and window.project['start']==[100,100]


def test_last_vehicle_remains_origin_after_long_bigmap_session(window,monkeypatch):
    mini(window);window.last_accepted_time-=3600;large(window)
    vehicles=[];render=window.big_overlay.update_map
    def recorded(*args):vehicles.append(args[5]);return render(*args)
    monkeypatch.setattr(window.big_overlay,'update_map',recorded)
    window.update_big_overlay();assert vehicles[-1]==[100,100]
    window.project['start']=[50,50];window.project['waypoints']=[[150,100]]
    window.apply_map_action('navigate',[300,100])
    assert window.project['start']==[100,100] and window.project['waypoints']==[] and window.pending_start
    mini(window,200)
    assert window.project['start']==[100,100] and window.navigator.active


def test_failed_bigmap_keeps_surface_hotkeys_and_recovers(window,monkeypatch):
    mini(window);large(window)
    view=window.big_view;view.captured_at-=10
    large(window,valid=False,reason='地形被遮挡')
    assert window.big_overlay.isVisible() and window.cursor_timer.isActive() and window.global_hotkeys.active
    assert window.big_view is view and window.hud.data['state']=='bigmap'
    assert '识别中' in window.fix_label.text() and window.hud.localization_text==window.fix_label.text()
    calls=[];monkeypatch.setattr('wardogs_nav.hotkeys.physical_cursor',lambda:calls.append(1) or (400,200))
    window.poll_map_cursor();assert not calls  # No cursor polling against stale geometry.
    window.on_map_hotkey('destination');assert window.worker.map_action and window.project['destination'] is None
    action=window.worker.take_actions();view=large(window,confidence=.82)
    window.on_big_map(view,None,action)
    assert window.project['destination']==[200,100] and '82%' in window.hud.localization_text
    mini(window);assert not window.big_overlay.isVisible() and not window.global_hotkeys.active


def test_no_previous_vehicle_gets_start_on_first_mini_fix(window):
    large(window);window.apply_map_action('navigate',[300,100])
    assert window.project['start'] is None and window.pending_start
    mini(window,100)
    assert window.project['start']==[100,100] and window.navigator.active


def test_worker_retries_multiple_hotkeys_until_a_valid_frame(app,monkeypatch):
    settings=default_settings();settings['bigmap']['enabled']=True;settings['interval_ms']=200
    worker=CaptureWorker(settings);valid=[False];frames=[];failures=[]
    class Source:
        def grab(self,region):return np.zeros((80,80,4),np.uint8)
        def close(self):pass
    class Matcher:
        last=None
        def locate(self,*args):return Fix()
        def locate_map(self,*args):return MapViewFix(valid=valid[0],matrix=np.eye(2,3),frame_size=(80,80))
    monkeypatch.setattr('mss.MSS',Source);monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Matcher())
    monkeypatch.setattr('wardogs_nav.worker.foreground_window',lambda:123)
    worker.map_result.connect(lambda *args:frames.append(args));worker.action_failed.connect(failures.append)
    worker.capture=True
    worker.request_action('destination',(20,30),123);worker.request_action('waypoint',(40,50),123)
    worker.start()
    try:
        until(app,lambda:len(frames)>=2)
        assert all(not item[2] for item in frames) and worker.map_action and not failures
        valid[0]=True;worker.wake.set();until(app,lambda:any(item[2] for item in frames))
        actions=next(item[2] for item in frames if item[2])
        assert [a[1:3] for a in actions]==[('destination',(20,30)),('waypoint',(40,50))]
        worker.request_action('start',(60,70),123);worker.wake.set()
        until(app,lambda:any(item[2] and item[2][0][1]=='start' for item in frames))
        assert not failures
    finally:worker.shutdown()


def test_expired_hotkey_reports_failure_instead_of_silently_disappearing(window):
    failures=[];window.worker.action_failed.connect(failures.append)
    old=(window.worker.session,'destination',(400,200),123,time.monotonic()-7)
    window.worker.retry_actions([old],123)
    assert failures and window.worker.map_action is None
    assert '已取消' in window.big_message


def test_full_hotkey_queue_reports_rejection_and_remains_bounded(window):
    for _ in range(8):assert window.worker.request_action('waypoint',(400,200),123)
    pending=window.worker.take_actions()
    for _ in range(8):assert window.worker.request_action('destination',(400,200),123)
    assert not window.worker.request_action('start',(400,200),123)
    assert '较多' in window.big_message
    window.worker.retry_actions(pending,123)
    actions=window.worker.take_actions()
    assert len(actions)==8 and all(a[1]=='waypoint' for a in actions)
    assert '取消' in window.big_message


def test_blocked_new_trip_reports_failure_when_mini_returns(window):
    mini(window);large(window)
    window.project['avoid']=[dict(point=[300,100],radius=10)]
    window.apply_map_action('navigate',[300,100]);mini(window)
    assert not window.navigator.active and not window.pending_start
    assert window.hud.data['state']=='offroute' and '无可行路线' in window.hud.data['text']


def test_bigmap_pan_does_not_move_vehicle_or_progress(window):
    mini(window);window.project['destination']=[300,100];window.begin_navigation();mini(window,140)
    original=list(window.last_accepted);progress=window.navigator.progress;start=window.project['start'][:]
    for offset in (400,600,900):large(window,matrix=np.array([[.1,0,offset],[0,.1,800]]))
    assert window.last_accepted==original and window.project['start']==start
    assert window.navigator.progress==progress and window.navigator.active and not window.fix_live


def test_edit_return_endpoint_resumes_same_leg_and_clear_keeps_hud(window):
    mini(window);window.project['destination']=[300,100];window.begin_navigation()
    window.navigator.lap=1;window.navigator.leg='返程';window.route=window.route.reversed();window.navigator.route=window.route
    large(window);window.apply_map_action('start',[120,100])
    assert window.big_resume['lap']==1 and window.route.points[-1]==pytest.approx([120,100])
    window.apply_map_action('destination',[280,100])
    assert window.project['start']==[120,100] and window.big_resume['lap']==1
    for _ in range(3):mini(window,250)  # Preserve the existing jump-confirmation gate.
    assert window.navigator.active and window.navigator.leg=='返程' and window.navigator.lap==1
    assert window.route.points[-1]==pytest.approx([120,100])
    large(window);window.hud.show();window.apply_map_action('clear',[200,100])
    assert window.project['start'] is None and window.project['destination'] is None
    assert not window.navigator.active and not window.big_resume and not window.pending_start
    assert window.hud.isVisible() and window.big_overlay.isVisible()


def test_nonroad_overlay_mask_covers_labels_and_does_not_draw_roads(window):
    mini(window);view=large(window)
    window.project.update(start=[100,100],destination=[300,100],waypoints=[[200,100]],
        avoid=[dict(shape='rect',point=[220,220],width=40,height=30)],
        notes=[dict(point=[150,200],type='caution',text='桥梁')])
    overlay=window.big_overlay;overlay.capture_excluded=False;masks=[];overlay.mask_changed.connect(masks.append)
    overlay.update_map(view,window.project)
    pixels=np.frombuffer(overlay.surface.constBits(),np.uint8).reshape(800,800,4)
    assert np.array_equal(masks[-1],pixels[:,:,3])
    mask=feature_mask(np.zeros((800,800,3),np.uint8),minimap=False,path_mask=masks[-1])
    assert np.all(mask[pixels[:,:,3]>0]==0)
    assert pixels[200,250,3]==0  # Between markers: the road itself is absent.
    assert pixels[200,200,3]>0 and pixels[200,600,3]>0


def test_hotkey_parser_and_settings_roundtrip(tmp_path,monkeypatch):
    assert parse_hotkey('Ctrl+Alt+N')==(0x4003,ord('N'))
    assert parse_hotkey('Alt+F11')==(0x4001,0x7A)
    assert parse_hotkey('') is None
    for text in ('N','Shift+N','Ctrl+F12','Win+N','Ctrl+Ctrl+N','Ctrl+A, Ctrl+B'):
        with pytest.raises(ValueError):parse_hotkey(text)
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    settings=default_settings();settings['bigmap']['enabled']=True;settings['bigmap_capture']['left']=-1600
    settings['bigmap_hotkeys']['navigate']='Alt+F8';atomic_json(tmp_path/'settings.json',settings)
    assert load_settings()==settings

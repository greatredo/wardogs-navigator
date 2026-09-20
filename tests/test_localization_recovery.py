"""Recovery through the production worker and UI, with isolated synthetic frames."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from copy import deepcopy
import json
import threading
import time
import cv2
import numpy as np
import pytest
from PySide6.QtWidgets import QApplication,QFileDialog
from wardogs_nav.app import MainWindow
from wardogs_nav.model import default_settings
from wardogs_nav.vision import Fix
from wardogs_nav.worker import CaptureWorker


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path/'config'))
    w=MainWindow(start_worker=False)
    w.settings['voice']=False
    w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def until(app,predicate,timeout=8):
    deadline=time.monotonic()+timeout
    while not predicate() and time.monotonic()<deadline:
        app.processEvents()
        time.sleep(.005)  # Yield Python execution to the real QThread.
    app.processEvents()
    assert predicate()


def good_fix(worker,x=505,y=1245):
    return Fix(x=x,y=y,confidence=1,inliers=40,scale=.4,valid=True,
               map_id=worker.context[0],generation=worker.context[1])


class FrameSource:
    """Replace only the screen input; never capture a user's desktop in tests."""
    def __init__(self):self.count=0;self.closed=False;self.error_at=set()
    def grab(self,region):
        self.count+=1
        if self.count in self.error_at:raise OSError('temporary capture failure')
        return np.full((80,80,4),min(self.count,200),np.uint8)
    def close(self):self.closed=True


@pytest.mark.parametrize('roundtrip',[False,True])
def test_live_worker_recovers_after_frame_failure(window,app,monkeypatch,roundtrip):
    source=FrameSource()
    fail_now=threading.Event();recover_now=threading.Event()
    class Localizer:
        last=None
        def locate(self,frame,*args):
            if int(frame[0,0,0])==2:
                fail_now.wait(10)
                raise cv2.error('synthetic frame failure')
            if int(frame[0,0,0])==3:recover_now.wait(10)
            return good_fix(window.worker)
    monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Localizer())
    monkeypatch.setattr('mss.MSS',lambda:source)
    window.settings['interval_ms']=200
    window.project['destination']=[1300,796];window.project['roundtrip']=roundtrip
    project=deepcopy(window.project)
    window.worker.start()
    try:
        window.start_navigation()
        until(app,lambda:window.navigator.active and window.fix_live)
        project['start']=[505,1245]
        fail_now.set()
        until(app,lambda:window.fix is not None and not window.fix.valid)
        assert window.worker.capture and window.worker.isRunning()
        assert not window.fix_live and '100%' not in window.fix_label.text()
        assert window.map.player_item is None and not window.minimap_overlay.isVisible()
        assert window.capture_button.text()=='关闭定位'
        assert window.navigator.active and window.navigator.last_point is None
        recover_now.set()
        until(app,lambda:source.count>=3 and window.fix_live)
        assert window.navigator.active and window.navigator.roundtrip==roundtrip
        assert window.project==project and window.project['start']==[505,1245]
    finally:
        fail_now.set();recover_now.set();window.worker.shutdown()


@pytest.mark.parametrize('navigating',[False,True])
def test_timeout_clears_live_fix_even_without_navigation(window,navigating):
    window.worker.capture=True
    window.on_fix(good_fix(window.worker),np.zeros((80,80,3),np.uint8),True)
    if navigating:
        window.project['destination']=[1300,796];window.begin_navigation()
    window.fix_time=time.monotonic()-3
    window.check_stale()
    assert not window.fix.valid and not window.fix_live
    assert '100%' not in window.fix_label.text()
    assert window.map.player_item is None and not window.minimap_overlay.isVisible()
    assert window.hud.data['state']=='lost'
    assert window.navigator.active==navigating and window.worker.capture


def test_fatal_error_clears_old_fix_and_frame(window):
    window.worker.capture=True
    window.on_fix(good_fix(window.worker),np.ones((80,80,3),np.uint8),True)
    window.worker.capture=False
    window.worker_error('地图特征初始化失败','ozeti',0)
    assert not window.fix.valid and not window.fix_live and window.frame is None
    assert window.map.player_item is None and '100%' not in window.fix_label.text()
    assert window.capture_button.text()=='开启定位'


def test_failed_frame_is_saved_after_recovery(window,tmp_path,monkeypatch):
    window.worker.capture=True
    failed=np.full((80,80,3),23,np.uint8)
    window.on_fix(good_fix(window.worker),np.zeros_like(failed),True)
    failure=Fix(reason='synthetic locate failure',map_id='ozeti',generation=0)
    window.on_fix(failure,failed,True)
    window.on_fix(good_fix(window.worker),np.full_like(failed,99),True)
    target=tmp_path/'失败帧.png'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),''))
    window.save_capture_diagnostic()
    saved=cv2.imdecode(np.fromfile(str(target),np.uint8),cv2.IMREAD_COLOR)
    metadata=json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
    assert np.array_equal(saved,failed)
    assert metadata['fix']['reason']=='synthetic locate failure' and not metadata['fix']['valid']
    assert metadata['selected']=='latest_failure' and metadata['current_fix']['valid']
    assert metadata['frame_available'] and metadata['source']=='live'


def test_capture_failure_without_frame_saves_only_json(window,tmp_path,monkeypatch):
    window.worker.capture=True
    window.on_fix(good_fix(window.worker),np.ones((80,80,3),np.uint8),True)
    window.on_fix(Fix(reason='capture unavailable',map_id='ozeti'),None,True)
    assert window.frame is None and not window.fix.valid
    target=tmp_path/'截图失败.json'
    monkeypatch.setattr(QFileDialog,'getSaveFileName',lambda *a,**k:(str(target),''))
    window.save_capture_diagnostic()
    metadata=json.loads(target.read_text(encoding='utf-8'))
    assert not metadata['frame_available'] and not metadata['fix']['valid']
    assert not target.with_suffix('.png').exists()


def test_diagnostic_selection_survives_new_result_during_save_dialog(window,tmp_path,monkeypatch):
    window.worker.capture=True
    original=np.full((80,80,3),12,np.uint8)
    window.on_fix(good_fix(window.worker),original,True)
    target=tmp_path/'dialog.png'
    def choose(*args,**kwargs):
        window.on_fix(Fix(reason='new failure',map_id='ozeti'),np.full_like(original,55),True)
        return str(target),''
    monkeypatch.setattr(QFileDialog,'getSaveFileName',choose)
    window.save_capture_diagnostic()
    metadata=json.loads(target.with_suffix('.json').read_text(encoding='utf-8'))
    assert metadata['selected']=='latest_frame' and metadata['fix']['valid']
    assert not metadata['current_fix']['valid']
    assert np.array_equal(cv2.imdecode(np.fromfile(str(target),np.uint8),cv2.IMREAD_COLOR),original)


def test_stopped_capture_ignores_late_frame_and_error(window):
    window.worker.capture=True
    initial=np.ones((80,80,3),np.uint8)
    window.on_fix(good_fix(window.worker),initial,True)
    window.toggle_capture()
    assert not window.worker.capture and not window.fix.valid
    label=window.fix_label.text()
    for fix in [good_fix(window.worker),Fix(reason='late error',map_id='ozeti')]:
        window.on_fix(fix,np.full_like(initial,99),True)
    assert window.frame is initial and window.fix_label.text()==label
    assert not window.fix_live and not window.navigator.active


def test_map_generation_discards_late_failures(window):
    window.worker.capture=True
    window.on_fix(Fix(reason='first map failure',map_id='ozeti'),np.ones((80,80,3),np.uint8),True)
    window.switch_map('bakurani');window.switch_map('ozeti')
    window.worker.capture=True
    window.on_fix(good_fix(window.worker),np.full((80,80,3),4,np.uint8),True)
    label=window.fix_label.text();frame=window.frame
    window.on_fix(Fix(reason='old generation failure',map_id='ozeti',generation=0),None,True)
    window.worker_error('old initialization failure','ozeti',0)
    assert window.frame is frame and window.fix_label.text()==label and window.fix_live
    assert window.failure_diagnostic is None


@pytest.mark.parametrize('roundtrip',[False,True])
def test_recovery_near_arrival_keeps_journey_and_return_leg(window,roundtrip):
    window.project['roads']=[dict(id='line',name='line',kind='major',points=[[100,100],[200,100]])]
    window.project['meters_per_pixel']=1
    window.project['destination']=[200,100];window.project['waypoints']=[]
    window.project['roundtrip']=roundtrip;window.worker.capture=True
    frame=np.zeros((80,80,3),np.uint8)
    window.on_fix(good_fix(window.worker,100,100),frame,True);window.begin_navigation()
    window.on_fix(good_fix(window.worker,160,100),frame,True)
    window.on_fix(Fix(reason='temporary obstruction',map_id='ozeti'),frame,True)
    for _ in range(2):window.on_fix(good_fix(window.worker,200,100),frame,True)
    assert window.project['destination']==[200,100] and window.project['start']==[100,100]
    if roundtrip:
        assert window.navigator.active and window.navigator.lap==1 and window.navigator.leg=='返程'
        assert window.route.points[-1]==pytest.approx([100,100])
    else:assert not window.navigator.active and window.hud.data['state']=='arrived'


def test_hud_localization_recovers_without_starting_navigation(window):
    window.worker.capture=True;frame=np.zeros((80,80,3),np.uint8)
    window.on_fix(Fix(reason='temporary obstruction'),frame,True)
    assert window.hud.data['state']=='lost'
    window.on_fix(good_fix(window.worker),frame,True)
    assert not window.navigator.active and window.hud.data['state']=='idle'
    assert window.hud.localization_text==window.fix_label.text()=='实时定位 · 100%'


def test_capture_restart_restores_hud_title_without_navigation(window):
    frame=np.zeros((80,80,3),np.uint8)
    window.worker.capture=True;window.toggle_capture()
    assert window.hud.data['text']=='定位已关闭'
    window.toggle_capture()
    assert window.hud.data['state']=='locating'
    window.on_fix(good_fix(window.worker),frame,True)
    assert window.fix_live and not window.navigator.active
    assert window.hud.data['text']=='等待导航'
    assert window.hud.localization_text==window.fix_label.text()=='实时定位 · 100%'


def test_failed_replan_waits_and_resumes_same_return_trip(window,monkeypatch):
    window.project.update(roads=[dict(id='line',name='line',kind='major',points=[[100,100],[600,100]])],
                          start=[100,100],destination=[600,100],waypoints=[[250,100]],meters_per_pixel=1,roundtrip=True)
    window.fix=Fix(x=500,y=100,valid=True);window.fix_live=True
    assert window.plan_route(quiet=True,anchors=[[500,100],[250,100],[100,100]])
    window.start_trip_navigation(1,'返程');saved=deepcopy(window.project)
    original=window.plan_route;calls=[]
    def recorded(*args,**kwargs):calls.append(kwargs.get('anchors'));return original(*args,**kwargs)
    monkeypatch.setattr(window,'plan_route',recorded)
    window.fix=Fix(x=500,y=200,valid=True);window.replan_navigation()
    assert window.navigator.active and window.navigator.waiting_for_road and window.route
    for t in range(20):
        assert not window.navigator.update([500,200],time.monotonic()+t,100).get('replan')
    assert len(calls)==1 and window.project==saved and window.navigator.lap==1
    assert window.navigator.update([500,110],time.monotonic()+21,10)['replan']
    window.fix=Fix(x=500,y=110,valid=True);window.replan_navigation()
    assert not window.navigator.waiting_for_road and window.navigator.active
    assert window.navigator.lap==1 and window.navigator.leg=='返程' and window.project==saved
    assert calls[-1]==[[500,110],[250,100],[100,100]]
    assert window.route.points[-1]==pytest.approx([100,100])


def test_arrival_radius_control_saves_and_updates_running_trip(window):
    from wardogs_nav.model import load_settings
    window.arrival_radius.setValue(180)
    assert window.settings['arrival_m']==180 and load_settings()['arrival_m']==180


def test_real_worker_retries_capture_errors_and_stops_for_invalid_region(app,monkeypatch):
    source=FrameSource();source.error_at={2}
    worker=CaptureWorker(default_settings());worker.settings['interval_ms']=200
    class Localizer:
        last=None
        def locate(self,*args):return good_fix(worker)
    monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Localizer())
    monkeypatch.setattr('mss.MSS',lambda:source)
    results=[];errors=[]
    worker.result.connect(lambda fix,frame,live:results.append((fix,frame,live)))
    worker.failed.connect(lambda *args:errors.append(args))
    worker.capture=True;worker.start()
    try:
        until(app,lambda:len(results)>=3)
        assert [r[0].valid for r in results[:3]]==[True,False,True]
        assert results[1][1] is None and worker.capture
        worker.settings['capture']['width']=20;worker.wake.set()
        until(app,lambda:bool(errors))
        assert not worker.capture and '60' in errors[-1][0]
        count=source.count
        time.sleep(.3);app.processEvents();assert source.count==count
    finally:worker.shutdown()
    assert source.closed


def test_worker_initialization_failure_is_terminal(app,monkeypatch):
    worker=CaptureWorker(default_settings());worker.capture=True
    errors=[]
    def fail(*_):raise OSError('missing map features')
    monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',fail)
    worker.failed.connect(lambda *args:errors.append(args))
    worker.start()
    try:
        until(app,lambda:bool(errors))
        assert not worker.capture and '地图特征初始化失败' in errors[0][0]
    finally:worker.shutdown()


@pytest.mark.parametrize('change',['stop','map'])
@pytest.mark.parametrize('outcome',['success','failure'])
def test_worker_discards_inflight_frame_after_stop_or_map_change(app,monkeypatch,change,outcome):
    entered=threading.Event();release=threading.Event()
    source=FrameSource()
    worker=CaptureWorker(default_settings());worker.settings['interval_ms']=200
    class Localizer:
        last=None
        def locate(self,*args):
            entered.set();release.wait(10)
            if outcome=='failure':raise RuntimeError('late frame')
            return good_fix(worker)
    monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Localizer())
    monkeypatch.setattr('mss.MSS',lambda:source)
    results=[];errors=[];ready=[]
    worker.result.connect(lambda *args:results.append(args))
    worker.failed.connect(lambda *args:errors.append(args))
    worker.ready.connect(lambda *args:ready.append(args))
    worker.capture=True;worker.start()
    try:
        until(app,entered.is_set)
        if change=='map':worker.request_map('bakurani')
        else:worker.capture=False
        release.set()
        if change=='map':until(app,lambda:worker.context in ready)
        worker.shutdown();app.processEvents()
        assert not results and not errors and not worker.capture
    finally:release.set();worker.shutdown()


def test_failed_image_sample_returns_no_frame_without_enabling_capture(app,monkeypatch,tmp_path):
    worker=CaptureWorker(default_settings());results=[]
    class Localizer:last=None
    monkeypatch.setattr('wardogs_nav.worker.Locator.from_assets',lambda *_:Localizer())
    worker.result.connect(lambda *args:results.append(args))
    worker.request_sample(tmp_path/'missing.png');worker.start()
    try:
        until(app,lambda:bool(results))
        fix,frame,live=results[0]
        assert not fix.valid and frame is None and not live and not worker.capture
        assert (fix.map_id,fix.generation)==worker.context
    finally:worker.shutdown()

import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import json
import time
from copy import deepcopy
import cv2
import pytest
from PySide6.QtWidgets import QApplication,QFileDialog
from PySide6.QtCore import Qt,QPointF
from PySide6.QtTest import QTest
from wardogs_nav.app import MainWindow
from wardogs_nav.maps import all_maps,map_info,map_asset,project_path,load_map_project
from wardogs_nav.model import default_settings,read_project,validate_project,atomic_json,load_settings
from wardogs_nav.library import library_payload,merge_library,saved_route,follow_saved
from wardogs_nav.routing import plan,distance
from wardogs_nav.vision import Fix,Locator,read_image
from wardogs_nav.worker import CaptureWorker


@pytest.fixture(scope='module')
def app():return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app,tmp_path,monkeypatch):
    monkeypatch.setenv('WARDOGS_NAV_DATA',str(tmp_path))
    w=MainWindow(start_worker=False);w.show();app.processEvents()
    yield w
    w.close();app.processEvents()


def test_map_switch_preserves_each_project_and_remembers_selection(window,app,tmp_path):
    snapshots={}
    for index,mid in enumerate(['ozeti','bakurani','zestafona']):
        window.map_combo.setCurrentIndex(window.map_combo.findData(mid));app.processEvents()
        assert window.project['map']==mid
        window.project['roads'][0]['name']='自绘道路 '+mid
        window.project['destination']=[100+index,200]
        window.project['avoid']=[dict(shape='rect',point=[400,400],width=30,height=20)]
        window.project['notes']=[dict(id='note',type='left',grade=3,point=[400,420],direction='both')]
        window.project['route_library']=[dict(id='route',name='收藏 '+mid,points=[[20,20],[30,20]],kinds=['offroad'])]
        window.project['meters_per_pixel']=2.+index
        window.project['policy']['allowed']=['minor']
        snapshots[mid]=validate_project(window.project)
    assert project_path('ozeti')==tmp_path/'project.json'
    for mid in ['ozeti','bakurani','zestafona']:
        assert window.switch_map(mid)
        assert window.project==snapshots[mid]
        assert window.map.pixmap.width()==map_info(mid)['width']
        assert window.kind_checks['minor'].isChecked() and not window.kind_checks['major'].isChecked()
    window.save_project()
    assert all(load_map_project(mid)==data for mid,data in snapshots.items())
    assert load_settings()['map_id']=='zestafona'
    restored=MainWindow(start_worker=False)
    try:
        assert restored.project==snapshots['zestafona']
        assert restored.map_combo.currentData()=='zestafona'
    finally:restored.close()


def test_switch_stops_navigation_and_discards_inflight_results_even_after_return(window):
    frame=read_image(map_asset('ozeti','image'))[100:200,100:200]
    window.fix=Fix(x=505,y=1245,valid=True);window.fix_live=True
    window.project['destination']=[1300,796];assert window.plan_route()
    window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'])
    window.pending_start=True;window.home=[505,1245];window.worker.capture=True
    window.worker.path_mask={'points':[[1,2],[3,4]],'width':4}
    window.set_tool('road');window.map.draft=[[500,500]];window.snapshot()
    assert window.switch_map('bakurani')
    assert not window.navigator.active and not window.worker.capture and not window.pending_start
    assert window.fix is None and window.route is None and window.home is None and window.frame is None
    assert not window.map.draft and not window.history and window.worker.path_mask is None
    assert not window.minimap_overlay.isVisible()
    assert window.switch_map('ozeti')
    label=window.fix_detail.text();status=window.statusBar().currentMessage()
    window.on_fix(Fix(x=50,y=50,valid=True,map_id='ozeti',generation=0),frame,False)
    window.worker_ready('ozeti',0);window.worker_error('旧地图错误','ozeti',0)
    assert window.fix is None and window.fix_detail.text()==label
    assert window.statusBar().currentMessage()==status
    mid,generation=window.worker.context
    window.on_fix(Fix(x=50,y=50,valid=True,map_id=mid,generation=generation),frame,False)
    assert window.fix.valid and window.fix.x==50


def test_full_config_import_switches_map_and_libraries_reject_wrong_map(window,tmp_path,monkeypatch):
    ozeti=deepcopy(window.project)
    bak=read_project(map_asset('bakurani','project'));bak['destination']=[1800,1800]
    path=tmp_path/'另一张地图.json';atomic_json(path,bak)
    monkeypatch.setattr(QFileDialog,'getOpenFileName',lambda *a,**k:(str(path),''))
    window.import_project()
    assert window.project==bak and window.map_combo.currentData()=='bakurani'
    assert load_map_project('ozeti')==ozeti
    for kind in ('roads','routes'):
        payload=library_payload(bak,kind);assert payload['map']=='bakurani'
        with pytest.raises(ValueError,match='地图'):merge_library(ozeti,payload,kind)
    assert window.switch_map('ozeti') and window.project==ozeti


def test_failed_switch_keeps_current_map_and_user_changes(window,monkeypatch):
    window.project['destination']=[777,777]
    old=deepcopy(window.project)
    monkeypatch.setattr(window,'save_project',lambda:False)
    window.map_combo.setCurrentIndex(window.map_combo.findData('bakurani'))
    assert window.map_combo.currentData()=='ozeti' and window.project==old


def test_new_map_supports_drawing_and_dragging_beyond_ozeti_bounds(window,app):
    assert window.switch_map('bakurani')
    window.project['destination']=[1800,1700];window.refresh_map();window.map.fit();app.processEvents()
    start=window.map.mapFromScene(QPointF(1800,1700));end=window.map.mapFromScene(QPointF(1950,1900))
    QTest.mousePress(window.map.viewport(),Qt.LeftButton,pos=start)
    QTest.mouseMove(window.map.viewport(),end,60)
    QTest.mouseRelease(window.map.viewport(),Qt.LeftButton,pos=end);app.processEvents()
    assert window.project['destination']==pytest.approx([1950,1900],abs=8)
    assert validate_project(window.project)['map']=='bakurani'
    window.project['destination']=[2050,1900]
    with pytest.raises(ValueError,match='边界'):validate_project(window.project)


@pytest.mark.parametrize('mid',['bakurani','zestafona'])
def test_new_map_assets_match_their_coordinate_frame(mid):
    info=map_info(mid);im=read_image(map_asset(mid,'image'))
    assert im.shape[:2]==(info['height'],info['width'])
    meta=json.loads(map_asset(mid,'source').read_text(encoding='utf-8'))
    p=read_project(map_asset(mid,'project'))
    assert p['meters_per_pixel']==pytest.approx(2/meta['reference_to_map'][0][0])
    assert len(p['roads'])>=100 and all(r['confirmed'] for r in p['roads'])
    locator=Locator.from_assets(mid)
    crop=read_image(map_asset(mid,'source').parent/'reference-crop.png')
    for image in (crop,cv2.resize(crop,None,fx=1.25,fy=1.25)):
        fix=locator.locate(image)
        assert fix.valid and distance([fix.x,fix.y],meta['reference_crop']['point'])<2
    # A second location uses the actual bundled display image, away from the
    # centre fixture, so a swapped image or incorrect scale cannot pass.
    x,y=(int(info['width']*.3),int(info['height']*.6))
    query=cv2.resize(im[y-64:y+64,x-72:x+72],(340,303))
    fix=locator.locate(query)
    assert fix.valid and distance([fix.x,fix.y],[x,y])<2


@pytest.mark.parametrize('mid,anchors',[
    ('bakurani',[[311,968],[1190,1803],[1771,1090],[1449,144]]),
    ('zestafona',[[362,278],[1269,822],[1016,1669],[1800,1310]]),
])
def test_new_map_main_roads_connect_and_favorites_keep_geometry(mid,anchors):
    p=read_project(map_asset(mid,'project'))
    for start,end in zip(anchors,anchors[1:]):
        route=plan(p['roads'],[start,end],p['policy']['allowed'])
        assert len(route.points)>10 and route.length>distance(start,end)*.8
        assert max(route.snap_distances)<45
    saved=saved_route('跨区运输',route);p['route_library']=[saved]
    payload=library_payload(p,'routes');assert payload['map']==mid
    restored,count,_=merge_library(read_project(map_asset(mid,'project')),payload,'routes')
    assert count==1
    full=follow_saved(restored['roads'],restored['route_library'][0],restored['policy'])
    assert full.length==pytest.approx(route.length,abs=.1)
    assert distance(full.points[0],route.points[0])<.1 and distance(full.points[-1],route.points[-1])<.1


def test_real_worker_switches_indexes_and_samples(app):
    worker=CaptureWorker(default_settings());ready=[];results=[];errors=[]
    worker.ready.connect(lambda mid,g:ready.append((mid,g)))
    worker.result.connect(lambda fix,frame,live:results.append((fix,live)))
    worker.failed.connect(lambda *args:errors.append(args))
    def until(predicate):
        deadline=time.monotonic()+20
        while not predicate() and not errors and time.monotonic()<deadline:
            app.processEvents();QTest.qWait(10)
        assert not errors
        assert predicate()
    worker.start()
    try:
        for mid in ['ozeti','bakurani','zestafona','ozeti']:
            if worker.context[0]!=mid:worker.request_map(mid)
            context=worker.context;until(lambda:context in ready)
            source=map_asset(mid,'image').parent/('sample_minimap.png' if mid=='ozeti' else 'reference-crop.png')
            worker.request_sample(source)
            until(lambda:any((fix.map_id,fix.generation)==context for fix,_ in results))
            fix,live=results[-1];assert fix.valid and not live
        assert [fix.map_id for fix,_ in results]==['ozeti','bakurani','zestafona','ozeti']
        assert [fix.generation for fix,_ in results]==[0,1,2,3]
    finally:worker.shutdown()

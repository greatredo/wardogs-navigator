"""Explicit command-line self-test for a packaged executable."""
import json
import time
import os
from pathlib import Path
from dataclasses import asdict
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QPointF
from .model import asset_path,read_project,atomic_json,validate_project
from .vision import Locator,read_image
from .routing import plan,blocked
from .navigation import Navigator,cues_for
from .library import saved_route,supplement_roads,library_payload,merge_library,snap_saved,follow_saved
from .app import MainWindow,STYLE
from .maps import map_info,map_asset


def run_selftest(output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('WARDOGS_NAV_DATA',str(output.parent/(output.stem+'-data')))
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    report={'version':'0.5.0','game_test':False,'checks':{},'errors':[]}
    window=None
    try:
        p=read_project(asset_path('default_project.json'))
        fix=Locator.from_assets().locate(read_image(asset_path('sample_minimap.png')))
        report['localization']=asdict(fix);assert fix.valid
        report['checks']['image_localization']=True
        route=plan(p['roads'],[[fix.x,fix.y],[1300,796]],['major','minor'])
        report['checks']['routing']=len(route.points)>5
        danger={'shape':'rect','point':[1152,789],'width':14,'height':14}
        detour=plan(p['roads'],[[fix.x,fix.y],[1300,796]],['major','minor'],avoid=[danger])
        report['checks']['danger_detour']=all(not blocked(a,b,danger) for a,b in zip(detour.points,detour.points[1:]))
        window=MainWindow(start_worker=False)
        window.switch_map('ozeti')
        window.project=p;window.project['destination']=[1300,796];window.on_fix(fix,read_image(asset_path('sample_minimap.png')),False)
        window.plan_route(quiet=True);window.refresh_lists();window.show();app.processEvents();window.map.fit()
        window.grab().save(str(output.with_suffix('.png')))
        report['checks']['gui']=True
        window.store_favorite(saved_route('打包验收路线',route));window.favorite_list.setCurrentRow(0);window.load_favorite()
        report['checks']['exact_favorite']=abs(window.route.length-route.length)<.1
        payload=library_payload(window.project,'routes');portable=output.with_name(output.stem+'-routes.json')
        atomic_json(portable,payload)
        restored,count,_=merge_library(p,read_project(portable),'routes')
        report['checks']['favorite_import_export']=count==1 and restored['route_library'][0]['points']==[list(q) for q in route.points]
        roads=[];custom=dict(id='custom',name='自绘野地',points=[[100,100],[200,100],[200,200]],kinds=['minor','offroad'])
        first=supplement_roads(roads,custom);second=supplement_roads(roads,custom)
        report['checks']['missing_roads_added_once']=first==2 and second==0 and {r['kind'] for r in roads}=={'minor','offroad'}
        simple=[dict(id='line',name='道路',points=[[100,100],[200,100],[200,200]],kind='major',confirmed=True)]
        bend=plan(simple,[[100,100],[200,200]],['major'])
        report['checks']['normal_bend_is_silent']=[c.kind for c in cues_for(bend,[],'normal')]==['arrival']
        simple.append(dict(id='branch',name='岔路',points=[[200,100],[300,100]],kind='major',confirmed=True))
        junction=plan(simple,[[100,100],[200,200]],['major'])
        report['checks']['normal_junction_cue']=cues_for(junction,[],'normal')[0].kind=='right'
        wrc_settings=dict(window.settings,mode='wrc',wrc_lead_m=150.,wrc_lead_s=0.)
        notes=[dict(id='left',point=[150,100],type='left',grade=3,direction='forward',bearing=90),
               dict(id='brake',point=[170,100],type='hard_brake',grade=1,direction='forward',bearing=90),
               dict(id='square',point=[200,100],type='square_right',grade=1,direction='forward',bearing=90)]
        nav=Navigator();nav.start(junction,notes,wrc_settings,1.)
        data=nav.update([100,100],0)
        report['wrc_speech']=data['speech']
        report['checks']['wrc_roadbook']='左三' in data['speech'] and '急刹车' in data['speech'] and '右直角' in data['speech']
        # Check the same route-option implementation in the frozen executable.
        sketch=dict(id='coarse',name='粗绘贴路验收',points=[[105,105],[195,195]],kinds=['major'])
        matched=snap_saved(simple[:1],sketch,dict(allowed=['major'],confirmed_only=False))
        report['checks']['coarse_route_follows_road']=[200,100] in matched['points'] and not matched['build_roads']
        private=dict(id='private',name='不建路验收',points=[[20,20],[120,20],[120,120]],kinds=['minor','offroad'],snap_to_roads=False,build_roads=False)
        public=[];private_route=follow_saved(public,private,dict(allowed=['minor','offroad'],confirmed_only=False))
        report['checks']['private_favorite_without_public_roads']=abs(private_route.length-200)<.01 and not public
        portable_options=dict(p,route_library=[matched,private],active_route_id=None)
        option_payload=library_payload(portable_options,'routes')
        report['checks']['route_export_keeps_options']=option_payload['route_library']==[matched,private]
        private_payload=library_payload(dict(p,route_library=[private]),'routes')
        imported,_,added=merge_library(dict(p,route_library=[],roads=[],active_route_id=None),private_payload,'routes')
        report['checks']['private_route_import_does_not_build']=not imported['roads'] and added==0
        a,b=route.points[:2];position=window.map.mapFromScene(QPointF((a[0]+b[0])/2,(a[1]+b[1])/2))
        selected=window.map.road_at(position);window.select_road_on_map(selected)
        report['checks']['map_road_selection']=bool(selected) and window.road_list.currentRow()>=0 and window.map.selected_road==selected
        window.hud.set_data(data,'wrc');window.hud.show();app.processEvents()
        window.hud.grab().save(str(output.with_name(output.stem+'-wrc.png')))
        report['maps']={}
        saved_project=validate_project(window.project)
        for mid,destination in [('bakurani',[1190,1803]),('zestafona',[1269,822])]:
            assert window.switch_map(mid)
            metadata=json.loads(map_asset(mid,'source').read_text(encoding='utf-8'))
            image=read_image(map_asset(mid,'source').parent/'reference-crop.png')
            location=Locator.from_assets(mid).locate(image)
            expected=metadata['reference_crop']['point']
            error=((location.x-expected[0])**2+(location.y-expected[1])**2)**.5
            report['maps'][mid]={'fixture':'public_image_crop_not_game_capture','location':asdict(location),'position_error':error,'roads':len(window.project['roads'])}
            report['checks'][mid+'_reference_localization']=location.valid and error<2
            window.project['destination']=destination;window.on_fix(location,image,False)
            report['checks'][mid+'_routing']=bool(window.plan_route(quiet=True))
            window.refresh_lists()
            app.processEvents();window.map.fit();window.grab().save(str(output.with_name(output.stem+'-'+mid+'.png')))
            report['checks'][mid+'_map_view']=window.map_combo.currentData()==mid and window.map.pixmap.width()==map_info(mid)['width']
        # Finish the common HUD / speech checks on the unchanged OZETI path.
        assert window.switch_map('ozeti')
        report['checks']['map_switch_restores_config']=window.project==saved_project
        report['checks']['map_switch_clears_fix']=window.fix is None and window.route is None and not window.navigator.active
        window.on_fix(fix,read_image(asset_path('sample_minimap.png')),False);window.plan_route(quiet=True)
    except Exception as error:
        report['errors'].append(repr(error))
    finished=False
    def finish_report():
        nonlocal finished
        if finished:return
        finished=True
        if window:window.close()
        report['success']=not report['errors'] and all(report['checks'].values())
        atomic_json(output,report);app.exit(0 if report['success'] else 1)

    def finish():
      try:
        if window:
            window.load_voices();report['voices']=[v.name() for v in window.voices]
            report['checks']['system_voice_available']=bool(window.voices)
            window.hud.set_data({'state':'navigating','text':'前方右转','distance':120,'remaining':2800},'normal')
            window.hud.show();app.processEvents()
            window.hud.grab().save(str(output.with_name(output.stem+'-hud.png')))
            window.settings['hud']['locked']=True;window.hud.apply_settings()
            report['checks']['hud_mouse_passthrough_flag']=bool(window.hud.windowFlags() & __import__('PySide6.QtCore',fromlist=['Qt']).Qt.WindowTransparentForInput)
            window.navigator.start(window.route,[],window.settings,window.project['meters_per_pixel'],False)
            window.fix_live=True;window.fix_time=time.monotonic();window.settings['capture']=dict(left=75,top=75,width=340,height=303)
            window.update_minimap_overlay();app.processEvents()
            report['checks']['minimap_path_visible']=window.minimap_overlay.isVisible()
            report['checks']['path_capture_mask']=bool(window.worker.path_mask)
            report['checks']['minimap_mouse_passthrough_flag']=bool(window.minimap_overlay.windowFlags() & __import__('PySide6.QtCore',fromlist=['Qt']).Qt.WindowTransparentForInput)
            report['minimap_capture_excluded']=window.minimap_overlay.capture_excluded
            window.minimap_overlay.grab().save(str(output.with_name(output.stem+'-minimap-path.png')))
            window.minimap_overlay.hide()
            window.navigator.stop();window.watchdog.stop()
            # Exercise the production speech queue through the native SAPI
            # engine. Mute this diagnostic so it does not disturb the desktop.
            window.settings['voice']=True;window.tts.setVolume(0);window.tts.setRate(.5)
            report['queue_started']=[];report['checks']['native_speech_queue']=False
            def started(id):report['queue_started'].append(id)
            def state_changed(state):
                if state==window.tts.State.Ready and len(report['queue_started'])>=2:
                    report['checks']['native_speech_queue']=True;QTimer.singleShot(0,finish_report)
            window.tts.aboutToSynthesize.connect(started);window.tts.stateChanged.connect(state_changed)
            window.speak('路口直行。');window.speak('左三，接右六。')
            QTimer.singleShot(20000,finish_report)
        else:finish_report()
      except Exception as error:
        report['errors'].append(repr(error));finish_report()
    QTimer.singleShot(900,finish)
    return app.exec()

"""Explicit command-line self-test for a packaged executable."""
import json
import time
import os
import cv2
import numpy as np
from pathlib import Path
from dataclasses import asdict
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer,QPointF
from .model import asset_path,read_project,atomic_json,validate_project
from .vision import Locator,read_image,Fix,MapViewFix
from .routing import plan,blocked
from .navigation import Navigator,cues_for
from .library import saved_route,supplement_roads,library_payload,merge_library,snap_saved,follow_saved
from .app import MainWindow,STYLE
from .maps import map_info,map_asset
from . import __version__


def run_selftest(output):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('WARDOGS_NAV_DATA',str(output.parent/(output.stem+'-data')))
    app=QApplication.instance() or QApplication([]);app.setStyle('Fusion');app.setStyleSheet(STYLE)
    report={'version':__version__,'game_test':False,'checks':{},'errors':[]}
    window=None
    try:
        p=read_project(asset_path('default_project.json'))
        locator=Locator.from_assets()
        sample=read_image(asset_path('sample_minimap.png'))
        fix=locator.locate(sample)
        report['localization']=asdict(fix);assert fix.valid
        report['checks']['image_localization']=True
        view=locator.locate_map(sample)
        report['checks']['bigmap_localization']=bool(view.valid and np.linalg.norm(view.matrix@[sample.shape[1]/2,sample.shape[0]/2,1]-[fix.x,fix.y])<2)
        terrain=read_image(map_asset('ozeti','image'))
        ambiguous=cv2.resize(terrain[1177:1313,437:573],(340,340))
        ambiguous[148:193,148:193]=(70,70,70)
        polygon=np.int32([[157,175],[181,175],[159,159],[164,171],[164,173],
                          [167,179],[159,181],[182,175],[178,166],[154,184],[163,155]])
        cv2.fillPoly(ambiguous,[polygon],(255,255,255))
        degraded=locator.locate(ambiguous)
        report['heading_degradation']=asdict(degraded)
        report['checks']['ambiguous_heading_keeps_position']=(degraded.valid and degraded.heading is None
            and abs(degraded.x-505)<2 and abs(degraded.y-1245)<2)
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
        window.worker.capture=True;window.on_fix(fix,sample,True)
        window.fix_time=time.monotonic()-3;window.check_stale()
        report['checks']['stale_fix_clears_ui']=(not window.fix.valid and not window.fix_live
            and window.map.player_item is None and '100%' not in window.fix_label.text())
        window.on_fix(Fix(reason='合成单帧异常'),ambiguous,True)
        window.on_fix(fix,sample,True)
        report['checks']['hud_localization_recovers_without_navigation']=(window.hud.data['state']!='lost'
            and window.hud.localization_text==window.fix_label.text() and '实时定位' in window.hud.localization_text)
        report['checks']['failure_frame_retained_after_recovery']=(window.fix_live
            and np.array_equal(window.failure_diagnostic[0],ambiguous)
            and not window.failure_diagnostic[1]['fix']['valid'])
        window.worker.capture=False
        window.arrival_radius.setValue(180)
        report['checks']['arrival_radius_control']=window.settings['arrival_m']==180
        window.arrival_radius.setValue(25)
        from .routing import Route
        short=Route([[0,0],[500,0]],['major'],['fixture'],500,[0,0],0)
        check_nav=Navigator();check_nav.start(short,[],window.settings,1,True,goal=[500,60],return_goal=[0,0])
        wait=check_nav.update([100,100],0,100)
        report['checks']['offroad_wait_keeps_journey']=(wait['state']=='waiting_road' and not wait['replan'] and check_nav.active)
        report['checks']['road_rejoin_replans']=check_nav.update([100,5],1,5)['replan']
        check_nav.update([500,60],2,60)
        report['checks']['arrival_uses_actual_offroad_goal']=check_nav.update([500,60],3,60)['state']=='turnaround'
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
        # BAKURANI uses the maintained southern road endpoint, not the removed camp connector.
        for mid,destination in [('bakurani',[1206.5,1741.5]),('zestafona',[1269,822])]:
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
            window.fix_live=True;window.fix_time=time.monotonic();window.settings['capture']=dict(left=75,top=75,width=340,height=303)
            # Loading a favorite above already populated its endpoints. Exercise
            # automatic placement only with the required unset-start condition.
            window.project['start']=None
            window.begin_navigation()
            report['checks']['automatic_start_visible']=(window.project['start']==[window.fix.x,window.fix.y]
                and '返程终点' in window.start_label.text() and window.full_route is not None)
            window.update_minimap_overlay();app.processEvents()
            report['checks']['minimap_path_visible']=window.minimap_overlay.isVisible()
            report['checks']['path_capture_mask']=bool(window.worker.path_mask)
            report['checks']['minimap_mouse_passthrough_flag']=bool(window.minimap_overlay.windowFlags() & __import__('PySide6.QtCore',fromlist=['Qt']).Qt.WindowTransparentForInput)
            report['minimap_capture_excluded']=window.minimap_overlay.capture_excluded
            full_points=list(window.minimap_overlay.full_points)
            window.navigator.progress=window.route.length*.25;window.update_minimap_overlay()
            report['checks']['remaining_minimap_path']=(window.minimap_overlay.full_points==full_points
                and window.minimap_overlay.points[0]!=full_points[0]
                and len(window.worker.path_mask['paths'])==2)
            window.minimap_overlay.grab().save(str(output.with_name(output.stem+'-minimap-path.png')))
            window.clear_current_route();app.processEvents()
            report['checks']['clear_current_route']=(window.project['start'] is None and window.project['destination'] is None and not window.project['waypoints'] and not window.project.get('active_route_id')
                and window.route is None and window.map.route is None and not window.navigator.active and not window.pending_start
                and not window.minimap_overlay.isVisible() and window.worker.path_mask is None and window.hud.isVisible())
            # Native overlay and hotkey dispatch on this diagnostic's own windows.
            from .hotkeys import DEFAULT_HOTKEYS,physical_cursor
            from PySide6.QtCore import Qt
            window.settings['bigmap']['enabled']=True
            big=MapViewFix(matrix=np.array([[1.,0,350],[0,1.,950]]),frame_size=(600,500),valid=True,
                region=dict(left=200,top=200,width=600,height=500))
            window.project['start']=[505,1245];window.project['destination']=[700,1200]
            window.big_overlay.update_map(big,window.project)
            app.processEvents()
            report['checks']['bigmap_overlay_visible']=window.big_overlay.isVisible()
            report['checks']['bigmap_mouse_passthrough']=bool(window.big_overlay.windowFlags()&Qt.WindowTransparentForInput)
            report['checks']['bigmap_capture_exclusion_or_mask']=bool(window.big_overlay.capture_excluded or (window.worker.map_mask is not None and window.worker.map_mask.any()))
            window.big_overlay.grab().save(str(output.with_name(output.stem+'-bigmap.png')))
            window.big_overlay.hide()
            report['checks']['physical_cursor_api']=physical_cursor() is not None
            statuses=[];triggered=[]
            window.global_hotkeys.status.connect(statuses.append);window.global_hotkeys.triggered.connect(triggered.append)
            window.global_hotkeys.configure(dict(DEFAULT_HOTKEYS));window.global_hotkeys.set_active(True)
            report['checks']['global_hotkeys_registered']=len(window.global_hotkeys.registered)==len(DEFAULT_HOTKEYS)
            if window.global_hotkeys.registered:
                import ctypes
                from ctypes import wintypes
                ident=next(iter(window.global_hotkeys.registered))
                api=ctypes.WinDLL('user32',use_last_error=True).PostThreadMessageW
                api.argtypes=[wintypes.DWORD,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM];api.restype=wintypes.BOOL
                for _ in range(3):api(ctypes.windll.kernel32.GetCurrentThreadId(),0x0312,ident,0)
                app.processEvents()
                report['checks']['global_hotkey_repeated_native_dispatch']=len(triggered)==3
            window.global_hotkeys.set_active(False)
            report['hotkey_status']=statuses
            window.grab().save(str(output.with_name(output.stem+'-cleared.png')))
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

"""Large-map UI and actions; view coordinates never become vehicle fixes."""
import time
from PySide6.QtCore import QTimer
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QCheckBox,QFormLayout,QKeySequenceEdit
from . import hotkeys
from .bigmap import BigMapOverlay
from .dialogs import number
from .maps import map_info
from .routing import nearest_on_route


class GameMapController:
    def init_game_map(self):
        self.big_view=None;self.game_window=0;self.big_resume=None
        self.big_tracking=False
        self.big_message='大地图 · 快捷键就绪';self.big_message_until=0
        self.big_overlay=BigMapOverlay(self.settings['bigmap'])
        self.big_overlay.mask_changed.connect(lambda mask:setattr(self.worker,'map_mask',mask))
        self.cursor_timer=QTimer(self);self.cursor_timer.setInterval(100);self.cursor_timer.timeout.connect(self.poll_map_cursor)
        self.global_hotkeys=hotkeys.GlobalHotkeys(self)
        self.global_hotkeys.triggered.connect(self.on_map_hotkey)
        self.global_hotkeys.status.connect(self.hotkey_status_changed)
        self.global_hotkeys.configure(self.settings['bigmap_hotkeys'])
        self.worker.map_result.connect(self.on_big_map)
        self.worker.action_failed.connect(self.map_feedback)

    def build_game_map_settings(self,layout):
        group=self.group('局内大地图',layout)
        group.addWidget(self.text('先在游戏中打开大地图，再单独框选地图画面。小地图定位正常时，大地图识别和鼠标读取全部停止。',True))
        group.addWidget(self.button('框选此屏幕的大地图',lambda:self.select_region(large=True)))
        self.big_enabled=QCheckBox('启用大地图识别、叠加与快捷键')
        self.big_enabled.setChecked(self.settings['bigmap']['enabled'])
        self.big_enabled.toggled.connect(lambda v:self.big_setting('enabled',v));group.addWidget(self.big_enabled)
        form=QFormLayout();self.big_fields={}
        for key,label,lo,hi in [('left','左边 X',-30000,30000),('top','上边 Y',-30000,30000),('width','宽度',60,5000),('height','高度',60,5000)]:
            field=number(self.settings['bigmap_capture'][key],lo,hi)
            field.valueChanged.connect(lambda v,k=key:self.big_capture_setting(k,v));self.big_fields[key]=field;form.addRow(label,field)
        for key,label,lo,hi,dec in [('opacity','叠加不透明度',.2,1,2),('line_width','路线线宽 (屏幕像素)',1,10,0),('avoid_radius_m','快捷键危险区半径 (m)',5,500,0)]:
            field=number(self.settings['bigmap'][key],lo,hi,dec)
            field.valueChanged.connect(lambda v,k=key:self.big_setting(k,v));form.addRow(label,field)
        group.addLayout(form)
        self.big_status=self.text('尚未识别大地图',True);group.addWidget(self.big_status)
        form=QFormLayout();self.hotkey_fields={}
        for action,label in hotkeys.ACTIONS.items():
            field=QKeySequenceEdit(QKeySequence(self.settings['bigmap_hotkeys'][action]))
            field.setMaximumSequenceLength(1);self.hotkey_fields[action]=field;form.addRow(label,field)
        group.addLayout(form);group.addWidget(self.button('保存快捷键',self.save_map_hotkeys))
        self.hotkey_status=self.text('识别到前台游戏大地图后启用；留空可禁用单项。支持 Ctrl / Alt 与字母、数字或 F1–F11。',True);group.addWidget(self.hotkey_status)
        group.addWidget(self.text('一键新导航：最后一次小地图定位作为新起始点，鼠标位置作为目的地，并清除旧途经点。上次车辆位置保留至下一次定位或切换地图；尚未定位时，回到小地图后自动补上起始点。修改目的地会保留起始点。',True))

    def save_map_hotkeys(self):
        bindings={key:field.keySequence().toString(QKeySequence.PortableText) for key,field in self.hotkey_fields.items()}
        used=set()
        try:
            for action,text in bindings.items():
                binding=hotkeys.parse_hotkey(text)
                if binding and binding in used:raise ValueError(hotkeys.ACTIONS[action]+'：按键重复')
                if binding:used.add(binding)
        except ValueError as error:self.hotkey_status.setText(str(error));return
        self.settings['bigmap_hotkeys']=bindings;self.global_hotkeys.configure(bindings);self.save_settings()
        if not self.global_hotkeys.active:self.hotkey_status.setText('快捷键已保存；识别到前台大地图后启用')

    def hotkey_status_changed(self,message):
        self.hotkey_status.setText(message)
        if '占用' in message or '无法' in message:self.map_feedback(message)

    def big_setting(self,key,value):
        self.settings['bigmap'][key]=value
        if key=='enabled':self.reset_game_map();self.worker.reset_view()
        self.save_settings();self.update_big_overlay()

    def big_capture_setting(self,key,value):
        self.settings['bigmap_capture'][key]=value
        self.reset_game_map();self.worker.reset_view();self.save_settings()

    def reset_game_map(self):
        self.hide_game_map();self.game_window=0

    def hide_game_map(self):
        self.big_view=None;self.big_tracking=False;self.cursor_timer.stop();self.global_hotkeys.set_active(False);self.big_overlay.hide()

    def big_view_available(self):
        return (self.worker.capture and self.settings['bigmap']['enabled'] and self.big_view is not None
            and self.big_view.valid and self.big_view.session==self.worker.session
            and (self.big_view.map_id,self.big_view.generation)==self.worker.context
            and self.big_view.region==self.settings['bigmap_capture'])

    def big_view_fresh(self):
        return self.big_view_available() and self.big_tracking and time.monotonic()-self.big_view.captured_at<2.5

    def game_map_active(self):
        return (self.big_view_available() and self.worker.mode!='mini' and self.game_window
                and hotkeys.foreground_window()==self.game_window)

    def big_localization(self):
        if self.big_view_fresh():return f'大地图识别 · {self.big_view.confidence:.0%}'
        return '大地图识别中 · 保留上次画面'

    def on_big_map(self,view,frame,actions=None):
        if (not self.worker.capture or not self.settings['bigmap']['enabled'] or view.session!=self.worker.session
            or (view.map_id,view.generation)!=self.worker.context or view.region!=self.settings['bigmap_capture']):return
        self.big_status.setText(view.reason)
        if self.worker.mode=='mini':return
        if not view.foreground or hotkeys.foreground_window()!=view.foreground:
            self.hide_game_map();return
        if self.game_window and view.foreground!=self.game_window:
            self.hide_game_map();return
        if not view.valid or time.monotonic()-view.captured_at>=2.5:
            self.big_tracking=False
            if actions:self.worker.retry_actions(actions,view.foreground)
            self.invalidate_fix(view.reason);self.update_big_overlay();return
        self.game_window=view.foreground;self.worker.target_window=view.foreground;self.big_view=view
        self.big_tracking=True
        self.fix_live=False;self.minimap_overlay.hide();self.navigator.lost();self.tts.stop()
        self.set_localization(self.big_localization())
        self.set_hud({'state':'bigmap','text':'大地图操作中'})
        self.big_status.setText(f'{view.reason} · {view.inliers} 个匹配点')
        self.global_hotkeys.set_active(True)
        self.cursor_timer.start()
        self.update_big_overlay()
        if actions:
            for action in actions:
                if action[0]!=view.session or action[3]!=view.foreground or time.monotonic()-action[4]>=6:
                    self.map_feedback('操作超时或窗口已切换，请重试');continue
                point=self.valid_map_point(view.screen_to_map(action[2]))
                if point is not None:self.apply_map_action(action[1],point)
                else:self.map_feedback('鼠标不在有效地图范围内')

    def valid_map_point(self,point):
        if point is None:return None
        info=map_info(self.project['map'])
        return list(point) if 0<=point[0]<=info['width'] and 0<=point[1]<=info['height'] else None

    def poll_map_cursor(self):
        if not self.game_map_active():
            self.hide_game_map();return
        if not self.big_view_fresh():
            self.big_status.setText('等待大地图识别恢复；快捷键会核准新画面后执行');return
        point=hotkeys.physical_cursor()
        mapped=self.valid_map_point(self.big_view.screen_to_map(point)) if point else None
        if mapped:self.big_status.setText(f'大地图鼠标 {mapped[0]:.1f}, {mapped[1]:.1f} · 快捷键可用')
        else:self.big_status.setText('鼠标在大地图区域外')

    def on_map_hotkey(self,action):
        # This guard precedes the ONLY cursor query in the hotkey path.
        if action not in hotkeys.ACTIONS or not self.game_map_active():return
        point=hotkeys.physical_cursor()
        if point is None or self.big_view.screen_to_map(point) is None:
            self.map_feedback('鼠标不在大地图框选范围内');return
        if self.worker.request_action(action,point,self.game_window):self.map_feedback('正在核准鼠标位置…')

    def map_feedback(self,text):
        self.big_message=text;self.big_message_until=time.monotonic()+5
        self.big_status.setText(text)
        self.update_big_overlay()

    def update_big_overlay(self):
        if not self.big_view_available():return
        text=self.big_message if time.monotonic()<self.big_message_until else ('大地图 · 快捷键就绪 · 行车播报暂停' if self.big_view_fresh() else '识别中 · 保留上次画面，等待刷新')
        self.big_overlay.update_map(self.big_view,self.project,self.route,self.full_route,
            self.navigator.progress if self.navigator.active else 0,
            self.last_accepted,text)

    def resume_context(self):
        if self.big_resume:return self.big_resume
        if not self.navigator.active:return None
        passed=[]
        for point in self.project['waypoints']:
            hit=nearest_on_route(point,self.navigator.route.points)
            if hit and hit[0]<=25 and hit[1]<=self.navigator.progress+3:passed.append(point)
        return dict(lap=self.navigator.lap,leg=self.navigator.leg,passed=passed)

    def apply_map_action(self,action,point):
        if action=='clear':
            self.clear_current_route();self.map_feedback('路线及起始点已清除');return
        resume=self.resume_context();pending=self.pending_start
        if action=='navigate':
            self.snapshot();self.detach_favorite();self.stop_navigation(quiet=True)
            self.navigator.lap=0;self.navigator.leg='去程'
            self.project['start']=list(self.last_accepted) if self.last_accepted is not None else None
            self.project['destination']=point;self.project['waypoints']=[]
            self.changed();self.pending_start=True
            message='新路线已规划；关闭大地图后开始播报' if self.route else '目的地已设置；回到小地图后定位并规划'
            if self.project['start'] and not self.route:message='未找到可行路线；请调整目的地或道路规则'
            self.map_feedback(message);self.hud.show();return
        if action=='undo':
            if not self.history:self.map_feedback('没有可撤销的标注');return
            self.undo()
        else:
            self.snapshot()
            if action=='start':self.project['start']=point;self.favorite_trip=None
            elif action=='destination':self.detach_favorite();self.project['destination']=point
            elif action=='waypoint':self.detach_favorite();self.project['waypoints'].append(point)
            elif action=='avoid':
                radius=self.settings['bigmap']['avoid_radius_m']/(self.project['meters_per_pixel'] or 1)
                self.project['avoid'].append(dict(point=point,radius=max(1,min(1000,radius)),shape='circle'))
            else:return
            self.changed()
        self.big_resume=resume if self.project.get('destination') and self.project.get('start') else None
        self.pending_start=pending and bool(self.project.get('destination'))
        if self.big_resume and self.last_accepted:self.plan_big_resume(self.last_accepted,start=False)
        self.map_feedback(hotkeys.ACTIONS[action]+'已完成'+(' · 无可行路线，请调整标注' if not self.route and self.project.get('destination') and self.project.get('start') else ''))

    def plan_big_resume(self,position,start=True):
        resume=self.big_resume
        if not resume:return
        waypoints=[p for p in self.project['waypoints'] if p not in resume['passed']]
        if resume['lap']%2:waypoints.reverse()
        goal=self.project['start'] if resume['lap']%2 else self.project['destination']
        self.navigator.lap=resume['lap']
        success=bool(goal) and self.plan_route(quiet=True,anchors=[list(position),*waypoints,goal])
        if start:
            self.big_resume=None
            if success:
                self.start_trip_navigation(resume['lap'],resume['leg'])
            else:self.set_hud({'state':'offroute','text':'无可行路线'})

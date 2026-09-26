"""Map-local recording controls and persistence for the navigation window."""
import json
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox,QFormLayout,QMessageBox
from .dialogs import number
from .maps import map_info
from .model import user_dir,atomic_json
from .recording import RoadRecorder,add_recorded_roads


class RecordingController:
    def init_recording(self):
        self.settings['recording_minimum']=max(1,min(100,int(self.settings['recording_minimum'])))
        self.load_recording()
        self.record_timer=QTimer(self);self.record_timer.setInterval(2000)
        self.record_timer.timeout.connect(self.save_recording);self.record_timer.start()

    def recording_path(self):return user_dir()/'recordings'/(self.project['map']+'.json')

    def load_recording(self):
        state=None;self.record_load_error=''
        path=self.recording_path()
        if path.exists():
            try:
                data=json.loads(path.read_text(encoding='utf-8'))
                if data.get('map')!=self.project['map'] or data.get('schema')!=1:raise ValueError('地图或版本不符')
                state=data['state'];info=map_info(self.project['map'])
                if not isinstance(state['active'],bool) or len(state['units'])>20000:raise ValueError('记录数据无效')
                paths=list(state['manual'])
                for unit in state['units']:
                    if not isinstance(unit['id'],str) or not 1<=unit['count']<=100 or not isinstance(unit['added'],bool):raise ValueError('累计次数无效')
                    paths.append(unit['points'])
                for points in paths:
                    for p in points:
                        if len(p)!=2 or not 0<=p[0]<=info['width'] or not 0<=p[1]<=info['height']:raise ValueError('记录坐标无效')
            except (OSError,ValueError,KeyError,TypeError) as error:
                state=None;self.record_load_error=f'记录未读取，原文件保留：{error}'
        self.recorder=RoadRecorder(state,self.project['meters_per_pixel'] or 1)
        self.recorder.set_roads(self.project['roads'])
        if hasattr(self,'record_status'):self.update_recording_status()

    def build_recording(self,layout):
        group=self.group('行驶路线记录',layout)
        self.record_start=self.button('开始记录',self.start_recording)
        self.record_finish=self.button('结束并加入路网',self.finish_recording)
        group.addWidget(self.row(self.record_start,self.record_finish))
        self.auto_record=QCheckBox('自动累计经过次数并建路')
        self.auto_record.setChecked(self.settings['recording_auto'])
        self.auto_record.toggled.connect(self.toggle_auto_recording);group.addWidget(self.auto_record)
        form=QFormLayout();self.record_minimum=number(self.settings['recording_minimum'],1,100)
        self.record_minimum.valueChanged.connect(self.set_recording_minimum)
        form.addRow('最低经过次数',self.record_minimum);group.addLayout(form)
        group.addWidget(self.button('清空本地图累计次数',self.clear_recording_counts))
        self.record_status=self.text('',True);group.addWidget(self.record_status)
        group.addWidget(self.text('只记录实时小地图位置，无需开始导航。新增道路默认为越野，重合段跳过，地面交叉处拆段。停车不计次数，反向也算一次；丢失定位或打开大地图时断开，恢复后继续。',True))
        self.update_recording_status()

    def update_recording_status(self):
        if not hasattr(self,'record_status'):return
        self.record_start.setEnabled(not self.recorder.active and not self.record_load_error)
        self.record_finish.setEnabled(self.recorder.active and not self.record_load_error)
        if self.record_load_error:self.record_status.setText(self.record_load_error);return
        count=sum(len(p) for p in self.recorder.state['manual'])
        text=f'手动记录中 · {count} 个定位点' if self.recorder.active else '手动记录未开始'
        if self.recorder.active and not self.fix_live:text+=' · 等待有效定位'
        pending=[u for u in self.recorder.state['units'] if not u['added']]
        if self.settings['recording_auto']:
            text+=f"\n自动记录已开启 · 候选最高 {max((u['count'] for u in pending),default=0)} / {self.settings['recording_minimum']} 次"
        else:text+='\n自动记录已关闭 · 累计次数保留'
        self.record_status.setText(self.recorder.error or text)
        if hasattr(self,'map'):self.map.update_recording(self.recorder.state['manual'])

    def start_recording(self):
        self.recorder.start();self.update_recording_status();self.save_recording()
        self.notify('开始记录行驶路线；请开启小地图定位，结束后加入路网')

    def finish_recording(self):
        self.disconnect_recording()
        count=self.apply_recorded_roads(self.recorder.stop(),'manual')
        self.save_recording();self.update_recording_status()
        self.notify(f'已加入 {count} 条越野道路，可编辑属性或撤销' if count else '记录已结束：没有足够长的新路段，重合部分已跳过')

    def toggle_auto_recording(self,enabled):
        self.disconnect_recording()
        self.settings['recording_auto']=enabled;self.save_settings();self.update_recording_status()

    def set_recording_minimum(self,value):
        self.settings['recording_minimum']=int(value);self.save_settings()
        self.promote_recording();self.update_recording_status()

    def clear_recording_counts(self):
        if QMessageBox.question(self,'清空累计','清空本地图的自动记录累计？已加入路网的道路和手动记录会保留。',QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        self.recorder.clear_counts();self.save_recording();self.update_recording_status()

    def apply_recorded_roads(self,traces,source):
        if not traces:return 0
        roads,count=add_recorded_roads(self.project['roads'],traces,self.project['meters_per_pixel'] or 1,source)
        if count:
            self.snapshot();self.project['roads']=roads;self.recorder.set_roads(roads)
            # Appending roads must not cancel, reset, or announce the active trip.
            self.refresh_lists();self.refresh_map();self.autosave.start()
        return count

    def promote_recording(self):
        if not self.settings['recording_auto'] or self.record_load_error:return
        ready=self.recorder.ready(self.settings['recording_minimum'])
        if ready:
            count=self.apply_recorded_roads([u['points'] for u in ready],'auto')
            self.recorder.promoted(ready)
            if count:self.notify(f'自动记录已更新 {count} 条越野道路，可编辑属性或撤销')

    def record_fix(self,fix,now,live):
        if self.record_load_error:return
        if live and fix.valid:
            self.recorder.scale=self.project['meters_per_pixel'] or 1
            self.recorder.feed([fix.x,fix.y],now,self.settings['recording_auto'])
            self.promote_recording();self.update_recording_status()
        else:self.disconnect_recording()

    def disconnect_recording(self):
        if not hasattr(self,'recorder'):return
        self.recorder.disconnect();self.promote_recording();self.update_recording_status()

    def save_recording(self):
        if not self.recorder.dirty or self.record_load_error:return
        try:
            atomic_json(self.recording_path(),dict(schema=1,map=self.project['map'],state=self.recorder.state))
            self.recorder.dirty=False
        except (OSError,ValueError) as error:self.notify(f'行驶记录保存失败：{error}')

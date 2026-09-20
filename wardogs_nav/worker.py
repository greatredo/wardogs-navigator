import threading
import time
from collections import deque
import numpy as np
from PySide6.QtCore import QThread, Signal
from .vision import Locator, read_image, Fix, MapViewFix
from .hotkeys import foreground_window


class CaptureWorker(QThread):
    result=Signal(object,object,bool)
    ready=Signal(str,int)
    failed=Signal(str,str,int)
    map_result=Signal(object,object,object)
    action_failed=Signal(str)

    def __init__(self, settings):
        super().__init__()
        self.settings=settings
        self.capture=False
        self.sample=None
        self.path_mask=None
        self.map_mask=None
        self.mode='idle'
        self.session=0
        self.actions=deque()
        self.action_lock=threading.Lock()
        self.target_window=0
        self.context=(settings.get('map_id','ozeti'),0)
        self.wake=threading.Event()

    def request_map(self,map_id):
        self.reset_view()
        self.capture=False;self.sample=None;self.path_mask=None
        self.context=(map_id,self.context[1]+1)
        self.wake.set()

    def reset_view(self):
        self.session+=1;self.mode='idle';self.map_mask=None;self.target_window=0
        with self.action_lock:self.actions.clear()
        self.wake.set()

    @property
    def map_action(self):
        with self.action_lock:return self.actions[0] if self.actions else None

    def request_action(self,action,point,foreground):
        with self.action_lock:
            full=len(self.actions)>=8
            if not full:self.actions.append((self.session,action,point,foreground,time.monotonic()))
        if full:
            self.action_failed.emit('待核准操作较多，请稍后再试');return False
        self.wake.set()
        return True

    def take_actions(self):
        with self.action_lock:
            actions=list(self.actions);self.actions.clear()
        return actions

    def retry_actions(self,actions,foreground):
        retry=[]
        for action in actions:
            if action[0]==self.session and action[3]==foreground and time.monotonic()-action[4]<6:retry.append(action)
            else:self.action_failed.emit('未能核准鼠标位置，操作已取消；请等待大地图识别恢复后重试')
        with self.action_lock:
            pending=retry+list(self.actions);self.actions=deque(pending[:8])
        if len(pending)>8:self.action_failed.emit('待核准操作较多，最后的操作已取消，请稍后重试')

    def request_sample(self,path):
        self.reset_view()
        self.sample=(self.context,str(path))
        self.wake.set()

    def run(self):
        grabber=None;locator=None;loaded=None;view_session=None
        while not self.isInterruptionRequested():
            context=self.context
            if loaded!=context or (locator is None and self.capture):
                # Release the previous FLANN index before loading a new map;
                # laptop memory use stays tied to one active map.
                locator=None
                try:
                    locator=Locator.from_assets(context[0])
                    if context!=self.context:continue
                    loaded=context;self.ready.emit(*context)
                except Exception as error:
                    if context!=self.context:continue
                    loaded=context;self.capture=False
                    self.failed.emit(f'地图特征初始化失败：{error}',*context)
            if context!=self.context:continue
            sample=self.sample
            if sample and sample[0]==context:self.sample=None
            elif sample:continue
            live=self.capture and sample is None
            if locator is not None and (sample or live):
                session=self.session
                if view_session!=session:
                    locator.map_reference=None;view_session=session
                actions=self.take_actions()
                frame=None
                try:
                    if sample:
                        frame=read_image(sample[1])
                    else:
                        region=dict(self.settings['capture'])
                        if region['width'] < 60 or region['height'] < 60:
                            if context!=self.context or not self.capture:continue
                            self.capture=False
                            self.failed.emit('截图区域至少为 60 × 60 像素；调整后重新开启定位',*context)
                            continue
                        if grabber is None:
                            import mss
                            grabber=mss.MSS()
                        frame=np.asarray(grabber.grab(region))[:,:,:3].copy()
                    fix=locator.locate(frame,tuple(self.settings['anchor']),self.settings['north_up'],None if sample else self.path_mask)
                except Exception as error:
                    if context!=self.context:continue
                    locator.last=None
                    fix=Fix(reason=f'截图或定位失败：{error}')
                    if not sample and frame is None and grabber is not None:
                        try:grabber.close()
                        except Exception:pass
                        grabber=None
                # A failed frame is a result too. Keep its image (or explicit
                # absence) paired with the error, and retry at the normal pace.
                if context!=self.context or session!=self.session or (live and not self.capture):continue
                fix.map_id,fix.generation=context
                fix.session=session
                if live and (fix.valid or self.mode!='big'):self.mode='mini' if fix.valid else 'searching'
                self.result.emit(fix,frame,live)
                if live and fix.valid:
                    locator.map_reference=None
                    if actions:self.action_failed.emit('已返回小地图，未完成的大地图操作已取消')
                    # No big-map capture, matching, foreground or cursor queries.
                elif live and self.settings.get('bigmap',{}).get('enabled'):
                    view=MapViewFix();big_frame=None
                    region=dict(self.settings['bigmap_capture'])
                    foreground=foreground_window();captured=time.monotonic()
                    try:
                        if self.target_window and foreground!=self.target_window:
                            view.reason='游戏不在前台'
                        elif region['width']<60 or region['height']<60:
                            view.reason='大地图区域至少为 60 × 60 像素'
                        else:
                            if grabber is None:
                                import mss
                                grabber=mss.MSS()
                            big_frame=np.asarray(grabber.grab(region))[:,:,:3].copy()
                            view=locator.locate_map(big_frame,self.map_mask)
                            if foreground_window()!=foreground:view.valid=False;view.reason='前台窗口已切换'
                    except Exception as error:
                        view=MapViewFix(reason=f'大地图截图或识别失败：{error}')
                    if context!=self.context or session!=self.session or not self.capture:continue
                    if region!=self.settings['bigmap_capture'] or not self.settings['bigmap']['enabled']:continue
                    view.map_id,view.generation=context
                    view.session=session;view.captured_at=captured;view.region=region;view.foreground=foreground
                    self.mode='big' if view.valid else 'lost'
                    # Retain quick consecutive presses and retry transient failures.
                    pending=[a for a in actions if a[0]==session and a[3]==foreground and captured-a[4]<6]
                    if len(pending)<len(actions):self.action_failed.emit('大地图操作超时或窗口已切换，请重试')
                    if not view.valid:
                        self.retry_actions(pending,foreground);pending=[]
                    self.map_result.emit(view,big_frame,pending)
            self.wake.wait(.2 if self.mode=='big' else max(.2,self.settings['interval_ms']/1000))
            self.wake.clear()
        if grabber:
            grabber.close()

    def shutdown(self):
        self.capture=False
        self.requestInterruption()
        self.wake.set()
        self.wait()

import threading
import time
import numpy as np
from PySide6.QtCore import QThread, Signal
from .vision import Locator, read_image, Fix


class CaptureWorker(QThread):
    result=Signal(object,object,bool)
    ready=Signal(str,int)
    failed=Signal(str,str,int)

    def __init__(self, settings):
        super().__init__()
        self.settings=settings
        self.capture=False
        self.sample=None
        self.path_mask=None
        self.context=(settings.get('map_id','ozeti'),0)
        self.wake=threading.Event()

    def request_map(self,map_id):
        self.capture=False;self.sample=None;self.path_mask=None
        self.context=(map_id,self.context[1]+1)
        self.wake.set()

    def request_sample(self,path):
        self.sample=(self.context,str(path))
        self.wake.set()

    def run(self):
        grabber=None;locator=None;loaded=None
        while not self.isInterruptionRequested():
            context=self.context
            if loaded!=context:
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
                try:
                    if sample:
                        frame=read_image(sample[1])
                    else:
                        if grabber is None:
                            import mss
                            grabber=mss.MSS()
                        region=dict(self.settings['capture'])
                        if region['width'] < 60 or region['height'] < 60:
                            raise ValueError('截图区域至少为 60 × 60 像素')
                        frame=np.asarray(grabber.grab(region))[:,:,:3].copy()
                    fix=locator.locate(frame,tuple(self.settings['anchor']),self.settings['north_up'],None if sample else self.path_mask)
                    if context!=self.context:continue
                    fix.map_id,fix.generation=context
                    self.result.emit(fix,frame,live)
                except Exception as error:
                    if context!=self.context:continue
                    self.failed.emit(f'截图或定位失败：{error}',*context)
                    self.capture=False
            self.wake.wait(max(.2,self.settings['interval_ms']/1000))
            self.wake.clear()
        if grabber:
            grabber.close()

    def shutdown(self):
        self.capture=False
        self.requestInterruption()
        self.wake.set()
        self.wait()

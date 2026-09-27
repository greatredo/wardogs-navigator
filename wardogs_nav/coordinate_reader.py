"""Read the game's crosshair labels without using terrain or a vehicle fix."""
from dataclasses import dataclass
from pathlib import Path
import re
import tempfile
import threading
import time
import cv2
import numpy as np
from wardogs_audio.bridge import WindowsBridge
from .coordinates import game_to_map


@dataclass
class CoordinateFix:
    game: list
    point: list
    cursor: tuple  # Physical pixels relative to the captured map.
    tolerance: float = 8

    def matches(self, screen_point, region):
        relative = np.asarray(screen_point) - [region['left'], region['top']]
        return bool(np.linalg.norm(relative - self.cursor) <= self.tolerance)


def text_regions(frame):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = ((hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 185)).astype(np.uint8) * 255
    joined = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((3, 9), np.uint8))
    boxes = [cv2.boundingRect(c) for c in cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]]
    return sorted((b for b in boxes if 8 <= b[3] <= 64 and max(28, b[3]*1.8) <= b[2] <= min(260, b[3]*9)), key=lambda b:(b[1], b[0]))[:24]


def crosshair(frame, x_box, y_box):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).astype(np.float32)
    positions = []
    # The x label sits above the horizontal line; y sits right of the vertical.
    for axis, begin, end in ((0, x_box[1]+x_box[3]+1, x_box[1]+x_box[3]+max(14, x_box[3])),
                             (1, y_box[0]-max(14, y_box[3]), y_box[0]-1)):
        ridge = gray - (np.roll(gray, 3, axis=axis) + np.roll(gray, -3, axis=axis))*.5
        score = np.mean(ridge > 12, axis=1-axis)
        begin, end = max(5, int(begin)), min(len(score)-5, int(end))
        if end <= begin:return None
        index = begin + int(np.argmax(score[begin:end]))
        if score[index] < .45:return None
        positions.append(index)
    return (positions[1], positions[0])


class CoordinateReader:
    def __init__(self):
        self.bridge = None
        self.directory = None
        self.previous = None
        self.context = None
        self.error = ''
        self.retry_at = 0
        self.closed = False
        self.lock = threading.Lock()

    def reset(self):
        self.previous = None

    def read(self, frame, map_id, context):
        if self.closed:return None
        if context != self.context:self.reset();self.context = context
        boxes = text_regions(frame)
        if len(boxes) < 2:self.reset();return None
        if time.monotonic() < self.retry_at:return None
        # Threshold only text bands, keeping small glyphs legible to local OCR.
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        binary = 255-(((hsv[:, :, 1] < 70) & (hsv[:, :, 2] > 160)).astype(np.uint8)*255)
        cell_height = (max(b[3] for b in boxes)+8)*3+40
        cell_width = (max(b[2] for b in boxes)+8)*3+40
        columns = max(1,int(np.ceil(len(boxes)*cell_height/2500)))
        rows = int(np.ceil(len(boxes)/columns))
        sheet = np.full((rows*cell_height,columns*cell_width),255,np.uint8)
        for i, (x,y,w,h) in enumerate(boxes):
            crop = binary[max(0,y-4):y+h+4,max(0,x-4):x+w+4]
            patch = cv2.resize(crop,None,fx=3,fy=3,interpolation=cv2.INTER_CUBIC)
            top = (i//columns)*cell_height+20
            left = (i%columns)*cell_width+20
            sheet[top:top+patch.shape[0],left:left+patch.shape[1]] = patch
        try:
            with self.lock:
                if self.closed:return None
                if self.bridge is None:self.bridge = WindowsBridge(script=Path(__file__).with_name('windows_ocr.ps1'))
                if self.directory is None:self.directory = tempfile.TemporaryDirectory(prefix='wardogs-coordinates-')
                path = Path(self.directory.name)/'labels.png'
                bridge = self.bridge
            cv2.imencode('.png',sheet)[1].tofile(path)
            lines = bridge.call('recognize',timeout=2.5,path=str(path))['lines']
            self.error = ''
        except (OSError, ValueError, RuntimeError) as error:
            self.error = str(error).replace('语音','文字识别')
            with self.lock:
                if self.bridge:self.bridge.close();self.bridge = None
            self.retry_at = time.monotonic()+30
            self.reset();return None
        labels = {}
        for line in lines:
            match = re.fullmatch(r'\s*([xy])\s*([+-]?\d{1,3}[.,]\d{2})\s*',line['text'],re.I)
            words = line.get('words',[])
            if not match or not words:continue
            row = int(np.mean([word['y']+word['height']*.5 for word in words])//cell_height)
            column = int(np.mean([word['x']+word['width']*.5 for word in words])//cell_width)
            index = row*columns+column
            if not 0 <= index < len(boxes):continue
            key = match[1].lower()
            if key in labels:self.reset();return None
            labels[key] = (float(match[2].replace(',','.')),boxes[index])
        if set(labels) != {'x','y'}:self.reset();return None
        cursor = crosshair(frame,labels['x'][1],labels['y'][1])
        if cursor is None:self.reset();return None
        game = [labels['x'][0],labels['y'][0]]
        try:point = game_to_map(map_id,game)
        except ValueError:self.reset();return None
        result = CoordinateFix(game,point,cursor)
        previous, self.previous = self.previous, (result,time.monotonic())
        if (previous and time.monotonic()-previous[1] < 2.5
            and np.linalg.norm(np.asarray(previous[0].game)-game) <= .025
            and np.linalg.norm(np.asarray(previous[0].cursor)-cursor) <= 3):return result
        return None

    def close(self):
        with self.lock:
            self.closed = True
            if self.bridge:self.bridge.close();self.bridge = None

    def cleanup(self):
        self.close()
        if self.directory:self.directory.cleanup();self.directory = None

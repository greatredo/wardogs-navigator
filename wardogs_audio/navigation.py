"""Navigation speech queue; playback receipts survive asynchronous synthesis."""
from collections import deque
from pathlib import Path
import tempfile
import time
from PySide6.QtCore import QObject, Signal, QTimer
from .player import FilePlayer, find_device
from .speech import SpeechService


class NavigationSpeech(QObject):
    status = Signal(str)
    voices_ready = Signal(list)
    completed = Signal(object)
    cancelled = Signal(object)
    started = Signal(str)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.service = SpeechService(self)
        self.player = FilePlayer(self)
        self.queue = deque()
        self.current = None
        self.generation = 0
        self.volume = .85
        self.audio_path = None
        self.failed_texts = set()
        self.temp = tempfile.TemporaryDirectory(prefix='wardogs-nav-audio-')
        self.service.ready.connect(self._ready)
        self.service.failed.connect(self._failed)
        self.service.status.connect(self.status)
        self.service.voices_ready.connect(self.voices_ready)
        self.service.idle.connect(self._next)
        self.player.finished.connect(self._complete)
        self.player.failed.connect(self._play_failed)
        self.player.started.connect(lambda: self.started.emit(self.current[0]) if self.current else None)
        self.timer = QTimer(self)
        self.timer.setInterval(500)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.closed = False

    def load_voices(self):
        if self.settings.get('voice_backend', 'auto') == 'local':
            self.status.emit('默认本地语音包 · 无需 Windows 语音')
        else:
            self.service.load_voices()

    def enqueue(self, text, receipt=None):
        if self.closed or len(self.queue) >= 8:
            self.cancelled.emit(receipt)
            return False
        key = (text, self.settings.get('voice_backend', 'auto'), self.settings.get('voice_name', ''))
        if key in self.failed_texts:
            self.cancelled.emit(receipt)
            return False
        self.queue.append((text, receipt, time.monotonic()))
        self._next()
        return True

    def _next(self):
        if self.closed or self.current is not None or self.service.busy:
            return
        while self.queue:
            item = self.queue.popleft()
            if time.monotonic() - item[2] > 12 or not self._valid(item[1]):
                self.cancelled.emit(item[1])
                continue
            self.current = item
            path = Path(self.temp.name) / f'speech-{self.generation}.wav'
            self.service.synthesize(item[0], 'zh-CN', self.settings.get('voice_name', ''),
                round(self.settings.get('voice_rate', 0) * 10), path, self.generation,
                self.settings.get('voice_backend', 'auto'))
            break

    def _ready(self, path, generation, provider):
        if generation != self.generation or self.current is None:
            return
        self.audio_path = Path(path)
        if not self._valid(self.current[1]):
            self._complete(cancelled=True)
            return
        try:
            self.player.configure(find_device(default=True), self.volume)
            rate = 2 ** max(-1., min(1., self.settings.get('voice_rate', 0))) if provider == 'local' else 1.
            error = self.service.unavailable.get(('zh-CN', self.settings.get('voice_name', '')))
            self.status.emit(('默认本地语音包 · 播报中' + ('\n系统语音错误：' + error if error else '')) if provider == 'local' else '系统语音 · 独立进程播报')
            self.player.play(path, rate=rate)
        except Exception as exc:
            self._play_failed(str(exc))

    def _failed(self, message, generation):
        if generation == self.generation:
            self._play_failed(message)

    def _play_failed(self, message):
        if self.current:
            self.failed_texts.add((self.current[0], self.settings.get('voice_backend', 'auto'), self.settings.get('voice_name', '')))
        self.stop()
        self.status.emit(message)

    def _complete(self, cancelled=False):
        if self.current is None:
            return
        receipt = self.current[1]
        self.current = None
        self._release_audio()
        self.generation += 1
        (self.cancelled if cancelled else self.completed).emit(receipt)
        self._next()

    def _tick(self):
        if self.current and time.monotonic() - self.current[2] > 60:
            self._play_failed('播报超时，已停止')

    @staticmethod
    def _valid(receipt):
        if receipt is None or not receipt[3]:
            return True
        nav, route, lap, ids = receipt
        if not nav.active or nav.route is not route or nav.lap != lap:
            return False
        future = {c.id for c in nav.cues if c.at >= nav.progress - 6 / nav.scale}
        return all((ident[6:] if ident.startswith('along-') else ident) in future for ident in ids)

    def _release_audio(self):
        self.player.stop()
        if self.audio_path is not None:
            self.audio_path.unlink(missing_ok=True)
            self.audio_path = None

    def stop(self):
        self.generation += 1
        items = ([self.current] if self.current else []) + list(self.queue)
        self.current = None
        self.queue.clear()
        self._release_audio()
        self.service.cancel()
        for item in items:
            self.cancelled.emit(item[1])

    def close(self):
        self.closed = True
        self.stop()
        self.timer.stop()
        self.service.close()
        self.temp.cleanup()

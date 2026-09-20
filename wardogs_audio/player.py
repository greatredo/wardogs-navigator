"""One file player for navigation, public-mic output and optional monitoring."""
from PySide6.QtCore import QObject, Signal, QUrl
from PySide6.QtMultimedia import QMediaDevices, QMediaPlayer, QAudioOutput


def device_id(device):
    return bytes(device.id()).hex()


def find_device(identifier='', *, default=False):
    if not identifier and default:
        device = QMediaDevices.defaultAudioOutput()
        if not device.isNull():
            return device
    for device in QMediaDevices.audioOutputs():
        if device_id(device) == identifier:
            return device
    raise ValueError('所选音频设备已断开，请重新选择输出 / 监听设备')


class FilePlayer(QObject):
    finished = Signal()
    failed = Signal(str)
    started = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.monitor = QMediaPlayer(self)
        self.monitor_output = QAudioOutput(self)
        self.monitor.setAudioOutput(self.monitor_output)
        self.active = False
        self.use_monitor = False
        self.done = set()
        for name, player in [('output', self.player), ('monitor', self.monitor)]:
            player.mediaStatusChanged.connect(lambda status, n=name: self._status(n, status))
            player.errorOccurred.connect(lambda *_, n=name, p=player: self._error(n, p.errorString()))
        self.player.playbackStateChanged.connect(self._state)

    def configure(self, output, volume=.8, monitor=None, monitor_volume=.6):
        self.output.setDevice(output)
        self.output.setVolume(volume)
        self.use_monitor = monitor is not None and device_id(monitor) != device_id(output)
        if self.use_monitor:
            self.monitor_output.setDevice(monitor)
            self.monitor_output.setVolume(monitor_volume)

    def play(self, path, *, rate=1.):
        self.stop()
        self.done.clear()
        self.active = True
        source = QUrl.fromLocalFile(str(path))
        self.player.setPlaybackRate(rate)
        self.player.setSource(source)
        if self.use_monitor:
            self.monitor.setPlaybackRate(rate)
            self.monitor.setSource(source)
            self.monitor.play()
        self.player.play()

    def _state(self, state):
        if self.active and state == QMediaPlayer.PlayingState:
            self.started.emit()

    def _status(self, name, status):
        if self.active and status == QMediaPlayer.EndOfMedia:
            self.done.add(name)
            if 'output' in self.done and (not self.use_monitor or 'monitor' in self.done):
                self.active = False
                self.finished.emit()

    def _error(self, name, message):
        if self.active:
            self.stop()
            self.failed.emit(('监听失败：' if name == 'monitor' else '播放失败：') + message)

    def stop(self):
        self.active = False
        for player in (self.player, self.monitor):
            player.stop()
            player.setSource(QUrl())

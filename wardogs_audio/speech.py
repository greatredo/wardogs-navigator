"""Asynchronous, isolated SAPI synthesis with finite local WAV fallback."""
from pathlib import Path
import wave
from PySide6.QtCore import QObject, QThread, Signal
from .bridge import WindowsBridge
from .pack import DefaultVoicePack


class SpeechJob(QThread):
    ready = Signal(str, str)
    failed = Signal(str)
    system_failed = Signal(str)

    def __init__(self, bridge, pack, text, language, voice, rate, path, local):
        super().__init__()
        self.bridge, self.pack, self.local = bridge, pack, local
        self.text, self.language, self.voice, self.rate, self.path = text, language, voice, rate, str(path)

    def run(self):
        try:
            provider = 'local'
            if not self.local:
                try:
                    self.bridge.call('speak', text=self.text, language=self.language,
                                     voice=self.voice, rate=self.rate, path=self.path, timeout=12.)
                    with wave.open(self.path, 'rb') as audio:
                        if audio.getnframes() == 0:
                            raise ValueError('系统语音返回空音频')
                    provider = 'system'
                except Exception as exc:
                    if self.isInterruptionRequested():
                        return
                    self.system_failed.emit(str(exc))
                    self.pack.render(self.text, self.language, self.path)
            else:
                self.pack.render(self.text, self.language, self.path)
            if not self.isInterruptionRequested():
                self.ready.emit(self.path, provider)
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))


class VoiceJob(QThread):
    ready = Signal(list)
    failed = Signal(str)

    def __init__(self, bridge):
        super().__init__()
        self.bridge = bridge

    def run(self):
        try:
            result = self.bridge.call('voices')
            if not self.isInterruptionRequested():
                self.ready.emit(result['voices'])
        except Exception as exc:
            if not self.isInterruptionRequested():
                self.failed.emit(str(exc))
        finally:
            self.bridge.close()


class SpeechService(QObject):
    ready = Signal(str, int, str)
    failed = Signal(str, int)
    status = Signal(str)
    voices_ready = Signal(list)
    idle = Signal()

    def __init__(self, parent=None, *, bridge_factory=WindowsBridge, pack=None):
        super().__init__(parent)
        self.bridge_factory = bridge_factory
        self.pack = pack or DefaultVoicePack()
        self.bridge = None
        self.job = None
        self.voice_job = None
        self.unavailable = {}
        self.revision = 0
        self.voice_revision = 0
        self.closed = False
        self._jobs = set()

    @property
    def busy(self):
        return self.job is not None and self.job.isRunning()

    def _retain(self, job):
        self._jobs.add(job)
        job.finished.connect(lambda j=job: self._finished(j))
        job.start()

    def _finished(self, job):
        self._jobs.discard(job)
        if self.job is job:
            self.job = None
        if self.voice_job is job:
            self.voice_job = None
        if isinstance(job, SpeechJob) and job.isInterruptionRequested():
            Path(job.path).unlink(missing_ok=True)
        job.deleteLater()
        if not self.closed:
            self.idle.emit()

    def load_voices(self):
        if self.closed or (self.voice_job is not None and self.voice_job.isRunning()):
            return
        self.voice_job = VoiceJob(self.bridge_factory())
        revision = self.voice_revision
        self.voice_job.ready.connect(lambda voices: self.voices_ready.emit(voices) if revision == self.voice_revision else None)
        self.voice_job.failed.connect(lambda message: self._voices_failed(message) if revision == self.voice_revision else None)
        self._retain(self.voice_job)

    def _voices_failed(self, message):
        self.voices_ready.emit([])
        self.status.emit('系统声音读取失败，可使用默认本地语音包：' + message)

    def synthesize(self, text, language, voice, rate, path, generation, backend='auto'):
        if self.closed or self.busy:
            return False
        key = (language, voice)
        local = backend == 'local' or key in self.unavailable
        if not local and (self.bridge is None or self.bridge.closed):
            self.bridge = self.bridge_factory()
        self.job = SpeechJob(self.bridge, self.pack, text, language, voice, rate, path, local)
        revision = self.revision
        self.job.ready.connect(lambda p, provider: self.ready.emit(p, generation, provider) if revision == self.revision else None)
        self.job.failed.connect(lambda message: self.failed.emit(message, generation) if revision == self.revision else None)
        self.job.system_failed.connect(lambda message: self._system_failed(key, message, revision))
        self._retain(self.job)
        return True

    def _system_failed(self, key, message, revision):
        if revision == self.revision:
            self.unavailable[key] = message
            self.status.emit('系统语音失败，已切换默认本地语音包：' + message)

    def retry_system(self):
        self.cancel()
        self.cancel_voices()
        self.unavailable.clear()

    def cancel_voices(self):
        self.voice_revision += 1
        if self.voice_job is not None:
            self.voice_job.requestInterruption()
            self.voice_job.bridge.close()

    def cancel(self):
        self.revision += 1
        if self.job is not None:
            self.job.requestInterruption()
        if self.bridge is not None:
            self.bridge.close()
            self.bridge = None

    def close(self):
        self.closed = True
        self.cancel()
        self.cancel_voices()
        for job in list(self._jobs):
            job.requestInterruption()
            if getattr(job, 'bridge', None) is not None:
                job.bridge.close()
        for job in list(self._jobs):
            job.wait(5000)

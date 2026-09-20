"""Cancellable JSON-lines transport to a private Windows helper process."""
import json
import os
from pathlib import Path
from queue import Queue, Empty
import subprocess
import threading


class WindowsBridge:
    def __init__(self, script=None, *, command=None):
        self.script = Path(script) if script else Path(__file__).with_name('windows_speech.ps1')
        self.command = command
        self.process = None
        self.responses = Queue()
        self.lock = threading.RLock()
        self.calls = threading.Lock()
        self.closed = False

    def start(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('语音服务已停止')
            if self.process is not None:
                return
            command = self.command
            if command is None:
                if os.name != 'nt':
                    raise RuntimeError('Windows 系统语音不可用')
                executable = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
                command = [str(executable), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File', str(self.script)]
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            self.process = process
            responses = self.responses
            def read():
                try:
                    for line in process.stdout:
                        responses.put(line)
                finally:
                    responses.put(None)
            self.reader = threading.Thread(target=read, daemon=True)
            self.reader.start()

    def call(self, operation, timeout=8., **fields):
        with self.calls:
            self.start()
            process = self.process
            try:
                process.stdin.write(json.dumps(dict(op=operation, **fields), ensure_ascii=False) + '\n')
                process.stdin.flush()
                response = self.responses.get(timeout=timeout)
                if response is None:
                    raise RuntimeError(f'Windows 语音服务已退出（退出码 {process.poll()}）')
                result = json.loads(response)
                if not result.get('ok'):
                    raise RuntimeError(result.get('error', 'Windows 语音服务失败'))
                return result
            except Empty:
                self.close()
                raise RuntimeError('Windows 语音服务超时') from None
            except (OSError, ValueError, RuntimeError):
                self.close()
                raise

    def close(self):
        with self.lock:
            self.closed = True
            process, self.process = self.process, None
            self.responses.put(None)
        if process is not None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=1)
            self.reader.join(timeout=1)
            for stream in (process.stdin, process.stdout):
                if stream:
                    stream.close()

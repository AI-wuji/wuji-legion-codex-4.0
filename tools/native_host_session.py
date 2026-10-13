import json
import math
from pathlib import Path
import subprocess
import threading
import time


class SessionError(RuntimeError):
    pass


class ObservationTimeout(SessionError):
    pass


class RpcError(SessionError):
    def __init__(self, code):
        self.code = code
        super().__init__(f"Remote RPC error code {code}; no retry or fallback")


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SessionError("Duplicate JSON key in native frame")
        result[key] = value
    return result


def reject_constant(value):
    raise SessionError("Non-finite native JSON value")


class NativeSession:
    REQUEST_METHODS = frozenset({
        "initialize", "thread/start", "turn/start", "thread/read",
        "thread/unsubscribe", "turn/interrupt",
    })

    def __init__(self, command, cwd, max_frame_bytes=1048576, max_pending_frames=4096):
        self.command = list(command)
        self.cwd = Path(cwd).resolve(strict=True)
        if not self.command or not all(isinstance(argument, str) and argument for argument in self.command):
            raise SessionError("Explicit non-empty owned-process command required")
        if not self.cwd.is_dir():
            raise SessionError("Existing isolated workspace directory required")
        if not isinstance(max_frame_bytes, int) or isinstance(max_frame_bytes, bool) or not 1 <= max_frame_bytes <= 1048576:
            raise SessionError("Frame byte cap must be in 1..1048576")
        if not isinstance(max_pending_frames, int) or isinstance(max_pending_frames, bool) or not 1 <= max_pending_frames <= 4096:
            raise SessionError("Pending frame cap must be in 1..4096")
        self.max_frame_bytes = max_frame_bytes
        self.max_pending_frames = max_pending_frames
        self._process = None
        self._condition = threading.Condition()
        self._pending = []
        self._used_ids = set()
        self._failure = None
        self._stdout_done = False
        self._closed = False
        self._reader = None
        self._stderr_reader = None
        self._stderr_bytes = 0

    def start(self):
        if self._process is not None or self._closed:
            raise SessionError("Owned session cannot be restarted")
        self._process = subprocess.Popen(
            self.command, cwd=self.cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        self._reader = threading.Thread(target=self._read_frames, daemon=True)
        self._stderr_reader = threading.Thread(target=self._drain_errors, daemon=True)
        self._reader.start()
        self._stderr_reader.start()

    def is_live(self):
        return self._process is not None and self._process.poll() is None

    def _read_frames(self):
        try:
            while True:
                line = self._process.stdout.readline(self.max_frame_bytes + 2)
                if not line:
                    break
                if len(line.rstrip(b"\r\n")) > self.max_frame_bytes or (not line.endswith(b"\n") and len(line) > self.max_frame_bytes):
                    raise SessionError("Native frame exceeds byte cap")
                try:
                    frame = json.loads(line.decode("utf-8"), object_pairs_hook=strict_object, parse_constant=reject_constant)
                except (UnicodeError, ValueError, RecursionError) as error:
                    raise SessionError("Invalid native JSON frame") from error
                if not isinstance(frame, dict):
                    raise SessionError("Native frame must be an object")
                with self._condition:
                    if len(self._pending) >= self.max_pending_frames:
                        raise SessionError("Native pending-frame budget exhausted")
                    self._pending.append(frame)
                    self._condition.notify_all()
        except (SessionError, OSError, RecursionError) as error:
            with self._condition:
                self._failure = error if isinstance(error, SessionError) else SessionError("Owned frame reader failed")
                self._condition.notify_all()
        finally:
            self._process.stdout.close()
            with self._condition:
                self._stdout_done = True
                self._condition.notify_all()

    def _drain_errors(self):
        try:
            while True:
                chunk = self._process.stderr.read(4096)
                if not chunk:
                    break
                self._stderr_bytes = min(65536, self._stderr_bytes + len(chunk))
        except OSError:
            pass
        finally:
            self._process.stderr.close()

    @staticmethod
    def _timeout(timeout):
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise SessionError("Positive finite observation timeout required")
        return float(timeout)

    def _send(self, message):
        if self._closed or not self.is_live():
            raise SessionError("Owned session is not live; never automatically restart")
        try:
            payload = json.dumps(message, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        except (ValueError, TypeError) as error:
            raise SessionError("Request must contain finite JSON values") from error
        if len(payload) > self.max_frame_bytes:
            raise SessionError("Native request exceeds byte cap")
        try:
            self._process.stdin.write(payload + b"\n")
            self._process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise SessionError("Owned request write failed; submission may be unknown") from error

    def _await(self, predicate, timeout):
        deadline = time.monotonic() + self._timeout(timeout)
        with self._condition:
            while True:
                if self._failure is not None:
                    raise self._failure
                for index, frame in enumerate(self._pending):
                    if predicate(frame):
                        return self._pending.pop(index)
                if self._stdout_done and not self.is_live():
                    raise SessionError("Owned transport is terminal without a matched frame")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ObservationTimeout("Observation timed out; not proof of action end, close or free slot")
                self._condition.wait(min(remaining, 0.1))

    def request(self, request_id, method, params, timeout=30):
        self._timeout(timeout)
        if method not in self.REQUEST_METHODS:
            raise SessionError("RPC method outside bounded native observation/execution allowlist")
        if isinstance(request_id, bool) or not isinstance(request_id, int) or request_id < 0:
            raise SessionError("Non-negative exact integer request ID required")
        if not isinstance(params, dict):
            raise SessionError("RPC params object required")
        with self._condition:
            if request_id in self._used_ids:
                raise SessionError("Request ID already used; no retry or replayed submission")
            self._used_ids.add(request_id)
        self._send({"id": request_id, "method": method, "params": params})
        frame = self._await(
            lambda value: "method" not in value and type(value.get("id")) is int
            and value["id"] == request_id, timeout,
        )
        if "jsonrpc" in frame and frame["jsonrpc"] != "2.0":
            raise SessionError("Unsupported RPC jsonrpc version")
        if ("result" in frame) == ("error" in frame):
            raise SessionError("RPC response requires exactly one result or error")
        if "error" in frame:
            error = frame["error"]
            if not isinstance(error, dict) or type(error.get("code")) is not int or not isinstance(error.get("message"), str):
                raise SessionError("RPC error object requires an exact integer code and string message")
            raise RpcError(error["code"])
        if not isinstance(frame["result"], dict):
            raise SessionError("RPC object result required")
        return frame["result"]

    def notify(self, method, params):
        if method != "initialized" or not isinstance(params, dict):
            raise SessionError("Only initialized notification is permitted")
        self._send({"method": method, "params": params})

    def next_notification(self, method, thread_id, timeout=30):
        self._timeout(timeout)
        if not isinstance(method, str) or not method or not isinstance(thread_id, str) or not thread_id:
            raise SessionError("Exact notification method and thread ID required")
        return self._await(
            lambda frame: "id" not in frame and frame.get("method") == method
            and isinstance(frame.get("params"), dict) and frame["params"].get("threadId") == thread_id,
            timeout,
        )

    def next_event(self, thread_id, timeout=30):
        self._timeout(timeout)
        if not isinstance(thread_id, str) or not thread_id:
            raise SessionError("Exact notification thread ID required")
        return self._await(
            lambda frame: "id" not in frame and isinstance(frame.get("method"), str)
            and isinstance(frame.get("params"), dict) and frame["params"].get("threadId") == thread_id,
            timeout,
        )

    def close(self, timeout=5):
        timeout = self._timeout(timeout)
        if self._process is None:
            self._closed = True
            return {"owned_process_exited": True, "exit_code": None}
        self._closed = True
        try:
            self._process.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        if self._process.poll() is None:
            try:
                self._process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._process.terminate()
                try:
                    self._process.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait(timeout=timeout)
        for reader in [self._reader, self._stderr_reader]:
            if reader is not None:
                reader.join(timeout=timeout)
                if reader.is_alive():
                    raise SessionError("Owned transport reader exit not observed; close remains unknown")
        return {"owned_process_exited": self._process.poll() is not None, "exit_code": self._process.returncode}

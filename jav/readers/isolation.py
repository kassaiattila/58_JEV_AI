"""Bounded native-reader process with a credential-free environment.

Windows Job Objects enforce memory/process limits and kill-on-close. The worker's
audit policy rejects Python filesystem/network/process operations after trusted
dependencies load. This is not a sandbox for arbitrary malicious native code.
"""
from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import threading

from .contracts import ReadLimits
from .limits import ReadFailure


class Job:
    def __init__(self, process: subprocess.Popen, memory_bytes: int):
        if os.name != "nt":
            raise ReadFailure("excluded", "protection_unavailable", "This measured process boundary requires Windows")

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel, self.handle = kernel, kernel.CreateJobObjectW(None, None)
        try:
            if not self.handle:
                raise ctypes.WinError(ctypes.get_last_error())
            info = Extended()
            info.BasicLimitInformation.LimitFlags = 0x2000 | 0x100 | 0x8
            info.BasicLimitInformation.ActiveProcessLimit = 1
            info.ProcessMemoryLimit = memory_bytes
            if not kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
                raise ctypes.WinError(ctypes.get_last_error())
            if not kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
                raise ctypes.WinError(ctypes.get_last_error())
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def exchange(command: list[str], request: bytes, limits: ReadLimits, *, output_bound: int,
             timeout: float | None = None) -> bytes:
    """Send bounded input only after a trusted worker has joined its Job Object."""
    root = Path(__file__).resolve().parents[2]
    environment = {key: os.environ[key] for key in ("SYSTEMROOT", "WINDIR") if key in os.environ}
    environment["PYTHONUTF8"] = "1"
    environment["PYTHON_DOTENV_DISABLED"] = "1"
    environment["OMP_THREAD_LIMIT"] = "1"
    process = subprocess.Popen(command, cwd=root,
        env=environment, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True)
    job = None
    output, diagnostics, overflow = [], [], []
    threads = []

    def collect(stream, target, bound):
        try:
            chunk = stream.read(bound + 1)
            if len(chunk) > bound:
                overflow.append(True)
                process.kill()
            target.append(chunk[:bound])
        except OSError:
            pass

    try:
        try:
            job = Job(process, limits.memory_bytes)
        except (OSError, ReadFailure) as exc:
            raise ReadFailure("excluded", "protection_unavailable", "Could not enforce worker resource boundary") from exc
        for stream, target, bound in ((process.stdout, output, output_bound), (process.stderr, diagnostics, 4096)):
            thread = threading.Thread(target=collect, args=(stream, target, bound), daemon=True)
            thread.start()
            threads.append(thread)
        # Sending is included in the deadline, including a worker that never reads.
        def send():
            try:
                process.stdin.write(request)
                process.stdin.close()
            except (OSError, ValueError):
                pass
        writer = threading.Thread(target=send, daemon=True)
        writer.start()
        threads.append(writer)
        try:
            process.wait(timeout=timeout if timeout is not None else limits.wall_seconds)
        except subprocess.TimeoutExpired as exc:
            raise ReadFailure("resource_limited", "resource_limit", "Reader wall-clock deadline exceeded") from exc
        for thread in threads:
            thread.join(timeout=1)
        if overflow:
            raise ReadFailure("resource_limited", "resource_limit", "Reader output limit exceeded")
        if process.returncode != 0:
            raise ReadFailure("resource_limited", "resource_limit", "Reader stopped before publishing bounded output")
        return b"".join(output)
    finally:
        if process.poll() is None:
            process.kill()
        if job is not None:
            job.close()
        process.wait()
        for thread in threads:
            thread.join(timeout=1)
        for stream in (process.stdin, process.stdout, process.stderr):
            stream.close()


def run(data: bytes, filename: str, limits: ReadLimits, *, probe: str | None = None,
        recognise: bool = False) -> dict:
    """Parse source bytes under the existing Python and operating-system policy."""
    if len(data) > limits.input_bytes:
        raise ReadFailure("resource_limited", "resource_limit", "Input byte limit exceeded")
    script = Path(__file__).with_name("worker.py")
    # Avoid the Windows venv launcher's extra child process.
    executable = getattr(sys, "_base_executable", sys.executable)
    request = json.dumps({"data": base64.b64encode(data).decode(), "filename": filename,
                          "limits": limits.model_dump(mode="json"), "probe": probe,
                          "recognise": recognise}).encode()
    output = exchange([executable, "-I", "-B", str(script)], request, limits,
                      output_bound=limits.output_bytes + 2 * limits.expanded_bytes)
    try:
        response = json.loads(output)
    except (ValueError, UnicodeError) as exc:
        raise ReadFailure("corrupt", "corrupt", "Invalid reader response") from exc
    if "failure" in response:
        raise ReadFailure(**response["failure"])
    return response

"""Isolated PDF reading (077, J6): the third-party PDF parsers run in a separate helper process, with limits.

pdfplumber (pdfminer) and PDFium (pypdfium2) parse untrusted input: attachments from any sender reach the worker, and
the local service renders page images of them. A broken or hostile PDF could hang a parser or exhaust the memory; in
the calling process that would stop the worker, or every page-image request behind the shared lock. Here the parsing
runs in one long-lived helper process per calling process:

- one request at a time (PDFium is not thread-safe, 063; the local service serves requests on parallel threads), each
  with a time limit; on overrun the helper is stopped, and the next request starts a new one;
- a memory limit: on Windows a job object (the operating system refuses allocations above the limit; closing the job
  also stops the helper when the calling process dies), elsewhere `RLIMIT_AS`;
- the requests are the module-level functions at the end of this file, with every setting as a parameter, so the helper
  never reads a config file. Our own processing (lines, cells, candidates) stays in the calling process.

Settings: the `pdf_reader` section of `configs/service.json`. With `isolated: false` the same functions run in the
calling process, under one lock (the behaviour before 077).
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import sys
import threading
import time
from dataclasses import asdict, dataclass
from multiprocessing.connection import Connection
from typing import Any, Callable, Literal

log = logging.getLogger("jav.isolated_pdf")

Kind = Literal["read", "render", "page_image"]


class PdfReaderLimit(ValueError):
    """The helper went over its time or memory limit, or stopped during the request: the document is not read. `reason`:
    `timeout`, `memory`, `stopped` (crash, or a native allocation over the memory limit) or `startup`. Final for a worker
    item: a retry would hit the same limit."""

    def __init__(self, message: str, *, reason: str = "limit") -> None:  # the default keeps it picklable
        super().__init__(message)
        self.reason = reason


class PdfReaderError(ValueError):
    """The parser raised an error in the helper (e.g. a corrupt PDF); the message starts with the error's type name."""


@dataclass(frozen=True)
class ReaderSettings:
    isolated: bool
    read_timeout_s: float
    render_timeout_s: float
    page_image_timeout_s: float
    memory_mb: int
    startup_timeout_s: float
    require_memory_limit: bool = False

    def timeout_s(self, kind: Kind) -> float:
        return {"read": self.read_timeout_s, "render": self.render_timeout_s, "page_image": self.page_image_timeout_s}[kind]


def settings() -> ReaderSettings:
    """The reader settings (077) from the `pdf_reader` section of `configs/service.json`."""
    from jav import cfg

    return ReaderSettings(**cfg.load("service")["pdf_reader"])


# --- the calling side -------------------------------------------------------------------------------------------------

_INPROCESS_LOCK = threading.RLock()  # 063: PDFium is not thread-safe (the switched-off, in-process mode)
_default: Reader | None = None
_default_lock = threading.Lock()


def protection_status() -> dict[str, Any]:
    """A non-starting snapshot of this process's reader, distinct from its configuration."""
    s = settings()
    configured = asdict(s)
    with _default_lock:
        reader = _default
    if not s.isolated:
        report = _report("unprotected", "isolation_disabled")
    elif reader is None:
        report = _report("unknown", "not_started")
    else:
        report = reader.protection_status()
        if (reader.memory_mb, reader.require_memory_limit) != (s.memory_mb, s.require_memory_limit):
            report = {**report, "state": "stale", "reason": "settings_changed", "effective_memory_mb": None}
    return {**report, "configured": configured, "process_pid": os.getpid()}


def _report(state: str, reason: str, *, memory_mb: int | None = None,
            helper_pid: int | None = None) -> dict[str, Any]:
    return {"state": state, "reason": reason, "effective_memory_mb": memory_mb,
            "helper_pid": helper_pid, "observed_at": time.time()}


def run(fn: Callable[..., Any], *, kind: Kind, **kwargs: Any) -> Any:
    """Runs one request function of this module (`extract_words`, `page_sizes`, `render_pages`, `render_page_png`,
    `page_count`) in the helper, within the time limit of its `kind`."""
    s = settings()
    if not s.isolated:
        if s.require_memory_limit:
            raise PdfReaderLimit("the PDF reader requires an isolated memory limit", reason="memory_limit_unavailable")
        with _INPROCESS_LOCK:
            return fn(**kwargs)
    global _default
    with _default_lock:
        if _default is not None and (_default.memory_mb, _default.startup_timeout_s, _default.require_memory_limit) != (
                s.memory_mb, s.startup_timeout_s, s.require_memory_limit):
            _default.close()
            _default = None
        if _default is None:
            _default = Reader(memory_mb=s.memory_mb, startup_timeout_s=s.startup_timeout_s,
                              require_memory_limit=s.require_memory_limit)
        reader = _default
    return reader.call(fn, timeout_s=s.timeout_s(kind), **kwargs)


class Reader:
    """One helper process and its pipe; started on the first request, started again after a stop."""

    def __init__(self, *, memory_mb: int, startup_timeout_s: float, require_memory_limit: bool = False) -> None:
        self.memory_mb = memory_mb
        self.startup_timeout_s = startup_timeout_s
        self.require_memory_limit = require_memory_limit
        self.starts = 0  # how many helpers have been started (tests; a growing number means limit overruns)
        self.memory_limited = False  # whether the current helper runs under the memory limit
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._state = _report("unknown", "not_started")
        self._proc: Any = None
        self._conn: Connection | None = None
        self._job: int | None = None

    def protection_status(self) -> dict[str, Any]:
        """Does not wait for a parser request. A dead helper invalidates a former green state."""
        with self._state_lock:
            state = dict(self._state)
            if state["helper_pid"] is not None and (self._proc is None or not self._proc.is_alive()):
                self.memory_limited = False
                state.update(state="stale", reason="helper_stopped", effective_memory_mb=None)
            return {**state, "observed_at": time.time()}

    def call(self, fn: Callable[..., Any], *, timeout_s: float, **kwargs: Any) -> Any:
        with self._lock:
            conn = self._ensure()
            try:
                conn.send((fn, kwargs))
            except (EOFError, OSError):  # the helper stopped between two requests: one new start
                self._stop()
                conn = self._ensure()
                try:
                    conn.send((fn, kwargs))
                except (EOFError, OSError) as exc:
                    code = self._stop()
                    raise PdfReaderLimit(f"the PDF reader stopped before the request (exit code {code})",
                                         reason="stopped") from exc
            if not conn.poll(timeout_s):
                self._stop()
                raise PdfReaderLimit(f"the PDF reader gave no answer within {timeout_s:g} s", reason="timeout")
            try:
                status, payload = conn.recv()
            except (EOFError, OSError) as exc:
                code = self._stop()
                raise PdfReaderLimit(f"the PDF reader stopped while reading (exit code {code}; over the {self.memory_mb} MB "
                                     "memory limit, or a crash)", reason="stopped") from exc
            if status == "memory":
                self._stop()  # the helper exits after a failed allocation; its heap may be damaged
                raise PdfReaderLimit(f"the PDF reader went over its {self.memory_mb} MB memory limit", reason="memory")
        if status == "error":
            raise PdfReaderError(payload)
        return payload

    def close(self) -> None:
        with self._lock:
            self._stop()

    def _ensure(self) -> Connection:
        if self._proc is not None and self._conn is not None and self._proc.is_alive():
            if self.require_memory_limit and not self.memory_limited:
                raise PdfReaderLimit("the PDF reader memory limit is unavailable", reason="memory_limit_unavailable")
            return self._conn
        self._stop()
        if self.require_memory_limit and self.memory_mb <= 0:
            with self._state_lock:
                self._state = _report("unprotected", "memory_limit_disabled")
            raise PdfReaderLimit("the PDF reader memory limit is disabled", reason="memory_limit_unavailable")
        ctx = multiprocessing.get_context("spawn")
        parent, child = ctx.Pipe()
        proc = ctx.Process(target=_serve, args=(child, self.memory_mb * 1_048_576), name="jav-pdf-reader", daemon=True)
        proc.start()
        child.close()
        with self._state_lock:
            self._proc, self._conn = proc, parent
            self._state = _report("unknown", "starting", helper_pid=proc.pid)
        failure = "memory_limit_disabled" if self.memory_mb <= 0 else "memory_limit_unavailable"
        limited = False
        if sys.platform == "win32" and self.memory_mb > 0:
            try:
                self._job = _windows_job(proc.pid, self.memory_mb * 1_048_576)
                limited = True
            except OSError:
                # the time limit still applies; without the job the helper also stops when its pipe closes
                log.warning("the PDF reader runs without a memory limit: no job object for pid %s", proc.pid, exc_info=True)
                failure = "windows_job_unavailable"
        if not parent.poll(self.startup_timeout_s):
            self._stop()
            raise PdfReaderLimit(f"the PDF reader did not start within {self.startup_timeout_s:g} s", reason="startup")
        try:
            ready, details = parent.recv()
        except (EOFError, OSError) as exc:
            code = self._stop()
            raise PdfReaderLimit(f"the PDF reader stopped while starting (exit code {code})", reason="startup") from exc
        if ready != "ready" or not isinstance(details, dict) or details.get("pid") != proc.pid:
            self._stop()
            raise PdfReaderLimit("the PDF reader sent an invalid start-up report", reason="startup")
        if sys.platform != "win32":
            limited = details.get("memory_limited") is True and self.memory_mb > 0
            failure = details.get("reason", failure)
        with self._state_lock:
            self.memory_limited = limited
            self._state = _report("protected" if limited else "unprotected", "memory_limit_applied" if limited else failure,
                                  memory_mb=self.memory_mb if limited else None, helper_pid=proc.pid)
        if self.require_memory_limit and not limited:
            self._stop(state="unprotected", reason=failure)
            raise PdfReaderLimit("the PDF reader memory limit is unavailable", reason="memory_limit_unavailable")
        self.starts += 1
        return parent

    def _stop(self, *, state: str = "stale", reason: str = "helper_stopped") -> int | None:
        with self._state_lock:
            proc, conn, job = self._proc, self._conn, self._job
            self._proc, self._conn, self._job = None, None, None
            self.memory_limited = False
            if proc is not None or state == "unprotected":
                self._state = _report(state, reason)
        if conn is not None:
            conn.close()
        code = None
        if proc is not None:
            if proc.is_alive():
                proc.kill()
            proc.join(10)
            code = proc.exitcode
            if code is not None:
                proc.close()
        if job is not None:
            _close_handle(job)  # kills whatever is still in the job
        return code


# --- Windows job object (memory limit) --------------------------------------------------------------------------------

_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x0100
_JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x0400  # no error-report dialog holding a crashed helper open
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_SET_QUOTA = 0x0100
_PROCESS_TERMINATE = 0x0001


def _kernel32() -> Any:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.SetInformationJobObject.restype = wintypes.BOOL
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def _windows_job(pid: int, memory_bytes: int) -> int:
    """A job object with a per-process memory limit, killing its processes when closed; the helper `pid` is put in it.
    Returns the job's handle (closed by `_close_handle`)."""
    import ctypes
    from ctypes import wintypes

    class BasicLimit(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

    class IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                         "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class ExtendedLimit(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IoCounters), ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    k32 = _kernel32()
    job = k32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        info = ExtendedLimit()
        info.BasicLimitInformation.LimitFlags = (_JOB_OBJECT_LIMIT_PROCESS_MEMORY | _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
                                                 | _JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION)
        info.ProcessMemoryLimit = memory_bytes
        if not k32.SetInformationJobObject(job, _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION, ctypes.byref(info),
                                           ctypes.sizeof(info)):
            raise ctypes.WinError(ctypes.get_last_error())
        process = k32.OpenProcess(_PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, pid)
        if not process:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if not k32.AssignProcessToJobObject(job, process):
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            k32.CloseHandle(process)
    except OSError:
        k32.CloseHandle(job)
        raise
    return job


def _close_handle(handle: int) -> None:
    if sys.platform == "win32":
        _kernel32().CloseHandle(handle)


# --- the helper side --------------------------------------------------------------------------------------------------


def _serve(conn: Connection, memory_bytes: int) -> None:
    """The helper's loop: memory limit (outside Windows), parsers preloaded (so a request's time limit covers only its
    work), then one answer per request until the pipe closes. Answers: ("ok", result), ("error", "Type: message"),
    ("memory", "")."""
    limited = False
    reason = "memory_limit_disabled" if not memory_bytes else "memory_limit_unavailable"
    if memory_bytes and sys.platform != "win32":
        import resource

        try:
            resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
            limited = True
        except (OSError, ValueError):
            log.warning("the PDF reader could not apply RLIMIT_AS", exc_info=True)
    import pdfplumber  # noqa: F401 - preloaded
    import pypdfium2  # noqa: F401 - preloaded

    logging.getLogger("pdfminer").setLevel(logging.ERROR)  # a warning for every broken font descriptor: noise
    conn.send(("ready", {"pid": os.getpid(), "memory_limited": limited, "reason": reason}))
    while True:
        try:
            fn, kwargs = conn.recv()
        except (EOFError, OSError):
            return  # the calling process closed the pipe or has stopped
        try:
            reply: tuple[str, Any] = ("ok", fn(**kwargs))
        except MemoryError:
            reply = ("memory", "")
        except Exception as exc:  # noqa: BLE001 - every parser error goes back to the caller, by name
            reply = ("error", f"{type(exc).__name__}: {exc}")
        try:
            conn.send(reply)
        except (EOFError, OSError):
            return
        except MemoryError:
            _send_last(conn, ("memory", ""))
            return
        except Exception as exc:  # noqa: BLE001 - e.g. a result that cannot be pickled
            _send_last(conn, ("error", f"{type(exc).__name__}: {exc}"))
        if reply[0] == "memory":
            return  # after a failed allocation the heap may be damaged: the caller starts a new helper


def _send_last(conn: Connection, reply: tuple[str, Any]) -> None:
    try:
        conn.send(reply)
    except (EOFError, OSError, MemoryError):
        log.debug("could not send the last answer to the caller")


# --- the requests (run in the helper; every setting is a parameter) ---------------------------------------------------


def extract_words(path: str, *, max_pages: int, x_tolerance: float, y_tolerance: float
                  ) -> tuple[int, list[tuple[float, float]], list[list[dict[str, Any]]] | None]:
    """The raw words of the text layer, page by page (pdfplumber), and the page sizes. Over `max_pages` pages only the
    page count comes back (words: None), without parsing the pages. Each page is closed after its words are taken:
    pdfplumber otherwise keeps every parsed page in memory (measured: 35 pages 326 MB → 49 MB, the same words)."""
    import pdfplumber

    with pdfplumber.open(path) as doc:
        n_pages = len(doc.pages)
        if n_pages > max_pages:
            return n_pages, [], None
        sizes: list[tuple[float, float]] = []
        pages: list[list[dict[str, Any]]] = []
        for page in doc.pages:
            sizes.append((float(page.width), float(page.height)))
            pages.append(page.extract_words(x_tolerance=x_tolerance, y_tolerance=y_tolerance, keep_blank_chars=False))
            page.close()
    return n_pages, sizes, pages


def page_sizes(path: str) -> list[tuple[float, float]] | None:
    """Page sizes in points (PDFium); None for a file PDFium cannot open."""
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(path)
    except pdfium.PdfiumError:
        return None
    try:
        return [tuple(float(v) for v in doc[i].get_size()) for i in range(len(doc))]
    finally:
        doc.close()


def page_count(path: str) -> int:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(path)
    try:
        return len(doc)
    finally:
        doc.close()


def render_pages(path: str, *, out_dir: str, dpi: int, max_pages: int, grayscale: bool, max_megapixels: float
                 ) -> dict[str, Any]:
    """The OCR page images as PNG files in `out_dir`: {"pages": [paths]}. If any page would go over `max_megapixels`
    at `dpi`, no image is made: {"too_large": [page number, width, height]}."""
    import pypdfium2 as pdfium

    from jav.pdf import fit_scale

    scale = dpi / 72.0
    doc = pdfium.PdfDocument(path)
    try:
        n = min(len(doc), max_pages)
        for i in range(n):  # all page sizes first: if one is too large, make no image at all
            w, h = doc[i].get_size()
            if fit_scale(w, h, scale=scale, max_megapixels=max_megapixels) < scale:
                return {"too_large": [i + 1, w, h]}
        out: list[str] = []
        for i in range(n):
            page = doc[i]
            try:
                img = page.render(scale=scale, grayscale=grayscale).to_pil()
            finally:
                page.close()
            target = os.path.join(out_dir, f"p-{i + 1}.png")
            img.save(target)
            out.append(target)
    finally:
        doc.close()
    return {"pages": out}


def render_page_png(source: str | bytes, *, page: int, dpi: int, max_megapixels: float) -> dict[str, Any]:
    """One 1-based page as PNG, in colour, shrunk into the pixel budget if needed: {"png": bytes}; a page out of range:
    {"page_count": n}. `source`: a path, or the already verified bytes of the file (075)."""
    import io

    import pypdfium2 as pdfium

    from jav.pdf import fit_scale

    doc = pdfium.PdfDocument(source)
    try:
        if not 1 <= page <= len(doc):
            return {"page_count": len(doc)}
        pdf_page = doc[page - 1]
        try:
            w, h = pdf_page.get_size()  # 067: lower resolution for huge page sizes (the boxes are placed in percentages)
            img = pdf_page.render(scale=fit_scale(w, h, scale=dpi / 72.0, max_megapixels=max_megapixels)).to_pil()
        finally:
            pdf_page.close()
    finally:
        doc.close()
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return {"png": buf.getvalue()}

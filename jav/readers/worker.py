"""Private subprocess entry point. No model clients or application store imports."""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys

# -I removes caller-controlled import paths; this trusted checkout is explicit.
CHECKOUT = Path(__file__).resolve().parents[2]
DEPENDENCIES = CHECKOUT / ".venv" / "Lib" / "site-packages"
sys.path.insert(0, str(DEPENDENCIES))
sys.path.insert(0, str(CHECKOUT))


def install_policy():
    import os
    library_roots = [Path(sys.base_prefix, "Lib").resolve(), DEPENDENCIES.resolve()]

    def audit(event, args):
        if event.startswith(("socket.", "subprocess.", "ctypes.")) or event in {
            "os.system", "os.startfile", "os.spawn", "os.exec", "os.fork", "os.putenv", "os.unsetenv",
            "os.remove", "os.rename", "os.rmdir", "os.mkdir", "os.link", "os.symlink", "os.truncate",
        }:
            raise PermissionError("Reader policy denied network, process or mutation access")
        if event == "open":
            target, mode, flags = args
            if not isinstance(target, (str, bytes, os.PathLike)):
                raise PermissionError("Reader cannot open external descriptors")
            candidate = Path(os.fsdecode(target)).resolve()
            writing = flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
            if writing or not any(candidate.is_relative_to(root) for root in library_roots):
                raise PermissionError("Reader path is outside its read-only dependency roots")
        if event in {"os.listdir", "os.scandir"}:
            candidate = Path(args[0]).resolve()
            if not any(candidate.is_relative_to(root) for root in library_roots):
                raise PermissionError("Reader cannot enumerate application or user directories")
    sys.addaudithook(audit)


def main():
    # The parent assigns the Job Object before releasing this bounded request.
    request_bytes = sys.stdin.buffer.read(12_000_000)
    request = json.loads(request_bytes)
    from jav.readers.contracts import ReadLimits
    from jav.readers.limits import ReadFailure
    from jav.readers.native import evidence_view, read
    import docx  # noqa: F401 - trusted imports before filesystem restrictions
    import openpyxl  # noqa: F401
    from PIL import Image
    import encodings.utf_8_sig  # noqa: F401
    import encodings.cp1252  # noqa: F401
    import socket
    import time
    Image.init()
    limits = ReadLimits.model_validate(request["limits"])
    Image.MAX_IMAGE_PIXELS = limits.image_pixels
    try:
        install_policy()
        probe = request.get("probe")
        if probe == "network":
            socket.socket()
        elif probe == "path":
            Path(__file__).read_bytes()
        elif probe == "time":
            time.sleep(limits.wall_seconds + 5)
        elif probe == "memory":
            chunks = []
            while True:
                chunks.append(bytearray(32_000_000))
        elif probe == "output":
            sys.stdout.write("x" * (limits.output_bytes + 2 * limits.expanded_bytes + 1))
            return
        elif probe:
            raise ValueError("Unknown self-test operation")
        result = read(base64.b64decode(request["data"], validate=True), request["filename"], limits)
        output = json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        structure = json.dumps(evidence_view(result), ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        if len(structure) > limits.output_bytes or len(output) > limits.output_bytes + 2 * limits.expanded_bytes:
            raise ReadFailure("resource_limited", "resource_limit", "Serialized reading exceeds output limit")
    except ReadFailure as exc:
        output = json.dumps({"failure": {"status": exc.status, "code": exc.code, "message": str(exc)}}).encode()
    except MemoryError:
        output = b'{"failure":{"status":"resource_limited","code":"resource_limit","message":"Worker memory limit exceeded"}}'
    except PermissionError:
        output = b'{"failure":{"status":"excluded","code":"excluded","message":"Worker operation rejected by isolation policy"}}'
    except Exception as exc:
        # Exception type is useful; arbitrary parser messages may expose host paths.
        output = json.dumps({"failure": {"status": "corrupt", "code": "corrupt",
                            "message": f"Native reader rejected input ({type(exc).__name__})"}}).encode()
    sys.stdout.buffer.write(output)


if __name__ == "__main__":
    try:
        main()
    except ModuleNotFoundError:
        sys.stdout.buffer.write(b'{"failure":{"status":"unsupported","code":"unsupported","message":"Required reader dependency is not installed"}}')

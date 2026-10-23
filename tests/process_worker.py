"""A process-core worker for the failure tests (213): `python -m tests.process_worker --dir <folder> --name <name>`.

Runs the engine loop (`jav.core.process.engine.run`) on the folder's store with the invented quote case's step kinds
until its stop file (`stop-<name>` in the folder) appears; any number of workers may run on the same store. The stop
file goes by a name given on the command line, not by the process id: on Windows a virtual environment's `python.exe`
is a launcher that runs the interpreter as a child process, so the id the parent sees is not the worker's own.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from jav.core import store
from jav.core.process import engine
from tests import process_quote


def stop_file(folder: Path, name: str) -> Path:
    return folder / f"stop-{name}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A process-core worker for the failure tests (213).")
    parser.add_argument("--dir", type=Path, required=True, help="the test's folder (its store and the stand-in systems)")
    parser.add_argument("--name", required=True, help="the worker's name, for its stop file")
    parser.add_argument("--poll", type=float, default=0.1, help="seconds to wait when there is nothing to do")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(process)d %(name)s %(levelname)s %(message)s")
    folder = args.dir.resolve()
    stop = stop_file(folder, args.name)
    with store.use_store(folder / process_quote.STORE_FILE):
        info = engine.run(stop=stop.exists, poll_s=args.poll)
    stop.unlink(missing_ok=True)
    logging.getLogger(__name__).info("worker %s stopped: %s", args.name, info)
    return 0


if __name__ == "__main__":
    sys.exit(main())

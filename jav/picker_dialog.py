"""The dialog process of `jav/local_picker.py` (081): opens the system's folder or file picker above the other windows
and prints the chosen paths as one JSON line.

Run as `python -m jav.picker_dialog '<request JSON>'`, where the request is
`{"kind": "folder" | "files", "title": str, "initial": str | null}`. Cancelling prints `[]`. Any failure (no window
toolkit, no desktop session) ends with a non-zero exit code and the error on stderr.
"""

from __future__ import annotations

import json
import sys


def main(argv: list[str]) -> int:
    request = json.loads(argv[0])
    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.withdraw()
    root.attributes("-topmost", True)  # the dialog belongs to this window, so it opens above the browser
    root.update()
    options = {"parent": root, "title": request.get("title") or "", "initialdir": request.get("initial")}
    if request["kind"] == "folder":
        chosen = filedialog.askdirectory(mustexist=True, **options)
        paths = [chosen] if chosen else []
    else:
        chosen = filedialog.askopenfilenames(filetypes=[("PDF", "*.pdf"), ("*.*", "*.*")], **options)
        paths = list(root.tk.splitlist(chosen)) if chosen else []
    root.destroy()
    print(json.dumps(paths, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

"""265 (code review X-02): the system's folder picker never opens at a network path it was not asked to open.

The dialog's start folder comes from the page (the last path typed or chosen). A network path there was checked, and
the dialog opened at it, contacting the host (an outgoing SMB connection) before the person asked for anything. Now a
network start folder is left out; a network folder the person chooses in the dialog, or types, stays allowed (the NAS
backup, a shared work folder).
"""

from __future__ import annotations

from jav.service import local_picker

NETWORK = ("\\\\nas\\backup", "//nas/backup", "\\\\?\\UNC\\nas\\x", "C:relative")


def test_a_network_start_folder_is_left_out(tmp_path, monkeypatch) -> None:
    touched: list[str] = []
    monkeypatch.setattr(local_picker.Path, "is_dir", lambda self: touched.append(str(self)) or True)
    for network in NETWORK:
        assert local_picker._start_folder(network) is None, network
    assert touched == []  # never looked at
    assert local_picker._start_folder(str(tmp_path)) == str(tmp_path)

"""265 (code review X-08): a rules preview's side reads every config, process packs too, from its own copy.

The preview runs the stored decisions twice, each side in its own process reading the rule files of its own folder.
The side set the folder of the configs, the call sites and the type packs, but not the process packs, so both sides
read those from the real folder. One call now sets every folder. Temporary folders only.
"""

from __future__ import annotations

from jav.core import cfg


def test_every_config_folder_follows(tmp_path) -> None:
    kept = (cfg.CONFIG_DIR, cfg.CALLSITE_DIR, cfg.TYPES_DIR, cfg.PROCESSES_DIR)
    try:
        cfg.use_folder(tmp_path)
        assert (cfg.CONFIG_DIR, cfg.CALLSITE_DIR, cfg.TYPES_DIR, cfg.PROCESSES_DIR) == (
            tmp_path, tmp_path / "callsites", tmp_path / "types", tmp_path / "processes")
        assert cfg.path_of("process:invented") == tmp_path / "processes" / "invented.json"
    finally:
        cfg.CONFIG_DIR, cfg.CALLSITE_DIR, cfg.TYPES_DIR, cfg.PROCESSES_DIR = kept
        cfg.reload()

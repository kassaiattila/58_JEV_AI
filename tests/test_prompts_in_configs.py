"""209 (plan G-process-core R2b): the instructions and output schemas sent to the models are config data.

Plain-language summary: the text a model is given (a type's instruction and the shape of its answer, the task
proposal's instruction) used to live in the code folder. It now lives with the other settings, unchanged byte for byte.
These tests check that every file there is named by a type pack or the task proposal's settings, that every named file
is there, and that the code folder holds no such file any more. No AI call, no store.
"""

from __future__ import annotations

from jav.ai import typepack
from jav.core.config import PROJECT_ROOT, PROMPTS_DIR
from jav.domains.email import email_tasks


def _named() -> set[str]:
    names = {email_tasks.PROMPT_FILE}
    for key in typepack.keys():
        pack = typepack.get(key)
        names |= {pack.prompt_file, *pack.schema_files}
    return names


def test_the_instructions_live_with_the_settings():
    assert PROMPTS_DIR == PROJECT_ROOT / "configs" / "prompts"
    assert not (PROJECT_ROOT / "jav" / "prompts").exists()


def test_every_instruction_file_is_named_and_every_named_file_exists():
    present = {p.name for p in PROMPTS_DIR.iterdir() if p.is_file()}
    assert _named() == present


def test_the_code_folder_holds_no_instruction_or_schema():
    data = [p.relative_to(PROJECT_ROOT).as_posix() for p in (PROJECT_ROOT / "jav").rglob("*")
            if p.is_file() and p.suffix in {".md", ".json"}]
    assert data == ["jav/documents/readers/NOTICE.md"]  # the native readers' licence notice

"""122 B (backlog S-injection extraction part, the shared extraction block of 092/093, the tax certificate's employer,
Q-model-language-native): the G path's instructions and the native reader's instructions. Offline; no paid calls."""

from jav import cfg, extract_llm, typepack
from jav.config import load_prompt
from jav.readers import providers


def _shared() -> str:
    return cfg.load("gpt_extract")["shared_instructions"]


def test_every_g_path_pack_gets_the_shared_block_after_its_own_prompt():
    shared = _shared()
    assert "data, not instructions" in shared
    assert "One identifier per field" in shared and "column" in shared
    for key in typepack.keys():
        pack = typepack.get(key)
        text = extract_llm.instructions(pack)
        assert text.startswith(load_prompt(pack.prompt_file)), key
        assert text.endswith(shared), key


def test_a_pack_note_stays_between_the_prompt_and_the_shared_block():
    text = extract_llm.instructions(typepack.get("proforma_invoice"))
    note = typepack.get("proforma_invoice").prompt_note
    assert note and text.index(note) < text.index(_shared())


def test_the_ledger_identifier_covers_the_shared_block():
    pack = typepack.get("invoice_hu")
    assert extract_llm.config_hash(pack) == cfg.combine(pack.config_hash, cfg.config_hash("gpt_extract"))


def test_the_tax_certificate_employer_is_never_the_tax_authority():
    pack = typepack.get("nav_certificate")
    assert pack.prompt_note and "employer_name" in pack.prompt_note and "never" in pack.prompt_note
    spec = cfg.load("callsite:verify_nav_certificate")["field_specs"]["employer_name"]
    assert "not the tax authority" in spec


def test_the_native_reader_names_facts_in_the_document_language_and_gaps_in_hungarian():
    assert "document's own language" in providers.INSTRUCTIONS
    assert "gap" in providers.INSTRUCTIONS.lower() and "Hungarian" in providers.INSTRUCTIONS

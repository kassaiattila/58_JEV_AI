"""204 (R1j): a domain never imports another domain's module; it asks a shared registry instead.

Plain-language summary: two domains reached into each other: the reconciliation (finance) read the
suspicious-attachment to-do code from the mailbox module (email), and the email routing (email) called the statement
package (finance) to add or make a package. The to-do code now lives with the to-do kinds, and a logic pack takes files
through its registry entry. 208: that no domain imports another is checked with the other dependency rules
(`tests/test_dependency_direction.py`).

No AI call, no store.
"""

from __future__ import annotations


def test_the_suspicious_attachment_code_is_a_shared_to_do_kind():
    from jav.core import todo_kinds

    assert todo_kinds.SUSPICIOUS_ATTACHMENT == "attachment:suspicious_email"
    assert any(k.code == todo_kinds.SUSPICIOUS_ATTACHMENT for k in todo_kinds.kinds())


def test_the_statement_package_takes_files_through_its_registry_entry():
    from jav import logic_packs, registrations

    registrations.load_all()
    pack = logic_packs.of("statements")
    assert pack is not None and pack.take_files is not None and pack.create_with_files is not None

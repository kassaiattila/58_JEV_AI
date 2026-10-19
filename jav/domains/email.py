"""The email domain's registrations (180, plan 170 E7; 177: until then `mailbox.register`).

Plain-language summary: what the shared code does with emails beyond reading them is registered here, in one call
(`register`, from `registrations.load_all`):
- the rule run after every item of a run that marks the attachments of a suspicious email (154): each gets a to-do,
  so the run cannot be approved before a person has looked at it (`jav/item_kinds.py`);
- the mailbox package's part of its page: how many PDF attachments are not yet items, and (181) the routing of its
  attachments it offers;
- (181) a workflow's emails step: the mailbox download, then its package's run (`jav/workflow_steps.py`);
- (181) the email routing: a logic pack that proposes, for each emailed invoice, outgoing invoice and bank statement,
  the package it belongs to, and its workflow step (`jav/email_routing.py`).

The work itself stays in `jav/mailbox.py`.
"""

from __future__ import annotations

from typing import Any


def mailbox_page(wp: Any) -> dict[str, Any]:
    """A mailbox package's part of its page: its missing attachments (`mailbox.page_part`) and (181) the routing of its
    attachments it offers (`email_routing.offer`)."""
    from jav import email_routing, mailbox

    return {**mailbox.page_part(wp), **email_routing.offer(dict(wp))}


def register() -> None:
    """Every registration of the email domain (`registrations.load_all`)."""
    from jav import email_routing, item_kinds, logic_packs, mailbox, workflow_steps

    item_kinds.register_rule(item_kinds.ItemRule(kind=item_kinds.EMAIL, name="suspicious_email_source", module=__name__,
                                                 after_item=mailbox.mark_suspicious_source))
    item_kinds.register_page("mailbox", __name__, mailbox_page)
    workflow_steps.register(mailbox.STEP)  # 181: a workflow's emails step
    logic_packs.register(email_routing.LOGIC)  # 181: the email routing and its workflow step
    workflow_steps.register(email_routing.STEP)


__all__ = ["mailbox_page", "register"]

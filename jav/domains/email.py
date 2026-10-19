"""The email domain's registrations (180, plan 170 E7; 177: until then `mailbox.register`).

Plain-language summary: what the shared code does with emails beyond reading them is registered here, in one call
(`register`, from `registrations.load_all`):
- the rule run after every item of a run that marks the attachments of a suspicious email (154): each gets a to-do,
  so the run cannot be approved before a person has looked at it (`jav/item_kinds.py`);
- the mailbox package's part of its page: how many PDF attachments are not yet items;
- (181) a workflow's emails step: the mailbox download, then its package's run (`jav/workflow_steps.py`).

The work itself stays in `jav/mailbox.py`.
"""

from __future__ import annotations


def register() -> None:
    """Every registration of the email domain (`registrations.load_all`)."""
    from jav import item_kinds, mailbox, workflow_steps

    item_kinds.register_rule(item_kinds.ItemRule(kind=item_kinds.EMAIL, name="suspicious_email_source", module=__name__,
                                                 after_item=mailbox.mark_suspicious_source))
    item_kinds.register_page("mailbox", __name__, mailbox.page_part)
    workflow_steps.register(mailbox.STEP)  # 181: a workflow's emails step


__all__ = ["register"]

"""The email domain's registrations (180, plan 170 E7; 177: until then `mailbox.register`).

Plain-language summary: what the shared code does with emails beyond reading them is registered here, in one call
(`register`, from `registrations.load_all`):
- the rule run after every item of a run that marks the attachments of a suspicious email (154): each gets a to-do,
  so the run cannot be approved before a person has looked at it (`jav/app/item_kinds.py`);
- the mailbox package's part of its page: how many PDF attachments are not yet items, and (181) the routing of its
  attachments it offers;
- (185) the emails and their task proposals in a result's downloads (`jav/domains/email/email_export.py`);
- (185) how the review page shows an email item and a person corrects its intent (`mailbox.email_item_result`, `correct_email`);
- (181) a workflow's emails step: the mailbox download, then its package's run (`jav/app/workflow_steps.py`);
- (181) the email routing: a logic pack that proposes, for each emailed invoice, outgoing invoice and bank statement,
  the package it belongs to, and its workflow step (`jav/domains/email/email_routing.py`);
- (185) a mailbox download as a workflow step's source, the worker's download job and the due schedules' tick
  (`jav/domains/email/mailbox.py` `SOURCE`, `JOB`, `TICK`);
- (185) its tables on the interface: the emails, their task proposals and the mailbox downloads, and the label sets
  of the intents, the task actions and the next steps (`jav/domains/email/email_datasets.py`);
- (185) its addresses of the local service beyond the email routing's own: the mailboxes, an email package's
  attachments and the task proposals' decisions (`jav/domains/email/api_mailbox.py`), named in `SERVICE`.

The work itself stays in the domain's own modules, in this folder (208, plan G-process-core R2; until then `MODULES`
named them): the shared code imports none of them (`tests/test_dependency_direction.py`).
"""

from __future__ import annotations

from typing import Any

# 185 (plan G-full-move T1a): the module of the domain's addresses of the local service beyond its logic pack's own
# (`LogicPack.service`); `jav.api.service_modules` adds it by name
SERVICE = ("jav.domains.email.api_mailbox",)
# 202 (plan G-core-generalisation M3a): the module of the domain's commands (`register(sub)`); `jav.cli` adds it by name
COMMANDS = ("jav.domains.email.email_cli",)


def mailbox_page(wp: Any) -> dict[str, Any]:
    """A mailbox package's part of its page: its missing attachments (`mailbox.page_part`) and (181) the routing of its
    attachments it offers (`email_routing.offer`)."""
    from jav.domains.email import email_routing, mailbox

    return {**mailbox.page_part(wp), **email_routing.offer(dict(wp))}


def register() -> None:
    """Every registration of the email domain (`registrations.load_all`)."""
    from jav.app import datasets, item_kinds, logic_packs, workflow_steps
    from jav.domains.email import email_datasets, email_export, email_routing, mailbox
    from jav.app.outputs import parts
    from jav.runtime import job_kinds

    item_kinds.register_rule(item_kinds.ItemRule(kind=item_kinds.EMAIL, name="suspicious_email_source", module=__name__,
                                                 after_item=mailbox.mark_suspicious_source))
    item_kinds.register_page("mailbox", __name__, mailbox_page)
    # 192 (B6c): an email's table attachments, each one extraction of a quote request's part, in the run's budget
    item_kinds.register_item_extra(item_kinds.ItemExtra(kind=item_kinds.EMAIL, extra="email_table", plan_key="text_tables",
                                                        module=__name__, count=mailbox.table_attachments))
    # 185: how the review page shows an email item, and a person corrects its intent
    item_kinds.register_handler(item_kinds.ItemHandler(kind=item_kinds.EMAIL, module=__name__, result=mailbox.email_item_result,
                                                       correct=mailbox.correct_email, titles=mailbox.item_titles,
                                                       parent_labels=mailbox.parent_labels))
    # 185: the emails and their tasks in a result's downloads, before the documents
    parts.register_item_part(parts.ItemPart("emails", __name__, item_kinds.EMAIL, read=email_export.email_records,
                                            data=email_export.result_tables, json_key="emails",
                                            views=email_export.shown_tables, heads=email_export.HEADS))
    workflow_steps.register(mailbox.STEP)  # 181: a workflow's emails step
    workflow_steps.register_source(mailbox.SOURCE)  # 185: a mailbox download as a step's source
    logic_packs.register(email_routing.LOGIC)  # 181: the email routing and its workflow step
    workflow_steps.register(email_routing.STEP)
    for dataset, after in email_datasets.DATASETS:  # 185: its tables and label sets on the interface
        datasets.register(dataset, after=after, module=__name__)
    for labels in email_datasets.LABELS:
        datasets.register_labels(labels)
    job_kinds.register(mailbox.JOB)  # 185: the worker's mailbox download and the due schedules' tick
    job_kinds.register_tick(mailbox.TICK)


__all__ = ["mailbox_page", "register"]

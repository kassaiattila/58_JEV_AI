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
  attachments and the task proposals' decisions (`jav/domains/email/api_mailbox.py`), named in `SERVICE`;
- (209, plan G-process-core R2c) what the shared code read of its tables by name until then: the task decisions, done
  marks and mailbox downloads in "My work today", the task decisions in a run's reviewed version and its result
  fingerprint, and an email item's stored reading for another domain (the quote request); the tables themselves are
  in `jav/domains/email/email_store.py`.

The work itself stays in the domain's own modules, in this folder (208, plan G-process-core R2; until then `MODULES`
named them): the shared code imports none of them (`tests/test_dependency_direction.py`).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jav.core import activity_kinds

# 185 (plan G-full-move T1a): the module of the domain's addresses of the local service beyond its logic pack's own
# (`LogicPack.service`); `jav.service.api.service_modules` adds it by name
SERVICE = ("jav.domains.email.api_mailbox", "jav.domains.email.api_email_routing")  # 231 (C1c): the routing's, its logic pack's until then
# 202 (plan G-core-generalisation M3a): the module of the domain's commands (`register(sub)`); `jav.cli` adds it by name
COMMANDS = ("jav.domains.email.email_cli",)


def mailbox_page(wp: Any) -> dict[str, Any]:
    """A mailbox package's part of its page: its missing attachments (`mailbox.page_part`). 231 (C1c): the routing of its
    attachments is offered by the shared intake (`jav/app/intake.py` `package_offers`), as the email routing's case."""
    from jav.domains.email import mailbox

    return mailbox.page_part(wp)


def mailbox_pull_detail(raw: Any) -> str | None:
    """A mailbox download's detail in "My work today": the mailbox's name (until 209 in `jav/app/activity.py`)."""
    try:
        req = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return req.get("mailbox") if isinstance(req, dict) else None


# 209 (plan G-process-core R2c): the sources of "My work today" that read the domain's tables, right after the closed
# to-dos (where `jav/app/activity.py` had them), each after the one before
SOURCES = (
    activity_kinds.Source("task_decision", "SELECT d.decided_at at, d.actor, NULL workpackage_id, d.run_id, d.decision detail"
                                           " FROM email_task_decisions d WHERE d.decided_at >= ? AND d.decided_at < ?"),
    activity_kinds.Source("task_done", "SELECT d.done_at at, d.done_by actor, NULL workpackage_id, d.run_id, NULL detail"
                                       " FROM email_task_decisions d WHERE d.done_at >= ? AND d.done_at < ?"),  # 062
    activity_kinds.Source("mailbox_pull", "SELECT created_at at, actor, NULL workpackage_id, NULL run_id, request detail FROM mailbox_pulls"
                                          " WHERE created_at >= ? AND created_at < ?", detail=mailbox_pull_detail),
)


def _build_email(mod: Any, b: Any) -> Any:
    # 048 T2: the item is the email's `message.json`; the flow reads its folder (229: the domain's flow entry; until then
    # the shared flow registry's)
    return mod.build_app(source_dir=str(Path(b.source_path).parent), tracker=False, run_id=b.app_id,
                         persister=b.persister, use_cache=b.use_cache, propose_tasks=b.params.get("tasks") == "propose",
                         attachment_reads=b.attachment_reads, jev=b.jev,
                         extract_text=b.params.get("email_text") == "extract")  # 190: a run before the setting: off


def _lint_email(mod: Any) -> Any:
    return mod.build_app(source_dir="lint", tracker=False)


def register() -> None:
    """Every registration of the email domain (`registrations.load_all`)."""
    from jav import flows
    from jav.app import datasets, item_kinds, workflow_steps
    from jav.domains.email import email_datasets, email_export, email_routing, email_store, flow_email, mailbox  # noqa: F401
    from jav.app.outputs import parts
    from jav.runtime import job_kinds

    # 229 (MD1): the email item kind and the mailbox source are this domain's: it registers their rules, handler and
    # page part; its flow is registered here, and importing `flow_email` registers its decision points
    item_kinds.claim(item_kinds.EMAIL, __name__)
    item_kinds.claim_source("mailbox", __name__)
    flows.register(flows.FlowSpec("email", "jav.domains.email.flow_email", _build_email, _lint_email))

    item_kinds.register_rule(item_kinds.ItemRule(kind=item_kinds.EMAIL, name="suspicious_email_source", module=__name__,
                                                 after_item=mailbox.mark_suspicious_source))
    item_kinds.register_page("mailbox", __name__, mailbox_page)
    # 231 (A8): the send capability's Outlook ways (a draft in the person's Outlook; the real send, allowlist only)
    from jav.domains.email import outlook_drafts

    outlook_drafts.register()
    # 192 (B6c): an email's table attachments, each one extraction of a quote request's part, in the run's budget
    item_kinds.register_item_extra(item_kinds.ItemExtra(kind=item_kinds.EMAIL, extra="email_table", plan_key="text_tables",
                                                        module=__name__, count=mailbox.table_attachments))
    # 185: how the review page shows an email item, and a person corrects its intent
    item_kinds.register_handler(item_kinds.ItemHandler(kind=item_kinds.EMAIL, module=__name__, result=mailbox.email_item_result,
                                                       correct=mailbox.correct_email, titles=mailbox.item_titles,
                                                       parent_labels=mailbox.parent_labels, reading=email_store.reading,
                                                       found_as=email_store.found_as))
    # 209: "My work today"'s task decisions, done marks and mailbox downloads, and the reviewed version's task decisions
    after = "reason_resolve"
    for source in SOURCES:
        activity_kinds.register_source(source, after=after)
        after = source.code
    activity_kinds.register_decision(activity_kinds.DecisionKind("tasks", email_store.task_rows, wraps="corrections",
                                                                 fingerprint=email_store.task_fingerprint),
                                     after="corrections")
    # 185: the emails and their tasks in a result's downloads, before the documents
    parts.register_item_part(parts.ItemPart("emails", __name__, item_kinds.EMAIL, read=email_export.email_records,
                                            data=email_export.result_tables, json_key="emails",
                                            views=email_export.shown_tables, heads=email_export.HEADS))
    workflow_steps.register_source(mailbox.SOURCE)  # 185: a mailbox download as a step's source
    from jav.domains.email import mailbox_examples

    mailbox_examples.register()  # 231 (U1e): the invented mailboxes, read by the invented bridge instead of Outlook
    from jav.app import document_processing

    # 231 (C3d): the mailbox download as a package maker of the document processing step (the mailbox pack's), with
    # its workflow hooks: a workflow's emails step is the mailbox pack's step kind
    document_processing.register_maker(document_processing.Maker(
        mailbox.PACK, mailbox.__name__, fetch=mailbox.case_fetch, collect=mailbox.case_collect, sources=("mailbox",),
        package_kinds=("mailbox",), step_offer=mailbox.workflow_offer, step_poll=mailbox.workflow_poll_offer))
    from jav.domains.email import capabilities

    # 231 (C1c): the email routing is the email routing process pack's case (its step's capability); until then its own
    # logic pack and workflow step kind (181)
    capabilities.register()
    for dataset, after in email_datasets.DATASETS:  # 185: its tables and label sets on the interface
        datasets.register(dataset, after=after, module=__name__)
    for labels in email_datasets.LABELS:
        datasets.register_labels(labels)
    job_kinds.register(mailbox.JOB)  # 185: the worker's mailbox download and the due schedules' tick
    job_kinds.register_tick(mailbox.TICK)


__all__ = ["SOURCES", "mailbox_page", "mailbox_pull_detail", "register"]

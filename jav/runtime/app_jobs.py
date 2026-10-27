"""The application's own kinds of job for the worker (231, stage D, D-c7e).

Plain-language summary: a domain registers its jobs with the worker's registry itself, as the domains sit above the
worker. An application module cannot name the worker (its layer is below), so the worker's layer names the
application's jobs here: the rule proposals from a condition document (`jav/app/rule_proposal_runs.py`).

Layer: runtime; it imports the application modules whose jobs it names.
"""

from __future__ import annotations

from jav.app import rule_proposal_runs
from jav.runtime import job_kinds

JOBS = (
    job_kinds.JobKind(rule_proposal_runs.JOB_KIND, rule_proposal_runs.__name__, process=rule_proposal_runs.process_job,
                      abandon=lambda job, error: rule_proposal_runs.abandon(job.payload["run_id"], error)),
)


def register() -> None:
    for job in JOBS:
        job_kinds.register(job)

"""265 (code review AI-05): an error a flow turns into a to-do is logged with its traceback.

The extraction's general error, the type recognition's and the detailed type choice's non-provider errors and the
native interpretation's boundary turned an exception into a to-do (`llm:failed:TypeError`) without a trace anywhere,
so a programming error looked like a model failure. They now log it with its traceback; the to-do stays as it was.
"""

from __future__ import annotations

import inspect

from jav.ai import native_processing
from jav.flows import flow, flow_detect


def test_each_boundary_logs_the_exception() -> None:
    assert 'exception("the extraction failed' in inspect.getsource(flow)
    assert 'exception("the type recognition failed' in inspect.getsource(flow_detect)
    assert 'exception("the detailed type choice failed' in inspect.getsource(flow_detect)
    assert 'exception("the native interpretation failed' in inspect.getsource(native_processing)

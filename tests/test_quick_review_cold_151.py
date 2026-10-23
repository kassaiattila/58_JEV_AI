"""151: the quick review's first request after a restart.

After the service started, the first quick review of the 2022-2025 package took 6-7 s on a copy of the store (0.2 s
when kept). Two causes: the workspace's change mark imported the AI proposal module for its tables, and with it the
GPT client libraries (about 1.6 s); and the pairing compared every line with every open invoice before looking at the
dates. Now the GPT module is loaded with the first GPT question, the pairing passes over a line booked outside both of
an invoice's windows first, and the name words are memoised: 1.8-1.9 s, with the same result on all six packages.
"""

import subprocess
import sys

from jav.domains.finance import reconcile


def test_the_ai_proposal_module_does_not_load_the_gpt_libraries():
    code = "import sys, jav.service.api, jav.domains.finance.reconcile_ai; print('jav.ai.gpt_choice' in sys.modules, 'openai' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["False", "False"]


def test_a_gpt_question_still_reaches_the_gpt_module():
    from jav.ai import gpt_choice
    from jav.domains.finance import reconcile_ai

    assert reconcile_ai._gpt() is gpt_choice  # the tests' stand-ins on gpt_choice keep working


def test_the_name_words_are_memoised_and_unchanged():
    assert reconcile.name_words("Example Supplier Kft. 1234 Budapest, Main street 1") == ["example", "supplier"]
    assert reconcile.name_words("Example Supplier Kft. 1234 Budapest, Main street 1") is not reconcile.name_words(
        "Example Supplier Kft. 1234 Budapest, Main street 1")  # each caller gets its own list
    assert reconcile.line_words({"counterparty_name": "EXAMPLE*SUPPLIER 12345 BP"}) == ["example", "supplier"]

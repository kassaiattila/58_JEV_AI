"""Páros GPT/JEV-próba: a valódi Burr-gráf G-karja, külön modellfüggőséggel."""
import pytest


def test_generative_burr_arm_resumes_without_repeating_gpt(tmp_path, monkeypatch):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    from jav.adapters.jev import JevAdapter
    from jav.experiments.stack_trial import DirectAdapter, run_trial
    from jav.pdf import PdfText
    from jav.models import LineLayout, CellLayout
    from test_stack_trial import DetectClient

    source = tmp_path/'invoice.pdf'
    source.write_bytes(b'fixed source')
    lines = ['Seller Kft.', 'Invoice TEST-1', 'Total 1270 HUF']
    layout = [LineLayout(no=i, page=1, text=t, cells=[CellLayout(text=t,x0=0,x1=200)])
              for i,t in enumerate(lines,1)]
    monkeypatch.setattr('jav.pdf.read_pdf', lambda p: PdfText(path=str(p), text='\n'.join(lines),
        lines=lines, layout=layout, page_count=1, has_text_layer=True, text_source='pdf'))
    calls = []
    def factory(pack):
        calls.append(pack.key)
        return Agent(TestModel(), output_type=pack.llm_model(), retries=0)
    client = DetectClient()
    adapter = DirectAdapter(JevAdapter(client=client,cache_dir=tmp_path/'cache',model='jev-1.13.0'))
    args = dict(flow='invoice', source_path=str(source), directory=tmp_path/'run', run_id='gpt',
                adapter=adapter, arm='G', agent_factory=factory, generator_identity='test-model-v1')
    first = run_trial(**args,halt_after=['extract_llm'])
    assert first.llm_output is not None and calls == ['invoice_hu']
    result = run_trial(**args)
    again = run_trial(**args)
    assert result.final_status == again.final_status
    assert result.llm_output == first.llm_output and calls == ['invoice_hu']
    assert len(client.requests) == 1
    with pytest.raises(ValueError,match='identity'):
        run_trial(**(args | {'generator_identity':'changed-model'}))

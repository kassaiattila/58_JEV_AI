import json
from typesafe_sdk import SystemOneResponse
from jav.legacy_packs import PACK_ROOT
from jav.legacy_runtime import run_pack
from jav.experiments.long_document_trial import read
from jav.config import PROJECT_ROOT


def test_legacy_burr_preserves_nested_records_and_replays_without_providers(tmp_path):
    fixture=read(next((PACK_ROOT/'meeting_minutes/fixtures').glob('*.json')))['datapoints']
    cfg=read(PROJECT_ROOT/'configs/experiments/legacy_extraction.json')
    calls=[]
    def generate(pack,text,rid):
        calls.append('gpt');return fixture
    def ask(step,state,questions,rid):
        calls.append('jev')
        return SystemOneResponse.model_validate({'model':'jev-1.13.0','usage':{'input_tokens':10,'output_tokens':10},'answers':
            {key:{'type':'noul','noul':.99} for key in questions}})
    args=dict(key='meeting_minutes',text=json.dumps(fixture),directory=tmp_path,run_id='legacy-1',config=cfg,generate=generate,ask=ask)
    paused=run_pack(**args,halt_after=['generate'])
    assert paused['proposals']['attendees']==fixture['attendees']
    result=run_pack(**args)['result']
    assert result['validation']['valid']
    assert result['verification_complete_for_extracted_values']
    count=len(calls)
    assert run_pack(**args)['result']==result and len(calls)==count
    assert calls.count('gpt')==1

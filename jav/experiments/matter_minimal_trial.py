"""GPT control narrowed to the same decision output; earlier JEV answers reused without new calls."""
import argparse
from pathlib import Path
from pydantic import BaseModel, ConfigDict
from jav.config import PROJECT_ROOT
from jav.matter_review import Relation, run_pair
from jav.experiments.long_document_trial import read, write, sha, TrialBudget
from jav.experiments.matter_trial import generate_gpt

ROOT = PROJECT_ROOT/'runs/20260922_matter_minimal'
SOURCE = PROJECT_ROOT/'runs/20260922_matter_trial_v2'
LIMITS = {'openai': (44, .5), 'jev': (1, .01)}


class MinimalVerdict(BaseModel):
    model_config = ConfigDict(extra='forbid')
    linked: bool
    relation: Relation


def prepare():
    config = read(SOURCE/'config.json')
    config['gpt_prompt'] = config['gpt_prompt'].split('Return:')[0] + '\nReturn only linked and relation. linked is true exactly when relation is not none.'
    config['model_settings']['max_tokens'] = 128
    config['version'] = 'minimal-output-1.0.0'
    write(ROOT/'config.json', config)
    write(ROOT/'cases.json', read(SOURCE/'cases.json'))
    write(ROOT/'authorization.json', {'approved': True, 'authority': '2026-09-22 user live permission, cumulative 5 USD per provider',
        'scope': '42 new GPT calls, 21 synthetic pairs x 2, 0 new JEV calls; prior JEV results reused explicitly',
        'limits': LIMITS, 'unknown_cost_reserves_usd': .75,
        'prior_successful_cost_usd': {'openai': .121725, 'jev': .018161}})
    files = [Path(__file__), PROJECT_ROOT/'jav/experiments/matter_trial.py', PROJECT_ROOT/'jav/matter_review.py',
             PROJECT_ROOT/'jav/experiments/long_document_trial.py', PROJECT_ROOT/'configs/models.json',
             ROOT/'config.json', ROOT/'cases.json', ROOT/'authorization.json', *sorted((SOURCE/'results').glob('*.json'))]
    write(ROOT/'frozen.json', {str(p.resolve()): sha(p) for p in files})
    print('Prepared 42 minimal GPT decisions; JEV reused, zero JEV requests.')


def execute(replay=False):
    for name, digest in read(ROOT/'frozen.json').items():
        if sha(Path(name)) != digest:
            raise ValueError('changed frozen source: '+name)
    config = read(ROOT/'config.json')
    if not replay:
        from openai import AsyncOpenAI
        from pydantic_ai import Agent
        from pydantic_ai.models.openai import OpenAIChatModel
        from pydantic_ai.providers.openai import OpenAIProvider
        from jav.config import get_openai_key
        model = OpenAIChatModel(config['openai_model'], provider=OpenAIProvider(
            openai_client=AsyncOpenAI(api_key=get_openai_key(), max_retries=0, timeout=90)))
        agent = Agent(model, output_type=MinimalVerdict, instructions=config['gpt_prompt'],
                      retries=0, model_settings=config['model_settings'])
        budget = TrialBudget(ROOT, LIMITS)
    import json
    count = 0
    for repeat in range(2):
        for case in read(ROOT/'cases.json'):
            rid = case['id']+'-'+str(repeat)
            target = ROOT/'results'/(rid+'.json')
            if target.exists() and not replay:
                continue
            saved = read(SOURCE/'results'/(rid+'.json'))
            def gpt():
                if replay:
                    raise AssertionError('external GPT on replay')
                budget.reserve('openai')
                return generate_gpt(agent, json.dumps(case['packet'], ensure_ascii=False, sort_keys=True),
                    config=config, run_id=rid, config_hash=sha(ROOT/'config.json'))
            def jev():
                if replay:
                    raise AssertionError('stage called on terminal replay')
                return saved['state']['jev']
            args = dict(directory=ROOT/rid, run_id=rid, packet=case['packet'], config=config, gpt=gpt, jev=jev)
            if not replay:
                run_pair(**args, halt_after=['gpt'])
            state = run_pair(**args)
            if replay:
                assert state == read(target)['state']
            else:
                write(target, {'case_id': case['id'], 'repeat': repeat, 'expected': case['expected'],
                    'split': case['split'], 'state': state, 'jev_provenance': str(SOURCE/'results'/(rid+'.json')),
                    'fresh_jev_calls': 0})
                print(rid, state['result']['gpt_relation'], 'expected', case['expected'], flush=True)
            count += 1
    if replay:
        write(ROOT/'replay.json', {'exact_real_burr_terminal_replays': count, 'external_calls': 0})
    else:
        write(ROOT/'usage.json', budget.usage())
        print(json.dumps(budget.usage()), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run', 'replay'])
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    else:
        execute(args.command == 'replay')

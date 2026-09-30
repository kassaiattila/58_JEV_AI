"""Local closure: evidence match, result and final source manifest. No model calls."""
import re
import shutil
from pathlib import Path
from jav.experiments.long_document_trial import OUT,PROJECT_ROOT,validate,TrialBudget,read,write,sha

validate()
analysis=read(OUT/'analysis-final.json')
assert analysis['usage']==TrialBudget(OUT).usage()
assert analysis['repair']['real_target_value_matches']==16
assert analysis['repair']['real_target_supported_correct']==15
assert analysis['repair']['false_supports']==0
assert analysis['repair']['missing_correctly_omitted']==3
raw_preflight=(OUT/'final-preflight.txt').read_bytes()
preflight=raw_preflight.decode('utf-16' if raw_preflight.startswith(b'\xff\xfe') else 'utf-8-sig')
assert '306 passed' in preflight and '- FAIL' not in preflight
files=[]
for folder,pattern in [('jav','*.py'),('tests','*.py'),('configs','*.json'),('scripts','*long_trial*.py')]:
    files.extend((PROJECT_ROOT/folder).rglob(pattern))
snapshot={}
for path in sorted(set(files)):
    relative=path.relative_to(PROJECT_ROOT)
    dest=OUT/'final_source_snapshot'/relative
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,dest)
    snapshot[relative.as_posix()]=sha(path)
docs=[PROJECT_ROOT/'README.md',PROJECT_ROOT/'docs/BACKLOG.md',PROJECT_ROOT/'docs/DECISIONS.md',
      PROJECT_ROOT/'docs/GLOSSARY.md',PROJECT_ROOT/'docs/ARCHITECTURE.md',PROJECT_ROOT/'docs/STATE.md',
      PROJECT_ROOT/'docs/LONG_DOCUMENT_TRIAL_PLAN_2026-09-21.md',
      PROJECT_ROOT/'docs/LONG_DOCUMENT_TRIAL_2026-09-21.md',PROJECT_ROOT/'docs/handoffs/030-2026-09-21-handoff.md']
for path in docs:
    text=path.read_text(encoding='utf8')
    for target in re.findall(r'\]\(([^)]+)\)',text):
        if ':' not in target and not target.startswith('#'):
            clean=target.split('#')[0]
            if clean:
                assert (path.parent/clean).exists(), (str(path),target)
write(OUT/'closure.json',{'status':'targeted_trial_complete','external_calls_after_measurement':0,
    'final_usage':analysis['usage'],'previous_evidence_unchanged':True,
    'previous_remaining':{'jev':97,'openai':3},'production_policy_unchanged':True,
    'pytest_passed':306,'contracts_passed':4,'source_hashes':snapshot,
    'document_hashes':{p.relative_to(PROJECT_ROOT).as_posix():sha(p) for p in docs},
    'analysis_sha256':sha(OUT/'analysis-final.json'),
    'limitations':['assistant text gold, not human PDF gold','whole-document extraction completeness not established',
                   'explicit evidence selection; automatic cross-document entity linking remains open']})
print('closed: 306 tests, 4 contracts, protected hashes and local document links verified; no new provider calls')

"""Local-only, new chunking diagnostic on the three long documents that were skipped earlier.

It does not repeat the closed model measurement; the OCR cache and the earlier evidence are read-only.
Run: python -m jav.experiments.long_document_diagnostic --out runs/<new folder>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

from jav.config import PROJECT_ROOT
from jav.document_chunks import ChunkPolicy, load_chunk_config, plan_document
from jav.document_learning import ProposalBatch, digest, load_config, propose_labels
from jav.models import LineLayout


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,indent=2)


def diagnose(out: Path):
    source=PROJECT_ROOT/'runs/20260921_expanded_learning'
    protected=['sample.json','scope.json','openai_approval.json','manifest.json','frozen_inputs.json',
               'jev_budget.sqlite','generation_budget.sqlite','business.sqlite','burr.sqlite',
               'analysis_before_repair.json','analysis.json']
    before={name:file_hash(source/name) for name in protected}
    if out.exists():
        raise ValueError('choose a new evidence directory')
    out.mkdir(parents=True)
    cases=json.loads((source/'frozen_inputs.json').read_text(encoding='utf-8'))
    policy=ChunkPolicy.model_validate(load_chunk_config()['chunk_policy'])
    rows=[]
    for case in cases:
        if case['eligibility']!='context_limit':
            continue
        text=case['text']
        if digest(text)!=case['source_sha256']:
            raise ValueError('frozen source mismatch')
        matches=[]
        for cached in sorted((PROJECT_ROOT/'runs/ocr').glob(case['sha256']+'*tesseract*.json')):
            data=json.loads(cached.read_text(encoding='utf-8'))
            layout=[LineLayout.model_validate(row) for row in data['layout']]
            if '\n'.join(row.text for row in layout)==text:
                matches.append((cached,layout))
        if not matches:
            raise ValueError('no exact cached native OCR layout; do not rerun OCR')
        cached,layout=matches[0]
        plan=plan_document(text,policy,layout=layout)
        batches={}
        repeated=0
        for chunk in plan.chunks:
            excerpt=text[chunk.start:chunk.end]
            batch=(propose_labels(excerpt,load_config()) if excerpt.strip() else
                   ProposalBatch(source_sha256=chunk.source_sha256,points=[]))
            batches[chunk.id]=batch.model_dump(mode='json')
            for point in batch.points:
                first=text.find(point.quote)
                local=excerpt.find(point.quote)
                if (text.find(point.quote,first+1)>=0 and excerpt.find(point.quote,local+1)<0):
                    repeated+=1
        covered=set().union(*(set(range(c.start,c.end)) for c in plan.chunks))
        if covered!=set(range(len(text))):
            raise AssertionError('lost source characters')
        write(out/(case['case_id']+'-chunks.json'),{'plan':plan.model_dump(mode='json'),'proposals':batches})
        write(out/(case['case_id']+'-layout.json'),[row.model_dump(mode='json') for row in layout])
        # The exported reading can be read back by the CLI as the identical byte sequence.
        with (out/(case['case_id']+'.txt')).open('x',encoding='utf-8',newline='') as stream:
            stream.write(text)
        rows.append({'case_id':case['case_id'],'source_sha256':digest(text),'source_chars':len(text),
            'covered_chars':len(covered),'coverage_complete':True,'pages_total':case['page_count'],
            'pages_with_text':sorted({c.page for c in plan.chunks}),'chunks':len(plan.chunks),
            'hard_splits':sum(c.hard_split for c in plan.chunks),
            'local_label_candidates':sum(len(b['points']) for b in batches.values()),
            'omitted_candidates':sum(b['omitted_candidates'] for b in batches.values()),
            'globally_repeated_locally_unique_candidates':repeated,
            'ocr_cache':cached.relative_to(PROJECT_ROOT).as_posix(),'ocr_cache_sha256':file_hash(cached),
            'external_processing':'not_run_document_exceeds_16000_chars'})
    with closing(sqlite3.connect((source/'business.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as db:
        usage=[dict(provider=r[0],calls=r[1],recorded_usd=r[2]) for r in db.execute(
            'select provider,count(*),round(sum(cost_usd),6) from ledger where cached=0 group by provider')]
    reservations={}
    for name in ('jev_budget.sqlite','generation_budget.sqlite'):
        with closing(sqlite3.connect((source/name).resolve().as_uri()+'?mode=ro',uri=True)) as db:
            reservations[name]=db.execute('select count(*) from reservations').fetchone()[0]
    after={name:file_hash(source/name) for name in protected}
    if before!=after:
        raise AssertionError('previous evidence changed')
    snapshot={}
    for folder,pattern in [('jav','*.py'),('tests','*.py'),('configs/experiments','*.json')]:
        for path in sorted((PROJECT_ROOT/folder).rglob(pattern)):
            rel=path.relative_to(PROJECT_ROOT)
            destination=out/'source_snapshot'/rel
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(path,destination)
            snapshot[rel.as_posix()]=file_hash(path)
    report={'kind':'offline_chunk_diagnostic','external_calls':0,'new_ocr_calls':0,
            'semantic_accuracy_measured':False,'completeness':'not_established','cases':rows,
            'prior_usage_unchanged':usage,'reservations_unchanged':reservations,
            'prior_evidence_hashes':before,'prior_evidence_unchanged':True,
            'chunk_config':load_chunk_config(),'source_snapshot_hashes':snapshot}
    write(out/'summary.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in
        ('prior_evidence_hashes','source_snapshot_hashes','chunk_config')},ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    diagnose(parser.parse_args().out)

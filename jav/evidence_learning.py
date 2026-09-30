"""Távoli forrásrészek közös ellenőrzése, eredeti forráshelyekkel; nincs automatikus keresés."""
from __future__ import annotations

from pathlib import Path

from jav.document_learning import digest, ProposalBatch
from jav.learning_runtime import run_learning
from jav import store


def build_bundle(text, spans, *, source_sha256, max_chars=8000):
    """Explicit, rendezett, nem átfedő részletek; nincs csonkolás vagy kitalált oldaladat."""
    if digest(text)!=source_sha256:
        raise ValueError('source hash mismatch')
    if not spans or not 0 < max_chars <= 8000:
        raise ValueError('missing spans or invalid evidence limit')
    parts, mapping, offset, previous = [], [], 0, 0
    for i,(start,end) in enumerate(spans):
        if not 0 <= start < end <= len(text) or (i and start < previous):
            raise ValueError('unordered, overlapping or invalid source spans')
        marker=f'\n[SOURCE PART {i+1}; original characters {start}:{end}; gaps are omitted]\n'
        parts.append(marker)
        offset+=len(marker)
        quote=text[start:end]
        mapping.append(dict(start=start,end=end,bundle_start=offset,bundle_end=offset+len(quote),
                            source_sha256=digest(quote)))
        parts.append(quote)
        offset+=len(quote)
        previous=end
    assembled=''.join(parts)
    if len(assembled)>max_chars:
        raise ValueError('evidence bundle exceeds limit; no requests were sent')
    return dict(source_sha256=source_sha256,source_chars=len(text),text=assembled,
                mapping=mapping,source_coverage_complete=sum(e-s for s,e in spans)==len(text))


def source_position(bundle, start, length):
    if start is None or length <= 0:
        return None
    for part in bundle['mapping']:
        if part['bundle_start'] <= start < start+length <= part['bundle_end']:
            left=part['start']+start-part['bundle_start']
            return left,left+length
    return None


def run_evidence_learning(*, text, spans, source_sha256, directory, run_id, adapter, config,
                          model=None, proposals=None, source_char_limit=16000):
    """Ugyanaz a Burr-gráf; a JEV-támogatás a kiválasztott környezetre vonatkozik.

    A hívó kötelessége a teljes forrás küldési engedélye és a költségőr.
    A részletek kiválasztása nem állít teljes dokumentumvizsgálatot.
    """
    if len(text)>source_char_limit:
        raise ValueError('document exceeds external source character limit')
    bundle=build_bundle(text,spans,source_sha256=source_sha256,
                        max_chars=min(8000,config['max_text_chars'],config['claims']['max_context_chars']))
    directory=Path(directory)
    directory.mkdir(parents=True,exist_ok=True)
    with store.use_store(directory/'evidence.sqlite'):
        store.save_artifact('evidence_bundle',run_id,bundle)
    if proposals is not None:
        proposals=ProposalBatch.model_validate(proposals)
    config=config|{'context_ranges':[(p['bundle_start'],p['bundle_end']) for p in bundle['mapping']]}
    result=run_learning(text=bundle['text'],directory=directory,run_id=run_id,adapter=adapter,
                        config=config,model=model,proposals=proposals)['result']
    mapped=[]
    for checked in result['points']:
        point=dict(checked)
        located=source_position(bundle,point['start'],len(point['proposal']['quote']))
        context=point['proposal'].get('context_quote')
        if context:
            at=bundle['text'].find(context)
            if at < 0 or source_position(bundle,at,len(context)) is None:
                located=None
        point['source_start'],point['source_end']=located if located else (None,None)
        # Marker vagy két rész összeragasztása nem lehet szó szerinti forrás.
        if located is None and point['verification']['status']=='supported':
            point['local_verification']=point['verification']
            point['verification']={'status':'invalid_source_span','response':None}
        point['support_scope']='selected_evidence'
        mapped.append(point)
    report=dict(source_sha256=source_sha256,bundle=bundle,result=result,points=mapped,
                source_coverage_complete=bundle['source_coverage_complete'],
                extraction_completeness='not_established',document_correctness='not_established')
    with store.use_store(directory/'evidence.sqlite'):
        store.save_artifact('evidence_result',run_id,report)
    return report

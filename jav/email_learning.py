"""Source-backed M3 data handling and an explicitly manual export of learning candidates."""
from __future__ import annotations
import json
import re
from pathlib import Path
from datetime import datetime, timezone

from jav.document_learning import digest
from jav.emails import EmailMessage
from jav.intent import build_state
from jav.intents import INTENT_KEYS
from jav.learning_runtime import canonical_hash


def validate_case(case):
    sources=case['sources']
    if len({s['id'] for s in sources})!=len(sources):
        raise ValueError('duplicate source IDs')
    if sum(len(s['text']) for s in sources)>50000:
        raise ValueError('email exceeds approved source limit')
    for s in sources:
        if digest(s['text'])!=s['sha256']:
            raise ValueError('source hash mismatch')
    body=next(s for s in sources if s['id']=='body')
    if body['text']!=case['message']['body']:
        raise ValueError('body and source differ')
    EmailMessage.model_validate(case['message'])


def _evidence(source,start,end):
    return dict(source_id=source['id'],kind=source['kind'],source_sha256=source['sha256'],
                start=start,end=end,quote=source['text'][start:end])


def body_anchors(source,limit=1800):
    """Exact positions of the first meaningful text spans; URLs/padding do not use up the character limit."""
    text=source['text'];out=[];used=0
    for line in re.finditer(r'[^\r\n]+',text):
        cursor=line.start()
        urls=list(re.finditer(r'<https?[^>]*>|https?://\S+',line.group()))
        stops=[(line.start()+m.start(),line.start()+m.end()) for m in urls]+[(line.end(),line.end())]
        for start,end in stops:
            piece=text[cursor:start]
            if any(ch.isalnum() for ch in piece):
                right=min(start,cursor+limit-used)
                if right>cursor:
                    out.append(_evidence(source,cursor,right));used+=right-cursor
            cursor=end
            if used>=limit:return out
    return out


def build_evidence_state(case, searches, *, max_chars=7500):
    validate_case(case)
    msg=EmailMessage.model_validate(case['message'])
    st=build_state(msg)
    # The old cleaned view gets no hidden priority; explicit original excerpts instead.
    st['body_lines']=[]
    evidence=[]; omitted=[]; size=0
    body=next(s for s in case['sources'] if s['id']=='body')
    # The sender's short current opening is always kept, together with the quote boundary.
    if body['text']:
        evidence=body_anchors(body,limit=min(1800,max_chars))
        size=sum(len(e['quote']) for e in evidence)
    for source in case['sources']:
        for c in searches.get(source['id'],{}).get('candidates',[]):
            if (c['source_sha256']!=source['sha256'] or
                not 0<=c['start']<c['end']<=len(source['text']) or
                source['text'][c['start']:c['end']]!=c['quote']):
                raise ValueError('invalid selected evidence')
            if any(e['source_id']==source['id'] and e['start']<=c['start'] and c['end']<=e['end'] for e in evidence):
                continue
            e=_evidence(source,c['start'],c['end'])
            if size+len(e['quote'])>max_chars:
                omitted.append({k:e[k] for k in ('source_id','start','end')})
            else:
                evidence.append(e); size+=len(e['quote'])
    reasons=[s['id']+':'+s['status'] for s in case['sources'] if s['status']!='read']
    reasons += ['no_selected_evidence:'+s['id'] for s in case['sources']
                if s['status']=='read' and s['text'].strip() and not searches.get(s['id'],{}).get('candidates')]
    if case.get('attachment_failures'):
        reasons.append('attachment_download_failed')
    if case.get('upstream_body_limit_possible'):
        reasons.append('upstream_body_may_be_truncated')
    readable=[s for s in case['sources'] if s['status']=='read']
    complete=all(searches.get(s['id'],{}).get('scanned_chars',0)==len(s['text']) for s in readable)
    if not complete:
        reasons.append('source_scan_incomplete')
    if omitted:
        reasons.append('selected_evidence_overflow')
    coverage=dict(source_chars=sum(len(s['text']) for s in case['sources']),
        scanned_chars=sum(x['scanned_chars'] for x in searches.values()),text_scan_complete=complete,
        all_sources_read=not any(s['status']!='read' for s in case['sources']) and not case.get('attachment_failures'),
        upstream_complete_known=not case.get('upstream_body_limit_possible'),evidence_chars=size,
        omitted_selected=omitted,review_reasons=reasons,extraction_completeness='not_established',correctness='not_established')
    st.update(evidence=evidence,source_status=[{k:s[k] for k in ('id','kind','status')} for s in case['sources']],
              coverage=coverage,current_message_rule='The first body text is the current message. Headers inside body can introduce quoted history. '
              'Attachments and quoted history explain context; they do not independently define the current sender intent.')
    return st,coverage


def group_splits(cases):
    """Transitive groups by sender, normalised thread subject and identical text/file stay together."""
    groups=[{c['case_id']} for c in cases]; seen={}
    for c in cases:
        m=c['message']; subject=re.sub(r'^(?:(?:re|fw|fwd|aw|wg|vá)\s*:\s*)+','',m['subject'].lower()).strip()
        keys=[('sender',(m.get('sender') or '').lower()),('subject',subject)]
        keys += [('content',s.get('file_sha256') or s['sha256']) for s in c['sources'] if s['text'] or s.get('file_sha256')]
        for key in keys:
            if not key[1]: continue
            group=next(g for g in groups if c['case_id'] in g)
            if key in seen:
                other=next(g for g in groups if seen[key] in g)
                if group is not other:
                    group.update(other); groups.remove(other)
            seen[key]=c['case_id']
    out={}
    for group in groups:
        group_id=digest('|'.join(sorted(group)))
        split='holdout' if int(group_id[:8],16)%3==0 else 'development'
        for cid in group: out[cid]=dict(group_id=group_id,split=split)
    return out


def review_record(case, *, intent, reviewer, rationale, evidence, human_confirmed=False):
    validate_case(case)
    if human_confirmed is not True or not reviewer.strip() or not rationale.strip() or intent not in INTENT_KEYS or not evidence:
        raise ValueError('explicit human review, known intent, rationale and evidence required')
    sources={s['id']:s for s in case['sources']}
    for e in evidence:
        s=sources[e['source_id']]
        if not 0<=e['start']<e['end']<=len(s['text']) or s['text'][e['start']:e['end']]!=e['quote']:
            raise ValueError('review evidence does not match source')
    return dict(authority='human',human_confirmed=True,reviewer=reviewer,intent=intent,rationale=rationale,
                evidence=evidence,case_sha256=canonical_hash(case),reviewed_at=datetime.now(timezone.utc).isoformat())


def export_candidate(case, prediction, label, path):
    if label.get('authority')!='human' or label.get('human_confirmed') is not True:
        raise ValueError('human review required; a prediction is not a label')
    if label.get('case_sha256')!=canonical_hash(case):
        raise ValueError('review source identity changed')
    review_record(case,intent=label['intent'],reviewer=label['reviewer'],rationale=label['rationale'],
                  evidence=label['evidence'],human_confirmed=True)
    packet=dict(schema_version='1.0.0',status='candidate_only',activation_allowed=False,
                case=case,prediction=prediction,review=label,
                required_next_steps=['grouped_holdout_evaluation','manual_framework_import'])
    with Path(path).open('x',encoding='utf-8') as f:
        json.dump(packet,f,ensure_ascii=False,indent=2)
    return packet

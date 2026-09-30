import json


def test_independent_draft_cli_and_unknown_label_cli_leave_active_types_unchanged(tmp_path):
    from jav.cli import main
    draft=tmp_path/'draft.json'
    report=tmp_path/'report.json'
    db=tmp_path/'trial.sqlite'
    assert main(['type-draft','--base','invoice_hu','--key','candidate_invoice','--out',str(draft)])==0
    assert main(['type-inspect',str(draft),'--out',str(report),'--store',str(db),'--work-id','new-type-1'])==0
    assert json.loads(report.read_text(encoding='utf-8'))['activation_eligible'] is False
    source=tmp_path/'unknown.txt'
    source.write_text('Temperature: 68 Celsius',encoding='utf-8')
    proposals=tmp_path/'proposals.json'
    assert main(['learn-propose',str(source),'--out',str(proposals)])==0
    assert json.loads(proposals.read_text(encoding='utf-8'))['points'][0]['raw_value']=='68 Celsius'
    # An explicit attempt to reuse the same destination never overwrites evidence.
    assert main(['learn-propose',str(source),'--out',str(proposals)])==2


def test_unknown_check_cli_saves_own_exchanges_and_refuses_reusing_run_identity(tmp_path,monkeypatch):
    from jav.cli import main
    from jav.adapters.jev import JevAdapter
    from jav import store
    from typesafe_sdk import SystemOneResponse
    calls=[]
    def provider(*args,**kwargs):
        calls.append(1)
        return SystemOneResponse.model_validate({'model':'jev-1.13.0','usage':{'input_tokens':100,'output_tokens':10},
            'answers':{'relation':{'type':'choice','choice':'supports','confidence':.95,
                                  'probabilities':{'supports':.95,'contradicts':.03,'says_nothing':.02}}}}),.01
    monkeypatch.setattr(JevAdapter,'_live',provider)
    source=tmp_path/'unknown.txt'
    source.write_text('Temperature: 68 Celsius',encoding='utf-8')
    proposals=tmp_path/'proposals.json'
    assert main(['learn-propose',str(source),'--out',str(proposals)])==0
    args=['learn-check',str(source),str(proposals),'--store',str(tmp_path/'business.sqlite'),
          '--cache',str(tmp_path/'cache'),'--run-id','unknown-1','--live']
    assert main(args+['--out',str(tmp_path/'result.json')])==0
    result=json.loads((tmp_path/'result.json').read_text(encoding='utf-8'))
    assert result['type_status']=='unknown' and result['completeness']=='not_established'
    assert result['points'][0]['verification']['status']=='supported'
    assert main(args+['--out',str(tmp_path/'second.json')])==2
    assert len(calls)==1
    with store.use_store(tmp_path/'business.sqlite'):
        assert store.load_artifact('jev_exchange','unknown-1:0')['response']['model']=='jev-1.13.0'
        assert store.ledger_for_run('unknown-1')[0]['config_hash']


def test_learning_flow_cli_resumes_imported_proposals(tmp_path,monkeypatch):
    from jav.cli import main
    from tests.test_learning_flow import services
    from jav.document_learning import ProposalBatch, digest
    kwargs,calls=services(tmp_path,monkeypatch)
    source=tmp_path/'source.txt'
    source.write_text(kwargs['text'],encoding='utf-8')
    proposals=tmp_path/'proposals.json'
    proposals.write_text(ProposalBatch(source_sha256=digest(kwargs['text']),points=[
        dict(name='temperature',role='temperature',raw_value='68',unit='Celsius',entity_id='Pump A',
             quote='Pump A reached 68 Celsius.')]).model_dump_json(),encoding='utf-8')
    args=['learn-flow',str(source),str(proposals),'--directory',str(tmp_path/'flow'),
          '--run-id','cli-one','--live','--resolve-literal-spans']
    assert main(args+['--out',str(tmp_path/'first.json')])==0
    assert main(args+['--out',str(tmp_path/'second.json')])==0
    assert len(calls)==1
    assert (tmp_path/'first.json').read_bytes()==(tmp_path/'second.json').read_bytes()


def test_long_document_cli_prepares_full_source_and_runs_without_network(tmp_path,monkeypatch):
    from jav.cli import main
    from jav.adapters.jev import JevAdapter
    def forbidden(*args,**kwargs):
        raise AssertionError('provider must not be called')
    monkeypatch.setattr(JevAdapter,'_live',forbidden)
    source=tmp_path/'long.txt'
    source.write_text('Unlabelled source line\n'*1000,encoding='utf-8')
    bundle=tmp_path/'chunks.json'
    assert main(['learn-chunks',str(source),'--out',str(bundle)])==0
    value=json.loads(bundle.read_text(encoding='utf-8'))
    assert value['plan']['source_chars']>16000
    assert len(value['plan']['chunks'])>1
    out=tmp_path/'result.json'
    args=['learn-document',str(source),str(bundle),'--directory',str(tmp_path/'flow'),
          '--run-id','long-offline','--out',str(out)]
    assert main(args)==0
    result=json.loads(out.read_text(encoding='utf-8'))
    assert result['coverage']['complete']
    assert result['completeness']=='not_established'
    assert result['points']==[]

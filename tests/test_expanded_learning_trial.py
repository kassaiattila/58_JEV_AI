def test_ocr_text_is_eligible_without_a_pdf_text_layer_and_oversize_is_explicit():
    from jav.experiments.expanded_learning_trial import eligibility
    from jav.pdf import PdfText
    pdf=PdfText(path='scan.pdf',text='readable OCR',has_text_layer=False,text_source='ocr')
    assert eligibility(pdf)=='eligible'
    pdf.text='x'*16001
    assert eligibility(pdf)=='context_limit'
    pdf.text_source=None
    assert eligibility(pdf)=='no_readable_text'


def test_larger_sample_scan_uses_real_burr_and_does_not_repeat_completed_cases(tmp_path,monkeypatch):
    import hashlib
    from typesafe_sdk import SystemOneResponse, Choice
    from jav.experiments import expanded_learning_trial as trial
    from jav.document_learning import digest,load_config,propose_labels
    from jav.adapters.jev import JevAdapter
    from jav import store
    monkeypatch.setattr(trial,'OUT',tmp_path)
    source=tmp_path/'input.pdf'
    source.write_bytes(b'local source identity')
    text='Owner: Alice'
    case={'case_id':'test-001','eligibility':'eligible','path':str(source),'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
          'text':text,'lines':[text],'page_count':1,'text_source':'pdf','source_sha256':digest(text),
          'label_baseline':propose_labels(text,load_config()).model_dump(mode='json')}
    trial.write(tmp_path/'frozen_inputs.json',[case])
    trial.write(tmp_path/'manifest.json',{'hashes':trial.code_hashes(),
        'frozen_inputs_sha256':digest((tmp_path/'frozen_inputs.json').read_text(encoding='utf-8')),
        'config':load_config(),'jev_model':'jev-1.13.0','maximum_jev_calls':2,'jev_recorded_stop_usd':1})
    calls=[]
    def provider(self,request_id,state,questions,**kwargs):
        calls.append(request_id)
        answers={}
        for name,q in questions.items():
            if isinstance(q,Choice):
                choice='supports' if name=='relation' else 'unknown' if name=='doc_type' else 'hu'
                answers[name]={'type':'choice','choice':choice,'confidence':.99,'probabilities':{choice:.99}}
            else:
                answers[name]={'type':'noul','noul':.99}
        return SystemOneResponse.model_validate({'model':'jev-1.13.0',
            'usage':{'input_tokens':100,'output_tokens':20},'answers':answers}),.01
    monkeypatch.setattr(JevAdapter,'_live',provider)
    trial.scan()
    trial.scan()
    assert calls==['detect','claim_relation']
    assert trial.read(tmp_path/'test-001-scan.json')['baseline']['points'][0]['verification']['status']=='supported'
    with store.use_store(tmp_path/'business.sqlite'):
        assert store.load_artifact('expanded_detection_response','test-001-detect')['response']['model']=='jev-1.13.0'


def test_unknown_recorded_cost_stops_larger_batch(tmp_path,monkeypatch):
    import pytest
    from jav.experiments import expanded_learning_trial as trial
    from jav import store
    monkeypatch.setattr(trial,'OUT',tmp_path)
    with store.use_store(tmp_path/'business.sqlite'):
        store.ledger_add(run_id='failed',step='generate',provider='openai',model='unknown',cost_usd=None,
                         input_tokens=None,output_tokens=None,seconds=0)
    with pytest.raises(RuntimeError,match='unresolved provider cost'):
        trial.enforce_cost('openai',3)

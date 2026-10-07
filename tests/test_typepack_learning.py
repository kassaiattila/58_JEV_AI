from jav import store


def test_existing_pack_can_seed_an_independent_draft_and_receipt_without_activation(tmp_path):
    from jav.typepack_learning import make_draft,inspect_draft,save_receipt
    from jav.typepack import keys
    before=keys()
    draft=make_draft('invoice_hu','new_invoice_layout')
    report=inspect_draft(draft)
    assert report['status']=='structurally_valid'
    assert report['activation_eligible'] is False
    assert 'evaluation_not_run' in report['blockers']
    with store.use_store(tmp_path/'business.sqlite'):
        save_receipt('draft-1',report)
        assert store.load_artifact('typepack_inspection','draft-1')==report
    assert keys()==before and 'new_invoice_layout' not in keys()


def test_draft_money_schema_must_preserve_decimal_strings_and_bad_required_is_a_report():
    from jav.typepack_learning import make_draft,inspect_draft,TypeDraft
    draft=make_draft('invoice_hu','new_invoice_layout').model_dump(mode='json')
    draft['output_schema']['properties']['gross_total']['type']='number'
    draft['output_schema']['required']=None
    report=inspect_draft(TypeDraft.model_validate(draft))
    assert report['status']=='invalid'
    assert 'money_requires_decimal_string:gross_total' in report['errors']
    assert 'invalid_schema_required' in report['errors']


def test_draft_rejects_missing_field_unsupported_validator_and_leaking_evaluation_samples():
    from jav.typepack_learning import make_draft,inspect_draft,TypeDraft
    draft=make_draft('invoice_hu','new_invoice_layout').model_dump(mode='json')
    draft['output_schema']['properties'].pop('gross_total')
    draft['pack']['validators'].append({'check':'execute_python','field':'gross_total'})
    draft['samples']=[dict(source_sha256='a'*64,group='supplier-template-a',split=split,label='positive')
                      for split in ('development','evaluation')]
    report=inspect_draft(TypeDraft.model_validate(draft))
    assert report['status']=='invalid'
    assert 'missing_schema_field:gross_total' in report['errors']
    assert 'unsupported_validator:execute_python' in report['errors']
    assert 'sample_leakage' in report['errors']
    assert report['activation_eligible'] is False

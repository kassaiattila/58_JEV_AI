import pytest
from pydantic import ValidationError
from jav.legacy_packs import keys, load, schema_model, validate_record, PACK_ROOT
import json


def test_all_ported_schemas_compile_and_existing_fixtures_keep_validator_result():
    assert len(keys()) == 15
    checked = 0
    for key in keys():
        pack = load(key)
        schema_model('Check_'+key,pack['schema'])
        for file in (PACK_ROOT/key/'fixtures').glob('*.json'):
            fixture = json.loads(file.read_text(encoding='utf-8'))
            result = validate_record(pack,fixture['datapoints'])
            assert result['valid'] == fixture['expected_valid'], key
            assert result['flags'] == fixture['expected_flags'], key
            checked += 1
    assert checked == 10


def test_nested_string_arrays_enum_and_required_are_preserved():
    pack=load('meeting_minutes')
    fixture=json.loads(next((PACK_ROOT/'meeting_minutes/fixtures').glob('*.json')).read_text(encoding='utf-8'))
    model=schema_model('Minutes',pack['schema'])
    record=model.model_validate(fixture['datapoints']).model_dump()
    assert record['attendees'] == fixture['datapoints']['attendees']
    with pytest.raises(ValidationError):
        model.model_validate(record|{'document_kind':'invented_kind'})
    with pytest.raises(ValidationError):
        model.model_validate({k:v for k,v in record.items() if k!='resolutions'})


def test_bank_wrong_closing_balance_remains_a_code_failure():
    pack=load('statement_cib')
    f=next((PACK_ROOT/'statement_cib/fixtures').glob('*.json'))
    record=json.loads(f.read_text(encoding='utf-8'))['datapoints']
    result=validate_record(pack,record|{'closing_balance':'999999999.00'})
    assert not result['valid']

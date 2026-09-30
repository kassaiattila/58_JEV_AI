from jav.capability_catalog import build_catalog


def test_catalog_covers_legacy_types_nested_datapoints_and_active_intents():
    catalog=build_catalog()
    docs={d['key']:d for d in catalog['documents']}
    assert len(docs)==23
    assert len(catalog['intents'])==11
    assert len(catalog['retired_intent_keys'])==5
    assert sum(d['legacy_catalog_active'] for d in docs.values())==20
    bank=docs['statement_cib']
    assert bank['recognition']['broad_key']=='bank_statement'
    # 047 T1.1: the legacy type is a full pack too (G path only, legacy copy as source); automatic route in T1.2
    assert bank['processing']['mode']=='typepack' and bank['processing']['arms']==['G'] and bank['processing']['legacy_source']
    assert bank['recognition']['anchors_scope']=='detailed_pack' and bank['recognition']['anchors']['required_any']
    fields={f['path']:f for f in bank['datapoints']}
    assert fields['/transactions/*/amount']['type']==['string','null']
    assert fields['/transactions/*/amount']['required_in_parent'] is True
    assert fields['/transactions/*/direction']['enum']
    assert docs['meeting_minutes']['recognition']['broad_key']=='other'
    assert build_catalog()==catalog


def test_catalog_includes_inherited_fields_and_nullable_array_members():
    catalog=build_catalog()
    docs={d['key']:d for d in catalog['documents']}
    fields={f['path'] for f in docs['villamos_energia_szamla']['datapoints']}
    assert '/supplier_name' in fields and '/line_items/*/description' in fields
    paths={f['path']:f for f in docs['meeting_minutes']['datapoints']}
    assert paths['/agenda_items/*']['type']=='string'
    assert paths['/resolutions/*/votes_for']['type']==['number','null']

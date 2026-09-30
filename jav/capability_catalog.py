"""Deterministic discovery of configured capabilities, without provider calls."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from jav.config import PROJECT_ROOT, PROMPTS_DIR
from jav import typepack, legacy_packs


def _read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def datapoints(schema, path=''):
    """Schema paths, including arrays and fields whose value may be absent/null."""
    rows=[]
    required=set(schema.get('required',[]))
    for key, prop in sorted(schema.get('properties',{}).items()):
        current=path+'/'+key.replace('~','~0').replace('/','~1')
        rows.append({'path':current,'type':prop.get('type'),
                     'required_in_parent':key in required,
                     **{k:prop[k] for k in ('description','enum','format','pattern') if k in prop}})
        if 'properties' in prop:
            rows.extend(datapoints(prop,current))
        if 'items' in prop:
            item=prop['items']
            rows.append({'path':current+'/*','type':item.get('type'),'required_in_parent':False,
                         **{k:item[k] for k in ('description','enum','format','pattern') if k in item}})
            rows.extend(datapoints(item,current+'/*'))
    return rows


def build_catalog():
    spec_path=PROJECT_ROOT/'configs/capability_catalog.json'
    spec=_read(spec_path)
    doc_path=PROJECT_ROOT/spec['document_registry']
    intent_path=PROJECT_ROOT/spec['intent_registry']
    registry=_read(doc_path); intents=_read(intent_path)['intents']
    core=set(typepack.keys()); legacy=set(legacy_packs.keys())
    expected=set(spec['expected_document_keys'])
    # 047 T1.1: all 23 types are full packs; the 15 legacy copies stay as sources (hash check), each has a pack
    if core != expected or not legacy <= core or set(registry['old_type_map']) != expected:
        raise ValueError('document catalog coverage mismatch')
    intent_keys=[x['key'] for x in intents]
    if len(set(intent_keys))!=len(intent_keys) or set(intent_keys)!=set(spec['expected_active_intent_keys']):
        raise ValueError('intent catalog coverage mismatch')
    if set(intent_keys)&set(spec['retired_intent_keys']):
        raise ValueError('retired intent activated')
    categories={d['key']:d for d in registry['types']}
    hashes={}
    def track(path):
        hashes[path.relative_to(PROJECT_ROOT).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
    for p in (spec_path,doc_path,intent_path):track(p)
    documents=[]
    for key in sorted(expected):
        broad=registry['old_type_map'][key]
        if broad not in categories:raise ValueError('unknown broad category: '+key)
        category=categories[broad]
        if key in core:
            pack=typepack.get(key);schema=pack.schema()
            sources=[PROJECT_ROOT/spec['processing_sources']['core']/(key+'.json')]
            if pack.extends:sources.append(PROJECT_ROOT/spec['processing_sources']['core']/'_base'/(pack.extends+'.json'))
            sources += [PROMPTS_DIR/n for n in pack.schema_files]+[PROMPTS_DIR/pack.prompt_file]
            processing={'mode':'typepack','runtime':'jav.flow','arms':list(pack.arms),'explicit_type_supported':True,
                        'automatic_routing_enabled':None,'routing_note':'not inferred from pack existence',
                        'legacy_source':key in legacy}
            if key in legacy:
                sources.append(PROJECT_ROOT/spec['processing_sources']['legacy']/key/'manifest.json')
            recognition={'broad_key':broad,'criteria':{k:category[k] for k in ('what','not_for','examples')},
                'anchors_scope':'detailed_pack' if pack.detect else 'broad_category',
                'anchors':{k:list(v) for k,v in pack.detect.items()} if pack.detect else {k:category.get(k,[]) for k in ('required_any','supporting','excluders')}}
            validation={'validators':list(pack.validators),'required_fields':list(pack.required),
                        'field_kinds':pack.fields,'text_labels':pack.text_labels}
            active=key not in spec['legacy_pending_document_keys']
        else:
            pack=legacy_packs.load(key);schema=pack['schema'];folder=PROJECT_ROOT/spec['processing_sources']['legacy']/key
            sources=[folder/'manifest.json']+[folder/n for n in pack['manifest']['files']]
            processing={'mode':'explicit_type_candidate','runtime':'jav.legacy_runtime.run_pack',
                        'explicit_type_supported':True,'automatic_routing_enabled':False}
            recognition={'broad_key':broad,'criteria':{k:category[k] for k in ('what','not_for','examples')},
                         'anchors_scope':'detailed_legacy_pack','legacy_detect':_read(folder/'detect.json')}
            validation={'rules':pack['rules']};active=pack['manifest']['legacy_catalog_active']
            if active != (key not in spec['legacy_pending_document_keys']):raise ValueError('legacy status mismatch')
        for p in sources:track(p)
        documents.append({'key':key,'legacy_catalog_active':active,'recognition':recognition,
            'processing':processing,'schema':schema,'datapoints':datapoints(schema),
            'validation':validation,'sources':[p.relative_to(PROJECT_ROOT).as_posix() for p in sources]})
    return {'version':spec['meta']['version'],'purpose':spec['purpose'],'documents':documents,
        'broad_categories':registry['types'],'unknown':{'key':registry['unknown_key'],**registry['unknown']},
        'intents':sorted(intents,key=lambda x:x['key']),'retired_intent_keys':spec['retired_intent_keys'],
        'recognition_semantics':spec['recognition_semantics'],'datapoint_path_semantics':spec['datapoint_path_semantics'],
        'source_sha256':dict(sorted(hashes.items()))}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args(); catalog=build_catalog()
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as f:json.dump(catalog,f,ensure_ascii=False,indent=2)
    print(json.dumps({'documents':len(catalog['documents']),
        'datapoint_paths':sum(len(d['datapoints']) for d in catalog['documents']),
        'active_intents':len(catalog['intents']),'retired_intents':len(catalog['retired_intent_keys']),
        'external_calls':0,'output':str(args.output) if args.output else None}))


if __name__=='__main__':main()

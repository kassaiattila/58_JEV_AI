"""A standalone, typed port of the legacy detailed schemas; no automatic category activation."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from pydantic import ConfigDict, Field, create_model
from jav.config import PROJECT_ROOT

PACK_ROOT = PROJECT_ROOT/'configs/legacy_types'


def keys():
    return sorted(p.name for p in PACK_ROOT.iterdir() if p.is_dir() and (p/'schema.json').exists())


def load(key):
    if key not in keys():
        raise ValueError('unknown legacy pack')
    folder = PACK_ROOT/key
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    for name, digest in manifest['files'].items():
        if hashlib.sha256((folder/name).read_bytes()).hexdigest() != digest:
            raise ValueError('legacy pack hash mismatch: '+name)
    return {'key':key, 'manifest':manifest,
            'schema':json.loads((folder/'schema.json').read_text(encoding='utf-8')),
            'rules':json.loads((folder/'rules.json').read_text(encoding='utf-8')),
            'prompt':(folder/'prompt.md').read_text(encoding='utf-8')}


def schema_model(name, schema):
    """The narrow, checked grammar of the ported schema: required/enum/nullable/list/object.

    The invoice TypePack compiler deliberately makes every field optional;
    here the original required and enum constraints must be preserved as well.
    """
    def annotation(prop, path):
        allowed = {'type','description','enum','properties','items','required','additionalProperties','title'}
        if set(prop)-allowed:
            raise ValueError('unsupported schema keyword at '+path)
        kinds = prop.get('type', 'string')
        kinds = [kinds] if isinstance(kinds,str) else kinds
        base = [k for k in kinds if k!='null']
        if len(base)!=1:
            raise ValueError('unsupported schema union at '+path)
        if 'enum' in prop:
            return Literal[tuple(prop['enum'])]
        kind = base[0]
        if kind=='object':
            result = schema_model(path,prop)
        elif kind=='array':
            result = list[annotation(prop['items'],path+'_item')]
        else:
            result = {'string':str,'number':float,'integer':int,'boolean':bool}[kind]
        return result | None if 'null' in kinds else result
    required = set(schema.get('required',[]))
    fields = {key:(annotation(value,name+'_'+key),Field(default=... if key in required else None,
              description=value.get('description'))) for key,value in schema.get('properties',{}).items()}
    return create_model(name,__config__=ConfigDict(extra='forbid',strict=True),**fields)


def validate_record(pack, record):
    from jav.legacy_validation import run_validation
    typed = schema_model('Legacy_'+pack['key'],pack['schema']).model_validate(record).model_dump(mode='json')
    return run_validation(typed,pack['rules'])

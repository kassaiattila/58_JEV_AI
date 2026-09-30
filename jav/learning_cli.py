"""Fájlos kísérleti taníthatósági parancsok; nincs automatikus csomagaktiválás."""
from __future__ import annotations

import json
from pathlib import Path

from jav import store
from jav.config import PROJECT_ROOT
from jav.document_learning import ProposalBatch,check_proposals,load_config,propose_labels,save_result,digest
from jav.typepack_learning import TypeDraft,make_draft,inspect_draft,save_receipt


def read_source(path):
    # Karakterpozíciók: a CRLF-et sem normalizálhatja a fájlbeolvasás.
    with Path(path).open(encoding='utf-8',newline='') as stream:
        return stream.read()


def run(args):
    try:
        destination = Path(args.out)
        if destination.exists():
            raise ValueError("output already exists; choose a new evidence path")
        destination.parent.mkdir(parents=True,exist_ok=True)
        if args.cmd in ('learn-chunks','learn-document'):
            from jav.document_chunks import ChunkPolicy,plan_document,load_chunk_config
            from jav.models import LineLayout
            text=read_source(args.source)
            layout=([LineLayout.model_validate(v) for v in json.loads(Path(args.layout).read_text(encoding='utf-8'))]
                    if args.layout else None)
            if args.cmd=='learn-chunks':
                policy=ChunkPolicy.model_validate(load_chunk_config()['chunk_policy'])
                plan=plan_document(text,policy,layout=layout)
                config=load_config()
                payload={'plan':plan.model_dump(mode='json'),'proposals':{
                    chunk.id:(propose_labels(text[chunk.start:chunk.end],config)
                              if text[chunk.start:chunk.end].strip() else
                              ProposalBatch(source_sha256=chunk.source_sha256,points=[])).model_dump(mode='json')
                    for chunk in plan.chunks}}
            else:
                from jav.adapters.jev import CacheOnlyAdapter
                from jav.learning_runtime import run_chunked_learning
                bundle=json.loads(Path(args.proposals).read_text(encoding='utf-8'))
                policy=ChunkPolicy.model_validate(bundle['plan']['policy'])
                if plan_document(text,policy,layout=layout).model_dump(mode='json')!=bundle['plan']:
                    raise ValueError('chunk plan does not match source and layout')
                payload=run_chunked_learning(text=text,directory=Path(args.directory),run_id=args.run_id,
                    adapter=CacheOnlyAdapter(cache_dir=Path(args.cache),model='jev-1.13.0'),
                    config=load_config(),chunk_policy=policy,layout=layout,proposals=bundle['proposals'],
                    offline=True,use_cache=True,stop_after_chunks=args.stop_after_chunks)
        elif args.cmd == "type-draft":
            payload = make_draft(args.base,args.key).model_dump(mode="json")
        elif args.cmd == "type-inspect":
            payload = inspect_draft(TypeDraft.model_validate_json(Path(args.draft).read_text(encoding="utf-8")))
            with store.use_store(Path(args.store)):
                save_receipt(args.work_id,payload)
        elif args.cmd == "learn-propose":
            payload = propose_labels(Path(args.source).read_text(encoding="utf-8"),load_config()).model_dump(mode="json")
        elif args.cmd == "learn-flow":
            from jav.adapters.jev import JevAdapter
            from jav.adapters.jev import CacheOnlyAdapter
            from jav.learning_runtime import run_learning
            adapter=(JevAdapter if args.live else CacheOnlyAdapter)(cache_dir=Path(args.cache),model="jev-1.13.0")
            config=load_config()
            if args.resolve_literal_spans:
                config['resolve_literal_spans']=True
            if args.resolve_context_spans:
                config['resolve_context_spans']=True
            payload=run_learning(text=Path(args.source).read_text(encoding="utf-8"),
                proposals=ProposalBatch.model_validate_json(Path(args.proposals).read_text(encoding="utf-8")),
                directory=Path(args.directory),run_id=args.run_id,adapter=adapter,config=config,
                use_cache=not args.live)["result"]
        else:
            from jav.adapters.jev import JevAdapter
            from jav.adapters.jev import CacheOnlyAdapter
            text = Path(args.source).read_text(encoding="utf-8")
            batch = ProposalBatch.model_validate_json(Path(args.proposals).read_text(encoding="utf-8"))
            config = load_config()
            config_hash = digest(json.dumps(config,sort_keys=True,ensure_ascii=False))
            adapter = (JevAdapter if args.live else CacheOnlyAdapter)(cache_dir=Path(args.cache),model="jev-1.13.0")
            with store.use_store(Path(args.store)):
                if (store.load_artifact("generic_extraction",args.run_id) is not None
                        or store.load_artifact("generic_run_request",args.run_id) is not None):
                    raise ValueError("run identity already exists; choose a new run ID")
                store.save_artifact("generic_run_request",args.run_id,dict(
                    source_ref=str(Path(args.source).resolve()),source_sha256=digest(text),
                    proposals=batch.model_dump(mode="json"),config=config))
                counter = 0
                def ask(step,state,questions):
                    nonlocal counter
                    answer = adapter.ask(step,state,questions,run_id=args.run_id,config_hash=config_hash,use_cache=not args.live)
                    store.save_artifact("jev_exchange",f"{args.run_id}:{counter}",dict(
                        step=step,state=state,questions={k:q.model_dump(mode="json") for k,q in questions.items()},
                        response=answer.response.model_dump(mode="json"),call=answer.call.model_dump(mode="json")))
                    counter += 1
                    return answer.response
                result = check_proposals(text,batch,ask,config)
                save_result(args.run_id,result)
                payload = result.model_dump(mode="json")
        with destination.open("x",encoding="utf-8") as f:
            json.dump(payload,f,ensure_ascii=False,indent=2)
        print(f"{args.cmd}: {destination}")
        return 2 if payload.get("status") == "invalid" else 0
    except (ValueError,OSError,RuntimeError,KeyError,TypeError) as exc:
        # Modellvalidációs hibák tartalmazhatnak bemeneti adatot; csak a fajtájuk kerül konzolra.
        print(f"{args.cmd}: {type(exc).__name__}; output was not replaced")
        return 2


def register(sub):
    for command,help_text in [('learn-chunks','hosszú szöveg helyi darabolása és címkejelöltjei'),
                              ('learn-document','részenként folytatható feldolgozás; kizárólag saját napló/cache')]:
        p=sub.add_parser(command,help=help_text)
        p.add_argument('source')
        p.add_argument('--layout',help='azonos olvasat PDF/OCR-soradata JSON-listában, opcionális')
        p.add_argument('--out',required=True)
        if command=='learn-document':
            p.add_argument('proposals',help='learn-chunks csomag, részenkénti javaslatokkal')
            p.add_argument('--directory',required=True)
            p.add_argument('--run-id',required=True)
            p.add_argument('--cache',default=str(PROJECT_ROOT/'runs/learning/cache'))
            p.add_argument('--stop-after-chunks',type=int)
        p.set_defaults(fn=run)
    p = sub.add_parser("learn-flow",help="tartós Burr-folyamat importált javaslatokkal; azonos run-id = folytatás")
    p.add_argument("source")
    p.add_argument("proposals")
    p.add_argument("--directory",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--cache",default=str(PROJECT_ROOT/"runs/learning/cache"))
    p.add_argument("--live",action="store_true",help="TypeSafe-ellenőrzés; nélküle kizárólag cache / saját válasznapló")
    p.add_argument("--resolve-literal-spans",action="store_true",help="egyedi, szó szerinti idézet hibás pozíciójának naplózott javítása")
    p.add_argument('--resolve-context-spans',action='store_true',help='ismétlődő idézet csak egyedi, pontos környezettel oldható fel')
    p.set_defaults(fn=run)
    p = sub.add_parser("type-draft",help="új csomagtervezet meglévő típusból, aktiválás nélkül")
    p.add_argument("--base",required=True)
    p.add_argument("--key",required=True)
    p.add_argument("--out",required=True)
    p.set_defaults(fn=run)
    p = sub.add_parser("type-inspect",help="önálló csomagtervezet szerkezeti ellenőrzése és bizonylata")
    p.add_argument("draft")
    p.add_argument("--out",required=True)
    p.add_argument("--store",required=True)
    p.add_argument("--work-id",required=True)
    p.set_defaults(fn=run)
    p = sub.add_parser("learn-propose",help="helyi címke: érték javaslatok ismeretlen szövegből, AI-hívás nélkül")
    p.add_argument("source")
    p.add_argument("--out",required=True)
    p.set_defaults(fn=run)
    p = sub.add_parser("learn-check",help="típusfüggetlen adatpontok forrásellenőrzése; --live: TypeSafe-küldés")
    p.add_argument("source")
    p.add_argument("proposals")
    p.add_argument("--out",required=True)
    p.add_argument("--store",required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--cache",default=str(PROJECT_ROOT/"runs/learning/cache"))
    p.add_argument("--live",action="store_true",help="élő JEV-ellenőrzés; nélküle kizárólag cache")
    p.set_defaults(fn=run)

"""Típusos Pydantic AI-hívás teljes válaszmentéssel és szolgáltatói naplóval."""
import json
import re
import time
from pydantic_ai.usage import UsageLimits
from jav import store
from jav.config import OPENAI_USD_PER_MTOK


def generate(agent, text, *, run_id, step, model_name, config_hash):
    started=time.perf_counter()
    try:
        result=agent.run_sync(text,usage_limits=UsageLimits(request_limit=1))
        output=result.output.model_dump(mode='json') if hasattr(result.output,'model_dump') else result.output
        raw={'output':output,'model':result.response.model_name,'messages':json.loads(result.all_messages_json())}
        store.save_artifact('provider_response',run_id+':'+step,raw)
        usage=result.usage() if callable(result.usage) else result.usage
        price=OPENAI_USD_PER_MTOK.get(model_name)
        if not re.fullmatch(re.escape(model_name)+r'(-\d{4}-\d{2}-\d{2})?',raw['model']):
            price=None
        cost=round((usage.input_tokens*price[0]+usage.output_tokens*price[1])/1e6,6) if price else None
    except Exception as exc:
        store.ledger_add(run_id=run_id,step=step,provider='openai',model=model_name,input_tokens=None,
            output_tokens=None,cost_usd=None,seconds=time.perf_counter()-started,config_hash=config_hash,error=type(exc).__name__)
        raise
    store.ledger_add(run_id=run_id,step=step,provider='openai',model=raw['model'],input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,cost_usd=cost,seconds=time.perf_counter()-started,config_hash=config_hash)
    return raw

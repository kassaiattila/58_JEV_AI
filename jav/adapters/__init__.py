"""Adapter-réteg: a flow-k innen hívnak AI-t, soha nem közvetlenül SDK-t.

- `jev.JevAdapter.ask()`  - Jev (typesafe-sdk) kérés-hash cache-sel és ledgerrel
- `llm`                    - Pydantic AI (OpenAI) ugyanazzal a ledger-fegyelemmel
"""

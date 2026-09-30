"""Adapter layer: flows call AI through here, never through an SDK directly.

- `jev.JevAdapter.ask()`  - JEV (typesafe-sdk) with a request-hash cache and the ledger
- `llm`                    - Pydantic AI (OpenAI) under the same ledger discipline
"""

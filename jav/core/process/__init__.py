"""The process core (213, plan G-process-core P1a): cases run step by step by a versioned process definition.

Plain-language summary: a case is one business matter followed from start to finish, possibly over days. Its process
definition names its steps, the order a person may override and the gates nobody may. The core keeps the case's steps,
its history, the events it receives, the handovers it sends and its timers in the store, each change with its history
row in one transaction, and a worker moves the case on under a claim no live process takes over. The core knows no
domain: the step kinds are registered by the layers above it.

- `definition`: the process definition and its fingerprint (rules 1, 2);
- `actor`: who acts (rule 8); `hooks`: the authorisation check and the observability sink (rule 9, plug-in points);
- `kinds`: the step kinds' registry;
- `cases`: the case, its steps, history and incoming events (rules 1, 3, 4, 5); `timers`: durable timers (rule 7);
  `outbox`: outgoing handovers (rule 4);
- `engine`: the claim, the worker's turn and the four operations of the durable workflow engine plug-in point (rules 6,
  10).

Layer: shared core; it imports only `jav.core`.
"""

"""The shared core (208, plan G-process-core R2): the store, the settings and their loader, the registries that every
layer reads, the decisions log, the call log with its cost reservation, the job queue and the clock.

The lowest layer: it imports no other layer of `jav` (`tests/test_dependency_direction.py`).
"""

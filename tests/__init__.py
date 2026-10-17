"""The test suite as one package (167, review T-4).

pytest imports every module here as `tests.<name>` and puts the repository root on the import path, so a helper module
imported by another test (`from tests.test_api import ...`) is the same module object as the collected one, not a
second copy with its own state, and `jav` is importable whatever the working directory.
"""

# scopify: dynamic-module
"""Escape hatch 3: a module-level marker comment near the top of the file.

The ``# scopify: dynamic-module`` marker above silences every PA01x
diagnostic in this *whole* module -- useful for legacy or generated files
where dynamic behaviour is pervasive rather than one-off. Compare with
``escape_hatches.py``, which suppresses one construct at a time.
"""
import importlib


def load(module_name: str):
    return importlib.import_module(module_name)  # would be SC012, but silenced module-wide

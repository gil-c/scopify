"""Two of the three ways to silence a PA01x dynamic-construct diagnostic.

(The third, whole-module suppression, is demonstrated separately in
``module_marker.py`` because it silences an entire file and would be
confusing to mix with the other two techniques here.)
"""
import importlib

from scopify import dynamic


def inline_suppressed(obj: object, attr_name: str) -> object:
    # Escape hatch 1: an inline trailing comment on the offending line.
    return getattr(obj, attr_name)  # scopify: allow-dynamic


@dynamic(reason="plugin loader needs a runtime-computed import path")
def decorator_suppressed(module_name: str):
    # Escape hatch 2: @dynamic (bare or with reason=...) on the enclosing
    # function/class silences every dynamic diagnostic in its body.
    return importlib.import_module(module_name)

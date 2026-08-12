"""SC016 / SC017 — frame introspection and monkey-patching.

Both patterns reach *outside* the current module's own AST: one inspects the
call stack at runtime, the other rewrites an attribute of an already-imported
module/object from a distance.
"""
import inspect
import sys

from core_pkg import api as core_api


def who_called_me() -> str:
    frame = inspect.currentframe()  # SC016 -- frame introspection escapes static analysis
    return frame.f_back.f_code.co_name if frame and frame.f_back else "?"


def raw_frame_hack() -> object:
    return sys._getframe(1)  # SC016 -- same concern, via sys._getframe


def patch_helper() -> None:
    core_api.helper = lambda x: x  # SC017 -- monkey-patches an attribute of an imported name

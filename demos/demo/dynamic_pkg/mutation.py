"""SC015 / SC018 — namespace mutation that bypasses declared visibility.

Reaching into ``__dict__`` (an instance/class namespace) or into
``globals()``/``locals()``/``vars()`` (a module/frame namespace) lets code
add, remove or overwrite attributes without going through any decorator
Scopify can see -- so it flags the mutation itself.
"""


class Box:
    pass


def mutate_instance_dict(box: Box) -> None:
    box.__dict__["new_field"] = 1  # SC015 -- subscript assignment into __dict__
    box.__dict__.update({"other": 2})  # SC015 -- .__dict__.update() call


def replace_whole_namespace(box: Box, other: Box) -> None:
    box.__dict__ = other.__dict__  # SC015 -- wholesale namespace replacement


def mutate_module_globals() -> None:
    globals()["_secret_value"] = 42  # SC018 -- subscript write into globals()
    globals().update({"_other": 1})  # SC018 -- .update() call on globals()/locals()/vars()

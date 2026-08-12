"""SC013 / SC014 — module-level attribute hooks and dynamic metaclasses.

Both constructs let an object's shape change *after* the class/module body
has been parsed, which is exactly what Scopify statically cannot follow.
"""


def __getattr__(name: str) -> object:  # SC013 -- module-level hook intercepts every lookup on this module
    raise AttributeError(name)


class _Meta(type):
    """A metaclass can rewrite the class body at creation time (add/remove
    members, change bases, ...), which defeats static visibility checks.
    """


class Widget(metaclass=_Meta):  # SC014 -- explicit custom metaclass
    pass

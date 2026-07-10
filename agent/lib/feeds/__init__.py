"""Feed adapter registry. Adapters are functions: fetch(spec, **kw) -> list[ChangeEntry]."""
from __future__ import annotations

_ADAPTERS: dict = {}


def register(name: str):
    def deco(fn):
        _ADAPTERS[name] = fn
        return fn
    return deco


def get_adapter(name: str):
    if name not in _ADAPTERS:
        raise KeyError(f"no feed adapter registered for '{name}'")
    return _ADAPTERS[name]


def adapter_names() -> set:
    return set(_ADAPTERS)

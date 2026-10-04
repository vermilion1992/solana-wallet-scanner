"""Shared bounded JSON parsing/serialization, independent of archive adapters."""
from __future__ import annotations

import json

MAX_DEPTH = 64


def bounded_value(value, *, max_depth=MAX_DEPTH, max_nodes=None, string_keys=False):
    """Inspect iteratively so deep/cyclic objects cannot escape as recursion errors."""
    if type(max_depth) is not int or max_depth < 1 or max_nodes is not None and (type(max_nodes) is not int or max_nodes < 1):
        raise ValueError('JSON inspection bounds must be positive integers')
    stack, ancestors, nodes = [(value, 1, False)], set(), 0
    while stack:
        item, depth, leaving = stack.pop()
        if leaving:
            ancestors.remove(id(item))
            continue
        nodes += 1
        if depth > max_depth or max_nodes is not None and nodes > max_nodes:
            raise ValueError('JSON depth/node inspection limit exceeded')
        if not isinstance(item, (dict, list, tuple)):
            continue
        if id(item) in ancestors:
            raise ValueError('Cyclic input is not JSON')
        ancestors.add(id(item))
        stack.append((item, depth, True))
        if isinstance(item, dict):
            if string_keys and any(not isinstance(key, str) for key in item):
                raise ValueError('JSON object keys must be strings')
            stack.extend((child, depth+1, False) for child in item.values())
        else:
            stack.extend((child, depth+1, False) for child in item)


def parse_json(raw, *, max_depth=MAX_DEPTH, max_nodes=None):
    """Preserve duplicate-key/nonfinite rejection while bounding interpretation."""
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate JSON keys are not accepted')
            value[key] = item
        return value
    def nonfinite(_):
        raise ValueError('Nonfinite JSON')
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
        bounded_value(value, max_depth=max_depth, max_nodes=max_nodes, string_keys=True)
        return value
    except (RecursionError, UnicodeError, OverflowError) as exc:
        raise ValueError('JSON cannot be interpreted within its depth/encoding limits') from exc


def canonical_bytes(value, *, max_depth=MAX_DEPTH, max_nodes=None, string_keys=False):
    """Use the existing canonical byte convention after bounded validation."""
    bounded_value(value, max_depth=max_depth, max_nodes=max_nodes, string_keys=string_keys)
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode()
    except (RecursionError, TypeError, UnicodeError, OverflowError) as exc:
        raise ValueError('Input cannot be canonically serialized') from exc

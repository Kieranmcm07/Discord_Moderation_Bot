"""Bounded, short-lived caching for frequently read database settings."""

from collections import OrderedDict
from copy import deepcopy
from functools import wraps
from inspect import signature
from time import monotonic


class AsyncTTLCache:
    """Cache successful reads, isolating callers from mutable cached values.

    Use on one asyncio event loop. Clearing during an awaited database read
    prevents that older read from repopulating the cache after a settings edit.
    """

    def __init__(self, *, ttl=30, maxsize=2048, namespace=lambda: None):
        self.ttl = ttl
        self.maxsize = maxsize
        self.namespace = namespace
        self._entries = OrderedDict()
        self._generation = 0

    def clear(self):
        self._generation += 1
        self._entries.clear()

    def cached(self, function):
        parameters = signature(function)

        @wraps(function)
        async def read(*args, **kwargs):
            bound = parameters.bind(*args, **kwargs)
            bound.apply_defaults()
            key = (self.namespace(), function.__name__, tuple(bound.arguments.items()))
            entry = self._entries.get(key)
            if entry is not None:
                expires, value = entry
                if monotonic() < expires:
                    self._entries.move_to_end(key)
                    return deepcopy(value)
                del self._entries[key]

            generation = self._generation
            value = await function(*args, **kwargs)
            if generation == self._generation:
                self._entries[key] = (monotonic() + self.ttl, deepcopy(value))
                self._entries.move_to_end(key)
                while len(self._entries) > self.maxsize:
                    self._entries.popitem(last=False)
            return value

        return read

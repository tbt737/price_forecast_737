"""Per-key synchronization for synchronous, cached computations in one process."""

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock


class _Entry:
    def __init__(self) -> None:
        self.lock = Lock()
        self.users = 0


class KeyedSingleFlight:
    """Serialize callers for the same key; callers must recheck their cache inside.

    Registry entries count owners and waiters and disappear after the last user,
    so arbitrary keys do not leave permanent locks. Different keys stay independent.
    This does not coordinate separate workers/containers or persist any result.
    """

    def __init__(self) -> None:
        self._guard = Lock()
        self._entries: dict[str, _Entry] = {}

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        with self._guard:
            entry = self._entries.setdefault(key, _Entry())
            entry.users += 1
        acquired = False
        try:
            entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            with self._guard:
                entry.users -= 1
                if entry.users == 0:
                    del self._entries[key]

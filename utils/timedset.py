import asyncio

from utils.utilities import call_later


class TimedSet(set):
    def __init__(self, iterable=None, loop=None):
        if not iterable:
            super().__init__()
        else:
            super().__init__(iterable)

        self._loop = loop
        self._tasks = []

    async def _remove_element(self, element, ttl):
        await asyncio.sleep(ttl)
        self.discard(element)

    def clear(self):
        super().clear()
        map(lambda t: t.cancel(), self._tasks)

    def add(self, element, ttl=60):
        """
        Add an element to the timed set.
        If element already exist won't update anything
        """
        if element in self:
            return

        super().add(element)
        self._tasks.append(
            call_later(self._remove_element, self._loop, ttl, element, ttl),
        )

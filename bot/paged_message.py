from enum import Enum


class Actions(Enum):
    DELETE = 0,
    INVALID = 1,
    VALID = 2


class PagedMessage:
    DELETE = Actions.DELETE
    INVALID = Actions.INVALID
    VALID = Actions.VALID

    def __init__(self, pages, prev='◀', next_='▶', stop='⏹', accept=None,
                 test_check=False, starting_idx=0):
        """
        Paged message where pages can be changed by reacting to a message

        Args:
            test_check: Set to False when the checks are done by other means
            accept: Emoji to indicate that the current result was accepted and no further changed will be done
        """
        self._pages = pages
        self._idx = starting_idx
        self._prev = prev
        self._next = next_
        self._stop = stop
        self._accept = accept
        self.test_check = test_check

    @property
    def index(self):
        return self._idx

    @property
    def current_page(self):
        return self._pages[self._idx]

    async def add_reactions(self, message):
        for e in (self._prev, self._next, self._stop, self._accept):
            if e:
                await message.add_reaction(e)

    def check(self, reaction, user):
        if reaction.emoji not in (self._prev, self._next, self._stop, self._accept):
            return False
        else:
            return True

    def reaction_changed(self, reaction, user):
        if self.test_check and not self.check(reaction, user):
            return self.INVALID

        if reaction.emoji == self._next:
            try:
                page = self._pages[self._idx + 1]
                self._idx += 1
            except IndexError:
                self._idx = 0
                page = self._pages[self._idx]

        elif reaction.emoji == self._prev:
            idx = self._idx - 1
            if idx < 0:
                idx = len(self._pages) - 1
                if idx == self._idx:
                    return self.INVALID

            self._idx = idx
            page = self._pages[idx]

        elif reaction.emoji == self._stop:
            return self.DELETE

        else:
            return Actions.VALID

        return page

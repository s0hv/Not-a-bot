class PagedMessage:
    def __init__(self, pages, prev='◀', next='▶', stop='⏹', accept=None, test_check=False, starting_idx=0):
        """
        Paged message where pages can be changed by reacting to a message

        Args:
            test_check: Set to False when the checks are done by other means
            accept: Emoji to indicate that the current result was accepted and no further changed will be done
        """
        self._pages = pages
        self._idx = starting_idx
        self._prev = prev
        self._next = next
        self._stop = stop
        self._accept = accept
        self.test_check = test_check

    @property
    def index(self):
        return self._idx

    async def add_reactions(self, message):
        for e in (self._prev, self._next, self._stop, self._accept):
            if e:
                await message.add_reaction(e)

    def check(self, reaction, user):
        if reaction.emoji not in (self._prev, self._next, self._stop):
            return False
        else:
            return True

    def reaction_changed(self, reaction, user):
        if self.test_check and not self.check(reaction, user):
            return

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
                    return

            self._idx = idx
            page = self._pages[idx]

        elif reaction.emoji == self._stop:
            return False

        else:
            return True

        return page

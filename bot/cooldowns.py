from disnake.ext import commands


def monkey_patch():
    def undo_one(self: commands.Cooldown):
        self._tokens = min(self._tokens + 1, self.rate)

    commands.Cooldown.undo_one = undo_one

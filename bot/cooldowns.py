from discord.ext import commands


class Cooldown(commands.Cooldown):
    def undo_one(self):
        self._tokens = min(self._tokens + 1, self.rate)

    def copy(self):
        return Cooldown(self.rate, self.per, self.type)


class CooldownMapping(commands.CooldownMapping):
    @classmethod
    def from_cooldown(cls, rate, per, type):
        return cls(Cooldown(rate, per, type))


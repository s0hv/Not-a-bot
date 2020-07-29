import asyncio

from discord.ext import commands

from bot.botbase import BotBase


class Cog(commands.Cog):
    def __init__(self, bot: BotBase):
        super().__init__()
        self._bot = bot

        # Add all commands to cmdstats db table
        cmds = set()
        for cmd in self.walk_commands():
            cmds.add(cmd)

        data = []
        for cmd in cmds:
            entries = []
            command = cmd
            while command.parent is not None:
                command = command.parent
                entries.append(command.name)
            entries = list(reversed(entries))
            entries.append(cmd.name)
            data.append((entries[0], ' '.join(entries[1:]) or ""))

        asyncio.run_coroutine_threadsafe(self.bot.dbutil.add_commands(data), loop=self.bot.loop)

    @property
    def bot(self):
        return self._bot

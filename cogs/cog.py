import asyncio

from discord.ext import commands
from discord.ext.commands import Command


class Cog(commands.Cog):
    def __init__(self, bot):
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
            data.append({'parent': entries[0], 'cmd': ' '.join(entries[1:]) or ""})

        asyncio.run_coroutine_threadsafe(self.bot.dbutil.add_commands(data), loop=self.bot.loop)

    @property
    def bot(self):
        return self._bot

    def __delattr__(self, name):
        o = getattr(self, name, None)
        if isinstance(o, Command):
            self.remove_command(name)
        super().__delattr__(name)

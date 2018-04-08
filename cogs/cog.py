from discord.ext.commands import GroupMixin, Command
import inspect


# By subclassing GroupMixin we can iterate over all commands in a cog
class Cog(GroupMixin):
    def __init__(self, bot):
        super().__init__()
        self._bot = bot
        members = inspect.getmembers(self)
        for name, member in members:
            # register commands the cog has
            if isinstance(member, Command):
                if member.parent is None:
                    self.add_command(member)
                continue

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

        self.bot.dbutil.add_commands(data)

    @property
    def bot(self):
        return self._bot

    def __delattr__(self, name):
        o = getattr(self, name, None)
        if isinstance(o, Command):
            self.remove_command(name)
        super().__delattr__(name)

import logging

from disnake.ext import commands

from bot.globals import Auth
from utils.utilities import is_owner

terminal = logging.getLogger('terminal')


def command(*args, **attrs):
    if 'cls' not in attrs:
        attrs['cls'] = Command
    return commands.command(*args, **attrs)


def group(name=None, **attrs):
    """Uses custom Group class"""
    if 'cls' not in attrs:
        attrs['cls'] = Group
    return commands.command(name=name, **attrs)


class Command(commands.Command):
    def __init__(self, func, **kwargs):
        # Init called twice because commands are copied
        super(Command, self).__init__(func, **kwargs)
        self.owner_only = kwargs.pop('owner_only', False)
        self.auth = kwargs.pop('auth', Auth.NONE)

        if self.owner_only:
            terminal.info(f'registered owner_only command {self.name}')
            self.checks.insert(0, is_owner)
            raise ValueError('owner_only is deprecated')

        if 'no_pm' in kwargs or 'no_dm' in kwargs:
            raise ValueError('no_pm is deprecated')

    def undo_use(self, ctx):
        """Undoes one use of command"""
        if self._buckets.valid:
            bucket = self._buckets.get_bucket(ctx.message)
            bucket.undo_one()


class Group(Command, commands.Group):
    def __init__(self, *args, **attrs):  # skipcq: PYL-W0231
        Command.__init__(self, *args, **attrs)
        self.invoke_without_command = attrs.pop('invoke_without_command', False)

    def group(self, *args, **kwargs):
        def decorator(func):
            kwargs.setdefault('parent', self)
            result = group(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def command(self, *args, **kwargs):
        def decorator(func):
            if 'owner_only' not in kwargs and self.owner_only:
                raise ValueError('group owner only deprecated')
                kwargs['owner_only'] = self.owner_only

            kwargs.setdefault('parent', self)
            result = command(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

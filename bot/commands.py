import logging

from discord.ext import commands

from bot.cooldowns import CooldownMapping, Cooldown
from bot.globals import Auth
from utils.utilities import is_owner, check_blacklist, no_dm

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


def cooldown(rate, per, type=commands.BucketType.default):
    """See `commands.cooldown` docs"""

    def decorator(func):
        if isinstance(func, Command):
            func._buckets = CooldownMapping(Cooldown(rate, per, type))
        else:
            func.__commands_cooldown__ = Cooldown(rate, per, type)
        return func
    return decorator


class Command(commands.Command):
    def __init__(self, func, **kwargs):
        # Init called twice because commands are copied
        super(Command, self).__init__(func, **kwargs)
        self._buckets = CooldownMapping(self._buckets._cooldown)
        self.owner_only = kwargs.pop('owner_only', False)
        self.auth = kwargs.pop('auth', Auth.NONE)

        if 'required_perms' in kwargs:
            raise DeprecationWarning('Required perms is deprecated, use "from bot.bot import has_permissions" instead')

        self.checks.insert(0, check_blacklist)

        if self.owner_only:
            terminal.info('registered owner_only command %s' % self.name)
            self.checks.insert(0, is_owner)

        if 'no_pm' in kwargs or 'no_dm' in kwargs:
            self.checks.insert(0, no_dm)

    def undo_use(self, ctx):
        """Undoes one use of command"""
        if self._buckets.valid:
            bucket = self._buckets.get_bucket(ctx.message)
            bucket.undo_one()


class Group(Command, commands.Group):
    def __init__(self, *args, **attrs):
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
            if 'owner_only' not in kwargs:
                kwargs['owner_only'] = self.owner_only

            kwargs.setdefault('parent', self)
            result = command(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

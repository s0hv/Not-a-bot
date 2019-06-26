"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import asyncio
import logging

import discord
from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientConnectionError
from discord.ext import commands
from discord.ext.commands import CheckFailure

from bot.commands import command, group, Command, Group, cooldown
from bot.cooldowns import CooldownMapping
from bot.formatter import HelpCommand
from utils.utilities import seconds2str

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass


from bot import exceptions


log = logging.getLogger('discord')
logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')

# Used to stop PyCharm from removing Command and Group from imports
__all__ = [
    'Group',
    'Command',
    'command',
    'group',
    'cooldown',
    'Context',
    'has_permissions',
    'Bot'
]


class Context(commands.context.Context):
    __slots__ = ('override_perms', 'skip_check', 'original_user', 'domain',
                 'received_at')

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.override_perms = attrs.pop('override_perms', None)
        self.original_user = self.author  # Used to determine original user with runas
        # Used when wanting to skip database check like in help command
        self.skip_check = attrs.pop('skip_check', False)
        self.domain = attrs.get('domain', None)
        self.received_at = attrs.get('received_at', None)


class Client(discord.Client):
    def __init__(self, loop=None, **options):
        super().__init__(loop=loop, **options)
        self._exit_code = 0


class Bot(commands.Bot, Client):
    def __init__(self, prefix, config, aiohttp=None, **options):
        options.setdefault('help_command', HelpCommand())
        super().__init__(prefix, owner_id=config.owner, **options)
        self._runas = None

        '''
        self.remove_command('help')

        @self.group(invoke_without_command=True)
        @bot_has_permissions(embed_links=True)
        @cooldown(2, 10, commands.BucketType.guild)
        async def help(ctx, *commands_: str):
            """Shows all commands you can use on this server.
            Use {prefix}{name} all to see all commands"""
            await self._help(ctx, *commands_)

        @help.command(name='all')
        @bot_has_permissions(embed_links=True)
        @cooldown(1, 10, commands.BucketType.guild)
        async def all_(ctx, *commands_: str):
            """Shows all available commands even if you don't have the correct
            permissions to use the commands. Bot owner only commands are still hidden tho"""
            await self._help(ctx, *commands_, type=Formatter.Generic)
        '''

        log.debug('Using loop {}'.format(self.loop))
        if aiohttp is None:
            aiohttp = ClientSession(loop=self.loop)

        self.aiohttp_client = aiohttp
        self.config = config
        self.voice_clients_ = {}
        self._error_cdm = CooldownMapping(commands.Cooldown(2, 5, commands.BucketType.guild))

    @property
    def runas(self):
        return self._runas

    def _check_error_cd(self, message):
        if self._error_cdm.valid:
            bucket = self._error_cdm.get_bucket(message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                return False

        return True

    async def on_command_error(self, context, exception):
        """|coro|

        The default command error handler provided by the bot.

        By default this prints to ``sys.stderr`` however it could be
        overridden to have a different implementation.

        This only fires if you do not specify any listeners for command error.
        """
        if self.extra_events.get('on_command_error', None):
            return
        if hasattr(context.command, "on_error"):
            return

        if hasattr(exception, 'original'):
            exception = exception.original

        if isinstance(exception, commands.errors.CommandNotFound):
            return

        if isinstance(exception, exceptions.SilentException):
            return

        if isinstance(exception, exceptions.PermException):
            return

        if isinstance(exception, discord.Forbidden):
            return

        if isinstance(exception, exceptions.NotOwner):
            return

        if isinstance(exception, ClientConnectionError):
            return

        channel = context.channel

        if isinstance(exception, commands.errors.BotMissingPermissions) or \
           isinstance(exception, commands.errors.MissingPermissions) or \
           isinstance(exception, exceptions.MissingFeatures):

            if self._check_error_cd(context.message):
                try:
                    return await channel.send(str(exception))
                except discord.Forbidden:
                    pass
            return

        if isinstance(exception, CheckFailure):
            return

        error_msg = None
        if isinstance(exception, commands.errors.CommandOnCooldown):
            error_msg = 'Command on cooldown. Try again in {}'.format(seconds2str(exception.retry_after, False))

        elif isinstance(exception, commands.errors.BadArgument) or isinstance(exception, commands.errors.MissingRequiredArgument) or isinstance(exception, commands.BadUnionArgument):
            error_msg = str(exception)

        elif isinstance(exception, exceptions.CommandBlacklisted):
            if exception.message is None:
                return
            error_msg = str(exception)

        elif isinstance(exception, exceptions.BotException):
            error_msg = str(exception)

        if isinstance(exception, OSError) and 'Errno 12' in str(exception):
            error_msg = "Couldn't allocate memory. Try again a bit later"

        if error_msg:
            if self._check_error_cd(context.message):
                try:
                    await channel.send(error_msg, delete_after=300)
                except discord.Forbidden:
                    pass
            return

        # Ignore exception logging when message is set as empty
        elif error_msg == '':
            return

        terminal.warning('Ignoring exception in command {}'.format(context.command))
        terminal.exception('', exc_info=exception)

    async def get_context(self, message, *, cls=Context):
        # Same as default implementation. This just adds runas variable
        ctx = await super().get_context(message, cls=cls)
        if self.runas is not None and message.author.id == self.owner_id:
            if ctx.guild:
                member = ctx.guild.get_member(self.runas.id)
                if not member:
                    return ctx
            else:
                member = self.runas

            ctx.author = member
            ctx.message.author = member

        return ctx

    async def process_commands(self, message, local_time=None):
        if message.author.bot:
            return

        ctx = await self.get_context(message, cls=Context)
        ctx.received_at = local_time
        await self.invoke(ctx)

    def command(self, *args, **kwargs):
        """A shortcut decorator that invokes :func:`command` and adds it to
        the internal command list via :meth:`add_command`.
        """
        def decorator(func):
            kwargs.setdefault('parent', self)
            result = command(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def group(self, *args, **kwargs):
        def decorator(func):
            kwargs.setdefault('parent', self)
            result = group(*args, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    def handle_reaction_changed(self, reaction, user):
        removed = []
        event = 'reaction_changed'
        listeners = self._listeners.get(event)
        if not listeners:
            return
        for i, (future, condition) in enumerate(listeners):
            if future.cancelled():
                removed.append(i)
                continue

            try:
                result = condition(reaction, user)
            except Exception as e:
                future.set_exception(e)
                removed.append(i)
            else:
                if result:
                    future.set_result((reaction, user))
                    removed.append(i)

        if len(removed) == len(listeners):
            self._listeners.pop(event)
        else:
            for idx in reversed(removed):
                del listeners[idx]

    async def on_reaction_add(self, reaction, user):
        self.handle_reaction_changed(reaction, user)

    async def on_reaction_remove(self, reaction, user):
        self.handle_reaction_changed(reaction, user)


def has_permissions(**perms):
    """
    Same as the default discord.ext.commands.has_permissions
    except this one supports overriding perms
    """
    def predicate(ctx):
        if ctx.override_perms:
            return True

        ch = ctx.channel
        permissions = ch.permissions_for(ctx.author)

        # Special case for when manage roles is requested
        # This is needed because the default implementation thinks that
        # manage_channel_perms == manage_roles which can create false negatives
        # Assumes ctx.author is instance of discord.Member
        if 'manage_roles' in perms:
            # Set manage roles based on server wide value
            permissions.manage_roles = ctx.author.guild_permissions.manage_roles

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm, None) != value]

        if not missing:
            return True

        raise commands.MissingPermissions(missing)

    return commands.check(predicate)


def guild_has_features(*features):
    def predicate(ctx):
        if not ctx.guild:
            return

        missing = [feature for feature in features if feature.upper() not in ctx.guild.features]

        if not missing:
            return True

        raise exceptions.MissingFeatures(missing)

    return commands.check(predicate)

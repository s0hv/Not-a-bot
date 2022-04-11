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
from typing import Optional, Union

import discord
from aiohttp import ClientSession
from aiohttp.client_exceptions import ClientConnectionError
from discord import ApplicationContext
from discord.ext import bridge
from discord.ext import commands
from discord.ext.commands import CheckFailure

from bot.commands import command, group, Command, Group, cooldown, \
    bridge_command
from bot.cooldowns import CooldownMapping
from bot.formatter import HelpCommand
from utils.utilities import seconds2str, call_later, check_blacklist

try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    uvloop = None


from bot import exceptions


log = logging.getLogger('discord')
logger = logging.getLogger('terminal')

# Used to stop PyCharm from removing Command and Group from imports
__all__ = [
    'Group',
    'Command',
    'command',
    'bridge_command',
    'group',
    'cooldown',
    'Context',
    'has_permissions',
    'bot_has_permissions',
    'guild_has_features',
    'Bot'
]


class Context(bridge.BridgeExtContext):
    __slots__ = ('override_perms', 'skip_check', 'original_user',
                 'received_at')

    undo_messages = {}

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.override_perms = attrs.pop('override_perms', None)
        self.original_user = self.author  # Used to determine original user with runas
        # Used when wanting to skip database check like in help command
        self.skip_check = attrs.pop('skip_check', False)
        self.received_at = attrs.get('received_at', None)

    async def undo(self):
        old = self.undo_messages.pop(self.author.id, None)
        if not old:
            return False

        msg, t = old
        t.cancel()
        try:
            await msg.delete()
        except discord.HTTPException:
            return False

        return True

    def _add_undo(self, msg: discord.Message):
        if msg:
            old = self.undo_messages.pop(self.author.id, None)
            if old:
                old[1].cancel()

            async def a():
                self.undo_messages.pop(self.author.id, None)

            self.undo_messages[self.author.id] = (msg, call_later(a, self.bot.loop, 60))

    async def respond(self, content: Optional[str]=None, *, undoable=False, **kwargs):
        msg = super().respond(content, **kwargs)
        if undoable:
            self._add_undo(msg)

        return msg

    async def send(self, content: Optional[str]=None, *, undoable=False, **kwargs):
        msg = await super().send(content, **kwargs)

        if undoable:
            self._add_undo(msg)

        return msg


class Bot(bridge.AutoShardedBot):
    def __init__(self, prefix, config, aiohttp=None, **options):
        options.setdefault('help_command', HelpCommand())
        super().__init__(prefix, owner_id=config.owner, **options)
        self._runas = None
        self._exit_code = 0
        self.add_check(check_blacklist)

        log.debug('Using loop {}'.format(self.loop))

        self.aiohttp_client = aiohttp

        async def set_client():
            self.aiohttp_client = ClientSession(loop=self.loop)

        if aiohttp is None:
            self.loop.create_task(set_client())

        self.config = config
        self.voice_clients_ = {}
        self._error_cdm = CooldownMapping(commands.Cooldown(2, 5), commands.BucketType.guild)

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

    async def on_error(self, event_method, *args, **kwargs):
        logger.exception('Ignoring exception in {}'.format(event_method))

    async def on_application_command_error(self, ctx: ApplicationContext, ex):
        await self.on_command_error(ctx, ex)

    async def on_command_error(self, context: Union[ApplicationContext, Context], exception):
        """|coro|

        The default command error handler provided by the bot.

        By default, this prints to ``sys.stderr`` however it could be
        overridden to have a different implementation.

        This only fires if you do not specify any listeners for command error.
        """
        if self.extra_events.get('on_command_error', None):
            return
        if hasattr(context.command, "on_error"):
            return

        if hasattr(exception, 'original'):
            exception = exception.original

        if isinstance(exception, (commands.errors.CommandNotFound,
                                  exceptions.SilentException,
                                  exceptions.PermException,
                                  discord.Forbidden,
                                  exceptions.NotOwner,
                                  ClientConnectionError,
                                  commands.errors.DisabledCommand)):
            return

        # Just ignore the moderator prefix on my server
        if isinstance(context, Context) and context.guild and context.guild.id == 217677285442977792 and context.prefix == 'm':
            return

        if isinstance(exception, (commands.errors.BotMissingPermissions,
                                  commands.errors.MissingPermissions,
                                  exceptions.MissingFeatures)):

            if self._check_error_cd(context):
                try:
                    return await context.respond(str(exception), ephemeral=True)
                except discord.Forbidden:
                    pass
            return

        if isinstance(exception, CheckFailure):
            return

        error_msg = None
        if isinstance(exception, commands.errors.CommandOnCooldown):
            # Delete message if hidden command
            if context.command.hidden and isinstance(context, Context):
                try:
                    await context.message.delete()
                except discord.HTTPException:
                    pass

                return

            error_msg = 'Command on cooldown. Try again in {}'.format(seconds2str(exception.retry_after, False))

        elif isinstance(exception, (commands.errors.BadArgument,
                                    commands.errors.MissingRequiredArgument,
                                    commands.UnexpectedQuoteError,
                                    commands.ExpectedClosingQuoteError,
                                    commands.InvalidEndOfQuotedStringError)):
            error_msg = str(exception)

        elif isinstance(exception, commands.BadUnionArgument):
            error_msg = str(exception.errors[-1])

        elif isinstance(exception, exceptions.CommandBlacklisted):
            if not exception.message:
                try:
                    if isinstance(context, Context):
                        await context.message.add_reaction('🚫')
                    else:
                        await context.respond('🚫', ephemeral=True)
                except discord.HTTPException:
                    pass

                return
            error_msg = str(exception)

        elif isinstance(exception, exceptions.BotException):
            error_msg = str(exception)

        elif isinstance(exception, OSError) and 'Errno 12' in str(exception):
            error_msg = "Couldn't allocate memory. Try again a bit later"

        if error_msg:
            if self._check_error_cd(context):
                try:
                    await context.respond(error_msg, ephemeral=True)
                except discord.Forbidden:
                    pass
            return

        # Ignore exception logging when message is set as empty
        elif error_msg == '':
            return

        logger.warning('Ignoring exception in command {}'.format(context.command))
        logger.exception('', exc_info=exception)

    async def get_context(self, message, *, cls=Context) -> Context:
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

        ctx = await self.get_context(message)
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
    def predicate(ctx: Context):
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


def bot_has_permissions(**perms):
    """Similar to :func:`.has_permissions` except checks if the bot itself has
    the permissions listed.

    This check raises a special exception, :exc:`.BotMissingPermissions`
    that is inherited from :exc:`.CheckFailure`.
    """
    def predicate(ctx):
        guild = ctx.guild
        me = guild.me if guild is not None else ctx.bot.user
        permissions = ctx.channel.permissions_for(me)

        # Special case for when manage roles is requested
        # This is needed because the default implementation thinks that
        # manage_channel_perms == manage_roles which can create false negatives
        # Assumes ctx.author is instance of discord.Member
        if guild and 'manage_roles' in perms:
            # Set manage roles based on server wide value
            permissions.manage_roles = me.guild_permissions.manage_roles

        missing = [perm for perm, value in perms.items() if getattr(permissions, perm, None) != value]

        if not missing:
            return True

        raise commands.BotMissingPermissions(missing)

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

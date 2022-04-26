import re
from datetime import timedelta
from typing import Any

import disnake
import pytz
from disnake import ApplicationCommandInteraction
from disnake.ext import commands
from disnake.ext.commands import converter, SubCommandGroup
from disnake.ext.commands.errors import BadArgument

from utils.tzinfo import fuzzy_tz
from utils.utilities import parse_time


class MentionedMember(converter.MemberConverter):
    async def convert(self, ctx, argument):
        message = ctx.message
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
        guild = message.guild
        result = None
        if match:
            user_id = int(match.group(1))
            result = guild.get_member(user_id)
            if not result:
                try:
                    result = await guild.fetch_member(user_id)
                except disnake.HTTPException:
                    pass

        if result is None:
            raise BadArgument('Member "{}" not found'.format(argument))

        return result


class PossibleUser(converter.IDConverter):
    """
    Possibly returns a user object
    If no user is found returns user id if it could be parsed from argument
    """
    async def convert(self, ctx, argument):
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
        state = ctx._state

        if match is not None:
            user_id = int(match.group(1))
            result = ctx.bot.get_user(user_id)
            if not result:
                try:
                    result = await ctx.bot.fetch_user(user_id)
                except disnake.HTTPException:
                    result = user_id
        else:
            arg = argument
            # check for discriminator if it exists
            if len(arg) > 5 and arg[-5] == '#':
                discrim = arg[-4:]
                name = arg[:-5]
                user = disnake.utils.find(lambda u: u.name == name and u.discriminator == discrim,
                                          state._users.values())
                if user is not None:
                    return user

            result = disnake.utils.find(lambda u: u.name == arg,
                                        state._users.values())
            if result is None:
                raise BadArgument(f'No user id or user found with "{argument}"')

        if result is None:
            raise BadArgument('User "{}" not found'.format(argument))

        return result


class AnyUser(PossibleUser):
    """
    Like possible user but fall back to given value when nothing is found
    """
    async def convert(self, ctx, argument):
        try:
            user = await PossibleUser.convert(self, ctx, argument)
            return user or argument
        except BadArgument:
            return argument


class MentionedUser(converter.UserConverter):
    def __init__(self):
        super().__init__()

    async def convert(self, ctx, argument):
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
        result = None
        if match:
            user_id = int(match.group(1))
            result = ctx.bot.get_user(user_id)
            if not result:
                try:
                    result = await ctx.bot.fetch_user(user_id)
                except disnake.HTTPException:
                    pass

        if result is None:
            raise BadArgument('Member "{}" not found'.format(argument))

        return result


class MentionedUserID(converter.UserConverter):
    def __init__(self):
        super().__init__()

    async def convert(self, ctx, argument):
        match = self._get_id_match(argument) or re.match(r'<@!?([0-9]+)>$', argument)
        result = None
        if match:
            result = int(match.group(1))

        if result is None:
            raise BadArgument('"{}" is not a valid mention/id'.format(argument))

        return result


class TimeDelta(converter.Converter):
    def __init__(self):
        super().__init__()

    async def convert(self, ctx, argument):
        return convert_timedelta(None, argument)


@commands.register_injection
def convert_timedelta(_, value: Any) -> timedelta:
    time = parse_time(value)
    if not time:
        raise BadArgument(f'Failed to parse time from {value}')

    return time


class FuzzyRole(converter.RoleConverter):
    async def convert(self, ctx, argument):
        guild = ctx.message.guild
        if not guild:
            raise converter.NoPrivateMessage()

        match = self._get_id_match(argument) or re.match(r'<@&([0-9]+)>$', argument)
        params = dict(id=int(match.group(1))) if match else dict(name=argument)
        result = disnake.utils.get(guild.roles, **params)
        if result is None:
            def pred(role):
                return role.name.lower().startswith(argument)

            result = disnake.utils.find(pred, guild.roles)

        if result is None:
            raise BadArgument('Role not found with "{}"'.format(argument))

        return result


class GuildEmoji(converter.EmojiConverter):
    """Same as EmojiConverter except it doesn't check local cache"""
    async def convert(self, ctx, argument):
        match = self._get_id_match(argument) or re.match(r'<a?:[a-zA-Z0-9\_]+:([0-9]+)>$', argument)
        result = None
        guild = ctx.guild

        if match is None:
            # Try to get the emoji by name. Try local guild first.
            if guild:
                result = disnake.utils.get(guild.emojis, name=argument)

        else:
            emoji_id = int(match.group(1))

            # Try to look up emoji by id.
            if guild:
                result = disnake.utils.get(guild.emojis, id=emoji_id)

        if result is None:
            raise BadArgument('Emoji "{}" not found.'.format(argument))

        return result


class CommandConverter(converter.Converter):
    async def convert(self, ctx, argument):
        bot = ctx.bot

        cmd = bot.get_command(argument)
        if not cmd:
            cmd = bot.get_slash_command(argument)

        if not cmd:
            raise BadArgument('Command "%s" not found' % argument)

        return cmd


class TzConverter(converter.Converter):
    async def convert(self, ctx, argument):
        try:
            argument = int(argument)
            argument *= 60

            try:
                tz = pytz.FixedOffset(argument)
            except ValueError:
                raise BadArgument('Timezone offset over 24h')

            return tz

        except ValueError:
            pass

        tz = fuzzy_tz.get(argument.lower().replace(' ', '_'))
        if tz is None:
            raise BadArgument('Unknown timezone %s' % argument)

        try:
            tz = await ctx.bot.loop.run_in_executor(ctx.bot.threadpool, pytz.timezone, tz)
        except pytz.UnknownTimeZoneError:
            raise BadArgument('Unknown timezone %s' % argument)

        return tz


class CleanContent(converter.clean_content):
    """Converts the argument to mention scrubbed version of
    said content.

    This behaves similarly to :attr:`.Message.clean_content`.

    Attributes
    ------------
    fix_channel_mentions: :obj:`bool`
        Whether to clean channel mentions.
    use_nicknames: :obj:`bool`
        Whether to use nicknames when transforming mentions.
    escape_markdown: :obj:`bool`
        Whether to also escape special markdown characters.
    remove_everyone: :obj:`bool`
        Whether to remove everyone mentions by inserting a zero width space in front of @
    fix_emotes: :obj:`bool`
        Whether to turn emotes to their names only
    """
    def __init__(self, *, fix_channel_mentions=False, use_nicknames=True, escape_markdown=False,
                 remove_everyone=True, fix_emotes=False):
        setattr(converter, 'Context', commands.Context)  # TODO remove in disnake 2.5
        super().__init__(
            fix_channel_mentions=fix_channel_mentions,
            use_nicknames=use_nicknames,
            escape_markdown=escape_markdown,
            remove_markdown=remove_everyone,
        )
        self.fix_emotes = fix_emotes

    async def convert(self, ctx, argument):
        msg = await super().convert(ctx, argument)

        if self.fix_emotes:
            def repl(obj):  # skipcq: PYL-E0102
                return obj.groups()[0]

            pattern = re.compile(r'<:(\w+):[0-9]{17,21}>')
            msg = pattern.sub(repl, msg)

        return msg


def autocomplete_command(inter: ApplicationCommandInteraction, user_input: str):
    """
    Autocomplete for a command name. Works for normal and slash commands
    """
    user_input = user_input.lower().strip()
    bot = inter.bot
    command_names: set[str] = {
        cmd.qualified_name for cmd in bot.walk_commands()
        if user_input in cmd.qualified_name and (cmd.cog is None or 'admin' not in cmd.cog.qualified_name.lower())
    }

    slash_commands = []
    for cmd in bot.slash_commands:
        if cmd.cog and 'admin' in cmd.cog.qualified_name.lower():
            continue

        if not cmd.children:
            if user_input in cmd.qualified_name:
                slash_commands.append(cmd.qualified_name)
            continue

        for child in cmd.children.values():
            if not isinstance(child, SubCommandGroup):
                if user_input in child.qualified_name:
                    slash_commands.append(child.qualified_name)
                continue

            for last_child in child.children.values():
                if user_input in last_child.qualified_name:
                    slash_commands.append(last_child.qualified_name)

    command_names.update(slash_commands)
    commands_sorted = list(sorted(command_names))[:20]
    return commands_sorted


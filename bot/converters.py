import re

import discord
import pytz
from discord.ext.commands import converter
from discord.ext.commands.errors import BadArgument

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
                result = user_id
        else:
            arg = argument
            # check for discriminator if it exists
            if len(arg) > 5 and arg[-5] == '#':
                discrim = arg[-4:]
                name = arg[:-5]
                user = discord.utils.find(lambda u: u.name == name and u.discriminator == discrim,
                                          state._users.values())
                if user is not None:
                    return user

            result = discord.utils.find(lambda u: u.name == arg,
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
        time = parse_time(argument)
        if not time:
            raise BadArgument(f'Failed to parse time from {argument}')

        return time


class FuzzyRole(converter.RoleConverter):
    async def convert(self, ctx, argument):
        guild = ctx.message.guild
        if not guild:
            raise converter.NoPrivateMessage()

        match = self._get_id_match(argument) or re.match(r'<@&([0-9]+)>$', argument)
        params = dict(id=int(match.group(1))) if match else dict(name=argument)
        result = discord.utils.get(guild.roles, **params)
        if result is None:
            def pred(role):
                return role.name.lower().startswith(argument)

            result = discord.utils.find(pred, guild.roles)

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
                result = discord.utils.get(guild.emojis, name=argument)

        else:
            emoji_id = int(match.group(1))

            # Try to look up emoji by id.
            if guild:
                result = discord.utils.get(guild.emojis, id=emoji_id)

        if result is None:
            raise BadArgument('Emoji "{}" not found.'.format(argument))

        return result


class CommandConverter(converter.Converter):
    async def convert(self, ctx, argument):
        bot = ctx.bot

        cmd = bot.get_command(argument)
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


class CleanContent(converter.Converter):
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
        self.fix_channel_mentions = fix_channel_mentions
        self.use_nicknames = use_nicknames
        self.escape_markdown = escape_markdown
        self.remove_everyone = remove_everyone
        self.fix_emotes = fix_emotes

    async def convert(self, ctx, argument):
        message = ctx.message
        transformations = {}

        if self.fix_channel_mentions and ctx.guild:
            def resolve_channel(id, *, _get=ctx.guild.get_channel):
                ch = _get(id)
                return ('<#%s>' % id), ('#' + ch.name if ch else '#deleted-channel')

            transformations.update(resolve_channel(channel) for channel in message.raw_channel_mentions)

        if self.use_nicknames and ctx.guild:
            def resolve_member(id_, *, _get=ctx.guild.get_member):
                m = _get(id_)
                return '@' + m.display_name if m else '@deleted-user'
        else:
            def resolve_member(id_, *, _get=ctx.bot.get_user):
                m = _get(id_)
                return '@' + m.name if m else '@deleted-user'

        transformations.update(
            ('<@%s>' % member_id, resolve_member(member_id))
            for member_id in message.raw_mentions
        )

        transformations.update(
            ('<@!%s>' % member_id, resolve_member(member_id))
            for member_id in message.raw_mentions
        )

        if ctx.guild:
            def resolve_role(_id, *, _find=ctx.guild.get_role):
                r = _find(_id)
                return '@' + r.name if r else '@deleted-role'

            transformations.update(
                ('<@&%s>' % role_id, resolve_role(role_id))
                for role_id in message.raw_role_mentions
            )

        def repl(obj):
            return transformations.get(obj.group(0), '')

        pattern = re.compile('|'.join(transformations.keys()))
        result = pattern.sub(repl, argument)

        if self.escape_markdown:
            transformations = {
                re.escape(c): '\\' + c
                for c in ('*', '`', '_', '~', '\\')
            }

            def replace(obj):
                return transformations.get(re.escape(obj.group(0)), '')

            pattern = re.compile('|'.join(transformations.keys()))
            result = pattern.sub(replace, result)

        if self.fix_emotes:
            def repl(obj):  # skipcq: PYL-E0102
                return obj.groups()[0]

            pattern = re.compile(r'<:(\w+):[0-9]{17,21}>')
            result = pattern.sub(repl, result)

        # Completely ensure no mentions escape:
        if self.remove_everyone:
            return re.sub(r'@(everyone|here|[!&]?[0-9]{17,21})', '@\u200b\\1', result)
        else:
            return result

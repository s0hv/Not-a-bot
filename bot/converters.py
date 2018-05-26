from discord.ext.commands import converter
import re
from discord.ext.commands.errors import BadArgument
import discord
from utils.utilities import parse_time


class MentionedMember(converter.MemberConverter):
    def __init__(self):
        super().__init__()

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
    def __init__(self):
        super().__init__()

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
                predicate = lambda u: u.name == name and u.discriminator == discrim
                user = discord.utils.find(predicate, state._users.values())
                if user is not None:
                    return user

            predicate = lambda u: u.name == arg
            result = discord.utils.find(predicate, state._users.values())
            if result is None:
                return arg

        if result is None:
            raise BadArgument('User "{}" not found'.format(argument))

        return result


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


class TimeDelta(converter.Converter):
    def __init__(self):
        super().__init__()

    async def convert(self, ctx, argument):
        time = parse_time(argument)
        if not time:
            raise BadArgument(f'Failed to parse time from {argument}')

        return time

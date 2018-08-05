import re

import discord
from discord.ext.commands import converter
from discord.ext.commands.errors import BadArgument

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
                predicate = lambda u: u.name == name and u.discriminator == discrim
                user = discord.utils.find(predicate, state._users.values())
                if user is not None:
                    return user

            predicate = lambda u: u.name == arg
            result = discord.utils.find(predicate, state._users.values())
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

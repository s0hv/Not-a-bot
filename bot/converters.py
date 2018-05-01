from discord.ext.commands import converter
import re
from discord.ext.commands.errors import BadArgument


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

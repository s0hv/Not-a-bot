from cogs.cog import Cog
from bot.bot import command
from discord.ext.commands import cooldown
from utils.utilities import split_string, emote_url_from_id, get_emote_id
import time


class Utilities(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(name='commands', pass_context=True, ignore_extra=True, enabled=False)
    async def bot_commands(self, ctx):
        s = ''

        seen = set()
        commands = self.bot.commands.values()
        commands = [seen.add(c.name) or c for c in commands if c.name not in seen]
        del seen
        commands = sorted(commands, key=lambda c: c.name)

        for command in commands:
            try:
                s += '{}: level {}\n'.format(command.name, command.level)
            except Exception as e:
                print('[ERROR] Command info failed. %s' % e)

        s = split_string(s, splitter='\n')
        for string in s:
            await self.bot.send_message(ctx.message.author, string)

    @command(ignore_extra=True)
    async def ping(self):
        """Ping pong"""
        t = time.time()

        msg = await self.bot.say('Pong!')
        t = time.time() - t
        await self.bot.edit_message(msg , 'Pong!\n🏓 took {:.0f}ms'.format(t*1000))

    @command(ignore_extra=True, aliases=['e', 'emoji'])
    async def emote(self, emote: str):
        emote = get_emote_id(emote)
        if emote is None:
            return await self.bot('You need to specify an emote. Default (unicode) emotes are not supported yet')

        await self.bot.say(emote_url_from_id(emote))

    @cooldown(1, 1)
    @command(pass_context=True, aliases=['howtoping'])
    async def how2ping(self, ctx, *, user):
        if ctx.message.server:
            members = ctx.message.server.members
        else:
            members = self.bot.get_all_members()

        def filter_users(predicate):
            for member in members:
                if predicate(member):
                    return member

                if member.nick and predicate(member.nick):
                    return member

        if ctx.message.raw_role_mentions:
            i = len(ctx.invoked_with) + len(ctx.prefix) + 1

            user = ctx.message.clean_content[i:]
            user = user[user.find('@')+1:]

        found = filter_users(lambda u: str(u).startswith(user))
        s = '`<@!{}>` {}'
        if found:
            return await self.bot.say(s.format(found.id, str(found)))

        found = filter_users(lambda u: user in str(u))

        if found:
            return await self.bot.say(
                s.format(found.id, str(found)))

        else:
            return await self.bot.say('No users found with %s' % user)

    @command(ignore_extra=True, aliases=['src', 'source_code'])
    async def source(self):
        await self.bot.say('You can find the source code for this bot here https://github.com/s0hvaperuna/Not-a-bot')


def setup(bot):
    bot.add_cog(Utilities(bot))
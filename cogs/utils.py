from cogs.cog import Cog
from bot.bot import command
from utils.utilities import split_string
import time


class Utilities(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(name='commands', pass_context=True, ignore_extra=True)
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

def setup(bot):
    bot.add_cog(Utilities(bot))
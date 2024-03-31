import logging
from asyncio.locks import Lock
from datetime import timedelta

import disnake

from cogs.cog import Cog
from utils.utilities import get_emote_id

logger = logging.getLogger('terminal')

class Turtle(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._channel = 354712220761980939 if bot.test_mode else 1224060274039066824

        self._turtle = '🐢'
        self._turtle_pol = '358523461796364290'

        self._last_emote = self._turtle

        self._guild = 353927534439825429 if bot.test_mode else 217677285442977792

        self._check_lock = Lock()
        self.timeout_duration_sec = 10

    def is_turtle_pol(self, msg: disnake.Message):
        s = msg.content
        if ' ' in s:
            return False

        return self._turtle_pol ==  get_emote_id(s)[1]

    def is_turtle(self, msg: disnake.Message):
        return self._turtle == msg.content

    def get_guild(self) -> disnake.Guild:
        return self.bot.get_guild(self._guild)

    def cog_check(self, ctx):
        if not ctx.guild or ctx.guild.id != self._guild:
            return False

        return True

    async def do_timeout(self, msg: disnake.Message):
        try:
            await msg.delete()
        except:
            pass

        if msg.author.bot:
            return

        try:
            await msg.author.timeout(duration=timedelta(seconds=self.timeout_duration_sec), reason='Follow the rules <:turtlePol:358523461796364290>🐢')
        except disnake.Forbidden:
            pass

    @Cog.listener()
    async def on_message(self, msg: disnake.Message):
        if (
                not msg.guild or
                msg.guild.id != self._guild or
                msg.channel.id != self._channel
        ):
            return

        if msg.webhook_id or msg.type != disnake.MessageType.default:
            await self.do_timeout(msg)
            return

        async with self._check_lock:
            check_fn = self.is_turtle_pol if self._last_emote == self._turtle else self.is_turtle
            if not check_fn(msg):
                await self.do_timeout(msg)
                return

            self._last_emote = self._turtle_pol if self._last_emote == self._turtle else self._turtle

        user = msg.author
        role_id = 355372865693941770 if self.bot.test_mode else 1224060782296305676
        role = self.get_guild().get_role(role_id)
        if role not in user.roles:
            try:
                await user.add_roles(role)
            except:
                pass


def setup(bot):
    bot.add_cog(Turtle(bot))

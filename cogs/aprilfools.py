import asyncio

import discord
from discord.ext.commands import is_owner

from bot.bot import command
from cogs.cog import Cog
from utils.utilities import random_color


class AprilFools(Cog):
    def __init__(self, bot):
        super().__init__(bot)

        self.channel_to_role = {
            561966820001710100: [322634440713043968, 322449547173298186, 326359426397110272, 313334185781755904],
            561966975228837890: [306742691658596353, 507969156369481729, 328910552120295434, 386583390494654465],
            561966892403785749: [309085821623992320, 387964682700587008, 330073758519787520, 329254217619603457],
            561967040605323274: [313286795183783936, 314457981448355840, 444171292053078026],
            561967098214088706: [328475109151211521, 306742630048333826, 306742724470505474, 364475743872221203],
            561967126982950919: [326936151296311296, 306748073311469579, 309086585641631746],
            561967161334300692: [306742849859223553, 328903709587144704, 306742652957622273],
            561967187833782273: [309078638173749252, 333612445539237898, 342058166772826117, 312125540242948097],
            561967216136945675: [420339169764573184, 329344112845389836, 306742607306817537],
            561967252350697473: [322080267475091457, 311274533271109654, 440567167625461781]
        }

        self.role_to_channel = {}
        for c, roles in self.channel_to_role.items():
            self.role_to_channel.update({r: c for r in roles})

        self._random_color = asyncio.ensure_future(self._random_color_task(), loop=self.bot.loop)

    def cog_unload(self):
        self._random_color.cancel()

    @Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.message_id != 0:
            return

        guild = self.bot.get_guild(217677285442977792)
        r = guild.get_role(0)
        m = guild.get_member(payload.user_id)
        if not m:
            return

        if r in m.roles:
            return

        try:
            await m.add_roles(r)
        except discord.HTTPException:
            pass

    @command()
    @is_owner()
    async def create_perms(self, ctx):
        for c in ctx.guild.categories:
            if c.id in (561966590124490763, 360692585687285761, 360730963598245891):
                continue

            await c.set_permissions(ctx.guild.default_role, read_messages=False)

        for c, roles in self.channel_to_role.items():
            c = ctx.guild.get_channel(c)

            for r in roles:
                r = ctx.guild.get_role(r)
                await c.set_permissions(r, read_messages=True)

    async def _random_color_task(self):
        guild = self.bot.get_guild(217677285442977792)
        if not guild:
            return

        role = guild.get_role(348208141541834773)
        if not role:
            return

        while True:
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                return

            c = random_color()
            try:
                await role.edit(color=c)
            except discord.HTTPException:
                role = guild.get_role(348208141541834773)
                if role is None:
                    return

            colors = self.bot.get_cog('Colors')
            if not colors:
                continue

            color_roles = colors._colors.get(guild.id)
            color = colors.rgb2lab(colors.check_rgb(c.to_rgb()))
            new_color = colors.closest_color_match(color, color_roles.values())

            new_channel = self.role_to_channel.get(new_color.role_id)
            old_channel = self.role_to_channel.get(role.id)

            if new_channel == old_channel:
                continue

            self.channel_to_role[old_channel].remove(role.id)
            self.channel_to_role[new_channel].append(role.id)

            old_channel = guild.get_channel(old_channel)
            new_channel = guild.get_channel(new_channel)

            try:
                await old_channel.set_permissions(role, read_messages=False)
                await new_channel.set_permissions(role, read_messages=True)
            except discord.HTTPException:
                pass


def setup(bot):
    bot.add_cog(AprilFools(bot))

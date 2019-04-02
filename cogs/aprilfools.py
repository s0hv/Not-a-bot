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
            561967098214088706: [328475109151211521, 306742630048333826, 306742724470505474, 364475743872221203, 322081252230561793],
            561967126982950919: [326936151296311296, 306748073311469579, 309086585641631746],
            561967161334300692: [306742849859223553, 328903709587144704, 306742652957622273],
            561967187833782273: [309078638173749252, 333612445539237898, 342058166772826117, 312125540242948097],
            561967216136945675: [420339169764573184, 329344112845389836, 306742607306817537],
            561967252350697473: [322080267475091457, 311274533271109654, 440567167625461781]
        }

        g = bot.get_guild(217677285442977792)
        r = g.get_role(348208141541834773)
        for c in self.channel_to_role.keys():
            c = g.get_channel(c)
            if r in c.changed_roles:
                self.channel_to_role[c.id].append(r.id)
                break

        self.role_to_channel = {}
        for c, roles in self.channel_to_role.items():
            self.role_to_channel.update({r: c for r in roles})

        self._random_color = asyncio.ensure_future(self._random_color_task(), loop=self.bot.loop)

    def cog_unload(self):
        self._random_color.cancel()

    @Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.message_id != 561980345239601173:
            return

        guild = self.bot.get_guild(217677285442977792)
        r = guild.get_role(561978446192967754)
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
        guild = ctx.guild
        # Remove color channel role overrides
        for c in self.channel_to_role.keys():
            c = guild.get_channel(c)
            for o, _ in c.overwrites:
                if o == guild.default_role:
                    continue

                await c.set_permissions(o, overwrite=None)

        # Archive perms for channel category
        await guild.get_channel(561966590124490763).set_permissions(guild.default_role, read_messages=None, send_messages=False)

        # Restore talk here
        cat = guild.get_channel(360694488290689024)
        o = cat.overwrites_for(guild.default_role)
        o.read_messages = None
        await cat.set_permissions(guild.default_role, overwrite=o)

        for c in cat.channels:
            if c.id in (341610158755020820, 515620023457546243, 509462073432997890):
                continue
            o = c.overwrites_for(guild.default_role)
            o.read_messages = None
            await c.set_permissions(guild.default_role, overwrite=o)

        # Mudae
        await guild.get_channel(509462073432997890).set_permissions(guild.get_role(492737863931265034), read_messages=True)

        #rt2
        await guild.get_channel(341610158755020820).set_permissions(guild.get_role(341673743229124609), read_messages=True)

        # restore topic channels
        cat = guild.get_channel(360695301457313792)
        o = cat.overwrites_for(guild.default_role)
        o.read_messages = None
        await cat.set_permissions(guild.default_role, overwrite=o)

        for c in cat.channels:
            if c.id in (499656404399947796, 338523738997915649):
                continue

            o = c.overwrites_for(guild.default_role)
            o.read_messages = None
            c.set_permissions(guild.default_role, overwrite=o)

        # Restore mod rules
        c = guild.get_channel(357982845509304320)
        o = c.overwrites_for(guild.default_role)
        o.read_messages = True
        await c.set_permissions(guild.default_role, overwrite=o)

        # Server stuff
        cat = guild.get_channel(360697181558145024)
        o = cat.overwrites_for(guild.default_role)
        o.read_messages = None
        await cat.set_permissions(guild.default_role, overwrite=o)

        for c in cat.channels:
            o = c.overwrites_for(guild.default_role)
            o.read_messages = None
            c.set_permissions(guild.default_role, overwrite=o)

        # NSFW
        cat = guild.get_channel(360699176394293248)
        o = cat.overwrites_for(guild.default_role)
        o.read_messages = None
        await cat.set_permissions(guild.default_role, overwrite=o)

        for c in cat.channels:
            o = c.overwrites_for(guild.default_role)
            o.read_messages = None
            c.set_permissions(guild.default_role, overwrite=o)

        # Misc
        cat = guild.get_channel(360694903824580608)
        o = cat.overwrites_for(guild.default_role)
        o.read_messages = None
        await cat.set_permissions(guild.default_role, overwrite=o)

        for c in cat.channels:
            o = c.overwrites_for(guild.default_role)
            o.read_messages = None
            c.set_permissions(guild.default_role, overwrite=o)

        self.bot.unload_extension('cogs.aprilfools')

    async def _random_color_task(self):
        guild = self.bot.get_guild(217677285442977792)
        if not guild:
            return

        role = guild.get_role(348208141541834773)
        if not role:
            return

        while True:
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
            color = colors.rgb2lab(colors.check_rgb([x/255 for x in c.to_rgb()]))
            new_color, _ = colors.closest_color_match(color, color_roles.values())

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

            try:
                await asyncio.sleep(1200)
            except asyncio.CancelledError:
                return


def setup(bot):
    bot.add_cog(AprilFools(bot))

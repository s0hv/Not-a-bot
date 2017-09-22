import json
import os

import discord
from colormath.color_conversions import convert_color
from colormath.color_objects import LabColor, sRGBColor
from colormath.color_diff import delta_e_cie2000
from colour import Color as Colour

from bot.bot import command
from cogs.cog import Cog
from utils.utilities import split_string
import logging
from bot.globals import Perms

logger = logging.getLogger('debug')


class Color:
    def __init__(self, role_id, name, value, server_id, lab):
        self.role_id = role_id
        self.name = name
        self.value = value
        if isinstance(lab, LabColor):
            self.lab = lab
        else:
            self.lab = LabColor(*lab)
        self.server_id = server_id

    def __str__(self):
        return self.name


class Colors(Cog):

    def __init__(self, bot):
        super().__init__(bot)
        self._colors = {}
        self._cache_colors()

        with open(os.path.join(os.getcwd(), 'data', 'color_names.json'), 'r', encoding='utf-8') as f:
            self._color_names = json.load(f)

    def _cache_colors(self):
        session = self.bot.get_session
        sql = 'SELECT colors.id, colors.name, colors.value, roles.server, colors.lab_l, colors.lab_a, colors.lab_b FROM ' \
              'colors LEFT OUTER JOIN roles on roles.id=colors.id'

        rows = session.execute(sql).fetchall()
        for row in rows:
            if not self.bot.get_server(str(row['server'])):
                continue

            self._add_color(**row)

    def _add_color(self, server, id, name, value, lab_l, lab_a, lab_b):
        try:
            server_id = str(int(server))
        except:
            server_id = server.id

        color = Color(id, name, value, server_id, (lab_l, lab_a, lab_b))

        if server_id in self._colors:
            self._colors[server_id][id] = color
        else:
            self._colors[server_id] = {id: color}

        return color

    def get_color(self, name, server_id):
        name = name.lower()
        return discord.utils.find(lambda n: str(n[1]).lower() == name,
                                  self._colors.get(server_id, {}).items())

    def match_color(self, color):
        color = color.lower()
        if color in self._color_names:
            rgb = self._color_names[color]['rgb']
        else:
            try:
                rgb = Colour(color).rgb
            except:
                return

        return rgb

    def closest_match(self, color, server):
        colors = self._colors.get(server.id)
        if not colors:
            return

        rgb = self.match_color(color)
        if not rgb:
            return

        color = sRGBColor(*rgb, is_upscaled=True)
        color = convert_color(color, LabColor)
        closest_match = None
        similarity = 0
        for c in colors.values():
            d = 100 - delta_e_cie2000(c.lab, color)
            if d > similarity:
                similarity = d
                closest_match = c

        return closest_match, similarity

    @command(pass_context=True, no_pm=True)
    async def color(self, ctx, *color):
        if not color:
            # TODO say users current color
            pass

        server = ctx.message.server
        if not self._colors.get(server.id, None):
            return await self.bot.say("This server doesn't have any color roles")

        color = ' '.join(color)
        color_ = self.get_color(color, server.id)
        if not color_:
            match = self.closest_match(color, server)
            if not match:
                return await self.bot.say('Could not find color %s' % color)

            color_, similarity = match
            return await self.bot.say('Could not find color {0}. Color closest to '
                                      '{0} is {1} with {2:.02f}% similarity'.format(color, color_.name, similarity))

        roles = [r.id for r in ctx.message.author.roles]
        id, color = color_
        if id in roles:
            return await self.bot.say('You already have that color')

        ids = self._colors.get(server.id).keys()
        roles = [r for r in roles if r not in ids]
        roles.append(str(id))
        print(roles)
        try:
            await self.bot.add_roles(ctx.message.author, *roles)
        except discord.DiscordException as e:
            return await self.bot.say('Failed to add color because of an error\n\n```\n%s```' % e)

        await self.bot.say('Color set to %s' % color.name)

    @command(pass_context=True, no_pm=True)
    async def colors(self, ctx):
        server = ctx.message.server
        colors = self._colors.get(server.id)
        if not colors:
            return await self.bot.say("This server doesn't have any color roles")

        s = ''
        le = len(colors) - 1
        for idx, color in enumerate(colors.values()):
            s += str(color)

            if le != idx:
                s += ', '

        s = split_string(s, maxlen=2000, splitter=', ')
        for msg in s:
            await self.bot.say(msg)

    @command(pass_context=True, no_pm=True, perms=Perms.MANAGE_ROLES)
    async def add_color(self, ctx, color: str, *name):
        if not name:
            name = color

        rgb = self.match_color(color)

        server = ctx.message.server
        color = sRGBColor(*rgb, is_upscaled=True)
        value = int(color.get_rgb_hex()[1:], 16)
        r = discord.utils.find(lambda i: i[1].value == value, self._colors.get(server.id, {}).items())
        if r:
            k, r = r
            if self.bot.get_role(server, r.id):
                return await self.bot.say('This color already exists')
            else:
                self._colors.pop(k, None)

        color = convert_color(color, LabColor)

        perms = discord.Permissions(server.default_role.permissions.value)
        try:
            color_role = await self.bot.create_role(server, name=name, perms=perms,
                                                    color=discord.Colour(value))
        except discord.DiscordException as e:
            return await self.bot.say('Failed to add color because of an error\n```%s```' % e)
        except:
            logger.exception('Failed to create color role')
            return await self.bot.say('Failed to add color because of an error')

        color_ = Color(color_role.id, name, value, server.id, color)
        if self._colors.get(server.id):
            role = self.bot.get_role(server, self._colors[server.id].keys()[0])

            if role:
                try:
                    await self.bot.move_role(server, color_role, max(1, role.position))
                except:
                    pass

            self._colors[server.id][color_role.id] = color_
        else:
            self._colors[server.id] = {color_role.id: color_}

def setup(bot):
    bot.add_cog(Colors(bot))

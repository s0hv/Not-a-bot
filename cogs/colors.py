import json
import os

import discord
from colormath.color_conversions import convert_color
from colormath.color_objects import LabColor, sRGBColor
from colormath.color_diff import delta_e_cie2000
from colour import Color as Colour
from math import ceil

from bot.bot import command
from discord.ext.commands import cooldown
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

    def _add_color2db(self, color):
        self.bot.dbutils.add_roles(color.server_id, color.role_id)
        sql = 'INSERT INTO `colors` (`id`, `name`, `value`, `lab_l`, `lab_a`, `lab_b`) VALUES ' \
              '(:id, :name, :value, :lab_l, :lab_a, :lab_b)'
        session = self.bot.get_session
        try:
            session.execute(sql, params={'id': color.role_id,
                                         'name': color.name,
                                         'value': color.value,
                                         'lab_l': color.lab.lab_l,
                                         'lab_a': color.lab.lab_a,
                                         'lab_b': color.lab.lab_b})
            session.commit()
        except:
            logger.exception('Failed to add color to db')
            return False
        else:
            return True

    def _add_color(self, server, id, name, value, lab_l, lab_a, lab_b):
        try:
            server_id = str(int(server))
        except:
            server_id = server.id
        id = str(id)
        color = Color(id, name, value, server_id, (lab_l, lab_a, lab_b))

        if server_id in self._colors:
            self._colors[server_id][id] = color
        else:
            self._colors[server_id] = {id: color}

        return color

    def _delete_color(self, server_id, role_id):
        try:
            del self._colors[server_id][role_id]
        except KeyError:
            pass

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

    async def server_role_delete(self, role):
        self._delete_color(role.server.id, role.id)

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 2)
    async def color(self, ctx, *color):
        server = ctx.message.server
        colors = self._colors.get(server.id, None)
        if not colors:
            return await self.bot.say("This server doesn't have any color roles")

        ids = set(colors.keys())
        roles = set([r.id for r in ctx.message.author.roles])
        if not color:
            user_colors = roles.intersection(ids)
            if not user_colors:
                return await self.bot.say("You don't have a color role")

            if len(user_colors) > 1:
                return await self.bot.say('You have multiple color roles <:gappyThinking:358523789170180097>')

            else:
                name = colors.get(user_colors.pop())
                return await self.bot.say('Your current color is %s. Use !colors to see a list of colors in this server. To also see the role colors use !show_colors' % name)

        color = ' '.join(color)
        color_ = self.get_color(color, server.id)
        if not color_:
            match = self.closest_match(color, server)
            if not match:
                return await self.bot.say('Could not find color %s' % color)

            color_, similarity = match
            return await self.bot.say('Could not find color {0}. Color closest to '
                                      '{0} is {1} with {2:.02f}% similarity'.format(color, color_.name, similarity))

        id, color = color_
        if id in roles:
            return await self.bot.say('You already have that color')

        roles = roles.difference(ids)
        roles.add(id)
        try:
            await self.bot.replace_roles(ctx.message.author, *roles)
        except discord.DiscordException as e:
            return await self.bot.say('Failed to set color because of an error\n\n```\n%s```' % e)

        await self.bot.say('Color set to %s' % color.name)

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 1)
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
    @cooldown(1, 3)
    async def add_color(self, ctx, color: str, *name):
        if not name:
            name = color
        else:
            name = ' '.join(name)

        rgb = self.match_color(color)

        server = ctx.message.server
        color = sRGBColor(*rgb)
        print(color.get_rgb_hex())
        value = int(color.get_rgb_hex()[1:], 16)
        r = discord.utils.find(lambda i: i[1].value == value, self._colors.get(server.id, {}).items())
        if r:
            k, r = r
            if self.bot.get_role(server, r.role_id):
                return await self.bot.say('This color already exists')
            else:
                self._colors.pop(k, None)

        color = convert_color(color, LabColor)

        default_perms = ctx.message.server.default_role.permissions
        try:
            color_role = await self.bot.create_role(server, name=name, permissions=default_perms,
                                                    colour=discord.Colour(value))
        except discord.DiscordException as e:
            return await self.bot.say('Failed to add color because of an error\n```%s```' % e)
        except:
            logger.exception('Failed to create color role')
            return await self.bot.say('Failed to add color because of an error')

        color_ = Color(color_role.id, name, value, server.id, color)
        success = self._add_color2db(color_)
        if not success:
            return await self.bot.say('Failed to add color')

        if self._colors.get(server.id):
            role = self.bot.get_role(server, list(self._colors[server.id].keys())[0])

            if role:
                try:
                    await self.bot.move_role(server, color_role, max(1, role.position))
                except:
                    pass

            self._colors[server.id][color_role.id] = color_
        else:
            self._colors[server.id] = {color_role.id: color_}

    @command(pass_context=True, no_pm=True, perms=Perms.MANAGE_ROLES, aliases=['del_color'])
    @cooldown(1, 3)
    async def delete_color(self, ctx, *, name):
        server = ctx.message.server
        color = self.get_color(name, server.id)
        if not color:
            return await self.bot.say("Couldn't find color %s" % name)

        role = self.bot.get_role(server, color.role_id)
        if not role:
            self.bot.dbutils.delete_role(color.role_id, server.id)
            self._delete_color(server.id, color.role_id)
            await self.bot.say('Removed color %s' % color)
            return

        try:
            await self.bot.delete_role(role)
        except discord.DiscordException as e:
            return await self.bot.say('Failed to remove color because of an error\n```%s```' % e)
        except:
            return await self.bot.say('Failed to remove color because of an error')

        await self.bot.say('Removed color %s' % color)

    @command(pass_context=True, no_pm=True)
    @cooldown(1, 4)
    async def show_colors(self, ctx):
        server = ctx.message.server
        colors = self._colors.get(server.id, None)
        if not colors:
            return await self.bot.say("This server doesn't have any colors")

        embed_count = ceil(len(colors)/50)

        switch = 0
        current_embed = 0
        fields = 0
        embeds = [discord.Embed() for i in range(embed_count)]
        for color in colors.values():
            if switch == 0:
                field_title = str(color)
                field_value = '<@&%s>' % color.role_id
                switch = 1
            elif switch == 1:
                field_title += ' --- ' + str(color)
                field_value += '    <@&%s>' % color.role_id
                switch = 0
                embeds[current_embed].add_field(name=field_title, value=field_value)
                fields += 1

                if fields == 25:
                    current_embed += 1

        if switch == 1:
            embeds[current_embed].add_field(name=field_title, value=field_value)

        chn = ctx.message.channel
        for embed in embeds:
            await self.bot.send_message(chn, embed=embed)


def setup(bot):
    bot.add_cog(Colors(bot))

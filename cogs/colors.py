import json
import os

import discord
from colormath.color_conversions import convert_color
from colormath.color_objects import LabColor, sRGBColor
from colormath.color_diff import delta_e_cie2000
from colour import Color as Colour
from math import ceil

from bot.bot import command
from discord.ext.commands import cooldown, BucketType
from cogs.cog import Cog
from utils.utilities import split_string, get_role, y_n_check, y_check
import logging
from bot.globals import Perms
logger = logging.getLogger('debug')
from numpy.random import choice


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
        self.bot.colors = self._colors
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
            session.rollback()
            logger.exception('Failed to add color to db')
            return False
        else:
            return True

    def _add_color(self, server, id, name, value, lab_l, lab_a, lab_b):
        try:
            server_id = str(int(server))
        except:
            server_id = server.id
        id_ = str(id)
        color = Color(id_, name, value, server_id, (lab_l, lab_a, lab_b))

        if server_id in self._colors:
            self._colors[server_id][id_] = color
        else:
            self._colors[server_id] = {id_: color}

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

    def search_color_(self, name):
        name = name.lower()
        names = list(self._color_names.keys())
        if name in names:
            return name, self._color_names[name]

        else:
            matches = [n for n in names if name in n]
            if not matches:
                return
            if len(matches) == 1:
                return matches[0], self._color_names[matches[0]]

            return matches

    def match_color(self, color):
        color = color.lower()
        if color in self._color_names:
            rgb = self._color_names[color]['rgb']
            rgb = tuple(map(lambda c: c/255.0, rgb))
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

    async def _add_colors_from_roles(self, roles, ctx):
        channel = ctx.message.channel
        server = channel.server
        colors = self._colors.get(server.id)
        if colors is None:
            colors = {}
            self._colors[server.id] = colors

        for role in roles:
            color = role.color
            if color.value == 0:
                await self.bot.send_message(channel, 'Role {0.name} has no color'.format(role))
                continue

            r = discord.utils.find(lambda c: c.value == color.value, colors.values())
            if r:
                await self.bot.send_message(channel, 'Color {0.name} already exists'.format(role))
                continue

            lab = convert_color(sRGBColor(*color.to_tuple(), is_upscaled=True), LabColor)
            color = Color(role.id, role.name, color.value, server.id, lab)
            if self._add_color2db(color):
                await self.bot.send_message(channel, 'Color {} created'.format(role))
                colors[role.id] = color
            else:
                await self.bot.send_message(channel, 'Failed to create color {0.name}'.format(role))

    async def on_server_role_delete(self, role):
        self._colors.get(role.server.id, {}).pop(role.id, None)

    @command(pass_context=True, no_pm=True, aliases=['colour'])
    @cooldown(1, 2, type=BucketType.user)
    async def color(self, ctx, *color):
        """Set you color on the server.
        To see the colors on this server use {prefix}colors or {prefix}show_colors"""
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
                return await self.bot.say('Your current color is {0}. Use {1}colors to see a list of colors in this server. To also see the role colors use {1}show_colors'.format(name, ctx.prefix))

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

    @command(pass_context=True, no_pm=True, aliases=['colours'])
    @cooldown(1, 2, type=BucketType.server)
    async def colors(self, ctx):
        """Shows the colors on this server"""
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

    @command(aliases=['search_colour'])
    @cooldown(1, 3, BucketType.user)
    async def search_color(self, *, name):
        """Search a color using a name and return it's hex value if found"""
        matches = self.search_color_(name)
        if matches is None:
            return await self.bot.say('No colors found with {}'.format(name))

        if isinstance(matches, list):
            total = len(matches)
            matches = choice(matches, 10)
            return await self.bot.say('Found matches a total of {0} matches\n{1}\n{2} of {0}'.format(total, '\n'.join(matches), len(matches)))

        name, match = matches
        await self.bot.say('Found color {0} {1[hex]}'.format(name, match))

    @command(pass_context=True, no_pm=True, perms=Perms.MANAGE_ROLES, aliases=['add_colour'])
    @cooldown(1, 3, type=BucketType.server)
    async def add_color(self, ctx, color: str, *name):
        """Add a new color to the server"""
        if not name:
            name = color
        else:
            name = ' '.join(name)

        rgb = self.match_color(color)
        if not rgb:
            return await self.bot.say('Color {} not found'.format(color))

        server = ctx.message.server
        color = sRGBColor(*rgb)
        value = int(color.get_rgb_hex()[1:], 16)
        r = discord.utils.find(lambda i: i[1].value == value, self._colors.get(server.id, {}).items())
        if r:
            k, r = r
            if self.bot.get_role(server, r.role_id):
                return await self.bot.say('This color already exists')
            else:
                self._colors.get(server.id, {}).pop(k, None)

        color = convert_color(color, LabColor)

        default_perms = ctx.message.server.default_role.permissions
        try:
            d_color = discord.Colour(value)
            color_role = await self.bot.create_role(server, name=name, permissions=default_perms,
                                                    colour=d_color)
        except discord.DiscordException as e:
            logger.exception('server {0.id} rolename: {1} perms: {2} color: {3} {4}'.format(server, name, default_perms.value, str(rgb), value))
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

        await self.bot.say('Added color {} {}'.format(name, str(d_color)))

    @command(pass_context=True, no_pm=True, perms=Perms.MANAGE_ROLES,
             aliases=['colors_from_roles'])
    @cooldown(1, 3, type=BucketType.server)
    async def add_colors_from_roles(self, ctx, *, roles):
        """Turn existing role(s) to colors.
        Usage:
            {prefix}{name} 326726982656196629 Red @Blue
        Works with role mentions, role ids and name matching"""
        if not roles:
            return await self.bot.say('Give some roles to turn to server colors')

        roles = roles.split(' ')
        server = ctx.message.server
        success = []
        failed = []
        for role in roles:
            r = get_role(role, server.roles, name_matching=True)
            if r:
                success.append(r)
            else:
                failed.append(role)

        s = ''
        if success:
            s += 'Adding roles {}\n'.format(', '.join(['`%s`' % r.name for r in success]))

        if failed:
            s += 'Failed to find roles {}'.format(', '.join(['`%s`' % r for r in failed]))

        for s in split_string(s, splitter=', '):
            await self.bot.say(s)

        await self.bot.say('Do you want to continue?', delete_after=20)
        channel, author = ctx.message.channel, ctx.message.author
        msg = await self.bot.wait_for_message(timeout=20, author=author, channel=channel, check=y_n_check)
        if msg is None or not y_check(msg.content):
            return await self.bot.say('Cancelling', delete_after=20)

        await self._add_colors_from_roles(success, ctx)

    @command(pass_context=True, no_pm=True, perms=Perms.MANAGE_ROLES,
             aliases=['del_color', 'remove_color', 'delete_colour', 'remove_colour'])
    @cooldown(1, 3, type=BucketType.server)
    async def delete_color(self, ctx, *, name):
        """Delete a color from the server"""
        server = ctx.message.server
        color = self.get_color(name, server.id)
        if not color:
            return await self.bot.say("Couldn't find color %s" % name)

        role_id = color[0]
        role = self.bot.get_role(server, role_id)
        if not role:
            self.bot.dbutils.delete_role(role_id, server.id)
            self._delete_color(server.id, role_id)
            await self.bot.say('Removed color %s' % color[1])
            return

        try:
            await self.bot.delete_role(role)
            self.bot.dbutils.delete_role(role_id, server.id)
            self._delete_color(server.id, role_id)
        except discord.DiscordException as e:
            return await self.bot.say('Failed to remove color because of an error\n```%s```' % e)
        except:
            return await self.bot.say('Failed to remove color because of an error')

        await self.bot.say('Removed color %s' % color[1])

    @command(pass_context=True, no_pm=True, aliases=['show_colours'])
    @cooldown(1, 4, type=BucketType.server)
    async def show_colors(self, ctx):
        """Show current colors on the server in an embed.
        This allows you to see how they look"""
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

    @command(pass_context=True, owner_only=True)
    async def color_uncolored(self, ctx):
        """Color users that don't have a color role"""
        server = ctx.message.server
        color_ids = list(self._colors.get(server.id, {}).keys())
        if not self._colors:
            return await self.bot.say('No colors')

        await self.bot.request_offline_members(server)
        roles = server.roles
        colored = 0
        duplicate_colors = 0
        for member in list(server.members):
            m_roles = member.roles
            found = list(filter(lambda r: r.id in color_ids, m_roles))
            if not found:
                color = choice(color_ids)
                role = list(filter(lambda r: r.id == color, roles))
                try:
                    await self.bot.add_roles(member, *role)
                    colored += 1
                except:
                    pass
            elif len(found) > 1:
                try:
                    await self.bot.replace_role(member, color_ids, (found[0],))
                    duplicate_colors += 1
                except:
                    pass

        await self.bot.say('Colored %s user(s) without color role\n'
                           'Removed duplicate colors from %s user(s)' % (colored, duplicate_colors))


def setup(bot):
    bot.add_cog(Colors(bot))

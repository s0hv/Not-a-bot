import asyncio
import json
import logging
import os
from math import ceil

import discord
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000
from colormath.color_objects import LabColor, sRGBColor
from colour import Color as Colour
from discord.errors import InvalidArgument
from discord.ext.commands import cooldown, BucketType
from numpy.random import choice
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command
from bot.globals import Perms
from cogs.cog import Cog
from utils.utilities import split_string, get_role, y_n_check, y_check, \
    Snowflake

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class Color:
    def __init__(self, role_id, name, value, guild_id, lab):
        self.role_id = role_id
        self.name = name
        self.value = value
        if isinstance(lab, LabColor):
            self.lab = lab
        else:
            self.lab = LabColor(*lab)
        self.guild_id = guild_id

    def __str__(self):
        return self.name


class Colors(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._colors = {}
        self.bot.colors = self._colors
        asyncio.run_coroutine_threadsafe(self._cache_colors(), self.bot.loop)

        with open(os.path.join(os.getcwd(), 'data', 'color_names.json'), 'r', encoding='utf-8') as f:
            self._color_names = json.load(f)

    async def _cache_colors(self):
        sql = 'SELECT colors.id, colors.name, colors.value, roles.guild, colors.lab_l, colors.lab_a, colors.lab_b FROM ' \
              'colors LEFT OUTER JOIN roles on roles.id=colors.id'

        try:
            rows = (await self.bot.dbutil.execute(sql)).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to cache colors')
            return

        for row in rows:
            if not self.bot.get_guild(row['guild']):
                continue

            await self._add_color(**row)

    async def _add_color2db(self, color, update=False):
        await self.bot.dbutils.add_roles(color.guild_id, color.role_id)
        sql = 'INSERT INTO `colors` (`id`, `name`, `value`, `lab_l`, `lab_a`, `lab_b`) VALUES ' \
              '(:id, :name, :value, :lab_l, :lab_a, :lab_b)'
        if update:
            sql += ' ON DUPLICATE KEY UPDATE name=:name, value=:value, lab_l=:lab_l, lab_a=:lab_a, lab_b=:lab_b'

        try:
            await self.bot.dbutil.execute(sql, params={'id': color.role_id,
                                                       'name': color.name,
                                                       'value': color.value,
                                                       'lab_l': color.lab.lab_l,
                                                       'lab_a': color.lab.lab_a,
                                                       'lab_b': color.lab.lab_b},
                                          commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add color to db')
            return False
        else:
            return True

    @staticmethod
    def check_rgb(rgb, to_role=True):
        """

        :param rgb: rgb tuple
        :param to_role: whether to convert the value to the one that shows on discord (False) or to the one you want to show (True)
        :return: new rgb tuple if change was needed
        """
        if max(rgb) == 0:
            if to_role:
                # Because #000000 is reserved for another color this must be used for black
                rgb = (0, 0, 1/255)
            else:
                # color #000000 uses the default color on discord which is the following color
                rgb = (185/255, 187/255, 190/255)

        return rgb

    def rgb2lab(self, rgb, to_role=True):
        rgb = self.check_rgb(rgb, to_role=to_role)
        return convert_color(sRGBColor(*rgb), LabColor)

    async def _update_color(self, color, role, to_role=True):
        r, g, b = role.color.to_rgb()
        lab = self.rgb2lab((r/255, g/255, b/255), to_role=to_role)
        color.value = role.color.value
        color.lab = lab
        await self._add_color2db(color, update=True)
        return color

    async def _add_color(self, guild, id, name, value, lab_l, lab_a, lab_b):
        if not isinstance(guild, int):
            guild_id = guild.id

        else:
            guild_id = guild
            guild = self.bot.get_guild(guild_id)

        role = self.bot.get_role(id, guild)
        if role is None:
            return await self._delete_color(guild_id, id)

        color = Color(id, name, value, guild_id, (lab_l, lab_a, lab_b))

        if guild_id in self._colors:
            self._colors[guild_id][id] = color
        else:
            self._colors[guild_id] = {id: color}

        if role.color.value != value:
            await self._update_color(color, role)

        return color

    async def _delete_color(self, guild_id, role_id):
        try:
            color = self._colors[guild_id].pop(role_id)
            logger.debug(f'Deleting color {color.name} with value {color.value} from guild {guild_id}')
        except KeyError:
            logger.debug(f'Deleting color {role_id} from guild {guild_id}')

        await self.bot.dbutils.delete_role(role_id, guild_id)

    def get_color(self, name, guild_id):
        name = name.lower()
        return discord.utils.find(lambda n: str(n[1]).lower() == name,
                                  self._colors.get(guild_id, {}).items())

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

        return self.check_rgb(rgb)

    def closest_match(self, color, guild):
        colors = self._colors.get(guild.id)
        if not colors:
            return

        rgb = self.match_color(color)
        if not rgb:
            return

        color = self.rgb2lab(rgb)
        closest_match = None
        similarity = 0
        for c in colors.values():
            d = 100 - delta_e_cie2000(c.lab, color)
            if d > similarity:
                similarity = d
                closest_match = c

        return closest_match, similarity

    async def on_guild_role_delete(self, role):
        await self._delete_color(role.guild.id, role.id)

    async def on_guild_role_update(self, before, after):
        if before.color.value != after.color.value:
            color = self._colors.get(before.guild.id, {}).get(before.id)
            if not color:
                return

            if before.name != after.name and before.name == color.name:
                color.name = after.name

            await self._update_color(color, before, to_role=False)

    async def _add_colors_from_roles(self, roles, ctx):
        guild = ctx.guild
        colors = self._colors.get(guild.id)
        if colors is None:
            colors = {}
            self._colors[guild.id] = colors

        for role in roles:
            color = role.color
            if color.value == 0:
                await ctx.send('Role {0.name} has no color'.format(role))
                continue

            r = discord.utils.find(lambda c: c.value == color.value, colors.values())
            if r:
                await ctx.send('Color {0.name} already exists'.format(role))
                continue

            lab = self.rgb2lab(color.to_rgb())
            color = Color(role.id, role.name, color.value, guild.id, lab)
            if await self._add_color2db(color):
                await ctx.send('Color {} created'.format(role))
                colors[role.id] = color
            else:
                await ctx.send('Failed to create color {0.name}'.format(role))

    @command(no_pm=True, aliases=['colour'])
    @cooldown(1, 2, type=BucketType.user)
    async def color(self, ctx, *color):
        """Set you color on the server.
        To see the colors on this server use {prefix}colors or {prefix}show_colors"""
        guild = ctx.guild
        colors = self._colors.get(guild.id, None)
        if not colors:
            return await ctx.send("This guild doesn't have any color roles")

        ids = set(colors.keys())
        roles = set([r.id for r in ctx.author.roles])
        if not color:
            user_colors = roles.intersection(ids)
            if not user_colors:
                return await ctx.send("You don't have a color role")

            if len(user_colors) > 1:
                return await ctx.send('You have multiple color roles <:gappyThinking:358523789170180097>')

            else:
                name = colors.get(user_colors.pop())
                return await ctx.send('Your current color is {0}. Use {1}colors to see a list of colors in this guild. To also see the role colors use {1}show_colors'.format(name, ctx.prefix))

        color = ' '.join(color)
        color_ = self.get_color(color, guild.id)
        if not color_:
            match = self.closest_match(color, guild)
            if not match:
                return await ctx.send('Could not find color %s' % color)

            color_, similarity = match
            return await ctx.send('Could not find color {0}. Color closest to '
                                  '{0} is {1} with {2:.02f}% similarity'.format(color, color_.name, similarity))

        id, color = color_
        if id in roles and len(roles) <= 1:
            return await ctx.send('You already have that color')

        roles = roles.difference(ids)
        roles.add(id)
        try:
            await ctx.author.edit(roles=[Snowflake(r) for r in roles])
        except discord.DiscordException as e:
            return await ctx.send('Failed to set color because of an error\n\n```\n%s```' % e)

        await ctx.send('Color set to %s' % color.name)

    @command(no_pm=True, aliases=['colours'])
    @cooldown(1, 2, type=BucketType.guild)
    async def colors(self, ctx):
        """Shows the colors on this guild"""
        guild = ctx.guild
        colors = self._colors.get(guild.id)
        if not colors:
            return await ctx.send("This guild doesn't have any color roles")

        s = ''
        le = len(colors) - 1
        for idx, color in enumerate(colors.values()):
            s += str(color)

            if le != idx:
                s += ', '

        s = split_string(s, maxlen=2000, splitter=', ')
        for msg in s:
            await ctx.send(msg)

    @command(aliases=['search_colour'])
    @cooldown(1, 3, BucketType.user)
    async def search_color(self, ctx, *, name):
        """Search a color using a name and return it's hex value if found"""
        matches = self.search_color_(name)
        if matches is None:
            return await ctx.send('No colors found with {}'.format(name))

        if isinstance(matches, list):
            total = len(matches)
            matches = choice(matches, 10)
            return await ctx.send('Found matches a total of {0} matches\n{1}\n{2} of {0}'.format(total, '\n'.join(matches), len(matches)))

        name, match = matches
        await ctx.send('Found color {0} {1[hex]}'.format(name, match))

    @command(no_pm=True, required_perms=Perms.MANAGE_ROLES, aliases=['add_colour'])
    @cooldown(1, 3, type=BucketType.guild)
    async def add_color(self, ctx, color: str, *name):
        """Add a new color to the guild"""
        if not name:
            name = color
        else:
            name = ' '.join(name)

        rgb = self.match_color(color)
        if not rgb:
            return await ctx.send(f'Color {color} not found')

        guild = ctx.guild
        lab = self.rgb2lab(rgb)
        color = convert_color(lab, sRGBColor)
        value = int(color.get_rgb_hex()[1:], 16)
        r = discord.utils.find(lambda i: i[1].value == value, self._colors.get(guild.id, {}).items())
        if r:
            k, r = r
            if self.bot.get_role(r.role_id, guild):
                return await ctx.send('This color already exists')
            else:
                self._colors.get(guild.id, {}).pop(k, None)

        color = lab

        default_perms = guild.default_role.permissions
        try:
            d_color = discord.Colour(value)
            color_role = await guild.create_role(name=name, permissions=default_perms,
                                                 colour=d_color, reason=f'{ctx.author} created a new color')
        except discord.DiscordException as e:
            logger.exception('guild {0.id} rolename: {1} perms: {2} color: {3} {4}'.format(guild, name, default_perms.value, str(rgb), value))
            return await ctx.send('Failed to add color because of an error\n```%s```' % e)
        except:
            logger.exception('Failed to create color role')
            return await ctx.send('Failed to add color because of an error')

        color_ = Color(color_role.id, name, value, guild.id, color)
        success = await self._add_color2db(color_)
        if not success:
            return await ctx.send('Failed to add color')

        if self._colors.get(guild.id):
            role = self.bot.get_role(list(self._colors[guild.id].keys())[0],
                                     guild)
            if role:
                try:
                    await color_role.edit(position=max(1, role.position))
                except:
                    logger.exception('Failed to move color to position')

            self._colors[guild.id][color_role.id] = color_
        else:
            self._colors[guild.id] = {color_role.id: color_}

        await ctx.send('Added color {} {}'.format(name, str(d_color)))

    @command(no_pm=True, required_perms=Perms.MANAGE_ROLES, aliases=['colors_from_roles'])
    @cooldown(1, 3, type=BucketType.guild)
    async def add_colors_from_roles(self, ctx, *, roles):
        """Turn existing role(s) to colors.
        Usage:
            {prefix}{name} 326726982656196629 Red @Blue
        Works with role mentions, role ids and name matching"""
        if not roles:
            return await ctx.send('Give some roles to turn to guild colors')

        roles = roles.split(' ')
        guild = ctx.guild
        success = []
        failed = []
        for role in roles:
            r = get_role(role, guild.roles, name_matching=True)
            if r:
                success.append(r)
            else:
                failed.append(role)

        s = ''
        if success:
            s += 'Adding roles {}\n'.format(', '.join(['`%s`' % r.name for r in success]))

        if failed:
            s += 'Failed to find roles {}'.format(', '.join([f'`{r}`' for r in failed]))

        for s in split_string(s, splitter=', '):
            await ctx.send(s)

        await ctx.send('Do you want to continue?', delete_after=60)
        channel, author = ctx.channel, ctx.author

        def check(msg):
            if msg.channel.id != channel.id:
                return False
            if msg.author.id != author.id:
                return False
            return y_n_check(msg)
        try:
            msg = await self.bot.wait_for('message', timeout=60, check=check)
        except asyncio.TimeoutError:
            msg = None
        if msg is None or not y_check(msg.content):
            return await ctx.send('Cancelling', delete_after=60)

        await self._add_colors_from_roles(success, ctx)

    @command(no_pm=True, required_perms=Perms.MANAGE_ROLES,
             aliases=['del_color', 'remove_color', 'delete_colour', 'remove_colour'])
    @cooldown(1, 3, type=BucketType.guild)
    async def delete_color(self, ctx, *, name):
        """Delete a color from the server"""
        guild = ctx.guild
        color = self.get_color(name, guild.id)
        if not color:
            return await ctx.send(f"Couldn't find color {name}")

        role_id = color[0]
        role = self.bot.get_role(role_id, guild)
        if not role:
            await self._delete_color(guild.id, role_id)
            await ctx.send(f'Removed color {color[1]}')
            return

        try:
            await role.delete(reason=f'{ctx.author} deleted this color')
            await self._delete_color(guild.id, role_id)
        except discord.DiscordException as e:
            return await ctx.send(f'Failed to remove color because of an error\n```{e}```')
        except:
            logger.exception('Failed to remove color')
            return await ctx.send('Failed to remove color because of an error')

        await ctx.send(f'Removed color {color[1]}')

    @command(no_pm=True, aliases=['show_colours'])
    @cooldown(1, 4, type=BucketType.guild)
    async def show_colors(self, ctx):
        """Show current colors on the guild in an embed.
        This allows you to see how they look"""
        guild = ctx.guild
        colors = self._colors.get(guild.id, None)
        if not colors:
            return await ctx.send("This guild doesn't have any colors")

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

        for embed in embeds:
            await ctx.send(embed=embed)

    @command(owner_only=True)
    async def color_uncolored(self, ctx):
        """Color users that don't have a color role"""
        guild = ctx.guild
        color_ids = list(self._colors.get(guild.id, {}).keys())
        if not color_ids:
            return await ctx.send('No colors')

        try:
            await self.bot.request_offline_members(guild)
        except InvalidArgument:
            pass
        roles = guild.roles
        colored = 0
        duplicate_colors = 0
        for member in list(guild.members):
            m_roles = member.roles
            found = [r for r in m_roles if r.id in color_ids]
            if not found:
                color = choice(color_ids)
                role = filter(lambda r: r.id == color, roles)
                try:
                    await member.add_roles(next(role))
                    colored += 1
                except discord.errors.Forbidden:
                    return
                except discord.HTTPException:
                    continue

            elif len(found) > 1:
                try:
                    removed_roles = color_ids.copy()
                    removed_roles.remove(found[0].id)
                    await member.remove_roles(*map(Snowflake, removed_roles), reason='Removing duplicate colors', atomic=False)
                    duplicate_colors += 1
                except:
                    logger.exception('failed to remove duplicate colors')

        await ctx.send('Colored %s user(s) without color role\n'
                       'Removed duplicate colors from %s user(s)' % (colored, duplicate_colors))


def setup(bot):
    bot.add_cog(Colors(bot))

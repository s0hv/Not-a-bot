import asyncio
import json
import logging
import os
import re
import shlex
from io import BytesIO
from math import ceil, sqrt

import discord
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from asyncpg.exceptions import PostgresError
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000
from colormath.color_objects import LabColor, sRGBColor
from colour import Color as Colour
from discord.errors import InvalidArgument
from discord.ext import commands
from discord.ext.commands import (BucketType, bot_has_permissions, BadArgument,
                                  clean_content)
from numpy.random import choice

from bot.bot import command, has_permissions, cooldown, group
from bot.globals import WORKING_DIR
from cogs.cog import Cog
from utils.utilities import (split_string, get_role, y_n_check, y_check,
                             Snowflake, check_botperm)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')

rgb_splitter = re.compile(r'^(\d{1,3})([, ])(\d{1,3})\2(\d{1,3})$')


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

    # https://stackoverflow.com/a/2262152/6046713
    def to_rgb(self):
        return (self.value >> 16) & 255, (self.value >> 8) & 255, self.value & 255

    @property
    def rgb(self):
        return self.to_rgb()


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
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
            logger.exception('Failed to cache colors')
            return

        for row in rows:
            if not self.bot.get_guild(row['guild']):
                continue

            await self._add_color(**row)

    async def _add_color2db(self, color, update=False):
        await self.bot.dbutils.add_roles(color.guild_id, color.role_id)
        sql = 'INSERT INTO colors (id, name, "value", lab_l, lab_a, lab_b) VALUES ' \
              '($1, $2, $3, $4, $5, $6)'
        if update:
            sql += ' ON CONFLICT (id) DO UPDATE SET name=$2, value=$3, lab_l=$4, lab_a=$5, lab_b=$6'

        # Determines if we executemany or not
        many = False
        if isinstance(color, list):
            args = [
                (
                    c.role_id,
                    c.name,
                    c.value,
                    c.lab.lab_l,
                    c.lab.lab_a,
                    c.lab.lab_b
                ) for c in color
            ]
            many = True

        else:
            args = (
                color.role_id,
                color.name,
                color.value,
                color.lab.lab_l,
                color.lab.lab_a,
                color.lab.lab_b
            )

        try:
            await self.bot.dbutil.execute(sql, args, insertmany=many)
        except PostgresError:
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
                # #b9bbbe
                rgb = (185/255, 187/255, 190/255)

        return rgb

    def rgb2lab(self, rgb, to_role=True):
        """
        Args:
            rgb (list or tuple):
                not upscaled rgb tuple
            to_role (bool or none):
                Bool if check_rgb is used.
                None if skip using check_rgb

        Returns:
            LabColor: lab color
        """
        if to_role is not None:
            rgb = self.check_rgb(rgb, to_role=to_role)
        return convert_color(sRGBColor(*rgb), LabColor)

    async def _update_color(self, color, role, to_role=True, lab: LabColor=None):
        if not lab:
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

        role = guild.get_role(id)
        if role is None:
            return

        color = Color(id, name, value, guild_id, (lab_l, lab_a, lab_b))

        if guild_id in self._colors:
            self._colors[guild_id][id] = color
        else:
            self._colors[guild_id] = {id: color}

        if role.color.value != value:
            await self._update_color(color, role)
        else:
            lab = self.rgb2lab(tuple(map(lambda x: x/255, role.color.to_rgb())))
            if not lab_l==lab.lab_l and lab_a==lab.lab_a and lab_b==lab.lab_b:
                await self._update_color(color, role, lab=lab)

        return color

    async def _delete_color(self, guild_id, role_id):
        try:
            color = self._colors[guild_id].pop(role_id)
            logger.debug(f'Deleting color {color.name} with value {color.value} from guild {guild_id}')
        except KeyError:
            logger.debug(f'Deleting color {role_id} from guild {guild_id} if it existed')

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

    def match_color(self, color, convert2discord=True):
        color = color.lower()
        if color in self._color_names:
            rgb = self._color_names[color]

            if not convert2discord:
                return rgb['hex']

            rgb = rgb['rgb']
            rgb = tuple(map(lambda c: c/255.0, rgb))
        else:
            try:
                rgb = Colour(color)

                if not convert2discord:
                    return rgb.get_hex_l()

                rgb = rgb.rgb
            except:
                return

        return self.check_rgb(rgb)

    @staticmethod
    def closest_color_match(color, colors):
        if isinstance(color, Color):
            lab = color.lab
        else:
            lab = color

        closest_match = None
        similarity = 0
        for c in colors:
            if isinstance(c, Color):
                clab = c.lab
            else:
                clab = c

            d = 100 - delta_e_cie2000(lab, clab)
            if d > similarity:
                similarity = d
                closest_match = c

        similarity = round(similarity, 2)
        return closest_match, similarity

    def closest_match(self, color, guild):
        colors = self._colors.get(guild.id)
        if not colors:
            return

        rgb = self.match_color(color)
        if not rgb:
            return

        color = self.rgb2lab(rgb)
        return self.closest_color_match(color, colors.values())

    @Cog.listener()
    async def on_guild_role_delete(self, role):
        await self._delete_color(role.guild.id, role.id)

    @Cog.listener()
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

            lab = self.rgb2lab(tuple(map(lambda v: v/255, color.to_rgb())))
            color = Color(role.id, role.name, color.value, guild.id, lab)
            if await self._add_color2db(color):
                await ctx.send('Color {} created'.format(role))
                colors[role.id] = color
            else:
                await ctx.send('Failed to create color {0.name}'.format(role))

    @staticmethod
    def concatenate_colors(images, width=50):
        max_width = width*len(images)
        height = max(map(lambda i: i.height, images))

        empty = Image.new('RGBA', (max_width, height), (0,0,0,0))

        offset = 0
        for im in images:
            empty.paste(im, (offset, 0))
            offset += width

        return empty

    @staticmethod
    def stack_colors(images, height=50, max_width: int=None):
        max_height = height*len(images)
        if not max_width:
            max_width = max(map(lambda i: i.width, images))

        empty = Image.new('RGBA', (max_width, max_height), (0,0,0,0))

        offset = 0
        for im in images:
            empty.paste(im, (0, offset))
            offset += height

        return empty

    @staticmethod
    def split_rgb(s):
        rgb = rgb_splitter.match(s)
        if rgb:
            rgb = rgb.groups()
            rgb = (rgb[0], *rgb[2:])
            return tuple(map(int, rgb))

    @staticmethod
    def rgb2hex(*rgb):
        rgb = map(lambda c: hex(c)[2:].zfill(2), rgb)
        return '#' + ''.join(rgb)

    @staticmethod
    def s_int2hex(i: str):
        """
        Convert integer string to hex
        """
        try:
            if len(i) > 8:
                raise BadArgument(f'Integer color value too long for {i}')

            return '#' + hex(int(i))[2:].zfill(6)
        except (ValueError, TypeError):
            raise BadArgument(f'Failed to convert int to hex ({i})')

    def parse_color_range(self, start, end, steps=10):
        color1 = self.color_from_str(start)
        color2 = self.color_from_str(end)
        colors = Colour(color1).range_to(color2, steps)
        return colors

    def color_from_str(self, color):
        color = color.lower()
        if color in ('transparent', 'none', 'invisible'):
            return 0, 0, 0, 0

        color = color.replace('0x', '#')
        if not color.startswith('#'):
            match = self.match_color(color, False)
            if not match:
                rgb = self.split_rgb(color.strip('()[]{}').replace(', ', ','))
                if not rgb:
                    color = self.s_int2hex(color)
                else:
                    if len(list(filter(lambda i: -1 < i < 256, rgb))) != 3:
                        raise BadArgument(f'Bad rgb values for {rgb}')

                    color = rgb

            else:
                color = match

        elif len(color) > 9:
            raise BadArgument(f'Hex value too long for {color}')

        return color

    @command(aliases=['cr', 'gradient', 'hue'])
    @cooldown(1, 5, BucketType.channel)
    async def color_range(self, ctx, start, end, steps: int=10):
        """
        Makes a color gradient from one color to another in the given steps
        Resulting colors are concatenated horizontally

        Example use
        {prefix}{name} red blue 25
        would give you color range from red to blue in 25 steps
        To see all values accepted as colors check `{prefix}help get_color`
        """
        if steps > 500 or steps < 2:
            raise BadArgument('Maximum amount of steps is 500 and minimum is 2')

        colors = list(self.parse_color_range(start, end, steps))
        size = (50, max(50, min(int(1.25*steps), 300)))
        images = []
        hex_colors = []

        def do_the_thing():
            for color in colors:
                try:
                    im = Image.new('RGB', size, color.get_hex_l())
                    images.append(im)
                    hex_colors.append(color.get_hex_l())
                except (TypeError, ValueError):
                    raise BadArgument(f'Failed to create image using color {color}')

            concat = self.concatenate_colors(images)
            data = BytesIO()
            concat.save(data, 'PNG')
            data.seek(0)
            return data

        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_the_thing)
        if steps > 10:
            s = f'From {colors[0].get_hex_l()} to {colors[-1].get_hex_l()}'
        else:
            s = ' '.join(hex_colors)
        await ctx.send(s, file=discord.File(data, 'colors.png'))

    @command(aliases=['c'], name='get_color')
    @cooldown(1, 5, BucketType.channel)
    async def get_color_image(self, ctx, *, color_list: clean_content):
        """
        Post a picture of a color or multiple colors
        when specifying multiple colors make sure colors that have a space in them
        like light blue are written using quotes like this `red "light blue" green`
        By default colors are concatenated horizontally. For vertical stacking
        use a newline like this
        ```
        {prefix}{name} red green
        blue yellow
        ```
        Which would have red and green on top and blue and yellow on bottom

        Color can be a
        \u200b \u200b \u200b• hex value (`#000000` or `0x000000`)
        \u200b \u200b \u200b• RGB tuple `(0,0,0)`
        \u200b \u200b \u200b• Color name. All compatible names are listed [here](https://en.wikipedia.org/wiki/List_of_colors_(compact))
        \u200b \u200b \u200b• Any of `invisible`, `none`, `transparent` for transparent spot
        """
        color_list = [shlex.split(c) for c in color_list.split('\n')]
        lengths = map(len, color_list)
        if sum(lengths) > 100:
            raise BadArgument('Maximum amount of colors is 100')

        images = []
        hex_colors = []
        size = (50, 50)

        def do_the_thing():
            for colors in color_list:
                ims = []
                for color in colors:
                    color = self.color_from_str(color)
                    try:
                        im = Image.new('RGBA', size, color)
                        ims.append(im)
                        if isinstance(color, tuple):
                            color = self.rgb2hex(*color)
                        hex_colors.append(color)
                    except (TypeError, ValueError):
                        raise BadArgument(f'Failed to create image using color {color}')

                images.append(self.concatenate_colors(ims))

            if len(images) > 1:
                concat = self.stack_colors(images)
            else:
                concat = images[0]

            data = BytesIO()
            concat.save(data, 'PNG')
            data.seek(0)
            return data

        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_the_thing)
        await ctx.send(' '.join(hex_colors), file=discord.File(data, 'colors.png'))

    @command(no_pm=True, aliases=['colour'])
    @bot_has_permissions(manage_roles=True)
    @commands.cooldown(1, 7, type=BucketType.member)
    async def color(self, ctx, *, color=None):
        """Set you color on the server.
        {prefix}{name} name of color
        To see the colors on this server use {prefix}colors or {prefix}show_colors"""
        guild = ctx.guild
        colors = self._colors.get(guild.id, None)
        if not colors:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send("This guild doesn't have any color roles")

        ids = set(colors.keys())
        roles = set([r.id for r in ctx.author.roles])
        if not color:
            ctx.command.reset_cooldown(ctx)
            user_colors = roles.intersection(ids)
            if not user_colors:
                return await ctx.send("You don't have a color role")

            if len(user_colors) > 1:
                return await ctx.send('You have multiple color roles <:gappyThinking:358523789170180097>')

            else:
                name = colors.get(user_colors.pop())
                return await ctx.send('Your current color is {0}. To set a color use {1}{2} color name\n'
                                      'Use {1}colors to see a list of colors in this guild. To also see the role colors use {1}show_colors'.format(name, ctx.prefix, ctx.invoked_with))

        color_ = self.get_color(color, guild.id)
        if not color_:
            ctx.command.reset_cooldown(ctx)
            match = self.closest_match(color, guild)
            if not match:
                return await ctx.send('Could not find color %s' % color)

            color_, similarity = match
            return await ctx.send('Could not find color {0}. Color closest to '
                                  '{0} is {1} with {2:.02f}% similarity'.format(color, color_.name, similarity))

        id, color = color_
        if id in roles and len(roles) <= 1:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send('You already have that color')

        roles = roles.difference(ids)
        roles.add(id)
        try:
            await ctx.author.edit(roles=[Snowflake(r) for r in roles])
        except discord.HTTPException as e:
            return await ctx.send('Failed to set color because of an error\n\n```\n%s```' % e)

        await ctx.send('Color set to %s' % color.name)

    @staticmethod
    def text_only_colors(colors):
        s = ''
        le = len(colors) - 1
        for idx, color in enumerate(colors.values()):
            s += str(color)

            if le != idx:
                s += ', '

        s = split_string(s, maxlen=2000, splitter=', ')
        return s

    def sort_by_color(self, colors):
        start = self.rgb2lab((0,0,0), to_role=None)
        color, _ = self.closest_color_match(start, colors)
        sorted_colors = [color]
        colors.remove(color)

        while colors:
            closest, _ = self.closest_color_match(sorted_colors[-1], colors)
            colors.remove(closest)
            sorted_colors.append(closest)

        return sorted_colors

    # https://stackoverflow.com/a/3943023/6046713
    @staticmethod
    def text_color(color: Color):
        r, g, b = color.rgb
        if (r * 0.299 + g * 0.587 + b * 0.114) > 186:
            return '#000000'

        return '#FFFFFF'

    def draw_text(self, color: Color, size, font: ImageFont.FreeTypeFont):
        im = Image.new('RGB', size, color.rgb)

        draw = ImageDraw.Draw(im)
        name = str(color)
        text_size = font.getsize(name)
        text_color = self.text_color(color)
        if text_size[0] > size[0]:
            all_lines = []
            lines = split_string(name, maxlen=len(name)//(text_size[0]/size[0]))
            margin = 2
            total_y = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if text_size[1] + total_y > size[1]:
                    break

                x = (size[0] - font.getsize(line)[0]) // 2
                all_lines.append((line, x))
                total_y += margin + text_size[1]

            y = (size[1] - total_y) // 2
            for line, x in all_lines:
                draw.text((x, y), line, font=font, fill=text_color)
                y += margin + text_size[1]

        else:
            x = (size[0] - text_size[0]) // 2
            y = (size[1] - text_size[1]) // 2
            draw.text((x, y), name, font=font, fill=text_color)
        return im

    def _sorted_color_image(self, colors):
        size = (100, 100)
        colors = self.sort_by_color(colors)
        side = ceil(sqrt(len(colors)))
        font = ImageFont.truetype(
            os.path.join(WORKING_DIR, 'M-1c', 'mplus-1c-bold.ttf'),
            encoding='utf-8', size=17)

        images = []
        reverse = False
        for i in range(0, len(colors), side):
            color_range = colors[i:i + side]
            ims = []
            for color in color_range:
                ims.append(self.draw_text(color, size, font))

            if not ims:
                continue

            if reverse:
                while len(ims) < side:
                    ims.append(Image.new('RGBA', size, (0, 0, 0, 0)))

                ims.reverse()
                reverse = False
            else:
                reverse = True

            images.append(self.concatenate_colors(ims, width=size[0]))

        stack = self.stack_colors(images, size[1])

        data = BytesIO()
        stack.save(data, 'PNG')
        data.seek(0)
        return data

    @group(no_pm=True, aliases=['colours'], invoke_without_command=True)
    @cooldown(1, 5, type=BucketType.guild)
    async def colors(self, ctx):
        """Shows the colors on this guild"""
        guild = ctx.guild
        colors = self._colors.get(guild.id)
        if not colors:
            return await ctx.send("This guild doesn't have any color roles")

        if not check_botperm('attach_files', ctx=ctx):
            for msg in self.text_only_colors(colors):
                await ctx.send(msg)

            return

        data = await self.bot.loop.run_in_executor(self.bot.threadpool, self._sorted_color_image, list(colors.values()))
        await ctx.send(file=discord.File(data, 'colors.png'))

    @colors.command(no_pm=True)
    @bot_has_permissions(attach_files=True)
    @cooldown(1, 60, type=BucketType.guild)
    async def roles(self, ctx):
        """
        Sorts all roles in the server by color and puts them in one file.
        Every role gets a square with it's color and name on it
        """
        colors = []
        for role in ctx.guild.roles:
            rgb = role.color.to_rgb()
            rgb = self.check_rgb(tuple(v/255 for v in rgb), to_role=False)
            lab = convert_color(sRGBColor(*rgb), LabColor)
            rgb = tuple(round(v*255) for v in rgb)
            value = rgb[0]
            value = (((value << 8) + rgb[1]) << 8) + rgb[2]
            colors.append(Color(None, role.name, value, None, lab))

        async with ctx.typing():
            data = await self.bot.loop.run_in_executor(self.bot.threadpool, self._sorted_color_image, colors)

        await ctx.send(file=discord.File(data, 'colors.png'))

    @command(no_pm=True, aliases=['colorpie'])
    @cooldown(1, 10, BucketType.guild)
    async def color_pie(self, ctx, all_roles: bool=False):
        """
        Posts a pie chart of colors of this servers members.
        If `all_roles` is set on will replace color hex with the role name
        of the highest role that has the same value.

        If off (default) it will only replace hex values with the corresponding
        color names if the guild has any colors added.
        """
        guild = ctx.guild

        def do():
            member_count = len(guild.members)

            # dict of
            # hex value: amount of users with said value
            data = {}

            if not all_roles:
                # Only resolve names for guild colors
                colors = self._colors.get(guild.id, {})
                color2name = {c.value: c.name for c in colors.values()}
            else:
                # Resolve names for all roles
                color2name = {}

                # Roles are ordered in hierarchy from lowest to highest
                # so higher roles with same color will override other colors
                for r in guild.roles:
                    color2name[r.color.value] = r.name

                # Exception for no color
                color2name[0] = '@everyone'

            for m in guild.members.copy():
                val = m.color.value
                if val in data:
                    data[val] += 1
                else:
                    data[val] = 1

            data = list(sorted(data.items(), key=lambda kv: kv[1], reverse=True))
            values_count = [d[1] for d in data]
            colors = [d[0] for d in data]
            colors_hex = ['#B9BBBE' if c == 0 else '#' + hex(c)[2:].zfill(6).upper()
                          for c in colors]

            # Values normalized
            values = [i/member_count for i in values_count]

            color_text = []
            used_color_lengths = [len(color2name.get(c, colors_hex[i])) for i, c in enumerate(colors)]
            maxlen = max(used_color_lengths)

            for i, c in enumerate(colors):
                # Percentage that always has 4 numbers 00.00%
                p = '{:>5.2%}'.format(values[i]).zfill(6)

                c = color2name.get(c, colors_hex[i])

                padding = maxlen - len(c)

                # We wanna center the - so we pad from both sides
                lpad = ceil(padding/2)
                rpad = padding//2
                color_text.append(f'{c} {" "*lpad}-{" "*rpad} {p} ({values_count[i]})')

            # Create plot with 2 columns
            fig, ax = plt.subplots(1, 2, figsize=(3, 3), subplot_kw={'aspect': 'equal'})

            try:
                # Scale radius based on amount of colors. This is because picture
                # size increases when color amount increases
                wedges, texts = ax[0].pie(values, colors=colors_hex, radius=len(colors)/5)

                ax[1].axis('off')
                x = len(colors)
                x = sqrt(x)/2 + min(2.0, (x*x)/2000) + (maxlen-7)/28
                f = ax[1].legend(wedges, color_text,
                                 title=f"Colors ({len(colors)})",
                                 loc="center",
                                 # We need to move the anchor point based on circle radius
                                 # and longest text. These values were created by trial and error
                                 bbox_to_anchor=(x, 0, 0, 1))

                # We wanna use monospace font so everything aligns nicely
                plt.setp(f.texts, family='monospace')

                buf = BytesIO()
                # bbox_inches='tight' makes it so picture is extended just enough to fit everything
                plt.savefig(buf, format='png', bbox_inches='tight')
                plt.close(fig)

            except Exception as e:
                # In case of exception just close figure
                plt.close(fig)
                raise e

            buf.seek(0)
            return buf.getvalue()

        async with ctx.typing():
            data = await self.bot.loop.run_in_executor(self.bot.threadpool, do)

        if not data:
            return

        await ctx.send(file=discord.File(data, 'colors.png'))

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

    @command(no_pm=True, aliases=['add_colour'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, type=BucketType.guild)
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

        # Find a role with the same color value as this one
        r = discord.utils.find(lambda i: i[1].value == value, self._colors.get(guild.id, {}).items())
        if r:
            k, r = r
            if guild.get_role(r.role_id):
                return await ctx.send(f'This color already exists. Conflicting color {r.name} `{r.role_id}`')
            else:
                self._colors.get(guild.id, {}).pop(k, None)

        color = lab

        default_perms = guild.default_role.permissions
        try:
            d_color = discord.Colour(value)
            color_role = await guild.create_role(name=name, permissions=default_perms,
                                                 colour=d_color, reason=f'{ctx.author} created a new color')
        except discord.HTTPException as e:
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
            role = guild.get_role(list(self._colors[guild.id].keys())[0])
            if role:
                try:
                    await color_role.edit(position=max(1, role.position))
                except discord.HTTPException as e:
                    await ctx.send(f'Failed to move color role up in roles hierarchy because of an exception\n{e}')

            self._colors[guild.id][color_role.id] = color_
        else:
            self._colors[guild.id] = {color_role.id: color_}

        await ctx.send('Added color {} {}'.format(name, str(d_color)))

    @command(no_pm=True, aliases=['colors_from_roles'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, type=BucketType.guild)
    async def add_colors_from_roles(self, ctx, *, roles):
        """Turn existing role(s) to colors.
        Usage:
            {prefix}{name} 326726982656196629 Red @Blue
        Works with role mentions, role ids and name matching"""
        if not roles:
            return await ctx.send('Give some roles to turn to guild colors')

        roles = shlex.split(roles)
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

    @command(no_pm=True, aliases=['del_color', 'remove_color', 'delete_colour', 'remove_colour'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 3, type=BucketType.guild)
    async def delete_color(self, ctx, *, name):
        """Delete a color from the server"""
        guild = ctx.guild
        color = self.get_color(name, guild.id)
        if not color:
            return await ctx.send(f"Couldn't find color {name}")

        role_id = color[0]
        role = guild.get_role(role_id)
        if not role:
            await self._delete_color(guild.id, role_id)
            await ctx.send(f'Removed color {color[1]}')
            return

        try:
            await role.delete(reason=f'{ctx.author} deleted this color')
            await self._delete_color(guild.id, role_id)
        except discord.HTTPException as e:
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

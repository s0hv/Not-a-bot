import asyncio
import json
import logging
import os
import re
import shlex
import typing
from io import BytesIO
from math import ceil, sqrt

import disnake
import matplotlib.pyplot as plt
from PIL import Image, ImageDraw, ImageFont
from asyncpg.exceptions import PostgresError
from colormath.color_conversions import convert_color
from colormath.color_diff import delta_e_cie2000
from colormath.color_objects import LabColor, sRGBColor
from colour import Color as Colour
from disnake.ext import commands
from disnake.ext.commands import (BucketType, BadArgument, cooldown, guild_only)
from numpy.random import choice

from bot.bot import (command, has_permissions, group, bot_has_permissions,
                     Context)
from bot.globals import WORKING_DIR
from bot.paginator import Paginator
from cogs.cog import Cog
from utils.imagetools import stack_images, concatenate_images
from utils.utilities import (split_string, get_role, y_n_check, y_check,
                             Snowflake, check_botperm, get_text_size)

logger = logging.getLogger('terminal')

rgb_splitter = re.compile(r'^(\d{1,3})([, ])(\d{1,3})\2(\d{1,3})$')


class Color:
    __slots__ = ('role_id', 'name', 'value', 'lab', 'guild_id')

    def __init__(self, role_id, name, value, guild_id, lab):
        self.role_id = role_id
        self.name = name
        self.value = value
        if isinstance(lab, LabColor):
            self.lab = lab
        else:
            self.lab = LabColor(*lab)
        self.guild_id = guild_id

    @classmethod
    def from_hex(cls, name, hex_s, set_lab=False):
        """
        Create a color from hex without id support
        Args:
            name (str): Name of the color
            hex_s (str): hex string of the color starting with #
            set_lab (bool): Determines if lab conversion should be used.
                            This function is ~10 times faster or more when this is False
        Returns:
            (Color): Color instance
        """
        c = Color(0, name, int(hex_s[1:], 16), 0, (0, 0, 0))
        if set_lab:
            lab = convert_color(sRGBColor(*c.to_rgb(), is_upscaled=True), LabColor)
            c.lab = lab
        return c

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
        # {guild_id: {role_id: Color} }
        self._colors = {}
        self.bot.colors = self._colors
        self._color_jobs = set()

        with open(os.path.join(os.getcwd(), 'data', 'color_names.json'), 'r', encoding='utf-8') as f:
            self._color_names = json.load(f)

    async def cog_load(self):
        await super().cog_load()
        await self._cache_colors()

    @Cog.listener()
    async def on_ready(self):
        logger.debug('Caching colors')
        await self._cache_colors()

    async def _cache_colors(self):
        sql = 'SELECT colors.id, colors.name, colors.value, roles.guild, colors.lab_l, colors.lab_a, colors.lab_b FROM ' \
              'colors LEFT OUTER JOIN roles on roles.id=colors.id'

        try:
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
            logger.exception('Failed to cache colors')
            return

        for row in rows:
            # This will fail before on ready is called
            if not self.bot.get_guild(row['guild']):
                continue

            await self._add_color(**row)

    @Cog.listener()
    async def on_guild_join(self, guild: disnake.Guild):
        await self._cache_guild_colors(guild.id)

    async def _cache_guild_colors(self, guild_id: int):
        sql = '''
        SELECT 
            colors.id, colors.name, colors.value, roles.guild, 
            colors.lab_l, colors.lab_a, colors.lab_b 
        FROM colors 
        LEFT OUTER JOIN roles on roles.id=colors.id 
        WHERE roles.guild=$1'''

        try:
            rows = await self.bot.dbutil.fetch(sql, (guild_id,))
        except PostgresError:
            logger.exception('Failed to cache colors')
            return

        for row in rows:
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

    def get_color_from_type(self, color, guild_id):
        """
        Gets the color role from a role or string
        Args:
            color (disnake.Role or str): color of the given server
            guild_id (int): id of the guild

        Returns:
            Color if color found. None otherwise
        """
        if isinstance(color, disnake.Role):
            color = self._colors[guild_id].get(color.id)
        else:
            color = self.get_color(color, guild_id)
            if color:
                color = self._colors[guild_id].get(color[0])

        return color

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
            if (lab_l, lab_a, lab_b) != (lab.lab_l, lab.lab_a, lab.lab_b):
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
        return disnake.utils.find(lambda n: str(n[1]).lower() == name,
                                  self._colors.get(guild_id, {}).items())

    def search_color_(self, name):
        name = name.lower()

        matches = []
        for color, value in self._color_names.items():
            if color == name:
                matches.insert(0, (color, value))

            elif name in color:
                matches.append((color, value))

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
            except (ValueError, AttributeError):
                return

        return self.check_rgb(rgb)

    @staticmethod
    def closest_color_match(color, colors):
        if isinstance(color, Color):
            lab = color.lab
        else:
            lab = color

        closest_match = None
        similarity = None
        for c in colors:
            if isinstance(c, Color):
                clab = c.lab
            else:
                clab = c

            d = 100 - delta_e_cie2000(lab, clab)
            if similarity is None or d > similarity:
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

            await self._update_color(color, after, to_role=False)

        elif before.name != after.name:
            color = self._colors.get(before.guild.id, {}).get(before.id)
            if not color:
                return

            color.name = after.name
            await self._add_color2db(color, update=True)

    async def _add_colors_from_roles(self, roles, ctx: Context):
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

            r = disnake.utils.find(lambda c: c.value == color.value, colors.values())
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

            concat = concatenate_images(images)
            data = BytesIO()
            concat.save(data, 'PNG')
            data.seek(0)
            return data

        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_the_thing)
        if steps > 10:
            s = f'From {colors[0].get_hex_l()} to {colors[-1].get_hex_l()}'
        else:
            s = ' '.join(hex_colors)
        await ctx.send(s, file=disnake.File(data, 'colors.png'))

    @command(aliases=['cdiff', 'color_diff'])
    @cooldown(1, 5, BucketType.user)
    async def color_difference(self, ctx, color1: str, color2: str):
        """
        Tells how different two colors are
        """
        c1, c2 = color1, color2
        color1 = Colour(self.color_from_str(color1))
        color2 = Colour(self.color_from_str(color2))

        color1 = self.rgb2lab(color1.rgb, to_role=False)
        color2 = self.rgb2lab(color2.rgb, to_role=False)

        diff = 100 - delta_e_cie2000(color1, color2)

        await ctx.send(f'Colors {c1} and {c2} are {diff:.2f}% alike')

    @command(aliases=['c'], name='get_color')
    @cooldown(1, 5, BucketType.channel)
    async def get_color_image(self, ctx, *, color_list): # clean_content): # TODO re add this when clean content works again
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
        \u200b \u200b \u200b• Color name. All compatible names are listed [here](https://en.wikipedia.org/wiki/List_of_colors_(compact)) and [here](https://encycolorpedia.com/named)
        \u200b \u200b \u200b• Any of `invisible`, `none`, `transparent` for transparent spot
        """
        try:
            color_list = [shlex.split(c) for c in color_list.split('\n')]
        except ValueError:
            await ctx.send("Invalid string given. Make sure all quotes are closed")
            return

        lengths = map(len, color_list)
        if sum(lengths) > 100:
            raise BadArgument('Maximum amount of colors is 100')

        images = []
        hex_colors = []
        size = (50, 50)

        def do_the_thing():
            for colors in color_list:
                if not colors:
                    continue

                ims = []
                for color in colors:
                    color = self.color_from_str(color)
                    try:
                        im = Image.new('RGBA', size, color)
                        ims.append(im)
                        if isinstance(color, tuple):
                            color = self.rgb2hex(*color)
                        hex_colors.append(color[:7])
                    except (TypeError, ValueError):
                        raise BadArgument(f'Failed to create image using color {color}')

                images.append(concatenate_images(ims))

            if len(images) > 1:
                concat = stack_images(images)
            else:
                concat = images[0]

            data = BytesIO()
            concat.save(data, 'PNG')
            data.seek(0)
            return data

        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_the_thing)
        await ctx.send(' '.join(hex_colors), file=disnake.File(data, 'colors.png'))

    @command(aliases=['colour'])
    @bot_has_permissions(manage_roles=True)
    @commands.cooldown(1, 7, type=BucketType.member)
    @guild_only()
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
        roles = {r.id for r in ctx.author.roles}
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
        except disnake.HTTPException as e:
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
        text_size = get_text_size(font, name)
        text_color = self.text_color(color)
        x_margin = 1

        if text_size[0] > size[0] - x_margin*2:
            all_lines = []
            lines = split_string(name, maxlen=len(name)//(text_size[0]/(size[0] - 2*x_margin)))

            y_margin = 2
            total_y = 0
            for line in lines:
                line = line.strip()
                if not line:
                    continue

                if text_size[1] + total_y > size[1]:
                    break

                x = (size[0] + x_margin - get_text_size(font, line)[0]) // 2
                all_lines.append((line, x))
                total_y += y_margin + text_size[1]

            y = (size[1] - total_y) // 2
            for line, x in all_lines:
                draw.text((x, y), line, font=font, fill=text_color)
                y += y_margin + text_size[1]

        else:
            x = (size[0] + x_margin - text_size[0]) // 2
            y = (size[1] - text_size[1]) // 2
            draw.text((x, y), name, font=font, fill=text_color)
        return im

    def _sorted_color_image(self, colors):
        return self._color_image(self.sort_by_color(colors))

    def _color_image(self, colors):
        size = (100, 100)
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

            images.append(concatenate_images(ims, width=size[0]))

        stack = stack_images(images, size[1])

        data = BytesIO()
        stack.save(data, 'PNG')
        data.seek(0)
        return data

    @group(aliases=['colours'], invoke_without_command=True)
    @cooldown(1, 5, type=BucketType.guild)
    @guild_only()
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

        try:
            data = await self.bot.loop.run_in_executor(self.bot.threadpool, self._sorted_color_image, list(colors.values()))
        except OSError:
            logger.exception('Failed to generate colors')
            await ctx.send('Failed to generate colors. Try again later')
            return

        await ctx.send(file=disnake.File(data, 'colors.png'))

    @colors.command()
    @bot_has_permissions(attach_files=True)
    @cooldown(1, 60, type=BucketType.guild)
    @guild_only()
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

        await ctx.send(file=disnake.File(data, 'colors.png'))

    def _format_color_names(self, guild, use_role_names):
        """
        Used in colorpie to get hex to name dict
        """
        if not use_role_names:
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

        return color2name

    @staticmethod
    def _get_colorpie(members, color2name):
        """

        Args:
            members (list of disnake.Member): Members to be used in colorpie
            color2name (dict[str, str]): Convert hex strings to color names

        Returns:
            color pie image
        """

        # dict of
        # hex value: amount of users with said value
        role_data: dict[int, int] = {}

        for m in members:
            val = m.color.value
            if val in role_data:
                role_data[val] += 1
            else:
                role_data[val] = 1

        member_count = sum(role_data.values())

        data = list(sorted(role_data.items(), key=lambda kv: kv[1], reverse=True))
        values_count = [d[1] for d in data]
        colors = [d[0] for d in data]
        colors_hex = ['#B9BBBE' if c == 0 else '#' + hex(c)[2:].zfill(6).upper()
                      for c in colors]

        # Values normalized
        values = [count / member_count for count in values_count]

        color_text = []
        used_color_lengths = [len(color2name.get(c, colors_hex[i])) for i, c in
                              enumerate(colors)]
        maxlen = max(used_color_lengths)

        for i, c in enumerate(colors):
            # Percentage that always has 4 numbers 00.00%
            p = '{:>5.2%}'.format(values[i]).zfill(6)

            c = color2name.get(c, colors_hex[i])

            padding = maxlen - len(c)

            # We wanna center the - so we pad from both sides
            lpad = ceil(padding / 2)
            rpad = padding // 2
            color_text.append(f'{c} {" " * lpad}-{" " * rpad} {p} ({values_count[i]})')

        # Create plot with 2 columns
        fig, ax = plt.subplots(1, 2, figsize=(3, 3), subplot_kw={'aspect': 'equal'})

        try:
            # Scale radius based on amount of colors. This is because picture
            # size increases when color amount increases
            wedges, texts = ax[0].pie(values, colors=colors_hex,
                                      radius=len(colors) / 5, normalize=False)

            ax[1].axis('off')
            x = len(colors)
            x = sqrt(x) / 2 + min(2.0, (x * x) / 2000) + (maxlen - 7) / 28
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
        return buf

    @group(aliases=['colorpie'], invoke_without_command=True)
    @cooldown(1, 10, BucketType.guild)
    @guild_only()
    async def color_pie(self, ctx, all_roles: typing.Optional[bool]=False):
        """
        Posts a pie chart of colors of this servers members.
        If `all_roles` is set on will replace color hex with the role name
        of the highest role that has the same value.

        If off (default) it will only replace hex values with the corresponding
        color names if the guild has any colors added.
        """
        guild = ctx.guild

        def do():
            return self._get_colorpie(guild.members.copy(), self._format_color_names(guild, all_roles))

        async with ctx.typing():
            data = await self.bot.loop.run_in_executor(self.bot.threadpool, do)

        if not data:
            return

        await ctx.send(file=disnake.File(data, 'colors.png'))

    @color_pie.command(name="actives")
    @cooldown(1, 10, BucketType.guild)
    @guild_only()
    async def colorpie_filtered(self, ctx, role_amount: typing.Optional[int]=3,
                                all_roles: typing.Optional[bool]=False):
        """
        Same as colorpie but will only count users with at least role_amount of roles.
        everyone isn't counted as a role
        """
        guild = ctx.guild
        members = [m for m in guild.members.copy() if len(m.roles) > role_amount]
        if not members:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f'No members found with at least {role_amount} roles')
            return

        def do():
            return self._get_colorpie(members, self._format_color_names(guild, all_roles))

        async with ctx.typing():
            data = await self.bot.loop.run_in_executor(self.bot.threadpool, do)

        if not data:
            return

        await ctx.send(file=disnake.File(data, 'colors.png'))

    @group(aliases=['search_colour', 'sc'], invoke_without_command=True)
    @cooldown(1, 4, BucketType.user)
    async def search_color(self, ctx, *, color_name):
        """
        Search a color using a name and return it's hex value if found
        and all other similarly named colors
        """
        matches = self.search_color_(color_name)
        if not matches:
            return await ctx.send('No colors found with {}'.format(color_name))

        total = len(matches)
        page_size = 10
        pages: list[None | str] = [None for _ in range(0, total, page_size)]

        def get_page(page_idx: int):
            page = pages[page_idx]
            if page:
                return page

            s = ""
            idx = page_size*page_idx
            for match in matches[idx:idx+page_size]:
                s += f'{match[0]} `{match[1]["hex"]}`\n'

            s += f'{page_idx+1}/{len(pages)}'
            pages[page_idx] = s
            return s

        paginator = Paginator(pages, generate_page=get_page,
                              hide_page_count=True,
                              show_stop_button=True)
        await paginator.send(ctx)

    @search_color.command(name='pic')
    @cooldown(1, 5, BucketType.user)
    async def search_as_picture(self, ctx, sort: typing.Optional[bool], page: typing.Optional[int], *, color_name):
        """
        Search colors but display the first 30 of them in a picture
        If you dont want search words to be converted to a boolean or integer escape
        them with \\ like this `{prefix}{name} \\on \\2 color`
        """
        color_name = color_name.replace('\\', '')
        if page is None:
            page = 1

        if page < 1:
            ctx.command.reset_cooldown(ctx)
            await ctx.send('Page cannot be less than one')
            return

        matches = self.search_color_(color_name)
        if not matches:
            return await ctx.send('No colors found with {}'.format(color_name))

        page_size = 42
        page -= 1  # Offset page to start indices at 0
        page *= page_size
        if len(matches) < page:
            ctx.command.reset_cooldown(ctx)
            await ctx.send('Page out of bounds')
            return

        def do_pic():
            colors = [Color.from_hex(name.replace('-', ' '), color['hex'], bool(sort)) for name, color in matches[page:page+page_size]]
            return self._sorted_color_image(colors)

        await ctx.trigger_typing()
        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_pic)
        await ctx.send(file=disnake.File(data, 'colors.png'))

    @command(aliases=['add_colour'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, type=BucketType.guild)
    @guild_only()
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
        r = disnake.utils.find(lambda i: i[1].value == value, self._colors.get(guild.id, {}).items())
        if r:
            k, r = r
            if guild.get_role(r.role_id):
                return await ctx.send(f'This color already exists. Conflicting color {r.name} `{r.role_id}`')
            else:
                self._colors.get(guild.id, {}).pop(k, None)

        color = lab

        default_perms = guild.default_role.permissions
        try:
            d_color = disnake.Colour(value)
            color_role = await guild.create_role(name=name, permissions=default_perms,
                                                 colour=d_color, reason=f'{ctx.author} created a new color')
        except disnake.HTTPException as e:
            logger.exception('guild {0.id} rolename: {1} perms: {2} color: {3} {4}'.format(guild, name, default_perms.value, str(rgb), value))
            return await ctx.send('Failed to add color because of an error\n```%s```' % e)

        color_ = Color(color_role.id, name, value, guild.id, color)
        success = await self._add_color2db(color_)
        if not success:
            return await ctx.send('Failed to add color')

        if self._colors.get(guild.id):
            role = guild.get_role(list(self._colors[guild.id].keys())[0])
            if role:
                try:
                    await color_role.edit(position=max(1, role.position))
                except disnake.HTTPException as e:
                    await ctx.send(f'Failed to move color role up in roles hierarchy because of an exception\n{e}')

            self._colors[guild.id][color_role.id] = color_
        else:
            self._colors[guild.id] = {color_role.id: color_}

        await ctx.send('Added color {} {}'.format(name, str(d_color)))

    @command(aliases=['rename_colour'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, type=BucketType.guild)
    @guild_only()
    async def rename_color(self, ctx, color: typing.Union[disnake.Role, str], *, new_name):
        """
        Edit the name of the given color. This is not the same as changing the name of the role
        that the color is associated with.
        """
        guild = ctx.guild
        c = color
        color = self.get_color_from_type(color, guild.id)

        if not color:
            await ctx.send(f'No color role found with {c}')
            return

        old_name = color.name
        color.name = new_name
        await self._add_color2db(color, update=True)
        await ctx.send(f"Renamed {old_name} to {new_name}")

    @command(aliases=['edit_colour'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, type=BucketType.guild)
    @guild_only()
    async def edit_color(self, ctx, color: typing.Union[disnake.Role, str], *, new_color):
        """
        Edit the color of an existing color role.
        Color is the name of the color role or the role id of the role it's assigned to
        and new_color is the new color that's gonna be assigned to it
        """
        guild = ctx.guild
        c = color
        color = self.get_color_from_type(color, guild.id)

        if not color:
            await ctx.send(f'No color role found with {c}')
            return

        rgb = self.match_color(new_color)
        if not rgb:
            return await ctx.send(f'Color {new_color} not found')

        lab = self.rgb2lab(rgb)
        rgb = convert_color(lab, sRGBColor)
        value = int(rgb.get_rgb_hex()[1:], 16)

        # Find a role with the same color value as this one
        r = disnake.utils.find(lambda i: i[1].value == value, self._colors.get(guild.id, {}).items())
        if r:
            k, r = r
            if guild.get_role(r.role_id):
                return await ctx.send(f'This color already exists {new_color} (#{value:06X}). Conflicting color {r.name} `{r.role_id}`')
            else:
                self._colors.get(guild.id, {}).pop(k, None)

        role = guild.get_role(color.role_id)
        if not role:
            await ctx.send('No color role found')
            return

        try:
            if role.name.lower() == color.name.lower():
                await role.edit(name=new_color, color=disnake.Colour(value))
                color.name = new_color
            else:
                await role.edit(color=disnake.Colour(value))
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to add color because of an error\n{e}')
            return

        color.value = value
        color.lab = lab

        await self._add_color2db(color, update=True)
        await ctx.send(f'Updated color to value {new_color} (#{value:06X})')

    @command(aliases=['colors_from_roles'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 5, type=BucketType.guild)
    @guild_only()
    async def add_colors_from_roles(self, ctx, *, roles):
        """Turn existing role(s) to colors.
        Usage:
            {prefix}{name} 326726982656196629 Red @Blue
        Works with role mentions, role ids and name matching"""
        if not roles:
            return await ctx.send('Give some roles to turn to guild colors')

        try:
            roles = shlex.split(roles)
        except ValueError:
            await ctx.send('Invalid string given. Make sure all quotes are closed')
            return

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
            s += 'Adding roles {}\n'.format(', '.join('`%s`' % r.name for r in success))

        if failed:
            s += 'Failed to find roles {}'.format(', '.join(f'`{r}`' for r in failed))

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

    @command(aliases=['del_color', 'remove_color', 'delete_colour', 'remove_colour'])
    @has_permissions(manage_roles=True)
    @bot_has_permissions(manage_roles=True)
    @cooldown(1, 3, type=BucketType.guild)
    @guild_only()
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
        except disnake.HTTPException as e:
            return await ctx.send(f'Failed to remove color because of an error\n```{e}```')

        await ctx.send(f'Removed color {color[1]}')

    @command(aliases=['show_colours'])
    @cooldown(1, 4, type=BucketType.guild)
    @guild_only()
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
        embeds = [disnake.Embed() for i in range(embed_count)]
        field_title = ''
        field_value = ''

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

    @command()
    @bot_has_permissions(manage_roles=True)
    @has_permissions(administrator=True)
    async def color_uncolored(self, ctx):
        """Color users that don't have a color role"""
        guild = ctx.guild
        color_ids = list(self._colors.get(guild.id, {}).keys())
        if not color_ids:
            await ctx.send('No colors')
            return

        if guild.id in self._color_jobs:
            await ctx.send('Coloring job is already running in this server')
            return

        self._color_jobs.add(guild.id)

        try:
            await guild.chunk()
        except (TypeError, ValueError):
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
                except disnake.errors.Forbidden:
                    return
                except disnake.HTTPException:
                    continue

            elif len(found) > 1:
                try:
                    removed_roles = color_ids.copy()
                    removed_roles.remove(found[0].id)
                    await member.remove_roles(*map(Snowflake, removed_roles), reason='Removing duplicate colors', atomic=False)
                    duplicate_colors += 1
                except (disnake.HTTPException, disnake.ClientException, ValueError):
                    logger.exception('failed to remove duplicate colors')

        self._color_jobs.discard(guild.id)
        await ctx.send('Colored %s user(s) without color role\n'
                       'Removed duplicate colors from %s user(s)' % (colored, duplicate_colors))


def setup(bot):
    bot.add_cog(Colors(bot))

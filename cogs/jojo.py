"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import argparse
import asyncio
import logging
import os
import sys
from collections import OrderedDict
from functools import partial
from io import BytesIO
from itertools import zip_longest
from threading import Lock

import discord
import numpy as np
from PIL import Image, ImageFont
from colour import Color
from discord.ext.commands import BucketType
from matplotlib import pyplot as plt
from matplotlib.patches import Polygon, Circle
from numpy import pi, random

from bot.bot import command, cooldown, bot_has_permissions
from cogs.cog import Cog
from utils.imagetools import (create_shadow, create_text,
                              create_geopattern_background, shift_color,
                              remove_background,
                              resize_keep_aspect_ratio, get_color,
                              IMAGES_PATH, image_from_url, GeoPattern,
                              color_distance, MAX_COLOR_DIFF)
from utils.utilities import (get_picture_from_msg, y_n_check,
                             check_negative, normalize_text,
                             get_image, basic_check, test_url)

logger = logging.getLogger('debug')
HALFWIDTH_TO_FULLWIDTH = str.maketrans(
    '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ!"#$%&()*+,-./:;<=>?@[]^_`{|}~ ',
    '０１２３４５６７８９ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ！゛＃＄％＆（）＊＋、ー。／：；〈＝〉？＠［］＾＿‘｛｜｝～　')

LETTERS_TO_INT = {k: idx for idx, k in enumerate(['A', 'B', 'C', 'D', 'E'])}
INT_TO_LETTER = ['A', 'B', 'C', 'D', 'E']
POWERS = ['power', 'speed', 'range', 'durability', 'precision', 'potential']


class ArgumentParser(argparse.ArgumentParser):
    def _get_action_from_name(self, name):
        """Given a name, get the Action instance registered with this parser.
        If only it were made available in the ArgumentError object. It is
        passed as it's first arg...
        """
        container = self._actions
        if name is None:
            return None
        for action in container:
            if '/'.join(action.option_strings) == name:
                return action
            elif action.metavar == name:
                return action
            elif action.dest == name:
                return action

    def error(self, message):
        exc = sys.exc_info()[1]
        if exc:
            exc.argument = self._get_action_from_name(exc.argument_name)
            raise exc
        super(ArgumentParser, self).error(message)


class JoJo(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.stat_lock = Lock()
        self.stats = OrderedDict.fromkeys(POWERS, None)
        self.stat_spread_figure = plt.figure()
        self.line_points = [1 - 0.2*i for i in range(6)]
        self.parser = ArgumentParser()

        args = ['-blur', '-canny_thresh_1', '-canny_thresh_2', '-mask_dilate_iter', '-mask_erode_iter']
        for arg in args:
            self.parser.add_argument(arg, type=int, default=argparse.SUPPRESS,
                                     required=False)

    def cog_unload(self):
        plt.close('all')

    def create_empty_stats_circle(self, color='k'):
        fig = plt.figure()
        ax = fig.add_subplot(111)
        for i in range(6):
            power = POWERS[i]
            rot = 60 * i / 180 * pi  # Lines every 60 degrees

            # Rotate the points in the line rot degrees
            x = list(map(lambda x: x * np.sin(rot), self.line_points))
            y = list(map(lambda y: y * np.cos(rot), self.line_points))
            line = ax.plot(x, y, '-', color=color, alpha=0.6, markersize=6,
                           marker=(2, 0, 360 - 90 - 60 * i))

            if i == 0:
                x, y = line[0].get_data()

                # Shift the letters so the are not on top of the line
                correctionx = 0.15
                correctiony = 0.05
                for l, idx in LETTERS_TO_INT.items():
                    ax.text(x[idx] + correctionx, y[idx] - correctiony, l,
                            horizontalalignment='right', color=color, alpha=0.65,
                            fontsize=10)

            self.stats[power] = line

        return fig, ax

    def create_stats_circle(self, color='b', bg_color=None, **kwargs):
        c = 'black'
        if color_distance(Color(c), bg_color) < (MAX_COLOR_DIFF/2):
            c = 'white'

        inner_circle = Circle((0, 0), radius=1.1, fc='none', ec=c)
        outer_circle = Circle((0, 0), radius=1.55, fc='none', ec=c)
        outest_circle = Circle((0, 0), radius=1.65, fc='none', ec=c)
        fig, ax = self.create_empty_stats_circle(c)
        stat_spread = []
        for idx, line in enumerate(self.stats.values()):
            x, y = line[0].get_data()
            power = POWERS[idx]
            power_value = kwargs.get(power, 'E')
            if power_value is None:
                power_value = 'E'
            power_value = power_value.upper()
            power_int = LETTERS_TO_INT.get(power_value, 0)

            # Small correction to the text position
            correction = 0.03
            r = 60 * idx / 180 * pi

            sinr = np.round(np.sin(r), 5)
            cosr = np.round(np.cos(r), 5)

            if sinr < 0:
                lx = 1.25 * sinr - correction
            else:
                lx = 1.25 * sinr + correction
            if cosr < 0:
                ly = 1.25 * cosr - correction
            else:
                ly = 1.25 * cosr + correction

            rot = (0 + min(check_negative(cosr) * 180, 0)) - 60 * idx
            if sinr == 0:
                rot = 0

            ax.text(lx, ly, power_value, color=c, alpha=0.9, fontsize=14,
                    weight='bold', ha='center', va='center')
            ax.text(lx * 1.50, ly * 1.50, power, color=c, fontsize=17,
                    ha='center', rotation=rot, va='center')

            x = x[power_int]
            y = y[power_int]
            stat_spread.append([x, y])

        r1 = outer_circle.radius
        r2 = outest_circle.radius
        w = 3.0
        for r in range(0, 360, 15):
            sinr = np.round(np.sin(np.deg2rad(r)), 5)
            cosr = np.round(np.cos(np.deg2rad(r)), 5)
            x = (r1*sinr, r2*sinr)
            y = (r1*cosr, r2*cosr)
            ax.plot(x, y, '-', color=c, linewidth=w)

        pol = Polygon(stat_spread, fc='y', alpha=0.7)
        pol.set_color(color)

        fig.gca().add_patch(inner_circle)
        fig.gca().add_patch(outer_circle)
        fig.gca().add_patch(outest_circle)
        fig.gca().add_patch(pol)
        fig.gca().autoscale(True)
        fig.gca().set_axis_off()

        ax.axis('scaled')

        fig.canvas.draw()

        return fig, ax

    @staticmethod
    def _standify_text(s, type_=0):
        types = ['『』', '「」', '']
        bracket = types[type_]
        s = normalize_text(s)
        s = s.translate(HALFWIDTH_TO_FULLWIDTH)
        if type_ > 1:
            return s

        s = bracket[0] + s + bracket[1]
        return s

    @staticmethod
    def pattern_check(msg):
        return msg.content.lower() in GeoPattern.available_generators

    @command(aliases=['stand'])
    async def standify(self, ctx, *, stand):
        """Standify text using these brackets 『』"""
        stand = self._standify_text(stand)
        await ctx.send(stand)

    @command(aliases=['stand2'])
    async def standify2(self, ctx, *, stand):
        """Standify text using these brackets 「」"""
        stand = self._standify_text(stand, 1)
        await ctx.send(stand)

    @command(aliases=['stand3'])
    async def standify3(self, ctx, *, stand):
        """Standify text using no brackets"""
        stand = self._standify_text(stand, 2)
        await ctx.send(stand)

    async def subcommand(self, ctx, content, delete_after=60, author=None, channel=None, check=None, del_msg=True):
        m = await ctx.send(content, delete_after=delete_after)
        if callable(check):
            def _check(msg):
                return check(msg) and basic_check(author, channel)
        else:
            _check = basic_check(author, channel)
        try:
            msg = await self.bot.wait_for('message', check=_check, timeout=delete_after)
        except asyncio.TimeoutError:
            msg = None

        if del_msg:
            try:
                await m.delete()
            except discord.HTTPException:
                pass

        return msg

    @command(aliases=['stand_generator', 'standgen'])
    @cooldown(1, 10, BucketType.user)
    @bot_has_permissions(attach_files=True)
    async def stand_gen(self, ctx, stand, user, image=None, *, params=None):
        """Generate a stand card. Arguments are stand name, user name and an image

        Image can be an attachment or a link. Passing -advanced as the last argument
        will enable advanced mode which gives the ability to tune some numbers.
        Use quotes for names that have spaces e.g.
        `{prefix}{name} "Star Platinum" "Jotaro Kujo" [image]`
        You can also answer all parameters in one command by adding the parameters on their own line
        It works something like this
        ```
        {prefix}{name} "stand" "user"
        A A A A A A
        backround_image.png
        triangles
        n
        ```

        You can make the bot ask you the parameters by setting it just as an empty line. e.g.
        ```
        A A A A A A

        triangles
        ```
        Would make the bot sak the background from you.

        Here is a tree of the questions being asked.
        If some answers lead to extra question they are indented to make it clear

        1. Stats from A to E in the order power, speed, range, durability, precision, potential

        2. Link to the background. Leave empty if you want a randomized pattern
        2.......a) The geopattern and bg color separated by space. If either is left out it will be selected randomly

        3. Do you want automatic background removal. Recommended answer is no. Typing y or yes will use it
        """
        author = ctx.author
        channel = ctx.channel
        stand = self._standify_text(stand, 2)
        user = '[STAND MASTER]\n' + user
        stand = '[STAND NAME]\n' + stand
        size = (1100, 700)
        shift = 800
        advanced = False

        if image is None:
            pass
        elif test_url(image):
            pass
        else:
            params = params if params else ''
            params = image + params
            image = None

        if params:
            params = params.strip().split('\n')
            advanced = params[-1].strip()
            if advanced.endswith('-advanced'):
                advanced = advanced[:-9].strip()
                if advanced:
                    params[-1] = advanced
                else:
                    params.pop(-1)

                advanced = True

            else:
                advanced = False
        else:
            params = []

        if advanced:
            await ctx.send(f'{author} Advanced mode activated', delete_after=20)

        image = await get_image(ctx, image)
        if not image:
            return

        def get_next_param():
            try:
                return params.pop(0)
            except IndexError:
                return

        stats = get_next_param()

        if not stats:
            msg = await self.subcommand(ctx,
                '{} Give the stand **stats** in the given order ranging from **A** to **E** '
                'separated by **spaces**.\nDefault value is E\n`{}`'.format(author, '` `'.join(POWERS)),
                delete_after=120, author=author, channel=channel)

            if msg is None:
                await ctx.send(f'Timed out. {author} cancelling stand generation')
                return

            stats = msg.content

        stats = stats.split(' ')
        stats = dict(zip_longest(POWERS, stats[:6]))

        bg = get_next_param()

        if not bg:
            msg = await self.subcommand(ctx,
                f'{author}`Use a custom background by uploading a **picture** or using a **link**. '
                'Posting something other than an image will use the **generated background**',
                delete_after=120, author=author, channel=channel)

            bg = get_picture_from_msg(msg)
        else:
            if not test_url(bg):
                bg = None

        color = None

        if bg is not None:
            try:
                bg = bg.strip()
                bg = await image_from_url(bg, self.bot.aiohttp_client)

                def process_bg():
                    nonlocal bg, color
                    bg = bg.convert('RGB')
                    dominant_color = get_color(bg)
                    color = Color(rgb=list(map(lambda c: c/255, dominant_color)))
                    bg = resize_keep_aspect_ratio(bg, size, crop_to_size=True)
                    return color, bg

                color, bg = await self.bot.loop.run_in_executor(self.bot.threadpool, process_bg)
            except Exception:
                logger.exception('Failed to get background')
                await ctx.send(f'{author} Failed to use custom background. Using generated one',
                               delete_after=60)
                bg = None

        if bg is None:
            pattern = random.choice(GeoPattern.available_generators)

            msg = get_next_param()

            if not msg:
                msg = await self.subcommand(ctx,
                    "{} Generating background. Select a **pattern** and **color** separated by space. "
                    "Otherwise they'll will be randomly chosen. Available patterns:\n"
                    '{}'.format(author, '\n'.join(GeoPattern.available_generators)),
                    delete_after=120, channel=channel, author=author)
                msg = msg.content if msg else ''

            if not msg:
                await ctx.send('{} Selecting randomly'.format(author), delete_after=20)
            else:
                msg = msg.split(' ')
                # Temporary containers for pattern and color
                _pattern, _color = None, None
                if len(msg) == 1:
                    _pattern = msg[0]
                elif len(msg) > 1:
                    _pattern, _color = msg[:2]

                if _pattern in GeoPattern.available_generators:
                    pattern = _pattern
                else:
                    await ctx.send('{} Pattern {} not found. Selecting randomly'.format(author, _pattern),
                                   delete_after=20)

                if _color:
                    try:
                        color = Color(_color)
                    except:
                        await ctx.send('{} {} not an available color'.format(author, _color),
                                       delete_after=20)

            def do_bg():
                return create_geopattern_background(size, stand + user,
                                                    generator=pattern, color=color)

            bg, color = await self.bot.loop.run_in_executor(self.bot.threadpool, do_bg)

        if advanced:
            msg = get_next_param()

            if not msg:
                msg = await self.subcommand(ctx,
                    '{} Input color value change as an **integer**. Default is {}. '
                    'You can also input a **color** instead of the change value. '
                    'The resulting color will be used in the stats circle'.format(author, shift),
                    delete_after=120, channel=channel, author=author)
                msg = msg.content if msg else ''

            try:
                shift = int(msg.strip())
            except ValueError:
                try:
                    color = Color(msg)
                    shift = 0
                except:
                    await ctx.send(f'{author} Could not set color or color change int. Using default values',
                                   delete_after=15)

        try:
            if not isinstance(color, str):
                color = Color(color.get_hex_l())

            bg_color = Color(color)
        except AttributeError:
            logger.exception(f'Failed to set bg color from {color}')
            return await ctx.send('Failed to set bg color')

        def do_stuff():
            # Shift color hue and saturation so it's not the same as the bg
            shift_color(color, shift)

            fig, _ = self.create_stats_circle(color=color.get_hex_l(), bg_color=bg_color, **stats)
            path = os.path.join(IMAGES_PATH, 'stats.png')
            with self.stat_lock:
                try:
                    fig.savefig(path, transparent=True)
                    stat_img = Image.open(path)
                except:
                    logger.exception('Could not create image')
                    return '{} Could not create picture because of an error.'.format(author)

            plt.close(fig)
            stat_img = stat_img.resize((int(stat_img.width * 0.85),
                                        int(stat_img.height * 0.85)),
                                       Image.BILINEAR)

            full = Image.new('RGBA', size)
            # Coords for stat circle
            x, y = (-60, full.height - stat_img.height)
            stat_corner = (x + stat_img.width, y + stat_img.height)
            full.paste(stat_img, (x, y, *stat_corner))
            font = ImageFont.truetype(os.path.join('M-1c', 'mplus-1c-bold.ttf'), 40)

            # Small glow blur can be created with create_glow and setting amount to 1 or lower
            text = create_text(stand, font, '#FFFFFF', (int(full.width*0.75), int(y*0.8)), (10, 10))
            text = create_shadow(text, 80, 3, 2, 4).convert('RGBA')
            full.paste(text, (20, 20), text)

            text2 = create_text(user, font, '#FFFFFF', (int((full.width - stat_corner[0])*0.8), int(full.height*0.7)), (10, 10))
            text2 = create_shadow(text2, 80, 3, 2, 4).convert('RGBA')
            text2.load()

            return full, stat_corner, text2

        res = await self.bot.loop.run_in_executor(self.bot.threadpool, do_stuff)
        if isinstance(res, str):
            return await ctx.send(res)

        full, stat_corner, text2 = res

        if image is not None:
            # No clue what this does so leaving it out
            #im = trim_image(image)
            im = image

            msg = get_next_param()

            if not msg:
                msg = await self.subcommand(ctx,
                    f'{author} Try to automatically remove background (y/n)? '
                    'This might fuck the picture up and will take a moment',
                    author=author, channel=channel, delete_after=120, check=y_n_check)

                msg = msg.content if msg else ''

            if msg and msg.lower() in ['y', 'yes']:
                kwargs = {}
                if advanced:
                    msg = get_next_param()

                    if not msg:
                        msg = await self.subcommand(ctx,
                            f'{author} Change the arguments of background removing. Available'
                            ' arguments are `blur`, `canny_thresh_1`, `canny_thresh_2`, '
                            '`mask_dilate_iter`, `mask_erode_iter`. '
                            'Accepted values are integers.\nArguments are added like this '
                            '`-blur 30 -canny_thresh_2 50`. All arguments are optional',
                            channel=channel, author=author, delete_after=140)

                        msg = msg.content if msg else ''

                    await channel.trigger_typing()
                    if msg is not None:
                        try:
                            kwargs = self.parser.parse_known_args(msg.split(' '))[0].__dict__
                        except:
                            await ctx.send(f'{author} Could not get arguments from {msg}',
                                           delete_after=20)

                try:
                    im = await self.bot.loop.run_in_executor(self.bot.threadpool, partial(remove_background, im, **kwargs))
                except Exception:
                    logger.exception('Failed to remove bg from image')
                    await ctx.send(f'{author} Could not remove background because of an error',
                                   delete_after=30)

            def resize_image():
                nonlocal im
                # Size of user pic
                box = (500, 600)
                im = resize_keep_aspect_ratio(im, box, can_be_bigger=False, resample=Image.BICUBIC)
                im = create_shadow(im, 70, 3, -22, -7).convert('RGBA')
                full.paste(im, (full.width - im.width, int((full.height - im.height)/2)), im)

            await self.bot.loop.run_in_executor(self.bot.threadpool, resize_image)

        await channel.trigger_typing()

        def finalize_image():
            full.paste(text2, (int((full.width - stat_corner[0]) * 0.9), int(full.height * 0.7)), text2)
            bg.paste(full, (0, 0), full)

            file = BytesIO()
            bg.save(file, format='PNG')
            file.seek(0)
            return file

        file = await self.bot.loop.run_in_executor(self.bot.threadpool, finalize_image)
        await ctx.send(file=discord.File(file, filename='stand_card.png'))


def setup(bot):
    bot.add_cog(JoJo(bot))

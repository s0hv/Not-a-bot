import asyncio
import base64
import logging
import os
import shlex
import subprocess
import time
from asyncio import Lock
from functools import partial
from io import BytesIO
from math import ceil
from random import randint
from typing import Optional

import aiohttp
import disnake
import matplotlib.pyplot as plt
from PIL import (Image, ImageSequence, ImageFont, ImageDraw, ImageChops,
                 GifImagePlugin)
from asyncpg.exceptions import PostgresError
from disnake import File
from disnake.ext.commands import BucketType, BotMissingPermissions, cooldown, \
    is_owner, guild_only
from disnake.ext.commands.errors import BadArgument
from selenium.common.exceptions import UnexpectedAlertPresentException
from selenium.common.exceptions import WebDriverException
from selenium.webdriver import Chrome
from selenium.webdriver.chrome.options import Options

from bot.bot import command
from bot.converters import CleanContent
from bot.exceptions import NoPokeFoundException, BotException
from bot.paginator import Paginator
from cogs.cog import Cog
from utils.imagetools import (resize_keep_aspect_ratio, gradient_flash, sepia,
                              func_to_gif, get_duration, convert_frames,
                              apply_transparency)
from utils.utilities import (get_image_from_ctx, find_coeffs, check_botperm,
                             split_string, get_image, dl_image, call_later,
                             get_images)

logger = logging.getLogger('terminal')
TEMPLATES = os.path.join('data', 'templates')
TEMP_DATA = os.path.join('data', 'temp')

os.makedirs(TEMP_DATA, exist_ok=True)


class Pokefusion:
    RANDOM = '%'
    LAST_UPDATED = 0

    def __init__(self, bot):
        self._last_dex_number = 0
        self._pokemon = {}
        self._poke_reverse = {}
        self._poke_ids = []
        self._quit_chrome_task = None
        self._data_folder = os.path.join(os.getcwd(), 'data', 'pokefusion')
        self._driver_lock = Lock()
        self._bot = bot
        self._update_lock = Lock()

        options = Options()
        options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-background-networking')
        options.add_argument('--no-first-run')
        options.add_argument('--disable-pinch')
        binary = self.bot.config.chrome
        if binary:
            options.binary_location = binary
        self.opts = options
        self._driver = None

    @property
    def bot(self):
        return self._bot

    @property
    def driver(self):
        # If driver is None create a driver for 60 seconds
        # Driver won't quit until driver lock is released though
        if self._driver is None:
            self._driver = Chrome(self.bot.config.chromedriver, chrome_options=self.opts)
            self._quit_chrome_task = call_later(self._quit_chrome, self.bot.loop, 60)
            return self._driver

        # Restart quit task if it's running so we dont end up with multiple overlapping tasks
        if self._quit_chrome_task:
            self._quit_chrome_task.cancel()
            self._quit_chrome_task = call_later(self._quit_chrome, self.bot.loop, 60)

        return self._driver

    async def _quit_chrome(self):
        if not self._driver:
            return

        async with self._driver_lock:
            self._driver.quit()
            self._driver = None

    async def cache_types(self, start=1):
        name = 'sprPKMType_{}.png'
        url = 'https://japeal.com/wordpress/wp-content/themes/total/PKM/others/sprPKMType_{}.png'
        async with aiohttp.ClientSession() as client:
            while True:
                r = await client.get(url.format(start))
                if r.status == 404:
                    r.close()
                    break

                with open(os.path.join(self._data_folder, name.format(start)), 'wb') as f:
                    f.write(await r.read())

                start += 1

    async def update_cache(self):
        if self._update_lock.locked():
            # If and update is in progress wait for it to finish and then continue
            await self._update_lock.acquire()
            self._update_lock.release()
            return

        await self._update_lock.acquire()
        success = False
        try:
            logger.info('Updating pokecache')
            await self.get_url('https://japeal.com/pkm/')

            # Get a list of tuples in the format of ("XXX Pokemon name", internal id)
            rows = self._driver.execute_script('return [...document.getElementById("msdropdown20_child").querySelectorAll("*[value]")].map(p => [p.innerText, p.getAttribute("value")])')

            for p in rows:
                i = int(p[1])
                name = p[0].split(' ', 1)[-1].lower().strip()
                if name.endswith('(new)'):
                    name = name[:-6]
                self._pokemon[name] = i
                self._poke_reverse[i] = name

            self._poke_ids = list(self._poke_reverse.keys())

            types = filter(lambda f: f.startswith('sprPKMType_'), os.listdir(self._data_folder))
            await self.cache_types(start=max(len(list(types)), 1))
            self.LAST_UPDATED = time.time()
            success = True
        except:  # skipcq: FLK-E722
            logger.exception('Failed to update pokefusion cache')
        finally:
            self._update_lock.release()
            return success

    def get_by_name(self, name):
        poke = self._pokemon.get(name.lower())
        if poke is None:
            for poke_, v in self._pokemon.items():
                if name in poke_:
                    return v
        return poke

    def get_pokemon(self, name):
        if name == self.RANDOM and self._poke_ids:
            # Get a random id of a pokemon
            return self._poke_ids[randint(0, len(self._poke_ids) - 1)]
        else:
            return self.get_by_name(name)

    async def get_url(self, url):
        # Attempt at making phantomjs async friendly
        # After visiting the url remember to put 1 item in self.queue
        # Otherwise the browser will be locked

        # If lock is not locked lock it until this operation finishes
        # This is required because some operations acquire the lock and call this function
        unlock = False
        if not self._driver_lock.locked():
            await self._driver_lock.acquire()
            unlock = True

        f = partial(self.driver.get, url)
        try:
            await self.bot.loop.run_in_executor(self.bot.threadpool, f)
        except UnexpectedAlertPresentException:
            self._driver.get_screenshot_as_file('test.png')
            self._driver.switch_to.alert.accept()
        if unlock:
            try:
                self._driver_lock.release()
            except RuntimeError:
                pass

    async def fuse(self, poke1=RANDOM, poke2=RANDOM):

        # Update cache once per week
        if time.time() - self.LAST_UPDATED > 604800:
            if not await self.update_cache():
                raise BotException('Could not cache pokemon')

        dex_n = []
        for p in (poke1, poke2):
            poke = self.get_pokemon(p)
            if poke is None:
                raise NoPokeFoundException(p)
            dex_n.append(poke)

        fmt = bytes(f'p1={dex_n[1]}@p2={dex_n[0]}', 'utf8')

        url = f'https://japeal.com/pkm/?efc={base64.b64encode(fmt).decode("ascii")}'

        async with self._driver_lock:
            driver = self.driver
            try:
                await self.get_url(url)
            except UnexpectedAlertPresentException:
                driver.switch_to.alert.accept()
                raise BotException('Invalid pokemon given')

            img_found = False
            for _ in range(3):
                # Char0div is the pokemon without the blue bg
                # If you want the blue bg use this
                # return document.getElementById('image').src
                data = driver.execute_script("return document.getElementById('Char0div').style.backgroundImage")
                if data and data.startswith('url("data:image/png'):
                    img_found = True
                    break
                await asyncio.sleep(1)

            if not img_found:
                raise BotException('Failed to get image of fused pokemon')

            types = driver.execute_script("return [document.getElementById('FusedTypeL').src, document.getElementById('FusedTypeR').src]")
            name = driver.execute_script("return document.getElementById('fnametxt').textContent")

        data = data.replace('url("data:image/png;base64,', '', 1)[:-1]
        # This fixes incorrect padding error
        img = Image.open(BytesIO(base64.b64decode(data + '===')))
        type_imgs = []

        for tp in types:
            file = tp.split('/')[-1]
            try:
                im = Image.open(os.path.join(self._data_folder, file))
                type_imgs.append(im)
            except (FileNotFoundError, OSError):
                raise BotException('Error while getting type images')

        bg = Image.open(os.path.join(self._data_folder, 'poke_bg.png'))

        # Paste pokemon in the middle of the background
        x, y = (bg.width//2-img.width//2, bg.height//2-img.height//2)
        bg.paste(img, (x, y), img)

        w, h = type_imgs[0].size
        padding = 2
        # Total width of all type images combined with padding
        type_w = len(type_imgs) * (w + padding)
        width = bg.width
        start_x = (width - type_w)//2
        y = y + img.height

        for tp in type_imgs:
            bg.paste(tp, (start_x, y), tp)
            start_x += w + padding

        font = ImageFont.truetype(os.path.join('M-1c', 'mplus-1c-bold.ttf'), 36)
        draw = ImageDraw.Draw(bg)

        name = name.strip()

        # Names need to be taken in reverse since the site treats the first pokemon as the rightmost one on the site
        pokename1 = self._poke_reverse[dex_n[1]]
        pokename2 = self._poke_reverse[dex_n[0]]

        # if name not present generate our own
        if not name:
            name = pokename1[:ceil(len(pokename1)/2)].title() + pokename2[ceil(len(pokename2)/2):]

        # If only half of name possibly present generate the other half based on
        # which name contains the given part
        elif len(name) <= 6:
            if name.lower() in pokename1:
                name = name + pokename2[ceil(len(pokename2)/2):]
            elif name.lower() in pokename2:
                name = pokename1[:ceil(len(pokename1)/2)].title() + name

        w, h = draw.textsize(name, font)
        draw.text(((bg.width-w)//2, bg.height//2-img.height//2 - h), name, font=font, fill='black')

        s = 'Fusion of {} and {}'.format(pokename2, pokename1)
        return bg, s


class Images(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.threadpool = bot.threadpool
        try:
            self._pokefusion = Pokefusion(bot)
        except WebDriverException:
            logger.exception('failed to load pokefusion')
            self._pokefusion = None

        self.mgr_lock = asyncio.Lock()

    def cog_unload(self):
        if self._pokefusion and self._pokefusion._driver:
            self._pokefusion._driver.quit()
            self._pokefusion._driver = None

    def cog_check(self, ctx):  # skipcq: PYL-R0201
        if not check_botperm('attach_files', ctx=ctx):
            raise BotMissingPermissions(('attach_files', ))

        return True

    async def image_func(self, func, *args, **kwargs):
        return await self.bot.loop.run_in_executor(self.bot.threadpool, func, *args, **kwargs)

    @staticmethod
    def save_image(img, format='PNG'):
        data = BytesIO()
        img.save(data, format)
        data.seek(0)
        return data

    @staticmethod
    def stretch_image(im):
        return im.mode != 'RGBA'

    @command()
    @cooldown(3, 5, type=BucketType.guild)
    async def anime_deaths(self, ctx, image=None):
        """Generate a top 10 anime deaths image based on provided image"""
        path = os.path.join(TEMPLATES, 'saddest-anime-deaths.png')
        img = await get_image(ctx, image)
        if img is None:
            return

        await ctx.trigger_typing()

        def do_it():
            nonlocal img

            x, y = 9, 10
            w, h = 854, 480
            template = Image.open(path)
            img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=False, resample=Image.BILINEAR)
            new_w, new_h = img.width, img.height
            if new_w != w:
                x += int((w - new_w)/2)

            if new_h != h:
                y += int((h - new_h) / 2)

            img = img.convert("RGBA")
            template.paste(img, (x, y), img)
            return self.save_image(template)

        await ctx.send(file=File(await self.image_func(do_it), filename='top10-anime-deaths.png'))

    @command()
    @cooldown(3, 5, type=BucketType.guild)
    async def anime_deaths2(self, ctx, image=None):
        """same as anime_deaths but with a transparent bg"""
        path = os.path.join(TEMPLATES, 'saddest-anime-deaths2.png')
        img = await get_image(ctx, image)
        if img is None:
            return

        await ctx.trigger_typing()

        def do_it():
            nonlocal img

            x, y = 9, 10
            w, h = 854, 480
            template = Image.open(path)
            img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=False, resample=Image.BILINEAR)
            new_w, new_h = img.width, img.height
            if new_w != w:
                x += int((w - new_w)/2)

            if new_h != h:
                y += int((h - new_h) / 2)

            img = img.convert("RGBA")
            template.paste(img, (x, y), img)
            return self.save_image(template)

        await ctx.send(file=File(await self.image_func(do_it), filename='top10-anime-deaths.png'))

    @command()
    @cooldown(3, 5, type=BucketType.guild)
    async def trap(self, ctx, image=None):
        """Is it a trap?
        """
        img = await get_image(ctx, image)
        if img is None:
            return

        await ctx.trigger_typing()

        def do_it():
            nonlocal img

            path = os.path.join(TEMPLATES, 'is_it_a_trap.png')
            path2 = os.path.join(TEMPLATES, 'is_it_a_trap_layer.png')
            img = img.convert("RGBA")
            x, y = 820, 396
            w, h = 355, 505
            rotation = -22.5

            img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=False,
                                           resample=Image.BILINEAR)
            img = img.rotate(rotation, expand=True, resample=Image.BILINEAR)
            x_place = x - int(img.width / 2)
            y_place = y - int(img.height / 2)

            template = Image.open(path)

            template.paste(img, (x_place, y_place), img)
            layer = Image.open(path2)
            template.paste(layer, (0, 0), layer)
            return self.save_image(template)

        await ctx.send(file=File(await self.image_func(do_it), filename='is_it_a_trap.png'))

    @command(aliases=['jotaro_no'])
    @cooldown(3, 5, BucketType.guild)
    async def jotaro(self, ctx, image=None):
        """Jotaro wasn't pleased"""
        img = await get_image(ctx, image)
        if img is None:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img

            # The size we want from the transformation
            width = 524
            height = 326
            d_x = 90
            w, h = img.size

            coeffs = find_coeffs(
                [(d_x, 0), (width - d_x, 0), (width, height), (0, height)],
                [(0, 0), (w, 0), (w, h), (0, h)])

            img = img.transform((width, height), Image.PERSPECTIVE, coeffs,
                                Image.BICUBIC)

            template = os.path.join(TEMPLATES, 'jotaro.png')
            template = Image.open(template)

            white = Image.new('RGBA', template.size, 'white')

            x, y = 9, 351
            white.paste(img, (x, y))
            white.paste(template, mask=template)

            return self.save_image(white)

        await ctx.send(file=File(await self.image_func(do_it), filename='jotaro_no.png'))

    @command(aliases=['jotaro2'])
    @cooldown(2, 5, BucketType.guild)
    async def jotaro_photo(self, ctx, image=None):
        """Jotaro takes an image and looks at it"""
        # Set to false because discord doesn't embed it correctly
        # Should be used if it can be embedded since the file size is much smaller
        use_webp = False

        img = await get_image(ctx, image)
        if img is None:
            return

        extension = 'webp' if use_webp else 'gif'
        await ctx.trigger_typing()

        def do_it():
            nonlocal img

            r = 34.7
            x = 6
            y = -165
            width = 468
            height = 439
            duration = [120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120,
                        80, 120, 120, 120, 120, 120, 30, 120, 120, 120, 120, 120,
                        120, 120, 760, 2000]  # Frame timing

            template = Image.open(os.path.join(TEMPLATES, 'jotaro_photo.gif'))
            frames = [frame.copy().convert('RGBA') for frame in ImageSequence.Iterator(template)]
            template.close()

            photo = os.path.join(TEMPLATES, 'photo.png')
            finger = os.path.join(TEMPLATES, 'finger.png')

            im = Image.open(photo)
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (width, height), resample=Image.BICUBIC,
                                           can_be_bigger=False, crop_to_size=True,
                                           center_cropped=True, background_color='black')
            w, h = img.size
            width, height = (472, 441)
            coeffs = find_coeffs(
                [(0, 0), (437, 0), (width, height), (0, height)],
                [(0, 0), (w, 0), (w, h), (0, h)])
            img = img.transform((width, height), Image.PERSPECTIVE, coeffs,
                                Image.BICUBIC)
            img = img.rotate(r, resample=Image.BICUBIC, expand=True)
            im.paste(img, box=(x, y), mask=img)
            finger = Image.open(finger)
            im.paste(finger, mask=finger)
            frames[-1] = im

            if use_webp:
                # We save room for some colors when not using the shadow in a gif
                shadow = os.path.join(TEMPLATES, 'photo.png')
                im.alpha_composite(shadow)
                kwargs = {}
            else:
                # Duration won't work in the save() params when using a gif so I have to do it this way
                frames[0].info['duration'] = duration
                kwargs = {'optimize': True}

            file = BytesIO()
            frames[0].save(file, format=extension, save_all=True, append_images=frames[1:], duration=duration, **kwargs)
            if file.tell() > 8000000:
                raise BotException('Generated image was too big in filesize')

            file.seek(0)
            return file

        await ctx.send(file=File(await self.image_func(do_it), filename='jotaro_photo.{}'.format(extension)))

    @command(aliases=['jotaro3'])
    @cooldown(2, 5, BucketType.guild)
    async def jotaro_smile(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img

            im = Image.open(os.path.join(TEMPLATES, 'jotaro_smile.png'))
            img = img.convert('RGBA')
            i = Image.new('RGBA', im.size, 'black')
            size = (337, 350)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                           crop_to_size=True, center_cropped=True,
                                           resample=Image.BICUBIC)
            img = img.rotate(13.7, Image.BICUBIC, expand=True)
            x, y = (207, 490)
            i.paste(img, (x, y), mask=img)
            i.paste(im, mask=im)

            return self.save_image(i)

        await ctx.send(file=File(await self.image_func(do_it), filename='jotaro.png'))

    @command(aliases=['jotaro4'])
    @cooldown(2, 5, BucketType.guild)
    async def jotaro_photo2(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'jotaro_photo2.png'))
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (305, 440), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)

            img = img.rotate(5, Image.BICUBIC, expand=True)
            bg = Image.new('RGBA', template.size)

            bg.paste(img, (460, 841), img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='jotaro_photo.png'))

    @command(aliases=['tbc'])
    @cooldown(2, 5, BucketType.guild)
    async def tobecontinued(self, ctx, image=None, no_sepia=False):
        """Make a to be continued picture
        Usage: {prefix}{name} `image/emote/mention` `[optional sepia filter off] on/off`
        Sepia filter is on by default
        """
        img = await get_image(ctx, image)
        if not img:
            return

        await ctx.trigger_typing()

        def do_it():
            nonlocal img
            if not no_sepia:
                img = sepia(img)

            width, height = img.width, img.height
            if width < 300:
                width = 300

            if height < 200:
                height = 200

            img = resize_keep_aspect_ratio(img, (width, height), resample=Image.BILINEAR)
            width, height = img.width, img.height
            tbc = Image.open(os.path.join(TEMPLATES, 'tbc.png'))
            x = int(width * 0.09)
            y = int(height * 0.90)
            tbc = resize_keep_aspect_ratio(tbc, (width * 0.5, height * 0.3),
                                           can_be_bigger=False, resample=Image.BILINEAR)

            if y + tbc.height > height:
                y = height - tbc.height - 10

            img.paste(tbc, (x, y), tbc)

            return self.save_image(img)

        await ctx.send(file=File(await self.image_func(do_it), filename='To_be_continued.png'))

    @command(aliases=['heaven', 'heavens_door'])
    @cooldown(2, 5, BucketType.guild)
    async def overheaven(self, ctx, image=None):
        img = await get_image(ctx, image)
        if not img:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img
            overlay = Image.open(os.path.join(TEMPLATES, 'heaven.png'))
            base = Image.open(os.path.join(TEMPLATES, 'heaven_base.png'))
            size = (750, 750)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                           crop_to_size=True, center_cropped=True)

            img = img.convert('RGBA')
            x, y = (200, 160)
            base.paste(img, (x, y), mask=img)
            base.alpha_composite(overlay)
            return self.save_image(base)

        await ctx.send(file=File(await self.image_func(do_it), filename='overheaven.png'))

    @command(aliases=['puccireset'])
    @cooldown(2, 5, BucketType.guild)
    async def pucci(self, ctx, image=None):
        img = await get_image(ctx, image)
        if not img:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img
            img = img.convert('RGBA')
            im = Image.open(os.path.join(TEMPLATES, 'pucci_bg.png'))
            overlay = Image.open(os.path.join(TEMPLATES, 'pucci_faded.png'))
            size = (682, 399)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                           crop_to_size=True, center_cropped=True)
            x, y = (0, 367)
            im.paste(img, (x, y), mask=img)
            im.alpha_composite(overlay)
            return self.save_image(im)

        await ctx.send(file=File(await self.image_func(do_it), filename='pucci_reset.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def dio(self, ctx, image=None):
        img = await get_image(ctx, image)
        if not img:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img
            img = img.convert('RGBA')
            template = Image.open(os.path.join(TEMPLATES, 'dio.png'))
            bg = Image.new('RGBA', template.size, 'black')
            size = (512, 376)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=True,
                                           resample=Image.BICUBIC)
            x, y = (117, 386)
            bg.paste(img, (x, y), mask=img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        await ctx.send(
            file=File(await self.image_func(do_it), filename='dio.png'))

    @command(aliases=['epitaph'])
    @cooldown(2, 5, BucketType.guild)
    async def doppio(self, ctx, image=None):
        """image of doppio"""
        img = await get_image(ctx, image)
        if not img:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img
            img = img.convert('RGBA')
            im = Image.open(os.path.join(TEMPLATES, 'doppio.png'))
            bg = Image.new('RGBA', im.size, 'black')

            x, y = (135, 196)
            width = 500
            height = 408
            if img.width > img.height:
                img = resize_keep_aspect_ratio(img, (None, height), resample=Image.BICUBIC)
                x = x + (width - img.width)//2
            else:
                img = resize_keep_aspect_ratio(img, (width, None), resample=Image.BICUBIC)
                y = y + (height - img.height)//2

            bg.paste(img, (x, y), mask=img)
            bg.alpha_composite(im)
            return self.save_image(bg)

        await ctx.send(file=File(await self.image_func(do_it), filename='epitaph.png'))

    @command(aliases=['cloud'])
    @cooldown(2, 5, BucketType.guild)
    async def clouds(self, ctx, image=None):
        img = await get_image(ctx, image)
        if not img:
            return
        await ctx.trigger_typing()

        def do_it():
            nonlocal img
            img = img.convert('RGBA')
            template = Image.open(os.path.join(TEMPLATES, 'cloud.png'))
            size = (151, 212)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                           resample=Image.BICUBIC)
            img = img.rotate(17, Image.BICUBIC, True)
            x, y = (412, 1578)
            template.paste(img, (x, y), mask=img)
            return self.save_image(template)

        await ctx.send(
            file=File(await self.image_func(do_it), filename='dio.png'))

    @command()
    @cooldown(1, 10, BucketType.guild)
    async def party(self, ctx, image=None):
        """Takes a long ass time to make the gif"""
        img = await get_image(ctx, image)
        if img is None:
            return

        async with ctx.typing():
            img = await self.bot.loop.run_in_executor(self.threadpool, partial(gradient_flash, img, get_raw=True))
        await ctx.send(content=f"Use {ctx.prefix}party2 if transparency guess went wrong",
                       file=File(img, filename='party.gif'))

    @command()
    @cooldown(1, 10, BucketType.guild)
    async def party2(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        async with ctx.typing():
            img = await self.bot.loop.run_in_executor(self.threadpool, partial(gradient_flash, img, get_raw=True, transparency=False))
        await ctx.send(file=File(img, filename='party.gif'))

    @command()
    @cooldown(2, 5, type=BucketType.guild)
    async def blurple(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            im = Image.new('RGBA', img.size, color='#7289DA')
            img = img.convert('RGBA')
            if img.format == 'GIF':
                def multiply(frame):
                    return ImageChops.multiply(frame, im)

                data = func_to_gif(img, multiply,  get_raw=True)
                name = 'blurple.gif'
            else:
                img = ImageChops.multiply(img, im)
                data = self.save_image(img)
                name = 'blurple.png'

            return data, name

        async with ctx.typing():
            file = File(*await self.image_func(do_it))
        await ctx.send(file=file)

    @command(aliases=['gspd', 'gif_spd', 'speedup', 'gspeed'])
    @cooldown(2, 5)
    async def gif_speed(self, ctx, image, speed: float=None):
        """
        Speed up or slow a gif down by multiplying the frame delay
        the specified speed (higher is faster, lower is slower, 1 is default speed).
        When gif speed cannot be increased by usual means this will start removing frames from the gif
        which makes the gif faster up to a point. After being sped up too much the gif will be reduced to a single frame.
        Due to the fact that different engines render gifs differently higher speed
        might not actually mean faster gif. After a certain threshold
        the engine will start throttling and set the frame delay to a preset default
        If this happens try making the speed value smaller
        """
        if speed is None:
            img = await get_image(ctx, None)
            speed = image
        else:
            img = await get_image(ctx, image)

        if img is None:
            return

        if not isinstance(img, GifImagePlugin.GifImageFile):
            raise BadArgument('Image must be a gif')

        try:
            speed = float(speed)
        except (ValueError, TypeError) as e:
            raise BadArgument(str(e))

        if speed == 1:
            return await ctx.send("Setting speed to 1 won't change the speed ya know")

        if not 0 < speed <= 10:
            raise BadArgument('Speed must be larger than 0 and less or equal to 10')

        def do_speedup():
            frames = convert_frames(img, 'RGBA')
            durations = get_duration(frames)
            duration_changed = 0

            def transform(duration):
                nonlocal duration_changed
                # Frame delay is stored as an unsigned 2 byte int
                # A delay of 0 would mean that the frame would change as fast
                # as the pc can do it which is useless. Also rendering engines
                # like to round delays higher up to 10 and most don't display the
                # smallest delays
                # The smallest delay chromium accepts is 0.02 seconds or 20ms
                # If the value goes below a way larger delay is used which is
                # usually 100ms
                if duration < 20:
                    duration = 100

                original = duration

                duration = min(max(duration//speed, 20), 65535)
                if duration != original:
                    duration_changed += 1

                return duration

            durations = list(map(transform, durations))
            # Percentage of frame delays that were changed
            percentage_changed = duration_changed/len(durations)

            # If under 5% of durations changed start removing frames
            # This will always leave at least one frame intact
            if speed > 1 and percentage_changed <= 0.05:
                # We remove every 11//speed indice. The number 5 was chosen
                # for no particular reason
                step = max(int(5//speed), 2)  # Values lower than 2 will remove every frame
                del durations[1::step]
                del frames[1::step]

            frames[0].info['duration'] = durations
            for f, d in zip(frames, durations):
                f.info['duration'] = d

            frames = apply_transparency(frames)
            file = BytesIO()
            frames[0].save(file, format='GIF', duration=durations, save_all=True,
                           append_images=frames[1:], loop=65535, optimize=True, disposal=2)
            file.seek(0)
            return file

        async with ctx.typing():
            file = await self.image_func(do_speedup)
        await ctx.send(file=File(file, filename='speedup.gif'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def smug(self, ctx, image=None):
        img = await get_image(ctx, image)

        if img is None:
            return

        def do_it():
            nonlocal img
            img = img.convert('RGBA')
            template = Image.open(os.path.join(TEMPLATES, 'smug_man.png'))

            w, h = 729, 607
            img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)
            template.paste(img, (168, 827), img)
            return self.save_image(template)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='smug_man.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def linus(self, ctx, stretch: Optional[bool]=True, image=None):
        """
        if you set stretch off the image will won't be stretched.
        Default behavior is stretch on

        `{prefix}{name} off image`
        This will set image stretching off
        """
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'linus.png'))
            bg = Image.new('RGBA', template.size, color="black")

            w, h = 1230, 792
            if stretch:
                img = img.resize((w, h), resample=Image.BICUBIC)
            else:
                img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=True,
                                               crop_to_size=True,
                                               center_cropped=True,
                                               resample=Image.BICUBIC)

            # Top and bottom left corner not transformed
            # right corners transformed inwards
            coeffs = find_coeffs(
                [(0, 0), (w, 66), (w, 730), (0, h)],
                [(0, 0), (w, 0), (w, h), (0, h)])

            img = img.transform((w, h), Image.PERSPECTIVE, coeffs,
                                Image.BICUBIC)

            bg.alpha_composite(img.convert('RGBA'), (155, 12))
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='linus.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def seeyouagain(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'seeyouagain.png'))
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (360, 300), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)

            template.paste(img, (800, 915), img)
            return self.save_image(template)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='see_you_again.png'))

    @command(aliases=['sha'])
    @cooldown(2, 5, BucketType.guild)
    async def sheer_heart_attack(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'sheer_heart_attack.png'))
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (1000, 567), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True, background_color='white')

            template.paste(img, (0, 563), img)
            return self.save_image(template)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='sha.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def kira(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'kira.png'))
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (810, 980), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)

            bg = Image.new('RGBA', (1918, 2132), (0, 0, 0, 0))

            bg.paste(img, (610, 1125), img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='kira.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def josuke(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'josuke.png'))
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (198, 250), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)

            bg = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))

            bg.paste(img, (1000, 155), img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='josuke.png'))

    @command(aliases=['josuke2'])
    @cooldown(2, 5, BucketType.guild)
    async def josuke_binoculars(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'josuke_binoculars.png'))
            img = img.convert('RGBA')
            size = (700, 415)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)

            bg = Image.new('RGBA', template.size, (255, 255, 255))

            bg.paste(img, (50, 460), img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='josuke_binoculars.png'))

    @command(aliases=['02'])
    @cooldown(2, 5, BucketType.guild)
    async def zerotwo(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'zerotwo.png')).convert('RGBA')
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (840, 615), can_be_bigger=False,
                                           resample=Image.BICUBIC, crop_to_size=True,
                                           center_cropped=True)

            img = img.rotate(4, Image.BICUBIC, expand=True)

            template.alpha_composite(img, (192, 29))
            return self.save_image(template)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='02.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def dante(self, ctx, image=None):
        """Dante looking at a scene"""
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'dante.png')).convert('RGBA')
            img = img.convert('RGBA')
            img = img.resize((1316, 990), resample=Image.BICUBIC)

            img.alpha_composite(template, (0, 0))
            return self.save_image(img)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='dante.png'))

    @command()
    @cooldown(2, 8, BucketType.guild)
    async def v(self, ctx, *, images=''):
        """Image of V reading a book. Needs 2 images for both of the pages"""
        images = await get_images(ctx, images, leave_empty=True)
        if len(images) < 2:
            await ctx.send("Did not find 2 images in your message")
            return

        img1 = await dl_image(ctx, images[0])
        img2 = None
        if img1:
            img2 = await dl_image(ctx, images[1])

        if not img1 or not img2:
            return

        def do_it():
            nonlocal img1, img2
            template = Image.open(os.path.join(TEMPLATES, 'v.png')).convert('RGBA')
            img = img1.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (370, 475), can_be_bigger=False,
                                           resample=Image.BILINEAR, crop_to_size=True,
                                           center_cropped=True)

            template.alpha_composite(img, (100, 590))

            img = img2.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (380, 475), can_be_bigger=False,
                                           resample=Image.BILINEAR, crop_to_size=True,
                                           center_cropped=True)
            template.alpha_composite(img, (518, 592))

            return self.save_image(template)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='v.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def chrollo(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'chrollo.png'))
            img = img.convert('RGBA')
            size = (1280, 720)
            img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                           resample=Image.BICUBIC,
                                           crop_to_size=True,
                                           center_cropped=True)

            template.alpha_composite(img, (0, 719))
            return self.save_image(template)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='chrollo.png'))

    @command(aliases=['zura'])
    @cooldown(2, 5, BucketType.guild)
    async def katsura(self, ctx, stretch: Optional[bool]=True, image=None):
        """
        If stretch is set on (default) the image will be stretched in order to fit
        """
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'katsura.png'))
            bg = Image.new('RGBA', template.size, (0,0,0,0))
            img = img.convert('RGBA')
            size = (1274, 793)
            if stretch:
                img = img.resize(size, resample=Image.BICUBIC)
            else:
                img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                               resample=Image.BICUBIC,
                                               crop_to_size=True,
                                               center_cropped=True)

            bg.paste(img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='ah_shit.png'))

    @command(aliases=['cj'])
    @cooldown(2, 5, BucketType.guild)
    async def ah_shit(self, ctx, stretch: Optional[bool]=True, image=None):
        """
        If stretch is set off the image will not be stretched to size
        """
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'ah_shit.png'))
            img = img.convert('RGBA')
            size = (843, 553)
            if stretch:
                img = img.resize(size, resample=Image.BICUBIC)
            else:
                img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                               resample=Image.BICUBIC,
                                               crop_to_size=True,
                                               center_cropped=True)

            img.alpha_composite(template)
            return self.save_image(img)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='ah_shit.png'))

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def secco(self, ctx, image=None):
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'secco.png'))
            bg = Image.new('RGBA', template.size, 'white')
            img = img.convert('RGBA')
            img = resize_keep_aspect_ratio(img, (250, 350), can_be_bigger=True,
                                           resample=Image.BICUBIC,
                                           crop_to_size=True,
                                           center_cropped=True)
            width, height = (409, 235)
            w, h = img.size

            coeffs = find_coeffs(
                [(0, 20), (223, 0), (width, 185), (207, height)],
                [(0, 0), (w, 0), (w, h), (0, h)])

            img = img.transform((width, height), Image.PERSPECTIVE, coeffs,
                                Image.BICUBIC)

            bg.alpha_composite(img, (241, 251))
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='secco.png'))

    @command(aliases=['greatview'])
    @cooldown(2, 5, BucketType.guild)
    async def giorno(self, ctx, stretch: Optional[bool]=True, image=None):
        """
        If stretch is set off the image will not be stretched to size
        """
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img
            template = Image.open(os.path.join(TEMPLATES, 'whatagreatview.png'))
            img = img.convert('RGBA')
            size = (868, 607)
            if stretch:
                img = img.resize(size, resample=Image.BICUBIC)
            else:
                img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                               resample=Image.BICUBIC,
                                               crop_to_size=True,
                                               center_cropped=True)

            bg = Image.new('RGBA', template.size, 'white')
            bg.paste(img, (212, 608), img)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='02.png'))

    @command()
    @cooldown(2, 7, BucketType.guild)
    async def thinking(self, ctx, stretch: Optional[bool]=None, image=None):
        """
        Stretch is either on or off. If stretch is on the image is stretched in order
        to fit in the image.

        By default the value of stretch is automatically decided based on
        if the given image is transparent (stretch is off) or not (stretch is on)
        """
        img = await get_image(ctx, image)
        if img is None:
            return

        def do_it():
            nonlocal img, stretch
            if stretch is None:
                stretch = self.stretch_image(img)

            template = Image.open(os.path.join(TEMPLATES, 'thinkingTemplate.png'))
            img = img.convert('RGBA')
            size = (565, 475)
            if stretch:
                img = img.resize(size, resample=Image.BICUBIC)
            else:
                img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                               resample=Image.BICUBIC,
                                               crop_to_size=True,
                                               center_cropped=True)

            mask = Image.open(os.path.join(TEMPLATES, 'thinkingTemplateMask.png'))
            bg = Image.new('RGBA', template.size, 'white')
            bg.alpha_composite(img)
            bg = ImageChops.multiply(bg, mask)
            bg.alpha_composite(template)
            return self.save_image(bg)

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='thinkingAbout.png'))

    @command(aliases=['mgr'])
    @cooldown(1, 5, BucketType.guild)
    async def armstrong(self, ctx, stretch: Optional[bool]=None, image=None):
        """Revengeance status"""
        img = await get_image(ctx, image)
        outfile = os.path.join(TEMP_DATA, 'armstrong_out.mp4')
        if img is None:
            return

        def do_it():
            nonlocal img, stretch

            if stretch is None:
                stretch = self.stretch_image(img)

            img = img.convert('RGBA')
            size = (1280, 720)
            if stretch:
                img = img.resize(size, resample=Image.BICUBIC)
            else:
                img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                               resample=Image.BICUBIC,
                                               crop_to_size=True,
                                               center_cropped=True)

            files = [
                '-i', os.path.join(TEMPLATES, 'armstrong_start.mp4'),
                '-i', os.path.join(TEMPLATES, 'armstrong_mask.mp4'),
                '-i', os.path.join(TEMPLATES, 'armstrong_clipped.mp4'),
                '-i', os.path.join(TEMPLATES, 'armstrong.mp4')
            ]
            cmd = [*shlex.split('ffmpeg -f image2pipe -i -'), *files]
            cmd.extend(shlex.split('-t 8 -r 30000/1001 -filter_complex "[1][2]alphamerge[alf];[0][alf]overlay[ovr];[ovr][3:v]concat" -map 4:a:0 -preset ultrafast'))
            cmd.append(outfile)

            p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
            buf = BytesIO()
            img.save(buf, format='png')
            p.communicate(buf.getvalue())

        async with ctx.typing():
            try:
                await asyncio.wait_for(self.mgr_lock.acquire(), timeout=5)
            except asyncio.TimeoutError:
                await ctx.send('Timed out. Try again in a bit')
                return

            try:
                await ctx.send('Please wait a moment while the video generates.')
                await self.image_func(do_it)

                file = disnake.File(outfile, filename='revengeance_status.mp4', description='Revengeance status')
                await ctx.send(file=file)
            finally:
                self.mgr_lock.release()
                if os.path.exists(outfile):
                    os.remove(outfile)

    @command()
    @cooldown(2, 5, BucketType.guild)
    async def narancia(self, ctx, *, text: CleanContent(escape_markdown=True, fix_channel_mentions=True,
                                                        remove_everyone=False, fix_emotes=True)):
        """
        Make narancia write your choice of text on paper
        """
        text = text.strip('\u200b \n\r\t')

        def do_it():
            nonlocal text
            # Linearly decreasing fontsize
            fontsize = int(round(45.0 - 0.08 * len(text)))
            fontsize = min(max(fontsize, 15), 45)
            font = ImageFont.truetype(os.path.join('M-1c', 'mplus-1c-bold.ttf'), fontsize)
            im = Image.open(os.path.join(TEMPLATES, 'narancia.png'))
            shadow = Image.open(os.path.join(TEMPLATES, 'narancia_shadow.png'))
            draw = ImageDraw.Draw(im)
            size = (250, 350)  # Size of the page
            spot = (400, 770)  # Pasting spot for first page
            text = text.replace('\n', ' ')

            # We need to replace the height of the text with the height of A
            # Since that what draw.text uses in it's text drawing methods but not
            # in the text size methods. Nice design I know. It makes textsize inaccurate
            # so don't use that method
            text_size = font.getsize(text)
            text_size = (text_size[0], font.getsize('A')[1])

            # Linearly growing spacing
            spacing = int(round(0.5 + 0.167 * fontsize))
            spacing = min(max(spacing, 3), 6)

            # We add 2 extra to compensate for measuring inaccuracies
            line_height = text_size[1]
            spot_changed = False

            all_lines = []
            # Split lines based on average width
            # If max characters per line is less than the given max word
            # use max line width as max word width
            max_line = int(len(text) // ((text_size[0] or 1) / size[0]))
            lines = split_string(text, maxlen=max_line, max_word=min(max_line, 30))
            total_y = 0

            for line in lines:
                line = line.strip()
                if not line:
                    continue

                total_y += line_height
                if total_y > size[1]:
                    draw.multiline_text(spot, '\n'.join(all_lines), font=font,
                                        fill='black', spacing=spacing)
                    all_lines = []
                    if spot_changed:
                        # We are already on second page. Let's stop here
                        break

                    spot_changed = True
                    # Pasting spot and size for second page
                    spot = (678, 758)
                    size = (250, 350)
                    total_y = line_height

                total_y += spacing

                all_lines.append(line)

            draw.multiline_text(spot, '\n'.join(all_lines), font=font,
                                fill='black', spacing=spacing)

            im.alpha_composite(shadow)
            return self.save_image(im, 'PNG')

        async with ctx.typing():
            file = await self.image_func(do_it)
        await ctx.send(file=File(file, filename='narancia.png'))

    @command(aliases=['poke', 'pf'])
    @cooldown(1, 3, type=BucketType.guild)
    async def pokefusion(self, ctx, poke1=Pokefusion.RANDOM, poke2=Pokefusion.RANDOM):
        """
        Gets a random pokemon fusion from http://pokefusion.japeal.com
        You can specify the wanted fusion by their name or just a part of their name.
        Passing % as a parameter will randomize that value. By default both pokemon are randomized
        """
        if not self._pokefusion:
            return await ctx.send('Pokefusion not supported')
        await ctx.trigger_typing()
        try:
            img, s = await self._pokefusion.fuse(poke1, poke2)
        except NoPokeFoundException as e:
            return await ctx.send(str(e))

        file = BytesIO()
        img.save(file, 'PNG')
        file.seek(0)
        await ctx.send(s, file=File(file, filename='pokefusion.png'))

    @command(aliases=['get_im', 'getim'])
    @cooldown(3, 3, BucketType.guild)
    async def get_image(self, ctx, *, data=None):
        """Get's the latest image in the channel if data is None
        otherwise gets the image based on data. If data is an id, first avatar lookup is done
        then message lookup. If data is an image url this will just return that url"""
        img = await get_image_from_ctx(ctx, data)
        s = img if img else 'No image found'
        await ctx.send(s, undoable=True)

    @command(aliases=['get_ims', 'getims'])
    @cooldown(3, 3, BucketType.guild)
    async def get_images(self, ctx, *, data=None):
        """Get all images from given data.
        To get images from another message give the id of that message (only 1 id, no more).
        If data contains an id, first it compared to server id and then user ids.
        All urls will be returned as is and embed urls will be extracted"""
        imgs = await get_images(ctx, data)

        def get_page(idx):
            return f'{idx+1}/{len(imgs)}\n{imgs[idx]}'

        paginator = Paginator(imgs, generate_page=get_page, hide_page_count=True,
                              show_stop_button=True)
        await paginator.send(ctx)

    @command()
    @is_owner()
    async def update_poke_cache(self, ctx):
        if await self._pokefusion.update_cache() is False:
            await ctx.send('Failed to update cache')
        else:
            await ctx.send('Successfully updated cache')

    @command(aliases=['mr_graph'])
    @cooldown(1, 10, BucketType.guild)
    @guild_only()
    async def mute_roll_histogram(self, ctx):
        sql = 'SELECT wins::decimal/games FROM mute_roll_stats WHERE guild=%s AND games>3' % ctx.guild.id
        try:
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
            await ctx.send('Failed to get mute roll stats')
            return

        if not rows:
            ctx.command.reset_cooldown(ctx)
            await ctx.send('No applicable mute roll data found')
            return

        def do_histogram():
            buf = None
            try:
                plt.hist([float(row[0]) for row in rows], bins=20, range=(0, 1))
                plt.xlabel('Winrate')
                plt.ylabel('Amount of users')

                buf = BytesIO()
                plt.savefig(buf, format='png', bbox_inches='tight')
                buf.seek(0)
            finally:
                plt.close()
                return buf

        await ctx.trigger_typing()
        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_histogram)

        if not data:
            await ctx.send('Failed to create histogram of mute roll stats')
            return

        await ctx.send(file=File(data, 'mute_roll_stats.png'))


def setup(bot):
    bot.add_cog(Images(bot))

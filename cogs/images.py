import logging
import os
from asyncio import Queue, Lock
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
from random import randint, random

from PIL import Image, ImageSequence, ImageFont, ImageDraw
from discord.ext.commands import cooldown, BucketType
from selenium.webdriver import PhantomJS
from bs4 import BeautifulSoup
import time
import base64

from bot.bot import command
from bot.exceptions import NoPokeFoundException, BotException
from cogs.cog import Cog
from utils.imagetools import (resize_keep_aspect_ratio, image_from_url,
                              gradient_flash, sepia, optimize_gif)
from utils.utilities import get_image_from_message, find_coeffs

logger = logging.getLogger('debug')
TEMPLATES = os.path.join('data', 'templates')


class Pokefusion:
    RANDOM = '%'

    def __init__(self, client, bot):
        self._last_dex_number = 0
        self._pokemon = {}
        self._poke_reverse = {}
        self._last_updated = 0
        self._client = client
        self._data_folder = os.path.join(os.getcwd(), 'data', 'pokefusion')
        self._driver_lock = Lock(loop=bot.loop)
        self.driver = PhantomJS(bot.config.phantomjs)
        self._bot = bot
        self._update_lock = Lock(loop=bot.loop)

    @property
    def bot(self):
        return self._bot

    @property
    def last_dex_number(self):
        return self._last_dex_number

    @property
    def client(self):
        return self._client

    def is_dex_number(self, s):
        # No need to convert when the number is that big
        if len(s) > 5:
            return False
        try:
            return int(s) <= self.last_dex_number
        except ValueError:
            return False

    async def cache_types(self, start=1):
        name = 'sprPKMType_{}.png'
        url = 'http://pokefusion.japeal.com/sprPKMType_{}.png'
        while True:
            r = await self.client.get(url.format(start))
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
        try:
            logger.info('Updating pokecache')
            r = await self.client.get('http://pokefusion.japeal.com/PKMSelectorV3.php')
            soup = BeautifulSoup(await r.text(), 'lxml')
            selector = soup.find(id='s1')
            if selector is None:
                logger.debug('Failed to update pokefusion cache')
                return False

            pokemon = selector.find_all('option')
            for idx, p in enumerate(pokemon[1:]):
                name = ' #'.join(p.text.split(' #')[:-1])
                self._pokemon[name.lower()] = idx + 1
                self._poke_reverse[idx + 1] = name.lower()

            self._last_dex_number = len(pokemon)
            types = filter(lambda f: f.startswith('sprPKMType_'), os.listdir(self._data_folder))
            await self.cache_types(start=max(len(list(types)), 1))
            self._last_updated = time.time()
        except:
            logger.exception('Failed to update pokefusion cache')
        finally:
            self._update_lock.release()

    def get_by_name(self, name):
        poke = self._pokemon.get(name.lower())
        if poke is None:
            for poke_, v in self._pokemon.items():
                if name in poke_:
                    return v
        return poke

    def get_by_dex_n(self, n: int):
        return n if n <= self.last_dex_number else None

    def get_pokemon(self, name):
        if name == self.RANDOM:
            return randint(1, self._last_dex_number)
        if self.is_dex_number(name):
            return int(name)
        else:
            return self.get_by_name(name)

    async def get_url(self, url):
        # Attempt at making phantomjs async friendly
        # After visiting the url remember to put 1 item in self.queue
        # Otherwise the browser will be locked

        # If lock is not locked lock it until this operation finishes
        unlock = False
        if not self._driver_lock.locked():
            await self._driver_lock.acquire()
            unlock = True

        f = partial(self.driver.get, url)
        await self.bot.loop.run_in_executor(self.bot.threadpool, f)
        if unlock:
            try:
                self._driver_lock.release()
            except RuntimeError:
                pass

    async def fuse(self, poke1=RANDOM, poke2=RANDOM, poke3=None):
        # Update cache once per day
        if time.time() - self._last_updated > 86400:
            await self.update_cache()

        dex_n = []
        for p in (poke1, poke2):
            poke = self.get_pokemon(p)
            if poke is None:
                raise NoPokeFoundException(p)
            dex_n.append(poke)

        if poke3 is None:
            color = 0
        else:
            color = self.get_pokemon(poke3)
            if color is None:
                raise NoPokeFoundException(poke3)

        url = 'http://pokefusion.japeal.com/PKMColourV5.php?ver=3.2&p1={}&p2={}&c={}&e=noone'.format(*dex_n, color)
        async with self._driver_lock:
            await self.get_url(url)
            data = self.driver.execute_script("return document.getElementById('image1').src")
            types = self.driver.execute_script("return document.querySelectorAll('*[width=\"30\"]')")
            name = self.driver.execute_script("return document.getElementsByTagName('b')[0].textContent")

        data = data.replace('data:image/png;base64,', '', 1)
        img = Image.open(BytesIO(base64.b64decode(data)))
        type_imgs = []

        for tp in types:
            file = tp.get_attribute('src').split('/')[-1].split('?')[0]
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
        w, h = draw.textsize(name, font)
        draw.text(((bg.width-w)//2, bg.height//2-img.height//2 - 5), name, font=font, fill='black')

        s = 'Fusion of {} and {}'.format(self._poke_reverse[dex_n[0]], self._poke_reverse[dex_n[1]])
        if color:
            s += ' using the color palette of {}'.format(self._poke_reverse[color])
        return bg, s


class Fun(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.driver = PhantomJS(self.bot.config.phantomjs)
        self.threadpool = ThreadPoolExecutor(3)
        self._driver_lock = Lock(loop=bot.loop)
        self.queue = Queue(loop=bot.loop)
        self.queue.put_nowait(1)
        self._pokefusion = Pokefusion(self.bot.aiohttp_client, bot)

    async def _get_image(self, ctx, image):
        img = get_image_from_message(ctx, image)
        if img is None:
            if image is not None:
                await self.bot.say('No image found from %s' % image)
            else:
                await self.bot.say('Please input a mention, emote or an image when using the command')

            return

        img = await self._dl_image(img)
        return img

    async def _dl_image(self, url):
        try:
            img = await image_from_url(url, self.bot.aiohttp_client)
        except OverflowError:
            await self.bot.say('Failed to download. File is too big')
        except TypeError:
            await self.bot.say('Link is not a direct link to an image')
        else:
            return img

    @command(pass_context=True, ignore_extra=True)
    @cooldown(3, 5, type=BucketType.server)
    async def anime_deaths(self, ctx, image=None):
        """Generate a top 10 anime deaths image based on provided image"""
        path = os.path.join(TEMPLATES, 'saddest-anime-deaths.png')
        img = await self._get_image(ctx, image)
        if img is None:
            return

        await self.bot.send_typing(ctx.message.channel)
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
        file = BytesIO()
        template.save(file, format='PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='top10-anime-deaths.png')

    @command(pass_context=True, ignore_extra=True)
    @cooldown(3, 5, type=BucketType.server)
    async def anime_deaths2(self, ctx, image=None):
        """same as anime_deaths but with a transparent bg"""
        path = os.path.join(TEMPLATES, 'saddest-anime-deaths2.png')
        img = await self._get_image(ctx, image)
        if img is None:
            return

        await self.bot.send_typing(ctx.message.channel)
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
        file = BytesIO()
        template.save(file, format='PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='top10-anime-deaths.png')

    @command(pass_context=True, ignore_extra=True)
    @cooldown(3, 5, type=BucketType.server)
    async def trap(self, ctx, image=None):
        """Is it a trap?
        """
        img = await self._get_image(ctx, image)
        if img is None:
            return

        path = os.path.join(TEMPLATES, 'is_it_a_trap.png')
        path2 = os.path.join(TEMPLATES, 'is_it_a_trap_layer.png')
        img = img.convert("RGBA")
        await self.bot.send_typing(ctx.message.channel)
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
        file = BytesIO()
        template.save(file, format='PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='is_it_a_trap.png')

    @command(pass_context=True, ignore_extra=True, aliases=['jotaro_no'])
    @cooldown(3, 5, BucketType.server)
    async def jotaro(self, ctx, image=None):
        """Jotaro wasn't pleased"""
        img = await self._get_image(ctx, image)
        if img is None:
            return
        await self.bot.send_typing(ctx.message.channel)
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

        file = BytesIO()
        white.save(file, format='PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='jotaro_no.png')

    @command(pass_context=True, ignore_extra=True, aliases=['jotaro_photo'])
    @cooldown(2, 5, BucketType.server)
    async def jotaro2(self, ctx, image=None):
        """Jotaro takes an image and looks at it"""
        # Set to false because discord doesn't embed it correctly
        # Should be used if it can be embedded since the file size is much smaller
        use_webp = False

        img = await self._get_image(ctx, image)
        if img is None:
            return
        await self.bot.send_typing(ctx.message.channel)

        r = 34.7
        x = 6
        y = -165
        width = 468
        height = 439
        duration = [120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120, 120,
                    80, 120, 120, 120, 120, 120, 30, 120, 120, 120, 120, 120,
                    120, 120, 760, 2000]  # Frame timing

        frames = [frame.copy().convert('RGBA') for frame in ImageSequence.Iterator(Image.open(os.path.join(TEMPLATES, 'jotaro_photo.gif')))]
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
            extension = 'webp'
            kwargs = {}
        else:
            # Duration won't work in the save() params when using a gif so I have to do it this way
            frames[0].info['duration'] = duration
            extension = 'gif'
            kwargs = {'optimize': True}

        file = BytesIO()
        frames[0].save(file, format=extension, save_all=True, append_images=frames[1:], duration=duration, **kwargs)
        if file.tell() > 8000000:
            return await self.bot.say('Generated image was too big in filesize')
        file.seek(0)
        file = await self.bot.loop.run_in_executor(self.threadpool, partial(optimize_gif, file.getvalue()))
        await self.bot.send_file(ctx.message.channel, file, filename='jotaro_photo.{}'.format(extension))

    @command(pass_context=True, ignore_extra=True, aliases=['jotaro3'])
    @cooldown(2, 5, BucketType.server)
    async def jotaro_smile(self, ctx, image=None):
        img = await self._get_image(ctx, image)
        if img is None:
            return
        await self.bot.send_typing(ctx.message.channel)

        im = Image.open(os.path.join(TEMPLATES, 'jotaro_smile.png'))
        img = img.convert('RGBA')
        i = Image.new('RGBA', im.size, 'black')
        size = (max(img.size), max(img.size))
        img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                       crop_to_size=True, center_cropped=True)
        coeffs = find_coeffs([(0, 68), (358, 0), (410, 335), (80, 435)],
                             [(0, 0), (img.width, 0), size, (0, img.height)])
        img = img.transform((410, 435), Image.PERSPECTIVE, coeffs,
                            Image.BICUBIC)
        x, y = (178, 479)
        i.paste(img, (x, y), mask=img)
        i.paste(im, mask=im)

        file = BytesIO()
        i.save(file, 'PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='jotaro.png')

    @command(pass_context=True, aliases=['tbc'], ignore_extra=True)
    @cooldown(2, 5, BucketType.server)
    async def tobecontinued(self, ctx, image=None, no_sepia=False):
        """Make a to be continued picture
        Usage: {prefix}{name} `image/emote/mention` `[optional sepia filter off] on/off`
        Sepia filter is on by default
        """
        img = await self._get_image(ctx, image)
        if not img:
            return

        await self.bot.send_typing(ctx.message.channel)
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

        file = BytesIO()
        img.save(file, 'PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='To_be_continued.png')

    @command(pass_context=True, aliases=['heaven', 'heavens_door'], ignore_extra=True)
    @cooldown(2, 5, BucketType.server)
    async def overheaven(self, ctx, image=None):
        img = await self._get_image(ctx, image)
        if not img:
            return
        await self.bot.send_typing(ctx.message.channel)

        overlay = Image.open(os.path.join(TEMPLATES, 'heaven.png'))
        base = Image.open(os.path.join(TEMPLATES, 'heaven_base.png'))
        size = (750, 750)
        img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                       crop_to_size=True, center_cropped=True)

        img = img.convert('RGBA')
        x, y = (200, 160)
        base.paste(img, (x, y), mask=img)
        base.alpha_composite(overlay)
        data = BytesIO()
        base.save(data, 'PNG')
        data.seek(0)
        await self.bot.send_file(ctx.message.channel, data, filename='overheaven.png')

    @command(pass_context=True, aliases=['puccireset'], ignore_extra=True)
    @cooldown(2, 5, BucketType.server)
    async def pucci(self, ctx, image=None):
        img = await self._get_image(ctx, image)
        if not img:
            return
        await self.bot.send_typing(ctx.message.channel)

        img = img.convert('RGBA')
        im = Image.open(os.path.join(TEMPLATES, 'pucci_bg.png'))
        overlay = Image.open(os.path.join(TEMPLATES, 'pucci_faded.png'))
        size = (682, 399)
        img = resize_keep_aspect_ratio(img, size, can_be_bigger=False,
                                       crop_to_size=True, center_cropped=True)
        x, y = (0, 367)
        im.paste(img, (x, y), mask=img)
        im.alpha_composite(overlay)
        data = BytesIO()
        im.save(data, 'PNG')
        data.seek(0)
        await self.bot.send_file(ctx.message.channel, data, filename='pucci_reset.png')

    async def get_url(self, url):
        # Attempt at making phantomjs async friendly
        # After visiting the url remember to put 1 item in self.queue
        # Otherwise the browser will be locked

        # If lock is not locked lock it until this operation finishes
        unlock = False
        if not self._driver_lock.locked():
            await self._driver_lock.acquire()
            unlock = True

        f = partial(self.driver.get, url)
        await self.bot.loop.run_in_executor(self.threadpool, f)
        if unlock:
            try:
                self._driver_lock.release()
            except RuntimeError:
                pass

    @command(pass_context=True, ignore_extra=True)
    @cooldown(1, 10, BucketType.server)
    async def party(self, ctx, image=None):
        """Takes a long ass time to make the gif"""
        img = await self._get_image(ctx, image)
        if img is None:
            return
        channel = ctx.message.channel
        await self.bot.send_typing(channel)
        img = await self.bot.loop.run_in_executor(self.threadpool, partial(gradient_flash, img, get_raw=True))
        await self.bot.send_file(channel, img, filename='party.gif')

    @command(pass_context=True, ignore_extra=True, aliases=['poke'])
    @cooldown(2, 2, type=BucketType.server)
    async def pokefusion(self, ctx, poke1=Pokefusion.RANDOM, poke2=Pokefusion.RANDOM, color_poke=None):
        """
        Gets a random pokemon fusion from http://pokefusion.japeal.com
        You can specify the wanted fusion by specifying their pokedex index or their name or just a part of their name.
        Color poke defines the pokemon whose color palette will be used. By default it's not used
        Passing % as a parameter will randomize that value
        """

        await self.bot.send_typing(ctx.message.channel)
        img, s = await self._pokefusion.fuse(poke1, poke2, color_poke)
        file = BytesIO()
        img.save(file, 'PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, content=s, filename='pokefusion.png')

    @command(owner_only=True)
    async def update_poke_cache(self):
        if await self._pokefusion.update_cache() is False:
            await self.bot.say('Failed to update cache')
        else:
            await self.bot.say('Successfully updated cache')


def setup(bot):
    bot.add_cog(Fun(bot))

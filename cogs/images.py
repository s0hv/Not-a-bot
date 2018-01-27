import logging
import os
from asyncio import Queue, Lock
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
from random import randint, random

from PIL import Image, ImageSequence
from discord.ext.commands import cooldown, BucketType
from selenium.webdriver import PhantomJS

from bot.bot import command
from cogs.cog import Cog
from utils.imagetools import (resize_keep_aspect_ratio, image_from_url,
                              gradient_flash, sepia, optimize_gif)
from utils.utilities import get_image_from_message, find_coeffs

logger = logging.getLogger('debug')
TEMPLATES = os.path.join('data', 'templates')


class Fun(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.driver = PhantomJS(self.bot.config.phantomjs)
        self.threadpool = ThreadPoolExecutor(3)
        self._driver_lock = Lock()
        self.queue = Queue()
        self.queue.put_nowait(1)

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
        file.seek(0)
        file = await self.bot.loop.run_in_executor(self.threadpool, partial(optimize_gif, file.getvalue()))
        await self.bot.send_file(ctx.message.channel, file, filename='jotaro_photo.{}'.format(extension))

    @command(pass_context=True, aliases=['tbc'], ignore_extra=True)
    @cooldown(2, 5, BucketType.server)
    async def tobecontinued(self, ctx, image=None, no_sepia=False):
        """Make a to be continued picture
        Usage: !tbc `image/emote/mention` `[optional sepia filter off] on/off`
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

    @command(pass_context=True, ignore_extra=True)
    @cooldown(2, 2, type=BucketType.server)
    async def pokefusion(self, ctx, poke1=None, poke2=None, color_poke=None):
        """
        Gets a random pokemon fusion from http://pokefusion.japeal.com
        You can specify the wanted fusion by specifying their pokedex index.
        Unspecified parameters will be randomized.
        By default if color_poke isn't given it has a random chance to be a random value.
        If you don't want this to happen set it as 0.
        e.g. `!pokefusion 1 2 0`
        Passing % as a parameter will randomize that value
        """

        async def get_int(s):
            try:
                return int(s[:5])
            except ValueError:
                await self.bot.say('%s is not a valid number' % s)
                return

        max_value = None

        def set_max_value():
            nonlocal max_value
            if max_value is not None:
                return
            max_value = self.driver.execute_script('return document.getElementById("s1").options.length')

        values = {1: poke1, 2: poke2, 3: color_poke}
        user_set = {}
        script = "var e = document.getElementById('%s'); return {text: e.options[e.selectedIndex].text, value: e.value}"
        if random() < 0.4:
            btn = 'myButtonALL'

            def clicker():
                self.driver.find_element_by_id(btn).click()
        else:
            btn = 'myButtonLR'

            def clicker():
                self.driver.execute_script("document.getElementById('s3').value = 0;")
                self.driver.find_element_by_id(btn).click()

        async with self._driver_lock:
            try:
                await self.bot.send_typing(ctx.message.channel)
                if not self.driver.current_url.startswith('http://pokefusion.japeal.com'):
                    logger.debug('Current url is %s. Switching to the correct one' % self.driver.current_url)
                    # We need to use this url so it doesn't render the whole site
                    # That improves performance a lot when getting the screenshot
                    await self.get_url('http://pokefusion.japeal.com/PKMSelectorV3.php?ver=2.0&p1=0&p2=0&c=0')

                for k in values:
                    v = values.get(k)
                    if v:
                        set_max_value()
                        if v != '%':
                            value = await get_int(v)
                            if value is None:
                                return

                            min_val = 0 if k == 3 else 1
                            if not (min_val <= value < max_value):
                                return await self.bot.say('Value must be between %s and %s' % (min_val, max_value - 1))

                            user_set[k] = value

                        if v == '%' and k == 3:
                            user_set[k] = randint(1, max_value)

                if user_set:
                    # We keep the old chance for random color
                    if 3 not in user_set and random() <= 0.4:
                        user_set[3] = 0
                    user_set = {k: user_set.get(k, randint(1, max_value)) for k in values.keys()}

                    s = ''
                    for k in user_set:
                        s += "document.getElementById('s%s').value=%s;" % (k, user_set[k])

                    def clicker():
                        self.driver.execute_script(s)
                        # We switch the places to render the image and also to
                        # make the order of the fusion correct or it would fuse
                        # poke2 with poke1
                        self.driver.find_element_by_id('myButtonS').click()

                clicker()
                poke1 = self.driver.execute_script(script % 's1')
                poke2 = self.driver.execute_script(script % 's2')
                color = self.driver.execute_script(script % 's3')

                img = BytesIO(self.driver.get_screenshot_as_png())
            except:
                logger.exception('Failed to get pokefusion. Refreshing page')
                await self.get_url('http://pokefusion.japeal.com/PKMSelectorV3.php?ver=2.0&p1=0&p2=0&c=0')
                return await self.bot.say('Failed to fuse pokemon')

        s = 'Fusion of {0[text]} and {1[text]}'.format(poke2, poke1)
        url = 'http://pokefusion.japeal.com/{0[value]}/{1[value]}'.format(poke2,
                                                                          poke1)

        if color and color['text'].lower() == 'none':
            color = None

        if color:
            s += ' using the color palette of {0[text]}\n{1}/{0[value]}'.format(
                color, url)
        else:
            s += '\n' + url

        img.seek(0)
        img = Image.open(img)
        img = img.crop((132, 204, 491, 478))
        file = BytesIO()
        img.save(file, 'PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='pokefusion.png', content=s)


def setup(bot):
    bot.add_cog(Fun(bot))

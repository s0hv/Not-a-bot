import logging
import os
from asyncio import Queue, Lock
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
from random import randint, random
from PIL import Image
from discord.ext.commands import cooldown
from selenium.webdriver import PhantomJS
from selenium.webdriver.support.select import Select

from bot.bot import command
from cogs.cog import Cog
from utils.imagetools import resize_keep_aspect_ratio, image_from_url
from utils.utilities import get_image_from_message

logger = logging.getLogger('debug')


class Fun(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.driver = PhantomJS(self.bot.config.phantomjs)
        self.threadpool = ThreadPoolExecutor(3)
        self._driver_lock = Lock()
        self.queue = Queue()
        self.queue.put_nowait(1)

    @command(pass_context=True, ignore_extra=True)
    @cooldown(5, 5)
    async def anime_deaths(self, ctx, image):
        path = os.path.join('data', 'templates', 'saddest-anime-deaths.png')
        img = get_image_from_message(ctx, image)
        if img is None:
            return await self.bot.say('No image found from %s' % image)

        img = await image_from_url(img, self.bot.aiohttp_client)
        if img is None:
            return await self.bot.say('Could not extract image from {}.'.format(image))

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
    @cooldown(5, 5)
    async def anime_deaths2(self, ctx, image):
        path = os.path.join('data', 'templates', 'saddest-anime-deaths2.png')
        img = get_image_from_message(ctx, image)
        if img is None:
            return await self.bot.say('No image found from %s' % image)

        img = await image_from_url(img, self.bot.aiohttp_client)
        if img is None:
            return await self.bot.say('Could not extract image from {}.'.format(image))

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

    @command(pass_context=True, ignore_extra=True, usage="""""")
    @cooldown(2, 5)
    async def trap(self, ctx, image=None):
        """Is it a trap?

        """
        path = os.path.join('data', 'templates', 'is_it_a_trap.png')
        path2 = os.path.join('data', 'templates', 'is_it_a_trap_layer.png')
        img = get_image_from_message(ctx, image)
        if img is None:
            return await self.bot.say('No image found from %s' % image)

        img = await image_from_url(img, self.bot.aiohttp_client)
        if img is None:
            return await self.bot.say('Could not extract image from {}.'.format(image))

        img = img.convert("RGBA")
        await self.bot.send_typing(ctx.message.channel)
        x, y = 820, 396
        w, h = 355, 505
        rotation = -22

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
    @cooldown(2, 2)
    async def pokefusion(self, ctx, poke1=None, poke2=None, color_poke=None):
        """Gets a random pokemon fusion from http://pokefusion.japeal.com"""

        async def get_int(s):
            try:
                return int(s[:5])
            except ValueError:
                await self.bot.say('%s is not a valid number')
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
                        value = await get_int(v)
                        if value is None:
                            return

                        if not (0 < value < max_value):
                            return await self.bot.say('Value must be between 1 and %s' % (max_value - 1))

                        user_set[k] = value

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

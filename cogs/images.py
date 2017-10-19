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
    async def pokefusion(self, ctx):
        """Gets a random pokemon fusion from http://pokefusion.japeal.com"""
        async with self._driver_lock:
            try:
                await self.bot.send_typing(ctx.message.channel)
                if not self.driver.current_url.startswith('http://pokefusion.japeal.com'):
                    logger.debug('Current url is %s. Switching to the correct one' % self.driver.current_url)
                    await self.get_url('http://pokefusion.japeal.com/')
                    self.driver.switch_to.frame('inneriframe')

                b1 = self.driver.find_element_by_id('myButtonR')
                b2 = self.driver.find_element_by_id('myButtonL')
                b_color = self.driver.find_element_by_id('myButtonColor')
                if b1:
                    b1.click()
                if b2:
                    b2.click()

                script = "var e = document.getElementById('%s'); return {text: e.options[e.selectedIndex].text, value: e.value}"
                poke1 = self.driver.execute_script(script % 's1')
                poke2 = self.driver.execute_script(script % 's2')
                s = 'Fusion of {0[text]} and {1[text]}'.format(poke1, poke2)
                url = 'http://pokefusion.japeal.com/{0[value]}/{1[value]}'.format(poke1, poke2)

                color_poke = None
                if b_color and random() < 0.4:
                    b_color.click()
                    color_poke = self.driver.execute_script(script % 's3')

                if color_poke and color_poke['text'].lower() == 'none':
                    color_poke = None

                if color_poke:
                    s += ' using the color palette of {0[text]}\n{1}/{0[value]}'.format(color_poke, url)
                else:
                    s += '\n' + url

                img = BytesIO(self.driver.get_screenshot_as_png())
            except:
                logger.exception('Failed to get pokefusion. Refreshing page')
                await self.get_url('http://pokefusion.japeal.com/')
                self.driver.switch_to.frame('inneriframe')
                return await self.bot.say('Failed to fuse pokemon')

        img.seek(0)
        img = Image.open(img)
        img = img.crop((141, 465, 502, 740))
        file = BytesIO()
        img.save(file, 'PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='pokefusion.png', content=s)


def setup(bot):
    bot.add_cog(Fun(bot))

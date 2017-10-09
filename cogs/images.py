import os
from asyncio import Queue
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from io import BytesIO
from random import randint

from PIL import Image
from discord.ext.commands import cooldown
from selenium.webdriver import PhantomJS

from bot.bot import command
from cogs.cog import Cog
from utils.imagetools import resize_keep_aspect_ratio, image_from_url
from utils.utilities import get_image_from_message


class Fun(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.driver = PhantomJS(self.bot.config.phantomjs)
        self.threadpool = ThreadPoolExecutor(3)
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

        await self.queue.get()
        f = partial(self.driver.get, url)
        await self.bot.loop.run_in_executor(self.threadpool, f)

    @command(pass_context=True, ignore_extra=True)
    @cooldown(2, 2)
    async def pokefusion(self, ctx):
        """Gets a random pokemon fusion from http://pokefusion.japeal.com"""
        r1 = randint(1, 386)  # Biggest id atm for gen 3 is 386
        r2 = randint(1, 386)
        while r1 == r2:
            r2 = randint(1, 386)

        url = 'http://pokefusion.japeal.com/%s/%s' % (r1, r2)
        await self.bot.send_typing(ctx.message.channel)
        await self.get_url(url)
        img = BytesIO(self.driver.get_screenshot_as_png())
        self.queue.put_nowait(1)
        img.seek(0)
        img = Image.open(img)
        img = img.crop((185, 367, 455, 637))
        file = BytesIO()
        img.save(file, 'PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='pokefusion.png', content=url)


def setup(bot):
    bot.add_cog(Fun(bot))

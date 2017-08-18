from cogs.cog import Cog
from bot.bot import command
from utils.utilities import get_image_from_message
from utils.imagetools import resize_keep_aspect_ratio, image_from_url
from PIL import Image
from io import BytesIO
from discord.ext.commands import cooldown
import os


class Fun(Cog):
    def __init__(self, bot):
        super().__init__(bot)

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

        x, y = 9, 10
        w, h = 854, 480
        template = Image.open(path)
        img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=False, resample=Image.BILINEAR)
        new_w, new_h = img.width, img.height
        if new_w != w:
            x += int((w - new_w)/2)

        if new_h != h:
            y += int((h - new_h) / 2)

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

        x, y = 9, 10
        w, h = 854, 480
        template = Image.open(path)
        img = resize_keep_aspect_ratio(img, (w, h), can_be_bigger=False, resample=Image.BILINEAR)
        new_w, new_h = img.width, img.height
        if new_w != w:
            x += int((w - new_w)/2)

        if new_h != h:
            y += int((h - new_h) / 2)

        template.paste(img, (x, y), img)
        file = BytesIO()
        template.save(file, format='PNG')
        file.seek(0)
        await self.bot.send_file(ctx.message.channel, file, filename='top10-anime-deaths.png')


def setup(bot):
    bot.add_cog(Fun(bot))

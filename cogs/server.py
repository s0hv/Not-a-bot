import base64
import logging

import discord
from discord.ext.commands import cooldown, BucketType
from validators import url as is_url

from bot.bot import command
from bot.globals import Perms
from cogs.cog import Cog
from utils.imagetools import raw_image_from_url

logger = logging.getLogger('debug')


class Server(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(no_pm=True, pass_context=True)
    @cooldown(1, 20, type=BucketType.user)
    async def top(self, ctx, page: str='1'):
        try:
            page = int(page)
            if page <= 0:
                page = 1
        except:
            page = 1

        server = ctx.message.server

        sorted_users = sorted(server.members, key=lambda u: len(u.roles), reverse=True)

        s = 'Leaderboards for **%s**\n\n```md\n' % server.name

        added = 0
        p = page*10
        for idx, u in enumerate(sorted_users[p-10:p]):
            added += 1
            s += '{}. {} with {} roles\n'.format(idx + p-9, u, len(u.roles) - 1)

        if added == 0:
            return await self.bot.say('Page out of range')

        try:
            idx = sorted_users.index(ctx.message.author) + 1
            s += '\nYour rank is {} with {} roles\n'.format(idx, len(ctx.message.author.roles) - 1)
        except:
            pass
        s += '```'

        await self.bot.say(s)

    @command(pass_context=True, no_pm=True, aliases=['addemote', 'addemoji', 'add_emoji'],
             required_perms=Perms.MANAGE_EMOJIS)
    @cooldown(2, 6, BucketType.server)
    async def add_emote(self, ctx, link, *name):
        server = ctx.message.server
        author = ctx.message.author

        async def dl(url):
            try:
                data, mime_type = await raw_image_from_url(url, self.bot.aiohttp_client, get_mime=True)
            except OverflowError:
                await self.bot.say('Failed to download. File is too big')
            except TypeError:
                await self.bot.say('Link is not a direct link to an image')
            else:
                return data, mime_type

        if is_url(link):
            if not name:
                await self.bot.say('What do you want to name the emote as', delete_after=30)
                msg = await self.bot.wait_for_message(author=author, channel=ctx.message.channel, timeout=30)
                if not msg:
                    return await self.bot.say('Took too long.')
            data = await dl(link)
            name = ' '.join(name)

        else:
            if not ctx.message.attachments:
                return await self.bot.say('No image provided')

            data = await dl(ctx.message.attachments[0])
            name = link + ' '.join(name)
            await self.bot.say('What do you want to name the emote as', delete_after=30)
            msg = await self.bot.wait_for_message(author=author,
                                                  channel=ctx.message.channel,
                                                  timeout=30)
            if not msg:
                return await self.bot.say('Took too long.')

        if not data:
            return

        data, mime = data
        if 'gif' in mime:
            fmt = 'data:{mime};base64,{data}'
            b64 = base64.b64encode(data.getvalue()).decode('ascii')
            img = fmt.format(mime=mime, data=b64)
            already_b64 = True
        else:
            img = data.getvalue()
            already_b64 = False

        try:
            await self.bot.create_custom_emoji(server=server, name=name, image=img, already_b64=already_b64)
        except discord.DiscordException as e:
            await self.bot.say('Failed to create emote because of an error\n%s' % e)
        except:
            await self.bot.say('Failed to create emote because of an error')
            logger.exception('Failed to create emote')
        else:
            await self.bot.say('created emote %s' % name)


def setup(bot):
    bot.add_cog(Server(bot))

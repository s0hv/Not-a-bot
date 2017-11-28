from bot.bot import command
from cogs.cog import Cog
from discord.ext.commands import cooldown, BucketType
from validators import url as is_url
from utils.imagetools import raw_image_from_url
import discord
import logging
from bot.globals import Perms


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
    async def add_emote(self, ctx, link, *name):
        server = ctx.message.server
        author = ctx.message.author

        if is_url(link):
            if not name:
                await self.bot.say('What do you want to name the emote as', delete_after=20)
                msg = await self.bot.wait_for_message(author=author, channel=ctx.message.channel, timeout=20)
                if not msg:
                    return await self.bot.say('Took too long.')
            data = await raw_image_from_url(link, self.bot.aiohttp_client)
            name = ' '.join(name)

        else:
            if not ctx.message.attachments:
                return await self.bot.say('No image provided')

            data = await raw_image_from_url(ctx.message.attachments[0], self.bot.aiohttp_client)
            name = link + ' '.join(name)

        if not data:
            return await self.bot.say('Failed to download image %s' % link)

        try:
            await self.bot.create_custom_emoji(server=server, name=name, image=data.getvalue())
        except discord.DiscordException as e:
            await self.bot.say('Failed to create emote because of an error\n%s' % e)
        except:
            await self.bot.say('Failed to create emote because of an error\n%s')
            logger.exception('Failed to create emote')
        else:
            await self.bot.say('created emote %s' % name)


def setup(bot):
    bot.add_cog(Server(bot))

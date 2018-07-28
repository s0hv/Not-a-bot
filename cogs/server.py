import asyncio
import base64
import logging
from math import ceil

import discord
from discord.ext.commands import cooldown, BucketType, bot_has_permissions
from discord.user import BaseUser
from validators import url as is_url

from bot.bot import command, has_permissions
from bot.converters import PossibleUser
from cogs.cog import Cog
from utils.imagetools import raw_image_from_url
from utils.utilities import (get_emote_url, get_emote_name, send_paged_message,
                             basic_check,
                             create_custom_emoji)

logger = logging.getLogger('debug')


class Server(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(no_pm=True)
    @cooldown(1, 20, type=BucketType.user)
    async def top(self, ctx, page: str='1'):
        """Get the top users on this server based on the most important values"""
        try:
            page = int(page)
            if page <= 0:
                page = 1
        except:
            page = 1

        guild = ctx.guild

        sorted_users = sorted(guild.members, key=lambda u: len(u.roles), reverse=True)
        pages = list(range(1, ceil(len(guild.members)/10)+1))

        def get_msg(page, index):
            s = 'Leaderboards for **{}**\n\n```md\n'.format(guild.name)
            added = 0
            p = page*10
            for idx, u in enumerate(sorted_users[p-10:p]):
                added += 1
                s += '{}. {} with {} roles\n'.format(idx + p-9, u, len(u.roles) - 1)

            if added == 0:
                return 'Page out of range'

            try:
                idx = sorted_users.index(ctx.author) + 1
                s += '\nYour rank is {} with {} roles\n'.format(idx, len(ctx.author.roles) - 1)
            except:
                pass
            s += '```'
            return s

        await send_paged_message(self.bot, ctx, pages, starting_idx=page-1, page_method=get_msg)

    @command(no_dm=True, aliases=['mr_top', 'mr_stats'])
    @cooldown(2, 5, BucketType.channel)
    async def mute_roll_top(self, ctx, user: PossibleUser=None):
        stats = await self.bot.dbutil.get_mute_roll(ctx.guild.id)
        if not stats:
            return await ctx.send('No mute roll stats on this server')

        page_length = ceil(len(stats)/10)
        pages = [False for _ in range(page_length)]

        title = f'Mute roll stats for guild {ctx.guild}'

        def cache_page(idx, custom_description=None):
            i = idx*10
            rows = stats[i:i+10]
            if custom_description:
                embed = discord.Embed(title=title, description=custom_description)
            else:
                embed = discord.Embed(title=title)

            embed.set_footer(text=f'Page {idx+1}/{len(pages)}')
            for row in rows:
                winrate = round(row['wins'] * 100 / row['games'], 1)
                v = f'<@{row["user"]}>\n' \
                    f'Winrate: {winrate}% with {row["wins"]} wins \n'\
                    f'Current streak: {row["current_streak"]}\n' \
                    f'Biggest streak: {row["biggest_streak"]}'
                embed.add_field(name=f'{row["games"]} games', value=v)

            pages[idx] = embed
            return embed

        def get_page(page, idx):
            if not page:
                return cache_page(idx)

            return page

        if isinstance(user, BaseUser):
            user_id = user.id
        else:
            user_id = user

        if user_id:
            for idx, r in enumerate(stats):
                if r['user'] == user_id:
                    i = idx // 10

                    winrate = round(r['wins'] * 100 / r['games'], 1)
                    d = f'Stats for <@{user_id}> at page {i+1}\n' \
                        f'Winrate: {winrate}% with {r["wins"]} wins \n' \
                        f'Current streak: {r["current_streak"]}\n' \
                        f'Biggest streak: {r["biggest_streak"]}'

                    e = discord.Embed(description=d)
                    e.set_footer(text=f'Ranking {idx+1}/{len(stats)}')
                    await ctx.send(embed=e)
                    return

            return await ctx.send(f"Didn't find user {user} on the leaderboards.\n"
                                  "Are you sure they have played mute roll")

        await send_paged_message(self.bot, ctx, pages, embed=True, page_method=get_page)

    async def _dl(self, ctx, url):
        try:
            data, mime_type = await raw_image_from_url(url, self.bot.aiohttp_client,
                                                       get_mime=True)
        except OverflowError:
            await ctx.send('Failed to download. File is too big')
        except TypeError:
            await ctx.send('Link is not a direct link to an image')
        else:
            return data, mime_type

    @command(no_pm=True, aliases=['addemote', 'addemoji', 'add_emoji'])
    @cooldown(2, 6, BucketType.guild)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def add_emote(self, ctx, link, *name):
        """Add an emote to the server"""
        guild = ctx.guild
        author = ctx.author

        if is_url(link):
            if not name:
                await ctx.send('What do you want to name the emote as', delete_after=30)
                try:
                    msg = await self.bot.wait_for('message', check=basic_check(author=author, channel=ctx.channel), timeout=30)
                except asyncio.TimeoutError:
                     msg = None
                if not msg:
                    return await ctx.send('Took too long.')
            data = await self._dl(ctx, link)
            name = ' '.join(name)

        else:
            if not ctx.message.attachments:
                return await ctx.send('No image provided')

            data = await self._dl(ctx, ctx.message.attachments[0].url)
            name = link + ' '.join(name)

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
            await create_custom_emoji(guild=guild, name=name, image=img, already_b64=already_b64,
                                      reason=f'{ctx.author} created emote')
        except discord.DiscordException as e:
            await ctx.send('Failed to create emote because of an error\n%s\nDId you check if the image is under 256kb in size' % e)
        except:
            await ctx.send('Failed to create emote because of an error')
            logger.exception('Failed to create emote')
        else:
            await ctx.send('created emote %s' % name)

    @command(no_pm=True, aliases=['trihard'])
    @cooldown(2, 6, BucketType.guild)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def steal(self, ctx, *emoji):
        """Add emotes to this server from other servers.
        Usage:
            {prefix}{name} :emote1: :emote2: :emote3:"""
        if not emoji:
            return await ctx.send('Specify the emotes you want to steal')

        errors = 0
        guild = ctx.guild
        emotes = []
        for e in emoji:
            if errors >= 3:
                return await ctx.send('Too many errors while uploading emotes. Aborting')
            url = get_emote_url(e)
            if not url:
                continue

            animated, name = get_emote_name(e)

            if not name:
                continue

            data = await self._dl(ctx, url)

            if not data:
                continue

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
                emote = await create_custom_emoji(guild=guild, name=name, image=img, already_b64=already_b64,
                                                  reason=f'{ctx.author} stole emote')
                emotes.append(emote)
            except discord.HTTPException as e:
                if e.code == 400:
                    return await ctx.send('Emote capacity reached\n{}'.format(e))
                errors += 1
            except discord.DiscordException as e:
                await ctx.send('Failed to create emote because of an error\n%s' % e)
                errors += 1
            except:
                await ctx.send('Failed to create emote because of an error')
                logger.exception('Failed to create emote')
                errors += 1

        await ctx.send('Successfully stole {}'.format(' '.join(map(lambda e: str(e), emotes))))


def setup(bot):
    bot.add_cog(Server(bot))

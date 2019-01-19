import asyncio
import base64
import logging
import os
from datetime import datetime
from math import ceil

import discord
from discord.ext.commands import BucketType, bot_has_permissions
from discord.user import BaseUser
from validators import url as is_url

from bot.bot import command, has_permissions, cooldown, group
from bot.converters import PossibleUser, GuildEmoji
from bot.formatter import Paginator
from cogs.cog import Cog
from utils.imagetools import raw_image_from_url
from utils.utilities import (get_emote_url, get_emote_name, send_paged_message,
                             basic_check, format_timedelta, DateAccuracy,
                             create_custom_emoji, wait_for_yes)

logger = logging.getLogger('debug')


class Server(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @group(no_pm=True, invoke_without_command=True)
    @cooldown(1, 20, type=BucketType.user)
    async def top(self, ctx, page: int=1):
        """Get the top users on this server based on the most important values"""
        if page > 0:
            page -= 1

        guild = ctx.guild

        sorted_users = sorted(guild.members, key=lambda u: len(u.roles), reverse=True)
        # Indexes of all of the pages
        pages = list(range(1, ceil(len(guild.members)/10)+1))

        def get_msg(page, _):
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

        await send_paged_message(ctx, pages, starting_idx=page,
                                 page_method=get_msg)

    async def _date_sort(self, ctx, page, key, dtype='joined'):
        if page > 0:
            page -= 1

        guild = ctx.guild
        sorted_users = list(sorted(guild.members, key=key))
        # Indexes of all of the pages
        pages = list(range(1, ceil(len(guild.members)/10)+1))

        own_rank = ''

        try:
            idx = sorted_users.index(ctx.author) + 1
            t = datetime.utcnow() - key(ctx.author)
            t = format_timedelta(t, DateAccuracy.Day)
            own_rank = f'\nYour rank is {idx}. You {dtype} {t} ago at {key(ctx.author).strftime("%a, %d %b %Y %H:%M:%S GMT")}\n'
        except:
            pass

        def get_page(pg, _):
            s = 'Leaderboards for **{}**\n\n```md\n'.format(guild.name)
            index = pg*10
            page = sorted_users[index-10:index]
            max_s = max(map(lambda u: len(str(u)), page))

            if not page:
                return 'Page out of range'

            for idx, u in enumerate(page):
                t = datetime.utcnow() - key(u)
                t = format_timedelta(t, DateAccuracy.Day)

                join_date = key(u).strftime('%a, %d %b %Y %H:%M:%S GMT')

                # We try to align everything but due to non monospace fonts
                # it will never be perfect
                tabs, spaces = divmod(max_s-len(str(u)), 4)
                padding = '\t'*tabs + ' '*spaces

                s += f'{idx+index-9}. {u} {padding}{dtype} {t} ago at {join_date}\n'

            s += own_rank
            s += '```'
            return s

        await send_paged_message(ctx, pages, starting_idx=page, page_method=get_page)

    @top.command(np_pm=True)
    @cooldown(1, 10)
    async def join(self, ctx, page: int=1):
        """Sort users by join date"""
        await self._date_sort(ctx, page, lambda u: u.joined_at or datetime.utcnow(), 'joined')

    @top.command(np_pm=True)
    @cooldown(1, 10)
    async def created(self, ctx, page: int=1):
        """Sort users by join date"""
        await self._date_sort(ctx, page, lambda u: u.created_at, 'created')

    @command(no_dm=True, aliases=['mr_top', 'mr_stats'])
    @cooldown(2, 5, BucketType.channel)
    async def mute_roll_top(self, ctx, *, user: PossibleUser=None):
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

        await send_paged_message(ctx, pages, embed=True, page_method=get_page)

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

    @command(no_pm=True, aliases=['delete_emoji', 'delete_emtoe', 'del_emote'])
    @cooldown(2, 6, BucketType.guild)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def delete_emote(self, ctx, *, emote: GuildEmoji):
        await ctx.send('Do you want to delete the emoji {0} {0.name} `{0.id}`'.format(emote))
        if not await wait_for_yes(ctx, 60):
            return

        try:
            await emote.delete()
        except discord.HTTPException as e:
            await ctx.send('Failed to delete emote because of an error\n%s' % e)
        except:
            logger.exception('Failed to delete emote')
            await ctx.send('Failed to delete emote because of an error')

        else:
            await ctx.send(f'Deleted emote {emote.name} `{emote.id}`')

    @command(no_pm=True, aliases=['addemote', 'addemoji', 'add_emoji', 'add_emtoe'])
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
        except discord.HTTPException as e:
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

            if e.startswith(url):
                name = url.split('/')[-1].split('.')[0]
            else:
                _, name = get_emote_name(e)

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
                await ctx.send('Error while uploading emote\n%s' % e)
                errors += 1
            except:
                await ctx.send('Failed to create emote because of an error')
                logger.exception('Failed to create emote')
                errors += 1

        if emotes:
            await ctx.send('Successfully stole {}'.format(' '.join(map(lambda e: str(e), emotes))))
        else:
            await ctx.send("Didn't steal anything")

    @command(no_pm=True)
    @bot_has_permissions(embed_links=True)
    @cooldown(1, 20, BucketType.guild)
    async def channels(self, ctx):
        """
        Lists all channels in the server in an embed
        """

        channel_categories = {}

        for chn in sorted(ctx.guild.channels, key=lambda c: c.position):
            if isinstance(chn, discord.CategoryChannel) and chn.id not in channel_categories:
                channel_categories[chn.id] = []
            else:
                category = chn.category_id
                if category not in channel_categories:
                    channel_categories[category] = []

                channel_categories[category].append(chn)

        description = None

        def make_category(channels):
            val = ''
            for chn in sorted(channels, key=lambda c: isinstance(c, discord.VoiceChannel)):
                if isinstance(chn, discord.VoiceChannel):
                    val += '\\🔊 '
                else:
                    val += '# '

                val += f'{chn.name}\n'

            return val

        if None in channel_categories:
            description = make_category(channel_categories.pop(None))

        paginator = Paginator(title='Channels', description=description)

        for category_id in sorted(channel_categories.keys(), key=lambda k: ctx.guild.get_channel(k).position):
            category = ctx.guild.get_channel(category_id)

            val = make_category(channel_categories[category_id])

            paginator.add_field(name=category.name.upper(), value=val, inline=False)

        paginator.finalize()

        for page in paginator.pages:
            await ctx.send(embed=page)

    @command(no_pm=True)
    @has_permissions(administrator=True)
    @cooldown(1, 10)
    async def delete_server(self, ctx):
        """
        Deletes server
        """
        p = os.path.join('data', 'templates', 'loading.gif')
        await ctx.send('Please wait. Server deletion in progress', file=discord.File(p, filename='loading.gif'))


def setup(bot):
    bot.add_cog(Server(bot))

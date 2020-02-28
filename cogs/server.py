import asyncio
import logging
import ntpath
import os
import random
import time
import typing
from datetime import datetime
from io import BytesIO
from math import ceil

import discord
from PIL import Image
from discord.ext.commands import BucketType, PartialEmojiConverter, Greedy, \
    clean_content
from discord.user import BaseUser
from validators import url as is_url

from bot.bot import (command, has_permissions, cooldown, group,
                     guild_has_features, bot_has_permissions)
from bot.converters import PossibleUser, GuildEmoji
from bot.cooldowns import CooldownMapping, Cooldown
from bot.formatter import Paginator
from cogs.cog import Cog
from utils.imagetools import raw_image_from_url
from utils.imagetools import (resize_keep_aspect_ratio, stack_images,
                              concatenate_images)
from utils.utilities import (send_paged_message,
                             basic_check, format_timedelta, DateAccuracy,
                             wait_for_yes, get_image,
                             get_emote_name_id, split_string)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')

# Size of banner thumbnail
THUMB_SIZE = (288, 162)


class AFK:
    def __init__(self, user, message):
        self.user = user
        self.message = message
        self.timestamp = time.time()


class Server(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.afks = getattr(bot, 'afks', {})
        self.bot.afks = self.afks
        self._afk_cd = CooldownMapping(Cooldown(1, 4, BucketType.guild))

    @group(no_pm=True, invoke_without_command=True)
    @cooldown(1, 20, type=BucketType.user)
    async def top(self, ctx, page: int=1):
        """Get the top users on this server based on the most important values"""
        if page > 0:
            page -= 1

        guild = ctx.guild
        filtered_roles = {}

        # remove some roles that have perms for my own guild
        if guild.id == 217677285442977792:
            # These should only be used for set operations
            filtered_roles = {321374867557580801, 331811458012807169, 361889118210359297, 380814558769578003,
                              337290275749756928, 422432520643018773, 322837972317896704, 323492471755636736,
                              329293030957776896, 317560511929647118, 363239074716188672, 365175139043901442}
            filtered_roles = {discord.Role(guild=None, state=None, data={"id": id_, "name": ""}) for id_ in filtered_roles}

            def sort(member):
                return len(set(member.roles) - filtered_roles)

            sorted_users = sorted(guild.members, key=sort, reverse=True)
        else:
            sorted_users = sorted(guild.members, key=lambda u: len(u.roles), reverse=True)

        # Indexes of all of the pages
        pages = list(range(1, ceil(len(guild.members)/10)+1))

        # Count user roles filtered if a specific server
        if guild.id == 217677285442977792:
            author_role_count = len(set(ctx.author.roles) - filtered_roles)
        else:
            author_role_count = len(ctx.author.roles)

        def get_msg(page, _):
            s = 'Leaderboards for **{}**\n\n```md\n'.format(guild.name)
            added = 0
            p = page*10
            for idx, u in enumerate(sorted_users[p-10:p]):
                # Count user roles filtered if a specific server
                if guild.id == 217677285442977792:
                    role_count = len(set(u.roles) - filtered_roles)
                else:
                    role_count = len(u.roles)

                added += 1
                # role_count - 1 to not count the default role
                s += '{}. {} with {} roles\n'.format(idx + p-9, u, role_count - 1)

            if added == 0:
                return 'Page out of range'

            try:
                idx = sorted_users.index(ctx.author) + 1
                s += '\nYour rank is {} with {} roles\n'.format(idx, author_role_count - 1)
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

    async def _post_mr_top(self, ctx, user, sort=None):
        stats = await self.bot.dbutil.get_mute_roll(ctx.guild.id, sort=sort)
        if not stats:
            return await ctx.send('No mute roll stats on this server')

        page_entries = 5
        page_count = ceil(len(stats) / page_entries)
        pages = [False for _ in range(page_count)]

        title = f'Mute roll stats for guild {ctx.guild}'

        def cache_page(idx, custom_description=None):
            i = idx * page_entries
            rows = stats[i:i + page_entries]
            if custom_description:
                embed = discord.Embed(title=title, description=custom_description)
            else:
                embed = discord.Embed(title=title)

            embed.set_footer(text=f'Page {idx + 1}/{len(pages)}')
            for row in rows:
                winrate = round(row['wins'] * 100 / row['games'], 1)
                v = f'<@{row["uid"]}>\n' \
                    f'Winrate: {winrate}% with {row["wins"]} wins\n' \
                    f'Current win streak: {row["current_streak"]}\n' \
                    f'Biggest win streak: {row["biggest_streak"]}\n' \
                    f'Current loss streak: {row["current_lose_streak"]}\n' \
                    f'Biggest loss streak: {row["biggest_lose_streak"]}'
                embed.add_field(name=f'{row["games"]} games', value=v)

            pages[idx] = embed
            return embed

        # Used for putting callers stats in the description of embed
        custom_desc = None

        def get_page(page, idx):
            if not page:
                return cache_page(idx, custom_desc)

            return page

        if isinstance(user, BaseUser) or isinstance(user, discord.Member):
            user_id = user.id
        else:
            user_id = user

        if user_id:
            for idx, r in enumerate(stats):
                if r['uid'] == user_id:
                    i = idx // page_entries

                    winrate = round(r['wins'] * 100 / r['games'], 1)
                    d = f'Stats for <@{user_id}> at page {i + 1}\n' \
                        f'Winrate: {winrate}% with {r["wins"]} wins \n' \
                        f'Games: {r["games"]}\n' \
                        f'Current/Biggest win streak: {r["current_streak"]}/{r["biggest_streak"]}\n' \
                        f'Current/Biggest loss streak: {r["current_lose_streak"]}/{r["biggest_lose_streak"]}\n' \
                        f'Ranking {idx + 1}/{len(stats)}'

                    custom_desc = d
                    break

        await send_paged_message(ctx, pages, embed=True, page_method=get_page)

    @group(no_dm=True, aliases=['mr_top', 'mr_stats', 'mrtop'], invoke_without_command=True)
    @cooldown(2, 5, BucketType.guild)
    async def mute_roll_top(self, ctx, *, user: PossibleUser=None):
        """
        Sort mute roll stats using a custom algorithm
        It prioritizes amount of wins and winrate over games played tho games played
        also has a decent impact on results
        """
        await self._post_mr_top(ctx, user or ctx.author)

    @mute_roll_top.command(no_dm=True)
    @cooldown(2, 5, BucketType.guild)
    async def games(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by amount of games played"""
        await self._post_mr_top(ctx, user or ctx.author, sort='games')

    @mute_roll_top.command(no_dm=True)
    @cooldown(2, 5, BucketType.guild)
    async def wins(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by amount of games won"""
        await self._post_mr_top(ctx, user or ctx.author, sort='wins')

    @mute_roll_top.command(no_dm=True, aliases=['wr'])
    @cooldown(2, 5, BucketType.guild)
    async def winrate(self, ctx, *, user: PossibleUser=None):
        """
        Sort mute roll stats by winrate while also taking games played into account tho only slightly
        """
        # Sort by winrate while prioritizing games played a bit
        # If we dont do this we'll only get 1 win 1 game users at the top
        sort = '1/SQRT( POWER((1 - wins / games::decimal), 2) + POWER(1 / games::decimal, 2)* 0.9 )'
        await self._post_mr_top(ctx, user or ctx.author, sort=sort)

    @mute_roll_top.command(no_dm=True, aliases=['ws'])
    @cooldown(2, 5, BucketType.guild)
    async def winstreak(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by highest winstreak"""
        await self._post_mr_top(ctx, user or ctx.author, sort='biggest_streak')

    @mute_roll_top.command(no_dm=True, aliases=['ls'])
    @cooldown(2, 5, BucketType.guild)
    async def losestreak(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by highest losing streak"""
        await self._post_mr_top(ctx, user or ctx.author, sort='biggest_lose_streak')

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
    async def add_emote(self, ctx, link, name=None):
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

        else:
            if not ctx.message.attachments:
                return await ctx.send('No image provided')

            data = await self._dl(ctx, ctx.message.attachments[0].url)
            name = link

        if not data:
            return

        data, _ = data

        try:
            await guild.create_custom_emoji(name=name, image=data.getvalue(), reason=f'{ctx.author} created emote')
        except discord.HTTPException as e:
            await ctx.send('Failed to create emote because of an error\n%s\nDId you check if the image is under 256kb in size' % e)
        except:
            await ctx.send('Failed to create emote because of an error')
            logger.exception('Failed to create emote')
        else:
            await ctx.send('created emote %s' % name)

    @command(no_pm=True)
    @cooldown(2, 6)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def rename(self, ctx, emote: discord.Emoji, new_name):
        """Rename the given emote"""
        if ctx.guild != emote.guild:
            await ctx.send('The emote is not from this server')
            return

        try:
            await emote.edit(name=new_name)
        except discord.HTTPException as e:
            await ctx.send(f'Failed to rename emote\n{e}')

        await ctx.send(f'Renamed the given emote to {new_name}')

    @command(no_pm=True, aliases=['trihard'])
    @cooldown(2, 6, BucketType.guild)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def steal(self, ctx, emoji: Greedy[PartialEmojiConverter]=None,
                    message: typing.Optional[discord.Message]=None,
                    user: discord.Member=None):
        """Add emotes to this server from other servers.
        You can either use the emotes you want separated by spaces in the message
        or you can give a message id in the channel that the command is run in to fetch
        the emotes from that message. Both cannot be used at the same time tho.
        Usage:
            `{prefix}{name} :emote1: :emote2: :emote3:`
            `{prefix}{name} message_id`
        """
        if not emoji and not message and not user:
            await ctx.send('Please either give emotes, a message id or a user to fetch the emotes from')
            return

        emotes = []
        if message:
            for e in message.content.split(' '):
                animated, name, eid = get_emote_name_id(e)
                if not eid:
                    continue

                emotes.append(
                    discord.PartialEmoji.with_state(self.bot._connection,
                                                    animated=animated,
                                                    name=name,
                                                    id=eid)
                )

        elif user:
            for activity in user.activities:
                if isinstance(activity, discord.CustomActivity) and activity.emoji:
                    e = activity.emoji
                    emotes.append(
                        discord.PartialEmoji.with_state(self.bot._connection,
                                                        animated=e.animated,
                                                        name=e.name,
                                                        id=e.id)
                    )
                    break
        else:
            for e in emoji:
                if e.is_custom_emoji():
                    emotes.append(e)

        errors = 0
        guild = ctx.guild
        stolen = []
        for emote in set(emotes):
            if errors >= 3:
                return await ctx.send('Too many errors while uploading emotes. Aborting')

            try:
                data = await emote.url.read()
            except (discord.DiscordException, discord.HTTPException) as e:
                await ctx.send(f'Failed to download emote {emote.name}\n{e}')
                errors += 1
                continue

            try:
                emote = await guild.create_custom_emoji(name=emote.name, image=data, reason=f'{ctx.author} stole emote')
                stolen.append(emote)
            except discord.HTTPException as e:
                if e.code == 400:
                    return await ctx.send('Emote capacity reached\n{}'.format(e))
                await ctx.send('Error while uploading emote\n%s' % e)
                errors += 1
            except discord.ClientException:
                await ctx.send('Failed to create emote because of an error')
                logger.exception('Failed to create emote')
                errors += 1

        if stolen:
            await ctx.send('Successfully stole {}'.format(' '.join(map(str, stolen))))
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
    @cooldown(1, 10, BucketType.user)
    async def join_date(self, ctx):
        """
        Returns the first recorded join date to this server.
        Dates before December 17th 2019 might not be the earliest join date
        """
        user = ctx.author
        date = await self.bot.dbutil.get_join_date(user.id, ctx.guild.id)
        if not date:
            await ctx.send('No join date logged for user or an error happened')
            return

        await ctx.send(f'First recorded join for {user} is {date.strftime("%Y-%m-%d %H:%M")} (YYYY-MM-DD)')

    @command(no_pm=True)
    @has_permissions(administrator=True)
    @cooldown(1, 10)
    async def delete_server(self, ctx):
        """
        Deletes server
        """
        p = os.path.join('data', 'templates', 'loading.gif')
        await ctx.send('Please wait. Server deletion in progress', file=discord.File(p, filename='loading.gif'))

    @command(no_pm=True)
    @cooldown(1, 15, BucketType.guild)
    @has_permissions(manage_guild=True)
    async def pls(self, ctx, image=None):
        """Add an image to the server banner rotation"""
        img = await get_image(ctx, image, True)
        if img is None:
            return

        def do_it():
            nonlocal img
            w, h = (960, 540)

            # According to docs LANCZOS is best for downsampling. In other cases use bicubic
            resample = Image.LANCZOS if (img.width > w and img.height > h) else Image.BICUBIC
            img = resize_keep_aspect_ratio(img, (w, h), crop_to_size=True,
                                           center_cropped=True,
                                           can_be_bigger=True,
                                           resample=resample)

            base_path = os.path.join('data', 'banners', str(ctx.guild.id))
            os.makedirs(base_path, exist_ok=True)
            filename = str(ctx.message.id) + '.png'
            img.save(
                os.path.join(base_path, filename),
                'PNG'
            )

            # Make thumbnails every banner for faster access when viewing multiple
            # banners at once
            base_path = os.path.join(base_path, 'thumbs')
            os.makedirs(base_path, exist_ok=True)

            img = img.resize(THUMB_SIZE, Image.LANCZOS)
            img.save(
                os.path.join(base_path, filename),
                'PNG'
            )

            return filename

        try:
            file = await self.bot.loop.run_in_executor(self.bot.threadpool, do_it)
        except:
            terminal.exception('Failed to save banner')
            await ctx.send('Failed to save banner image')
            return

        await ctx.send(f'Saved banner image as {file}')

    @command(no_pm=True, aliases=['bremove'])
    @cooldown(1, 5, BucketType.guild)
    @has_permissions(manage_guild=True)
    async def banner_remove(self, ctx, filename):
        """Remove a banner from the rotation"""
        guild = ctx.guild
        base_path = os.path.join('data', 'banners', str(guild.id))
        if not os.path.exists(base_path):
            await ctx.send('No banners found for guild')
            ctx.command.reset_cooldown(ctx)
            return

        files = os.listdir(base_path)

        # Sanitize path to only the filename
        filename = ntpath.basename(filename)

        if filename not in files:
            await ctx.send(f'File {filename} not found')
            ctx.command.reset_cooldown(ctx)
            return

        file = os.path.join(base_path, filename)
        thumb = os.path.join(base_path, 'thumbs', filename)

        def do_it():
            data = BytesIO()
            im = Image.open(file)
            im.save(data, 'PNG')
            data.seek(0)

            try:
                os.remove(file)
            except OSError:
                pass

            try:
                os.remove(thumb)
            except OSError:
                pass

            return data

        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_it)

        await ctx.send(f'Deleted {filename}', file=discord.File(data, filename))

    @command(no_pm=True)
    @cooldown(1, 15, BucketType.guild)
    async def banners(self, ctx, filename=None):
        """
        Show all banners in rotation for this server. If filename is specified
        gives the full banner corresponding to that filename
        """
        guild = ctx.guild
        base_path = os.path.join('data', 'banners', str(guild.id))
        if not os.path.exists(base_path):
            await ctx.send('No banners found for guild')
            ctx.command.reset_cooldown(ctx)
            return

        (_, _, banners) = next(os.walk(base_path))

        if filename:
            # Sanitize path to only the filename
            filename = ntpath.basename(filename)

            if filename not in banners:
                await ctx.send(f'File {filename} not found')
                ctx.command.reset_cooldown(ctx)
                return

            def do_it():
                data = BytesIO()
                with open(os.path.join(base_path, filename), 'rb') as f:
                    while True:
                        bt = f.read(4096)
                        if not bt:
                            break

                        data.write(bt)

                data.seek(0)
                yield data, (filename, )

        else:
            def do_it():
                thumbs_path = os.path.join(base_path, 'thumbs')
                os.makedirs(thumbs_path, exist_ok=True)
                w, h = (3, 4)  # How many banners we have in one image
                width = THUMB_SIZE[0]*w
                images = []  # Images to be concatenated together
                stack = []  # Concatenated images
                curr_files = []  # Filenames for images in the images variable
                filenames = []  # Filenames for current stack
                data = BytesIO()

                for banner in banners:
                    curr_files.append(banner)
                    thumb = os.path.join(thumbs_path, banner)

                    # Create thumb if it doesn't exist
                    if not os.path.exists(thumb):
                        im = Image.open(os.path.join(base_path, banner))
                        im = im.resize(THUMB_SIZE, Image.LANCZOS)
                        im.save(thumb, 'PNG')
                    else:
                        im = Image.open(thumb)

                    # Append thumb to list and concatenate them when the limit
                    # is reached
                    images.append(im)
                    if len(images) >= w:
                        stack.append(concatenate_images(
                            images, THUMB_SIZE[0]
                        ))
                        images.clear()
                        filenames.append(' '.join(curr_files))
                        curr_files.clear()

                    # Stack concatenated images when the limit is reached
                    if len(stack) >= h:
                        stack_images(stack, THUMB_SIZE[1], width).save(data, 'PNG')
                        data.seek(0)
                        yield data, filenames
                        filenames = []
                        data = BytesIO()
                        stack.clear()

                if images:
                    stack.append(concatenate_images(images, THUMB_SIZE[0]))
                    filenames.append(' '.join(curr_files))

                if stack:
                    stack_images(stack, THUMB_SIZE[1], width).save(data, 'PNG')
                    data.seek(0)
                    yield data, filenames

        try:
            for data, filenames in await self.bot.loop.run_in_executor(self.bot.threadpool, do_it):
                filenames = '\n'.join(filenames)
                await ctx.send(f'```\n{filenames}\n```', file=discord.File(data, 'banners.png'))
        except:
            terminal.exception('Failed to load banners')
            await ctx.send('Failed to show banners')
            return

    @command(no_pm=True, aliases=['brotate'])
    @guild_has_features('BANNER')
    @bot_has_permissions(manage_guild=True)
    @cooldown(1, 1800, BucketType.guild)
    async def banner_rotate(self, ctx, filename=None):
        """Change server banner to one of the banners saved for the server"""
        guild = ctx.guild
        base_path = os.path.join('data', 'banners', str(guild.id))
        if not os.path.exists(base_path):
            os.makedirs(base_path, exist_ok=True)

        (_, _, files) = next(os.walk(base_path))

        if filename:
            # Sanitize path to only the filename
            filename = ntpath.basename(filename)

            if filename not in files:
                await ctx.send(f'File {filename} not found')
                ctx.command.reset_cooldown(ctx)
                return

        old_banner = await self.bot.dbutil.last_banner(guild.id)

        try:
            files.remove(old_banner)
        except ValueError:
            pass
        else:
            if not files:
                await ctx.send('Server only has one banner to select from')
                ctx.command.reset_cooldown(ctx)
                return

        if not filename:
            if not files:
                await ctx.send('No banner rotation images found for guild')
                ctx.command.reset_cooldown(ctx)
                return

            filename = random.choice(files)

        if filename not in files:
            await ctx.send(f'File {filename} not found')
            ctx.command.reset_cooldown(ctx)
            return

        data = bytes()
        with open(os.path.join(base_path, filename), 'rb') as f:
            while True:
                bt = f.read(4096)
                if not bt:
                    break

                data += bt

        try:
            await guild.edit(banner=data)
        except (discord.HTTPException, discord.InvalidArgument) as e:
            await ctx.send(f'Failed to set banner because of an error\n{e}')
            return

        await self.bot.dbutil.set_last_banner(guild.id, filename)
        await ctx.send('♻')

    @Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return

        g = message.guild
        guild_afk = self.afks.get(g.id, {})
        if not guild_afk:
            return

        user = message.author
        if user.id in guild_afk:
            guild_afk.pop(user.id, None)
            await message.channel.send(f'`{user}` is no longer afk', delete_after=10)
            return

        mentions = message.mentions
        afks = []
        for mention in mentions:
            afk = guild_afk.get(mention.id, None)
            if afk:
                afks.append(afk)

        if not afks:
            return

        if self._afk_cd.valid:
            bucket = self._afk_cd.get_bucket(message)
            retry_after = bucket.update_rate_limit()
            if retry_after:
                return

        if len(afks) > 1:
            messages = []
            for afk in afks:
                messages.append(f'{afk.user} is afk {format_timedelta(int(time.time() - afk.timestamp), DateAccuracy.Hour - DateAccuracy.Minute)} ago: {afk.message}'[:2000])

            messages = split_string(messages)[:2]
        else:
            afk = afks[0]
            messages = (f'{afk.user} is afk {format_timedelta(int(time.time()-afk.timestamp), DateAccuracy.Hour-DateAccuracy.Minute)} ago: {afk.message}'[:2000], )

        for msg in messages:
            await message.channel.send(msg)

    @command(np_pm=True)
    @cooldown(1, 5, BucketType.user)
    async def afk(self, ctx, *, message: clean_content()=''):
        """
        Set an afk message on this server that will be posted every time someone
        pings you until you send your next message
        """
        g = ctx.guild
        if g.id not in self.afks:
            self.afks[g.id] = {}

        if ctx.message.attachments:
            message += ' ' + ctx.message.attachments[0].url

        self.afks[ctx.guild.id][ctx.author.id] = AFK(ctx.author, message.strip())
        await ctx.send(f'`{ctx.author}` is now afk')

    @command()
    @has_permissions(manage_roles=True)
    @cooldown(2, 4, BucketType.guild)
    async def remove_afk(self, ctx, *, user: discord.Member):
        """
        Removes the afk of the mentioned user on this server
        """
        self.afks.get(ctx.guild.id, {}).pop(user.id, None)
        await ctx.send(f'Removed afk message of the user {user}')


def setup(bot):
    bot.add_cog(Server(bot))

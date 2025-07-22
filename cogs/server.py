import asyncio
import datetime
import logging
import ntpath
import os
import random
import re
import time
from datetime import time as dtime, timedelta
from io import BytesIO
from math import ceil
from typing import Optional

import disnake
import pytz
from PIL import Image
from disnake import ApplicationCommandInteraction, Attachment, InteractionContextTypes
from disnake.ext import tasks
from disnake.ext.commands import (BucketType, Cooldown, CooldownMapping, Greedy, MessageConverter,
                                  NoPrivateMessage, Param, PartialEmojiConverter, cooldown,
                                  slash_command)
from disnake.user import BaseUser
from validators import url as is_url

from bot.Not_a_bot import NotABot
from bot.bot import (Context, bot_has_permissions, command, group, guild_has_features,
                     has_permissions)
from bot.converters import GuildEmoji, PossibleUser, TimeDelta, convert_timedelta
from bot.exceptions import BotException
from bot.formatter import EmbedPaginator
from bot.paginator import Paginator
from bot.types import BotContext
from cogs.cog import Cog
from utils.imagetools import (concatenate_images, raw_image_from_url, resize_gif,
                              resize_keep_aspect_ratio, stack_images)
from utils.utilities import (DateAccuracy, dl_image, format_timedelta,
                             get_emote_name_id, get_filename_from_url, get_image,
                             native_format_timedelta, split_string, utcnow, wait_for_yes)

logger = logging.getLogger('terminal')

# Size of banner thumbnail
THUMB_SIZE = (288, 162)
ICON_THUMB_SIZE = (128, 128)
GUILD_COOLDOWN: BucketType = BucketType.guild


def get_next_rotate_run_time(t: dtime, delay: timedelta) -> float:
    now = utcnow()
    fixed = now.replace(hour=t.hour, minute=t.minute, second=0,
                        microsecond=0) - delay - timedelta(days=1)

    while fixed < now:
        fixed += delay

    timeout = (fixed - now).total_seconds()

    return timeout


def read_image_file(base_path: str, filename: str | None) -> bytes:
    data = bytes()
    with open(os.path.join(base_path, filename), 'rb') as f:
        while True:
            bt = f.read(4096)
            if not bt:
                break

            data += bt

    return data


def read_image_file_to_buffer(file: str) -> BytesIO:
    data = BytesIO()
    with open(file, 'rb') as f:
        while True:
            bt = f.read(4096)
            if not bt:
                break

            data.write(bt)

    data.seek(0)
    return data


def get_id_from_ctx(ctx: BotContext) -> int:
    if isinstance(ctx, ApplicationCommandInteraction):
        return ctx.id

    return ctx.message.id


class AFK:
    def __init__(self, user, message):
        self.user = user
        self.message = message
        self.timestamp = time.time()


class Server(Cog[NotABot]):
    def __init__(self, bot):
        super().__init__(bot)
        self.afks = getattr(bot, 'afks', {})
        self.bot.afks = self.afks
        self._afk_cd = CooldownMapping(Cooldown(1, 4), GUILD_COOLDOWN)
        self._last_icons: dict[int, str] = {}

    async def cog_load(self):
        await super().cog_load()
        await self._load_banner_rotate()
        await self._load_icon_rotate()

    def cog_unload(self):
        self.load_expiring_events.cancel()

        for task in list(self.bot.banner_rotate.values()):
            task.cancel()
        self.bot.banner_rotate.clear()

        for task in list(self.bot.icon_rotate.values()):
            task.cancel()
        self.bot.icon_rotate.clear()

    @tasks.loop(hours=3)
    async def load_expiring_events(self):
        # Load events that expire in an hour
        await self._load_banner_rotate()

    async def _load_banner_rotate(self):
        sql = 'SELECT guild, banner_delay, banner_delay_start FROM guilds WHERE banner_delay IS NOT NULL'
        rows = await self.bot.dbutil.fetch(sql)
        for row in rows:
            self.load_guild_rotate(row['banner_delay_start'], timedelta(seconds=row['banner_delay']), row['guild'])

    async def _load_icon_rotate(self):
        sql = 'SELECT guild, icon_delay, icon_delay_start FROM guilds WHERE icon_delay IS NOT NULL'
        rows = await self.bot.dbutil.fetch(sql)
        for row in rows:
            self.load_icon_rotate(row['icon_delay_start'], timedelta(seconds=row['icon_delay']), row['guild'])

    async def cog_check(self, ctx: Context) -> bool:
        if ctx.guild is None:
            raise NoPrivateMessage()
        return True

    @group(invoke_without_command=True)
    @cooldown(1, 20, type=BucketType.user)
    async def top(self, ctx, page: int=1):
        """Get the top users on this server based on the most important values"""
        if page > 0:
            page -= 1

        guild = ctx.guild
        filtered_roles = {}

        # remove some roles that have perms for my own guild
        if guild.id == 217677285442977792:
            if not guild.chunked:
                await guild.chunk()

            # These should only be used for set operations
            filtered_roles = {321374867557580801, 331811458012807169, 361889118210359297, 380814558769578003,
                              337290275749756928, 422432520643018773, 322837972317896704, 323492471755636736,
                              329293030957776896, 317560511929647118, 363239074716188672, 365175139043901442}
            filtered_roles = {disnake.Role(guild=None, state=None, data={"id": id_, "name": ""}) for id_ in filtered_roles}

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

        def get_msg(page_idx):
            pg = pages[page_idx]
            if not isinstance(pg, int):
                return pg

            s = 'Leaderboards for **{}**\n\n'.format(guild.name)
            added = 0
            p = page_idx*10
            u: disnake.Member
            for idx, u in enumerate(sorted_users[p:p+10]):
                # Count user roles filtered if a specific server
                if guild.id == 217677285442977792:
                    role_count = len(set(u.roles) - filtered_roles)
                else:
                    role_count = len(u.roles)

                added += 1
                # role_count - 1 to not count the default role
                s += f'{idx + p + 1}. <@{u.id}> with {role_count - 1} roles  `{u}`\n'

            if added == 0:
                pages[page_idx] = 'Page out of range'
                return

            try:
                idx = sorted_users.index(ctx.author) + 1
                s += '\nYour rank is {} with {} roles\n'.format(idx, author_role_count - 1)
            except ValueError:
                pass
            pages[page_idx] = s

        paginator = Paginator(pages, initial_page=page, generate_page=get_msg)
        await paginator.send(ctx, allowed_mentions=disnake.AllowedMentions.none())

    @staticmethod
    async def _date_sort(ctx, starting_page, key, dtype='joined'):
        if starting_page > 0:
            starting_page -= 1

        guild = ctx.guild
        sorted_users = list(sorted(guild.members, key=key))
        # Indexes of all of the pages
        pages = list(range(1, ceil(len(guild.members)/10)+1))

        own_rank = ''

        try:
            author_idx = sorted_users.index(ctx.author) + 1
            t = utcnow() - key(ctx.author)
            t = format_timedelta(t, DateAccuracy.Day)
            own_rank = f'\nYour rank is {author_idx}. You {dtype} {t} ago at {disnake.utils.format_dt(key(ctx.author), "F")}\n'
        except ValueError:
            pass

        def get_page(page_idx):
            existing_page = pages[page_idx]
            if not isinstance(existing_page, int):
                return existing_page

            s = 'Leaderboards for **{}**\n\n'.format(guild.name)
            p = page_idx * 10

            page = sorted_users[p:p+10]

            if not page:
                pages[page_idx] = 'Page out of range'
                return

            u: disnake.Member
            for idx, u in enumerate(page):
                date = key(u)
                td = format_timedelta(utcnow() - date, DateAccuracy.Day)
                join_date = disnake.utils.format_dt(date, 'F')

                s += f'{idx + p + 1}. {u.mention} {dtype} {td} ago on {join_date}  `{u}`\n'

            s += own_rank
            pages[page_idx] = s

        paginator = Paginator(pages, initial_page=starting_page, generate_page=get_page)
        await paginator.send(ctx, allowed_mentions=disnake.AllowedMentions.none())

    @top.command(np_pm=True)
    @cooldown(1, 10)
    async def join(self, ctx, page: int=1):
        """Sort users by join date"""
        await self._date_sort(ctx, page, lambda u: u.joined_at or utcnow(), 'joined')

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
        pages: list[bool | disnake.Embed] = [False for _ in range(page_count)]

        title = f'Mute roll stats for guild {ctx.guild}'

        def cache_page(page_idx: int, custom_description=None):
            i = page_idx * page_entries
            rows = stats[i:i + page_entries]
            if custom_description:
                embed = disnake.Embed(title=title, description=custom_description)
            else:
                embed = disnake.Embed(title=title)

            embed.set_footer(text=f'Page {page_idx + 1}/{len(pages)}')
            for row in rows:
                winrate = round(row['wins'] * 100 / row['games'], 1)
                v = f'<@{row["uid"]}>\n' \
                    f'Winrate: {winrate}% with {row["wins"]} wins\n' \
                    f'Current win streak: {row["current_streak"]}\n' \
                    f'Biggest win streak: {row["biggest_streak"]}\n' \
                    f'Current loss streak: {row["current_lose_streak"]}\n' \
                    f'Biggest loss streak: {row["biggest_lose_streak"]}'
                embed.add_field(name=f'{row["games"]} games', value=v)

            pages[page_idx] = embed
            return embed

        # Used for putting callers stats in the description of embed
        custom_desc = None

        def get_page(page_idx: int):
            page = pages[page_idx]
            if not page:
                return cache_page(page_idx, custom_desc)

            return page

        if isinstance(user, BaseUser) or isinstance(user, disnake.Member):
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

        paginator = Paginator(pages, generate_page=get_page)

        await paginator.send(ctx)

    @group(aliases=['mr_top', 'mr_stats', 'mrtop'], invoke_without_command=True)
    @cooldown(2, 5, GUILD_COOLDOWN)
    async def mute_roll_top(self, ctx, *, user: PossibleUser=None):
        """
        Sort mute roll stats using a custom algorithm
        It prioritizes amount of wins and winrate over games played tho games played
        also has a decent impact on results
        """
        await self._post_mr_top(ctx, user or ctx.author)

    @mute_roll_top.command()
    @cooldown(2, 5, GUILD_COOLDOWN)
    async def games(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by amount of games played"""
        await self._post_mr_top(ctx, user or ctx.author, sort='games')

    @mute_roll_top.command()
    @cooldown(2, 5, GUILD_COOLDOWN)
    async def wins(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by amount of games won"""
        await self._post_mr_top(ctx, user or ctx.author, sort='wins')

    @mute_roll_top.command(aliases=['wr'])
    @cooldown(2, 5, GUILD_COOLDOWN)
    async def winrate(self, ctx, *, user: PossibleUser=None):
        """
        Sort mute roll stats by winrate while also taking games played into account tho only slightly
        """
        # Sort by winrate while prioritizing games played a bit
        # If we dont do this we'll only get 1 win 1 game users at the top
        sort = '1/SQRT( POWER((1 - wins / games::decimal), 2) + POWER(1 / games::decimal, 2)* 0.9 )'
        await self._post_mr_top(ctx, user or ctx.author, sort=sort)

    @mute_roll_top.command(aliases=['ws'])
    @cooldown(2, 5, GUILD_COOLDOWN)
    async def winstreak(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by highest winstreak"""
        await self._post_mr_top(ctx, user or ctx.author, sort='biggest_streak')

    @mute_roll_top.command(aliases=['ls'])
    @cooldown(2, 5, GUILD_COOLDOWN)
    async def losestreak(self, ctx, *, user: PossibleUser=None):
        """Sort mute roll stats by highest losing streak"""
        await self._post_mr_top(ctx, user or ctx.author, sort='biggest_lose_streak')

    async def _dl(self, ctx, url):
        try:
            data, mime_type = await raw_image_from_url(url, get_mime=True)
        except OverflowError:
            await ctx.send('Failed to download. File is too big')
        except TypeError:
            await ctx.send('Link is not a direct link to an image')
        else:
            return data, mime_type

    @command(aliases=['delete_emoji', 'delete_emtoe', 'del_emote'])
    @cooldown(2, 6, GUILD_COOLDOWN)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def delete_emote(self, ctx, emotes: Greedy[GuildEmoji]):
        """
        Delete one or more emotes from this server
        """

        await ctx.send(f'Do you want to delete the emote(s) {" ".join([str(e) for e in emotes])}')
        if not await wait_for_yes(ctx, 30):
            return

        emote = None
        try:
            for emote in emotes:
                await emote.delete()
        except disnake.HTTPException as e:
            await ctx.send('Failed to delete emote %s because of an error\n%s' % (emote, e))

        else:
            await ctx.send(f'Deleted emotes {" ".join([e.name for e in emotes])}')

    @command(aliases=['addemote', 'addemoji', 'add_emoji', 'add_emtoe'])
    @cooldown(2, 6, GUILD_COOLDOWN)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def add_emote(self, ctx, link=None, name=None):
        """Add an emote to the server. If name not give it will be taken from the filename."""
        guild = ctx.guild

        if link and is_url(link):
            pass

        else:
            if not ctx.message.attachments:
                return await ctx.send(f'No image provided in {link} or attachments', allowed_mentions=disnake.AllowedMentions.none())

            name = link or None
            link = ctx.message.attachments[0].url

        data = await self._dl(ctx, link)

        if not data:
            return

        if not name:
            name = get_filename_from_url(link).split('.')[0]

        data, _ = data

        try:
            await guild.create_custom_emoji(name=name, image=data.getvalue(), reason=f'{ctx.author} created emote')
        except disnake.HTTPException as e:
            await ctx.send('Failed to create emote because of an error\n%s\nDId you check if the image is under 256kb in size' % e)
        else:
            await ctx.send('created emote %s' % name)

    @command()
    @cooldown(2, 6)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def rename(self, ctx, emote: disnake.Emoji, new_name):
        """Rename the given emote"""
        if ctx.guild != emote.guild:
            await ctx.send('The emote is not from this server')
            return

        try:
            await emote.edit(name=new_name)
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to rename emote\n{e}')

        await ctx.send(f'Renamed the given emote to {new_name}')

    @staticmethod
    async def _add_sticker(ctx: BotContext, sticker_file: BytesIO | disnake.Attachment, name: str, emoji: str = 'no_emoji', description: str = ''):
        guild = ctx.guild

        if len(guild.stickers) > guild.sticker_limit:
           await ctx.send(f'Sticker limit reached for guild ({len(guild.stickers) + 1} > {guild.sticker_limit})')
           return

        if isinstance(sticker_file, disnake.Attachment):
            file = await sticker_file.to_file()
        else:
            file = disnake.File(sticker_file)

        try:
            sticker = await guild.create_sticker(
                name=name,
                emoji=emoji,
                file=file,
                description=description,
                reason=f'{ctx.author} created sticker {name}')
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to create sticker.\n{e}')
            return

        if isinstance(ctx, disnake.ApplicationCommandInteraction):
            await ctx.send(f'Created sticker {sticker.name}')
        else:
            await ctx.send('Created sticker', stickers=[sticker])

    @slash_command(name='add_sticker', contexts=InteractionContextTypes(guild=True), default_member_permissions=disnake.Permissions(manage_emojis=True))
    @cooldown(2, 6, GUILD_COOLDOWN)
    @bot_has_permissions(manage_emojis=True)
    async def add_sticker_slash(self, inter: disnake.ApplicationCommandInteraction,
                                sticker_file: disnake.Attachment = Param(name='sticker_file', description='Image of the sticker as a file', default=None),
                                sticker_url: str = Param(name='sticker_url', description='Image of the sticker as a url', default=None),
                                name: str = Param(name='name', description='Name of the sticker'),
                                emoji: str = Param(name='emoji', description='Emoji used for the sticker', default='no_emoji'),
                                description: str = Param(name='description', description='Description of the emoji', default='')):
        """
        Create a sticker from a url or an attachment
        """
        file = None
        if sticker_file:
            file = sticker_file
        elif sticker_url is not None and is_url(sticker_url):
            file = await dl_image(inter, sticker_url, get_raw=True)

        if file is None:
            await inter.send('Please provide either sticker_file or sticker_url', ephemeral=True)
            return

        await self._add_sticker(inter, file, name, emoji, description)

    @command(aliases=['create_sticker'])
    @cooldown(2, 6, GUILD_COOLDOWN)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def add_sticker(self, ctx: Context, name: str, sticker_url: str = None, emoji: str = 'no_emoji', description: str = ''):
        """
        Create a sticker from a url or an attachment.

        Usage with url
        `{prefix}{name} "Sticker name" https://imgur.com/image.png 🤯`

        Usage with attachment
        `{prefix}{name} "Sticker name" 🤯`
        """

        # Assume attachment given here and shift parameters by one
        if sticker_url is not None and not is_url(sticker_url):
            emoji = sticker_url
            description = emoji

        data = await get_image(ctx, sticker_url, get_raw=True, current_message_only=True)
        if data is None:
            return

        await self._add_sticker(ctx, data, name, emoji, description)

    @staticmethod
    async def _steal_sticker(ctx: BotContext, message: disnake.Message):
        guild = ctx.guild

        if len(guild.stickers) > guild.sticker_limit:
            await ctx.send('Sticker limit reached for guild')
            return

        if not message:
            message = ctx.message

        if not message.stickers:
            await ctx.send('No stickers found from message')
            return

        sticker = message.stickers[0]

        try:
            file = await sticker.to_file()
        except:
            logger.exception('Failed to download sticker')
            await ctx.send('Failed to download sticker. Try again later')
            return

        try:
            sticker = await guild.create_sticker(
                name=sticker.name,
                emoji='no_emoji',
                file=file,
                reason=f'{ctx.author} stole {sticker.name}')
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to steal sticker.\n{e}')
            return

        if isinstance(ctx, disnake.ApplicationCommandInteraction):
            await ctx.send(f'Created sticker {sticker.name}')
        else:
            await ctx.send('Created sticker', stickers=[sticker])

    @slash_command(name='steal_sticker', contexts=InteractionContextTypes(guild=True), default_member_permissions=disnake.Permissions(manage_emojis=True))
    @cooldown(2, 6, GUILD_COOLDOWN)
    @bot_has_permissions(manage_emojis=True)
    async def steal_sticker_slash(self, inter: disnake.ApplicationCommandInteraction,
                                  message: str = Param(name='message_id', description='Id of the message containing the sticker to be stolen')):
        """
        Steals a sticker from the given message or the command message by default
        """
        actual_message = await MessageConverter().convert(inter, message)

        await self._steal_sticker(inter, actual_message)

    @command(aliases=['ssteal'])
    @cooldown(2, 6, GUILD_COOLDOWN)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def steal_sticker(self, ctx: Context, message: Optional[disnake.Message] = None):
        """
        Steals a sticker from the given message or the command message by default
        """
        await self._steal_sticker(ctx, message or ctx.message)

    @command(aliases=['trihard'])
    @cooldown(2, 6, GUILD_COOLDOWN)
    @has_permissions(manage_emojis=True)
    @bot_has_permissions(manage_emojis=True)
    async def steal(self, ctx, emoji: Greedy[PartialEmojiConverter]=None,
                    message: Optional[disnake.Message]=None,
                    user: disnake.Member=None):
        """Add emotes to this server from other servers.
        You can either use the emotes you want separated by spaces in the message
        or you can give a message id in the channel that the command is run in to fetch
        the emotes from that message. Also a user can be specified and the current status emote will be stolen.
        Both cannot be used at the same time though.
        Maximum amount of emotes that can be stolen at a time is 20.
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
                    disnake.PartialEmoji.with_state(self.bot._connection,
                                                    animated=animated,
                                                    name=name,
                                                    id=eid)
                )

        elif user:
            for activity in user.activities:
                if isinstance(activity, disnake.CustomActivity) and activity.emoji:
                    e = activity.emoji
                    emotes.append(
                        disnake.PartialEmoji.with_state(self.bot._connection,
                                                        animated=e.animated,
                                                        name=e.name,
                                                        id=e.id)
                    )
                    break
        else:
            for e in emoji:
                if e.is_custom_emoji():
                    emotes.append(e)

        if len(emotes) > 20:
            await ctx.send(f'Too many emotes ({len(emotes)}). Maximum amount of emotes that can be stolen at a time is 20')
            return

        update_msg = None
        if len(emotes) > 2:
            update_msg = await ctx.send(f'Trying to steal {len(emotes)} emotes')

        errors = 0
        guild = ctx.guild
        stolen = []
        for emote in set(emotes):
            if errors >= 3:
                return await ctx.send('Too many errors while uploading emotes. Aborting')

            try:
                data = await emote.read()
            except (disnake.DiscordException, disnake.HTTPException) as e:
                await ctx.send(f'Failed to download emote {emote.name}\n{e}')
                errors += 1
                continue

            try:
                em = await guild.create_custom_emoji(name=emote.name, image=data, reason=f'{ctx.author} stole emote')
                stolen.append(str(em))
            except disnake.HTTPException as e:
                if e.code == 30008:
                    await ctx.send('Emote capacity reached\n{}'.format(e))
                    break

                await ctx.send(f'Error while uploading emote {emote.name}\n%s' % e)
                errors += 1
            except disnake.ClientException:
                await ctx.send(f'Failed to create emote {emote.name} because of an error')
                logger.exception('Failed to create emote')
                errors += 1

            try:
                if len(stolen) != 0 and len(stolen) % 5 == 0:
                    await update_msg.edit(content=f'{stolen} emotes stolen')
            except disnake.HTTPException:
                pass

        if stolen:
            await ctx.send('Successfully stole {}'.format(' '.join(map(str, stolen))))
        else:
            await ctx.send("Didn't steal anything")

    @command()
    @bot_has_permissions(embed_links=True)
    @cooldown(1, 20, GUILD_COOLDOWN)
    async def channels(self, ctx):
        """
        Lists all channels in the server in an embed
        """

        channel_categories = {}

        for chn in sorted(ctx.guild.channels, key=lambda c: c.position):
            if isinstance(chn, disnake.CategoryChannel) and chn.id not in channel_categories:
                channel_categories[chn.id] = []
            else:
                category = chn.category_id
                if category not in channel_categories:
                    channel_categories[category] = []

                channel_categories[category].append(chn)

        description = None

        def make_category(channels):
            val = ''
            for chn in sorted(channels, key=lambda c: isinstance(c, disnake.VoiceChannel)):
                if isinstance(chn, disnake.VoiceChannel):
                    val += '\\🔊 '
                else:
                    val += '# '

                val += f'{chn.name}\n'

            return val

        if None in channel_categories:
            description = make_category(channel_categories.pop(None))

        paginator = EmbedPaginator(title='Channels', description=description)

        for category_id in sorted(channel_categories.keys(), key=lambda k: ctx.guild.get_channel(k).position):
            category = ctx.guild.get_channel(category_id)

            val = make_category(channel_categories[category_id])

            paginator.add_field(name=category.name.upper(), value=val, inline=False)

        paginator.finalize()

        for page in paginator.pages:
            await ctx.send(embed=page)

    @command()
    @cooldown(1, 10, BucketType.user)
    async def join_date(self, ctx, user: disnake.User=None):
        """
        Returns the first recorded join date to this server.
        Dates before December 17th 2019 might not be the earliest join date
        """
        user = user or ctx.author
        date = await self.bot.dbutil.get_join_date(user.id, ctx.guild.id)
        if not date:
            await ctx.send('No join date logged for user or an error happened')
            return

        await ctx.send(f'First recorded join for {user} is {date.strftime("%Y-%m-%d %H:%M")} (YYYY-MM-DD)')

    @command()
    @has_permissions(administrator=True)
    @cooldown(1, 10)
    async def delete_server(self, ctx):
        """
        Deletes server
        """
        p = os.path.join('data', 'templates', 'loading.gif')
        await ctx.send('Please wait. Server deletion in progress', file=disnake.File(p, filename='loading.gif'))

    async def _delete_image_file(self, ctx: BotContext, base_path: str, filename: str):
        files = os.listdir(base_path)

        # Sanitize path to only the filename
        filename = ntpath.basename(filename)

        if filename not in files:
            await ctx.send(f'File {filename} not found')
            ctx.command.reset_cooldown(ctx)
            return

        file = os.path.join(base_path, filename)
        thumb = os.path.join(base_path, 'thumbs', filename)

        def do_it() -> BytesIO:
            data = read_image_file_to_buffer(file)

            try:
                os.remove(file)
            except OSError:
                logger.exception(f'Failed to delete file {file}')
                pass

            try:
                os.remove(thumb)
            except OSError:
                logger.exception(f'Failed to delete thumb {thumb}')
                pass

            return data

        image_data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_it)

        await ctx.send(f'Deleted {filename}', file=disnake.File(image_data, filename))

    async def _list_thumbs(self, ctx: BotContext, base_path: str, filename: str | None, image_type: str):
        (_, _, image_files) = next(os.walk(base_path))

        if not image_files:
            await ctx.send(f'No {image_type} found for guild')
            self.reset_cooldown(ctx)
            return None

        if filename:
            # Sanitize path to only the filename
            filename = ntpath.basename(filename)

            if filename not in image_files:
                await ctx.send(f'File {filename} not found')
                self.reset_cooldown(ctx)
                return None

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
                THUMB_SIZE_VAR = THUMB_SIZE if image_type == 'banners' else ICON_THUMB_SIZE

                # How many files we have in one image
                w = 3 if image_type == 'banners' else 5
                if len(image_files) > 30:
                    h = 6
                elif len(image_files) > 24:
                    h = 5
                else:
                    h = 4

                width = THUMB_SIZE_VAR[0]*w
                images = []  # Images to be concatenated together
                stack = []  # Concatenated images
                curr_files = []  # Filenames for images in the images variable
                filenames = []  # Filenames for current stack
                data = BytesIO()

                for banner in image_files:
                    curr_files.append(banner)
                    thumb = os.path.join(thumbs_path, banner)

                    # Create thumb if it doesn't exist
                    if not os.path.exists(thumb):
                        og_img = Image.open(os.path.join(base_path, banner))
                        im_resized = og_img.resize(THUMB_SIZE_VAR, Image.Resampling.LANCZOS)
                        im_resized.save(thumb, 'PNG')

                    im = Image.open(thumb)

                    # Append thumb to list and concatenate them when the limit
                    # is reached
                    images.append(im)
                    if len(images) >= w:
                        stack.append(concatenate_images(
                            images, THUMB_SIZE_VAR[0]
                        ))
                        images.clear()
                        filenames.append(' '.join(curr_files))
                        curr_files.clear()

                    # Stack concatenated images when the limit is reached
                    if len(stack) >= h:
                        stack_images(stack, THUMB_SIZE_VAR[1], width).save(data, 'PNG')
                        data.seek(0)
                        yield data, filenames
                        filenames = []
                        data = BytesIO()
                        stack.clear()

                if images:
                    stack.append(concatenate_images(images, THUMB_SIZE_VAR[0]))
                    filenames.append(' '.join(curr_files))

                if stack:
                    stack_images(stack, THUMB_SIZE_VAR[1], width).save(data, 'PNG')
                    data.seek(0)
                    yield data, filenames

        try:
            for image_data, filenames in await self.bot.loop.run_in_executor(self.bot.threadpool, do_it):
                filenames = '\n'.join(filenames)
                await ctx.send(f'```\n{filenames}\n```', file=disnake.File(image_data, filename or f'{image_type}.png'))
        except OSError:
            logger.exception(f'Failed to load {image_type}')
            await ctx.send(f'Failed to show {image_type}')
            return

    async def _validate_rotate_schedule(self, ctx: BotContext, delay: timedelta, start_time: str) -> datetime.time | None:
        if delay < timedelta(hours=6):
            await ctx.send('Minimum delay is 6 hours')
            self.reset_cooldown(ctx)
            return

        if delay > timedelta(days=4):
            await ctx.send('Maximum delay is 4 days')
            self.reset_cooldown(ctx)
            return

        if not re.match(r'^(\d{2}):(\d{2})$', start_time):
            await ctx.send('Start time should be in the 24h format. e.g. 18:00')
            self.reset_cooldown(ctx)
            return

        t = dtime.fromisoformat(start_time)

        tz = await self.get_timezone(ctx, ctx.author.id)
        tztime = utcnow().astimezone(tz).replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        t = tztime.astimezone(pytz.UTC).time()

        return t

    async def get_timezone(self, ctx, user_id: int):
        tz = await self.bot.dbutil.get_timezone(user_id)
        if tz:
            try:
                return await ctx.bot.loop.run_in_executor(ctx.bot.threadpool, pytz.timezone, tz)
            except pytz.UnknownTimeZoneError:
                pass

        return pytz.FixedOffset(0)

    # region banners

    @command()
    @cooldown(1, 15, GUILD_COOLDOWN)
    @has_permissions(manage_guild=True)
    async def upload_banner(self, ctx, no_resize: Optional[bool]=False, image=None):
        """Add an image to the server banner rotation.
        By default, images will be up or downscaled and cropped to 960x540.
        If no_resize is True then the image will be saved as is without resizing and cropping."""
        img: Image.Image = await get_image(ctx, image, True, get_raw=no_resize)
        if img is None:
            return

        data: Optional[BytesIO] = None
        if no_resize:
            data = img
            img = Image.open(data)

        def do_it():
            nonlocal img

            is_gif = img.format == 'GIF'

            if not no_resize:
                w, h = (960, 540)

                # According to docs LANCZOS is best for downsampling. In other cases use bicubic
                resample = Image.Resampling.LANCZOS if (img.width > w and img.height > h) else Image.Resampling.BICUBIC

                if is_gif:
                    # Returns bytes io
                    img = resize_gif(img, (w, h), crop_to_size=True,
                                     center_cropped=True,
                                     can_be_bigger=True,
                                     resample=resample,
                                     get_raw=True)
                else:
                    img = resize_keep_aspect_ratio(img, (w, h), crop_to_size=True,
                                                   center_cropped=True,
                                                   can_be_bigger=True,
                                                   resample=resample)

            base_path = os.path.join('data', 'banners', str(ctx.guild.id))
            os.makedirs(base_path, exist_ok=True)
            filename = str(ctx.message.id) + ('.gif' if is_gif else '.png')

            full_path = os.path.join(base_path, filename)

            if is_gif:
                img = data if no_resize else img
                buffer = img.getbuffer()
                if buffer.nbytes > 8_000_000:
                    raise BotException('Banner image was too big in filesize. '
                                       'If the gif is smaller than 960x540 try setting no_resize to true. '
                                       'To manually edit the gif use a service like <https://ezgif.com>')

                with open(full_path, 'wb') as f:
                    f.write(buffer)

                img.seek(0)
                img = Image.open(img)
            else:
                if no_resize:
                    with open(full_path, 'wb') as f:
                        f.write(data.getbuffer())
                else:
                    img.save(
                        full_path,
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
            async with ctx.typing():
                file = await self.bot.run_async(do_it)
        except OSError:
            logger.exception('Failed to save banner')
            await ctx.send('Failed to save banner image')
            return

        await ctx.send(f'Saved banner image as {file}')

    @command(aliases=['bremove', 'delete_banner'])
    @cooldown(1, 5, GUILD_COOLDOWN)
    @has_permissions(manage_guild=True)
    async def remove_banner(self, ctx, filename):
        """Remove a banner from the rotation"""
        guild = ctx.guild
        base_path = os.path.join('data', 'banners', str(guild.id))
        if not os.path.exists(base_path):
            await ctx.send('No banners found for guild')
            ctx.command.reset_cooldown(ctx)
            return

        await self._delete_image_file(ctx, base_path, filename)

    @command()
    @cooldown(1, 15, GUILD_COOLDOWN)
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

        await self._list_thumbs(ctx, base_path, filename, 'banners')

    async def random_banner(self, base_path, guild_id: int):
        if not os.path.exists(base_path):
            os.makedirs(base_path, exist_ok=True)

        (_, _, files) = next(os.walk(base_path))

        old_banner = await self.bot.dbutil.last_banner(guild_id)

        try:
            files.remove(old_banner)
        except ValueError:
            pass
        else:
            if not files:
                return None

        if not files:
            return None

        filename = random.choice(files)
        return filename

    async def rotate_banner(self, guild: disnake.Guild):
        base_path = os.path.join('data', 'banners', str(guild.id))
        filename = await self.random_banner(base_path, guild.id)

        if not filename:
            return

        data = read_image_file(base_path, filename)

        try:
            await guild.edit(banner=data)
        except (disnake.HTTPException, TypeError, ValueError):
            return

    async def do_guild_banner_rotate(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        await self.rotate_banner(guild)

    def load_guild_rotate(self, delay_start: dtime, delay: timedelta, guild_id: int):
        old_task = self.bot.banner_rotate.get(guild_id)
        if old_task and not old_task.done():
            return

        async def method():
            while True:
                await asyncio.sleep(get_next_rotate_run_time(delay_start, delay))
                await self.do_guild_banner_rotate(guild_id)

        task = asyncio.run_coroutine_threadsafe(method(), self.bot.loop)
        self.bot.banner_rotate[guild_id] = task

    @group(aliases=['brotate'], invoke_without_command=True)
    @guild_has_features('BANNER')
    @bot_has_permissions(manage_guild=True)
    @cooldown(1, 1800, GUILD_COOLDOWN)
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

        data = read_image_file(base_path, filename)

        try:
            await guild.edit(banner=data)
        except (disnake.HTTPException, TypeError, ValueError) as e:
            await ctx.send(f'Failed to set banner because of an error\n{e}')
            return

        await self.bot.dbutil.set_last_banner(guild.id, filename)
        await ctx.send('♻️')

    @banner_rotate.command(name='stop_schedule', aliases=['stop'])
    @has_permissions(manage_guild=True)
    async def banner_schedule_stop(self, ctx: Context):
        """
        Disables the automatic banner rotation
        """
        sql = 'UPDATE guilds SET banner_delay=NULL, banner_delay_start=NULL WHERE guild=$1'
        try:
            await self.bot.dbutil.execute(sql, (ctx.guild.id,))
        except:
            logger.exception('Failed to reset banner schedule')
            await ctx.send('Failed to update settings. Try again later')
            return

        await ctx.send('Automatic banner rotation disabled')

    @banner_rotate.command(name='schedule')
    @guild_has_features('BANNER')
    @bot_has_permissions(manage_guild=True)
    @has_permissions(manage_guild=True)
    @cooldown(1, 5)
    async def banner_schedule(self, ctx: Context, start_time: str, *, delay: TimeDelta):
        """
        Automatically rotate the server banner on a schedule.
        Usage:
        {prefix}{name} 12:00 12h
        """
        t = await self._validate_rotate_schedule(ctx, delay, start_time)
        if t is None:
            return

        sql = 'UPDATE guilds SET banner_delay=$1, banner_delay_start=$2::time WHERE guild=$3'
        try:
            await self.bot.dbutil.execute(sql, (delay.total_seconds(), t, ctx.guild.id))
        except:
            logger.exception('Failed to update banner schedule')
            await ctx.send('Failed to update settings. Try again later')
            return

        timeout = get_next_rotate_run_time(t, delay)

        task = self.bot.banner_rotate.get(ctx.guild.id)
        if task:
            task.cancel()
            self.bot.banner_rotate.pop(ctx.guild.id, None)

        self.load_guild_rotate(timeout, ctx.guild.id)
        await ctx.send(f'Next automatic banner rotation {native_format_timedelta(timedelta(seconds=timeout))}')

    # endregion banners

    # region server icons

    @staticmethod
    def _get_icon_path(guild_id: int) -> str:
        return os.path.join('data', 'server_icons', str(guild_id))

    def random_icon(self, base_path: str, guild_id: int) -> str | None:
        if not os.path.exists(base_path):
            os.makedirs(base_path, exist_ok=True)

        (_, _, files) = next(os.walk(base_path))
        old_icon = self._last_icons.get(guild_id)

        try:
            files.remove(old_icon)
        except ValueError:
            pass

        if not files:
            return None

        filename = random.choice(files)
        return filename

    async def rotate_icon(self, guild: disnake.Guild):
        base_path = self._get_icon_path(guild.id)
        filename = self.random_icon(base_path, guild.id)

        if not filename:
            return

        data = read_image_file(base_path, filename)

        try:
            await guild.edit(icon=data)
            self._last_icons[guild.id] = filename
        except (disnake.HTTPException, TypeError, ValueError):
            return

    async def do_guild_icon_rotate(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return

        await self.rotate_icon(guild)

    def load_icon_rotate(self, delay_start: dtime, delay: timedelta, guild_id: int):
        old_task = self.bot.icon_rotate.get(guild_id)
        if old_task and not old_task.done():
            return

        async def method():
            while True:
                await asyncio.sleep(get_next_rotate_run_time(delay_start, delay))
                await self.do_guild_icon_rotate(guild_id)

        task = asyncio.run_coroutine_threadsafe(method(), self.bot.loop)

        self.bot.icon_rotate[guild_id] = task

    @slash_command(name='rotate-icon-management',
                   contexts=InteractionContextTypes(guild=True),
                   default_member_permissions=disnake.Permissions(manage_guild=True))
    async def icon_rotate_management_base(self, inter: disnake.ApplicationCommandInteraction):
        pass

    @command(aliases=['pls'])
    @cooldown(1, 15, GUILD_COOLDOWN)
    @has_permissions(manage_guild=True)
    async def upload_icon(self, ctx: Context, no_resize: bool | None = False, image=None):
        await self._upload_icon(ctx, image, no_resize=no_resize)

    @icon_rotate_management_base.sub_command(name='upload')
    async def upload_icon_slash(self,
                                inter: disnake.ApplicationCommandInteraction,
                                image: disnake.Attachment | None = Param(description='Image to upload as server icon', default=None),
                                image_url: str = Param(description='Image url to upload as server icon. To support e.g. mentions, use the old style prefix command.', default=None, name='image_url'),
                                no_resize: bool = Param(description='If true, the image will not be resized or cropped', default=False)):
        """Upload an image to the server icon rotation."""
        self.share_cooldown(self.upload_icon, inter)
        await inter.response.defer()
        await self._upload_icon(inter, image or image_url, no_resize=no_resize)

    async def _upload_icon(self, ctx: BotContext, image: str | Attachment | None = None, no_resize: bool = False):
        """Add an image to the server icon rotation.
        By default, images will be up or downscaled and cropped to 960x540.
        If no_resize is True then the image will be saved as is without resizing and cropping."""
        data: BytesIO | None = await get_image(ctx, image, True, get_raw=True)
        if data is None:
            return

        img = Image.open(data)

        def do_it():
            nonlocal img

            is_gif = img.format == 'GIF'
            w, h = (512, 512)
            do_resize = img.width > w or img.height > h
            resized = do_resize and not no_resize

            if resized:
                # According to docs LANCZOS is best for downsampling. In other cases use bicubic
                resample = Image.Resampling.LANCZOS if (img.width > w and img.height > h) else Image.Resampling.BICUBIC

                if is_gif:
                    # Returns bytes io
                    img = resize_gif(
                        img,
                        (w, h),
                        crop_to_size=True,
                        center_cropped=True,
                        can_be_bigger=True,
                        resample=resample,
                        get_raw=True
                    )
                else:
                    img = resize_keep_aspect_ratio(
                        img,
                        (w, h),
                        crop_to_size=True,
                        center_cropped=True,
                        can_be_bigger=True,
                        resample=resample
                    )

            base_path = self._get_icon_path(ctx.guild.id)
            os.makedirs(base_path, exist_ok=True)

            filename = str(get_id_from_ctx(ctx)) + ('.gif' if is_gif else '.png')

            full_path = os.path.join(base_path, filename)
            if is_gif:
                buffer = data.getbuffer() if not resized else img.getbuffer()
                if buffer.nbytes > 5_000_000:
                    raise BotException('Icon image was too big in filesize. '
                                       'If the gif is larger than 512x512, try manually editing the gif using a service like <https://ezgif.com>')

                with open(full_path, 'wb') as f:
                    f.write(buffer)

                if resized:
                    img.seek(0)
                    img = Image.open(img)
            else:
                if not resized:
                    with open(full_path, 'wb') as f:
                        f.write(data.getbuffer())
                else:
                    img.save(
                        full_path,
                        'PNG'
                    )

            # Make thumbnails every icon for faster access when viewing multiple
            # icons at once
            base_path = os.path.join(base_path, 'thumbs')
            os.makedirs(base_path, exist_ok=True)

            img = img.resize(ICON_THUMB_SIZE, Image.Resampling.LANCZOS)
            img.save(
                os.path.join(base_path, filename),
                'PNG'
            )

            return filename

        try:
            self.reset_cooldown(ctx)
            file = await self.run_with_typing(ctx, do_it)

        except OSError:
            logger.exception('Failed to save icon')
            await ctx.send('Failed to save icon image')
            return

        await ctx.send(f'Saved icon image as {file}')

    @command(aliases=['iremove', 'delete_icon'])
    @cooldown(1, 5, GUILD_COOLDOWN)
    @has_permissions(manage_guild=True)
    async def remove_icon(self, ctx: Context, filename: str):
        """Remove an icon from the rotation"""
        await self._remove_icon(ctx, filename)

    @icon_rotate_management_base.sub_command(name='delete-icon')
    @cooldown(1, 5, GUILD_COOLDOWN)
    async def remove_icon_slash(self, inter: disnake.ApplicationCommandInteraction,
                                filename: str = Param(name='filename', description='Filename of the icon to remove')):
        """Remove an icon from the rotation"""
        await inter.response.defer()
        await self._remove_icon(inter, filename)

    async def _remove_icon(self, ctx: ApplicationCommandInteraction | Context, filename: str):
        guild = ctx.guild
        base_path = self._get_icon_path(guild.id)
        if not os.path.exists(base_path):
            await ctx.send('No icons found for guild')
            self.reset_cooldown(ctx)
            return

        await self._delete_image_file(ctx, base_path, filename)

    @command()
    @cooldown(1, 10, GUILD_COOLDOWN)
    async def icons(self, ctx: Context, filename: Optional[str] = None):
        """
        Show all icons in rotation for this server. If filename is specified,
        gives the full icon corresponding to that filename
        """
        await self._icons(ctx, filename)

    @slash_command(name='icons', contexts=InteractionContextTypes(guild=True))
    async def icons_slash(self, inter: disnake.ApplicationCommandInteraction, filename: str | None = Param(default=None, description='Filename of the icon to show')):
        """
        Show all icons in rotation for this server.
        """
        self.share_cooldown(self.icons, inter)
        await inter.response.defer()
        await self._icons(inter, filename)

    async def _icons(self, ctx: BotContext, filename: str | None = None):
        base_path = self._get_icon_path(ctx.guild.id)
        if not os.path.exists(base_path):
            await ctx.send('No icons found for guild')
            self.reset_cooldown(ctx)
            return

        await self._list_thumbs(ctx, base_path, filename, 'icons')

    @group(aliases=['rotate', 'potato', 'tomato', 'rotato', '🥔', '🍅'], invoke_without_command=True)
    @bot_has_permissions(manage_guild=True)
    @cooldown(1, 1800, GUILD_COOLDOWN)
    async def icon_rotate(self, ctx: Context, filename: str=None):
        await self._icon_rotate(ctx, filename)

    @slash_command(name='rotate-icon', contexts=InteractionContextTypes(guild=True))
    @bot_has_permissions(manage_guild=True)
    async def icon_rotate_slash(self, inter: disnake.ApplicationCommandInteraction, filename: str = Param(default=None, description='Filename of the icon to rotate to')):
        """Change server icon to one of the icons saved for the server"""
        self.share_cooldown(self.icon_rotate, inter)
        await inter.response.defer()
        await self._icon_rotate(inter, filename)

    async def _icon_rotate(self, ctx: BotContext, filename: str | None = None):
        guild = ctx.guild
        base_path = self._get_icon_path(guild.id)
        if not os.path.exists(base_path):
            os.makedirs(base_path, exist_ok=True)

        (_, _, files) = next(os.walk(base_path))

        if filename:
            # Sanitize path to only the filename
            filename = ntpath.basename(filename)

            if filename not in files:
                await ctx.send(f'File {filename} not found')
                self.reset_cooldown(ctx)
                return

        old_icon = self._last_icons.get(guild.id)

        try:
            files.remove(old_icon)
        except ValueError:
            pass
        else:
            if not files:
                await ctx.send('Server only has one icon to select from')
                self.reset_cooldown(ctx)
                return

        if not filename:
            if not files:
                await ctx.send('No icon rotation images found for guild')
                self.reset_cooldown(ctx)
                return

            filename = random.choice(files)

        if filename not in files:
            await ctx.send(f'File {filename} not found')
            self.reset_cooldown(ctx)
            return

        data = read_image_file(base_path, filename)

        try:
            await guild.edit(icon=data)
        except (disnake.HTTPException, TypeError, ValueError) as e:
            await ctx.send(f'Failed to set icon because of an error\n{e}')
            return

        self._last_icons[guild.id] = filename
        await ctx.send('♻️')

    @icon_rotate.command(name='stop_schedule', aliases=['stop'])
    @has_permissions(manage_guild=True)
    async def icon_schedule_stop(self, ctx: Context):
        """
        Disables the automatic icon rotation
        """
        await self._icon_schedule_stop(ctx)

    @icon_rotate_management_base.sub_command(name='stop-schedule')
    async def icon_schedule_stop_slash(self, inter: disnake.ApplicationCommandInteraction):
        """
        Disables the automatic icon rotation
        """
        await self._icon_schedule_stop(inter)

    async def _icon_schedule_stop(self, ctx: BotContext):
        """
        Disables the automatic icon rotation
        """
        sql = 'UPDATE guilds SET icon_delay=NULL, icon_delay_start=NULL WHERE guild=$1'
        try:
            await self.bot.dbutil.execute(sql, (ctx.guild.id,))
        except:
            logger.exception('Failed to reset icon rotate schedule')
            await ctx.send('Failed to update settings. Try again later')
            return

        await ctx.send('Automatic icon rotation disabled')

    @icon_rotate.command(name='schedule')
    @bot_has_permissions(manage_guild=True)
    @has_permissions(manage_guild=True)
    @cooldown(1, 5)
    async def icon_schedule(self, ctx: Context, start_time: str, *, delay: TimeDelta):
        """
        Automatically rotate the server icon on a schedule.
        Usage:
        {prefix}{name} 12:00 12h
        """
        await self._icon_schedule(ctx, delay, start_time)

    @icon_rotate_management_base.sub_command(name='schedule')
    @bot_has_permissions(manage_guild=True)
    @cooldown(1, 5)
    async def icon_schedule_slash(self, inter: disnake.ApplicationCommandInteraction,
                                  delay: timedelta = Param(converter=convert_timedelta, description='Delay in the format 1h 1m 1s', name='delay'),
                                  start_time: str = Param(description='Start time in 24h format. e.g. 18:00')):
        """
        Automatically rotate the server icon on a schedule.
        """
        await inter.response.defer()
        await self._icon_schedule(inter, delay, start_time)

    async def _icon_schedule(self, ctx: BotContext, delay: timedelta, start_time: str):
        t = await self._validate_rotate_schedule(ctx, delay, start_time)

        sql = 'UPDATE guilds SET icon_delay=$1, icon_delay_start=$2::time WHERE guild=$3'
        try:
            await self.bot.dbutil.execute(sql, (delay.total_seconds(), t, ctx.guild.id))
        except:
            logger.exception('Failed to update icon schedule')
            await ctx.send('Failed to update settings. Try again later')
            return

        timeout = get_next_rotate_run_time(t, delay)

        task = self.bot.icon_rotate.get(ctx.guild.id)
        if task:
            task.cancel()
            self.bot.icon_rotate.pop(ctx.guild.id, None)

        self.load_icon_rotate(timeout, delay.total_seconds(), ctx.guild.id)
        await ctx.send(f'Next automatic icon rotation {native_format_timedelta(timedelta(seconds=timeout))}')

    # endregion server icons

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
            try:
                await message.channel.send(f'`{user}` is no longer afk', delete_after=10)
            except disnake.HTTPException:
                pass
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

            messages = split_string(messages, list_join='\n')[:2]
        else:
            afk = afks[0]
            messages = (f'{afk.user} is afk {format_timedelta(int(time.time()-afk.timestamp), DateAccuracy.Hour-DateAccuracy.Minute)} ago: {afk.message}'[:2000], )

        try:
            for msg in messages:
                await message.channel.send(msg, allowed_mentions=disnake.AllowedMentions.none())
        except disnake.HTTPException:
            return

    @command(np_pm=True)
    @cooldown(1, 5, BucketType.user)
    async def afk(self, ctx, *, message: str = ''):
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

    @command(aliases=['delete_afk', 'clear_afk'])
    @has_permissions(manage_roles=True)
    @cooldown(2, 4, GUILD_COOLDOWN)
    async def remove_afk(self, ctx, *, user: disnake.User):
        """
        Removes the afk of the mentioned user on this server
        """
        self.afks.get(ctx.guild.id, {}).pop(user.id, None)
        await ctx.send(f'Removed afk message of the user {user}')


def setup(bot):
    bot.add_cog(Server(bot))

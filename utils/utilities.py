"""
MIT License

Copyright (c) s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import asyncio
import logging
import mimetypes
import os
import py_compile
import re
import shlex
import subprocess
from collections import OrderedDict
from collections.abc import Iterable
from datetime import timedelta, datetime, timezone
from enum import Enum
from random import randint
from typing import Union, TYPE_CHECKING, cast
from urllib.parse import urlparse

import disnake
import numpy
from aioredis.client import Redis
from asyncpg.exceptions import PostgresError
from disnake import ApplicationCommandInteraction
from disnake import abc
from validators import url as test_url

from bot.exceptions import CommandBlacklisted, NotOwner
from bot.globals import BlacklistTypes, PermValues
from enums.data_enums import RedisKeyNamespaces
from utils.imagetools import image_from_url

if TYPE_CHECKING:
    from bot.bot import Context
    from bot.botbase import BotBase

# Support for recognizing webp images used in many discord avatars
mimetypes.add_type('image/webp', '.webp')
logger = logging.getLogger('terminal')
audio = logging.getLogger('audio')

# https://stackoverflow.com/a/4628148/6046713
# Added days and aliases for names
# Also fixed any string starting with the first option (e.g. 10dd would count as 10 days) being accepted
time_regex = re.compile(
    r'((?P<days>\d+?) ?(d|days)( |$))?((?P<hours>\d+?) ?(h|hours)( |$))?((?P<minutes>\d+?) ?(m|min|minutes)( |$))?((?P<seconds>\d+?) ?(s|sec|seconds)( |$))?')
timeout_regex = re.compile(
    r'((?P<days>\d+?) ?(d|days)( |$))?((?P<hours>\d+?) ?(h|hours)( |$))?((?P<minutes>\d+?) ?(m|min|minutes)( |$))?((?P<seconds>\d+?) ?(s|sec|seconds)( |$))?(?P<reason>.*)+?',
    re.DOTALL)
timedelta_regex = re.compile(
    r'((?P<days>\d+?) )?(?P<hours>\d+?):(?P<minutes>\d+?):(?P<seconds>\d+?)')
seek_regex = re.compile(
    r'((?P<h>\d+)*(?:h ?))?((?P<m>\d+)*(?:m[^s]? ?))?((?P<s>\d+)*(?:s ?))?((?P<ms>\d+)*(?:ms ?))?')
FORMAT_BLACKLIST = ['mentions', 'channel_mentions', 'reactions', 'call',
                    'embeds', 'attachments', 'role_mentions', 'application',
                    'raw_channel_mentions', 'raw_role_mentions', 'raw_mentions']


class DateAccuracy(Enum):
    Second = 0
    Minute = 1
    Hour = 2
    Day = 3
    Week = -1  # Special case
    Month = 4
    Year = 5

    def __sub__(self, other):
        # When slicing weeks are off so we can assume we are working
        # from year (value of 1) to second (value of 6)
        # that's why slice value = 6-DateAccuracy.value
        if self.value > other.value:  # skipcq: PYL-W0143
            return slice(other.value, self.value)
        else:
            return slice(self.value, other.value)


class CallLater:
    def __init__(self, future, runs_at):
        self._future = future
        self.runs_at = runs_at

    @property
    def future(self):
        return self._future

    def cancel(self):
        self.future.cancel()

    def __repr__(self):
        return f'<{self.__class__.__name__}> Runs at {self.runs_at}'


# Made so only ids can be used
class Snowflake(abc.Snowflake):
    def __init__(self, id):
        self.id = id

    @property
    def created_at(self):
        return disnake.utils.snowflake_time(self.id)


def utcnow():
    """Datetime aware utc time"""
    return datetime.now(timezone.utc)


def split_string(to_split, list_join='', maxlen=2000, splitter=' ',
                 max_word: int = None):
    """

    Args:
        to_split: str, dict or iterable to be split
        list_join: the character that's used in joins
        maxlen: maximum line length
        splitter: what character are the lines split by
        max_word: if set will split words longer than this that go over the max
            line length. Currently only supported in str mode


    Returns:
        list of strings or list of dicts
    """
    if isinstance(to_split, str):
        if len(to_split) < maxlen:
            return [to_split]

        to_split = [s + splitter for s in to_split.split(splitter)]
        to_split[-1] = to_split[-1][:-len(splitter)]
        length = 0
        split = ''
        splits = []
        for s in to_split:
            l = len(s)
            if length + l > maxlen:
                if max_word and l > max_word:
                    delta = maxlen - length
                    if delta > 3:
                        split += s[:delta]
                        splits.append(split)
                        s = s[delta:]

                    l = len(s)

                    while l > maxlen:
                        splits.append(s[:maxlen])
                        s = s[maxlen:]
                        l = len(s)

                    split = s
                    length = l

                else:
                    splits.append(split)
                    split = s
                    length = l
            else:
                split += s
                length += l

        splits.append(split)

        return splits

    elif isinstance(to_split, dict):
        splits_dict = OrderedDict()
        splits = []
        length = 0
        for key in to_split:
            joined = list_join.join(to_split[key])
            if length + len(joined) > maxlen:
                splits += [splits_dict]
                splits_dict = OrderedDict()
                splits_dict[key] = joined
                length = len(joined)
            else:
                splits_dict[key] = joined
                length += len(joined)

        if length > 0:
            splits += [splits_dict]

        return splits

    elif isinstance(to_split, Iterable):
        splits = []
        chunk = ''
        for s in to_split:
            if len(chunk) + len(s) + len(list_join) <= maxlen:
                chunk += list_join + s
            elif chunk:
                splits.append(chunk)
                if len(s) > maxlen:
                    s = s[:maxlen - 3] + '...'
                    splits.append(s)
                else:
                    chunk = s
            elif not chunk:
                splits.append(s[:maxlen - 3] + '...')

        if chunk:
            splits.append(chunk)

        return splits

    logger.debug('Could not split string {}'.format(to_split))
    raise NotImplementedError('This only works with dicts, iterables and strings for now')


async def mean_volume(file, loop, threadpool, avconv=False, duration=0):
    """Gets the mean volume from"""
    audio.debug('Getting mean volume')
    ffmpeg = 'ffmpeg' if not avconv else 'avconv'
    file = '"{}"'.format(file)

    if not duration:
        start = 0
    else:
        start = int(duration * 0.2)

    analyze_duration = 50
    cmd = '{0} -ss {2} -i {1} -ss 0 -t {3} -filter:a "volumedetect" -vn -sn -f null /dev/null'.format(
        ffmpeg, file, start, analyze_duration)
    audio.debug(cmd)
    args = shlex.split(cmd)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = await loop.run_in_executor(threadpool, process.communicate)
    out += err

    matches = re.findall(r'mean_volume: [\-\d.]+ dB', str(out))

    if not matches:
        return
    try:
        volume = float(matches[0].split(' ')[1])
        audio.debug('Parsed volume is {}'.format(volume))
        return volume
    except ValueError:
        return


# Write the contents of an iterable or string to a file
def write_playlist(file, contents, mode='w'):
    if not isinstance(contents, str):
        contents = '\n'.join(contents) + '\n'
        if contents == '\n':
            return

    with open(file, mode, encoding='utf-8') as f:
        f.write(contents)


# Read lines from a file and put them to a list without newlines
def read_lines(file):
    if not os.path.exists(file):
        return []

    with open(file, 'r', encoding='utf-8') as f:
        songs = f.read().splitlines()

    return songs


# Empty the contents of a file
def empty_file(file):
    with open(file, 'w', encoding='utf-8'):
        pass


def get_config_value(config, section, option, option_type=None, fallback=None):
    try:
        if option_type is None:
            return config.get(section, option, fallback=fallback)

        if issubclass(option_type, bool):
            return config.getboolean(section, option, fallback=fallback)

        elif issubclass(option_type, str):
            return str(config.get(section, option, fallback=fallback))

        elif issubclass(option_type, int):
            return config.getint(section, option, fallback=fallback)

        elif issubclass(option_type, float):
            return config.getfloat(section, option, fallback=fallback)

        else:
            return config.get(section, option, fallback=fallback)

    except ValueError as e:
        logger.error('{0}\n{1} value is not {2}. {1} set to {3}'.format(e, option, str(option_type), str(fallback)))
        return fallback


def y_n_check(msg):
    msg = msg.content.lower().strip()
    return msg in ['y', 'yes', 'n', 'no']


def y_check(s):
    s = s.lower().strip()
    return is_true(s)


def bool_check(s):
    msg = s.lower().strip()
    return is_true(msg) or is_false(msg)


def is_true(s):
    return s in ['y', 'yes', 'true']


def is_false(s):
    return s in ['n', 'false', 'no', 'stop']


def check_negative(n):
    if n < 0:
        return -1
    else:
        return 1


def get_emote_url(emote):
    match = re.findall(r'(https://cdn.discordapp.com/emojis/\d+.(?:gif|png))(?:\?v=1)?', emote)
    if match:
        return match[0]

    animated, emote_id = get_emote_id(emote)
    if emote_id is None:
        return

    extension = 'png' if not animated else 'gif'
    return 'https://cdn.discordapp.com/emojis/{}.{}'.format(emote_id, extension)


def get_picture_from_msg(msg):
    if msg is None:
        return

    if len(msg.attachments) > 0:
        return msg.attachments[0].url

    words = msg.content.split(' ')
    for word in words:
        if test_url(word):
            return word


def normalize_text(s):
    # Get cleaned emotes
    matches = re.findall(r'<:\w+:\d+>', s)

    for match in matches:
        s = s.replace(match, match.split(':')[1])

    # matches = re.findall('<@\d+>')
    return s


def slots2dict(obj, d: dict = None, replace=True):
    # Turn slots and @properties to a dict

    if d is None:
        d = {k: getattr(obj, k, None) for k in obj.__slots__
             if not k.startswith('_')}
    else:
        for k in obj.__slots__:
            if k.startswith('_'):
                continue

            if not replace and k in d:
                continue

            d[k] = getattr(obj, k, None)

    for k in dir(obj):
        # get_relationship prints deprecation warnings. Not the best solution but whatever
        if k == 'get_relationship' or k.startswith('_'):  # We don't want any private variables
            continue

        v = getattr(obj, k, None)
        if not callable(v):  # Don't need methods here
            if not replace and k in d:
                continue

            d[k] = v

    return d


async def retry(f, *args, retries_=3, break_on=(), **kwargs):
    e = None
    for _ in range(0, retries_):
        try:
            retval = await f(*args, **kwargs)
        except break_on as e_:
            e = e_
            break

        except Exception as e_:
            e = e_
        else:
            return retval

    return e


def get_emote_id(s):
    emote = re.match(r'<(a)?:\w+:(\d+)(?=>)', s)
    if emote:
        return emote.groups()

    return None, None


def get_emote_name_id(s):
    """
    Returns:
        (animated, name, id)
    """
    emote = re.match(r'<(a)?:(\w+):(\d+)(?=>)', s)
    if emote:
        return emote.groups()

    return None, None, None


async def get_images(ctx: 'Context', content, current_message_only=False,
                     leave_empty=False):
    """
    Get all images from a message
    Args:
        ctx: Context
        content: message content to check for images
        current_message_only: Does not try to fetch a given message id
        leave_empty (bool): If set to true will return an empty list when no images were found
    """
    images = []
    msg_id = None

    def add_link(url):
        if not url or url in images:
            return

        images.append(url)

    def add_activities(member):
        if not isinstance(member, disnake.Member):
            return

        for activity in member.activities:
            if isinstance(activity, disnake.CustomActivity) and activity.emoji:
                add_link(str(activity.emoji.url))

    message = ctx.message

    # Check if message id given and fetch that message if that is the case
    if not current_message_only:
        try:
            msg_id = int(content)
        except (ValueError, TypeError):
            pass

        if msg_id:
            try:
                message = await ctx.channel.fetch_message(msg_id)
            except disnake.HTTPException:
                pass

    # Images from attachments
    for attachment in message.attachments:
        if not isinstance(attachment.width, int):
            continue

        add_link(attachment.url)

    for sticker in message.stickers:
        add_link(sticker.url)

    # Images from message contents
    content = message.content or ''
    for word in content.split(' '):
        # Image url
        if is_image_url(word):
            add_link(word)
            continue

        # emote url
        emote = get_emote_url(word)
        if emote:
            add_link(emote)
            continue

        # Check ids after ths
        try:
            snowflake = int(word)
        except ValueError:
            continue

        # Check if guild id given
        if snowflake == ctx.guild.id:
            add_link(str(ctx.guild.icon.url))
            add_link(str(ctx.guild.banner.url))
            add_link(str(ctx.guild.splash.url))
            continue

        # Check for user id
        user = ctx.guild.get_member(snowflake) or ctx.bot.get_user(snowflake)
        if user:
            add_link(get_avatar(user))
            add_activities(user)
            continue

    # Mentioned user avatars
    for user in message.mentions:
        add_link(get_avatar(user))
        add_activities(user)

    # Embed images
    for embed in message.embeds:
        embed_type = embed.type
        attachments = ()

        if embed_type == 'video':
            attachments = (embed.thumbnail.url,)
        elif embed_type == 'rich':
            attachments = (embed.image.url, embed.thumbnail.url)
        elif embed_type == 'image':
            attachments = (embed.url, embed.thumbnail.url)

        for attachment in attachments:
            if attachment is not None and is_image_url(attachment):
                add_link(attachment)

    if not images:
        add_link(await get_image_from_ctx(ctx, content))

    if not images and not leave_empty:
        images.append('No images found')

    return images


async def get_image(ctx, image, current_message_only=False, get_raw=False):
    img = await get_image_from_ctx(ctx, image, current_message_only)
    if img is None:
        if image is not None:
            await ctx.send(f'No image found from {image}')
        else:
            await ctx.send(
                'Please input a mention, emote or an image when using the command')

        return

    img = await dl_image(ctx, img, get_raw=get_raw)
    return img


async def dl_image(ctx, url, get_raw=False):
    try:
        img = await image_from_url(url, get_raw=get_raw)
    except OverflowError:
        await ctx.send('Failed to download. File is too big')
    except TypeError:
        await ctx.send('Link is not a direct link to an image')
    except OSError:
        logger.exception('Failed to dl image because of an unknown error')
        await ctx.send(
            'Failed to use image because of an unknown error. The image file is probably a bit broken')
    else:
        return img


def get_image_from_embeds(embeds: list[disnake.Embed]):
    for embed in embeds:
        embed_type = embed.type
        if embed_type == 'video':
            attachment = embed.thumbnail.url
            if attachment:
                return attachment
            else:
                continue

        elif embed_type == 'rich':
            attachment = embed.image.url
        elif embed_type == 'image':
            attachment = embed.url
            if not is_image_url(attachment):
                attachment = embed.thumbnail.url
        else:
            continue

        return attachment


def get_image_from_message(bot, message: disnake.Message, content=None):
    """
    Get image from disnake.Message
    """
    image = None
    if len(message.attachments) > 0 and isinstance(message.attachments[0].width, int):
        image = message.attachments[0].url
    elif message.stickers:
        image = message.stickers[0].url
    elif content or message.content:
        image = content or message.content.split(' ')[0]
        if not test_url(image):
            if re.match(r'<@!?\d+>', image) and message.mentions:
                image = get_avatar(message.mentions[0])
            elif get_emote_id(image)[1]:
                image = get_emote_url(image)
            else:
                try:
                    image = int(image)
                except ValueError:
                    image = None
                else:
                    user = bot.get_user(image)
                    if user:
                        image = get_avatar(user)

    if not image:
        image = get_image_from_embeds(message.embeds)

    return image


async def get_image_from_ctx(ctx, message, current_message_only=False):
    image = get_image_from_message(ctx.bot, ctx.message, content=message)
    redis: Redis = ctx.bot.redis
    if image is None or not isinstance(image, str) and not current_message_only:
        if isinstance(image, int):
            try:
                msg = await ctx.channel.fetch_message(image)
                return get_image_from_message(ctx.bot, msg)
            except disnake.HTTPException:
                pass
        elif redis:
            redis_key = f'{RedisKeyNamespaces.Attachment.value}:{ctx.channel.id}'
            try:
                row = await redis.get(redis_key)
                if row:
                    image = row.decode('utf-8')
            except PostgresError:
                pass

    if image is not None:
        if not isinstance(image, str):
            return None

        image = None if not test_url(image) else image
    return image


def random_color():
    """
    Create a random color to be used in discord
    Returns:
        disnake.Color
    """

    return disnake.Color(randint(0, 16777215))


# https://stackoverflow.com/a/4628148/6046713
def parse_time(time_str):
    parts = time_regex.match(time_str)
    if not parts:
        return

    parts = parts.groupdict()
    time_params = {name: int(param) for name, param in parts.items() if param}

    return timedelta(**time_params)


def parse_timeout(time_str):
    parts = timeout_regex.match(time_str)
    if not parts:
        return

    parts = parts.groupdict()
    reason = parts.pop('reason')
    time_params = {name: int(param) for name, param in parts.items() if param}

    return timedelta(**time_params), reason


def timedelta2sql(td: timedelta):
    return f'{td.days} {td.seconds // 3600}:{(td.seconds // 60) % 60}:{td.seconds % 60}'


def sql2timedelta(value):
    return timedelta(**{k: int(v) if v else 0 for k, v
                        in timedelta_regex.match(value).groupdict().items()})


def call_later(func, loop, timeout: float, *args, after=None, **kwargs):
    """
    Call later for async functions
    Args:
        func: async function
        loop: asyncio loop
        timeout: how long to wait
        after: Func to pass to future.add_done_callback

    Returns:
        CallLater
    """
    async def wait():
        if timeout > 0:
            try:
                await asyncio.sleep(timeout)
            except asyncio.CancelledError:
                return

        try:
            await func(*args, **kwargs)
        except:
            logger.exception('Failed to call_later')
            raise

    fut = asyncio.run_coroutine_threadsafe(wait(), loop)
    if callable(after):
        fut.add_done_callback(after)

    return CallLater(fut, utcnow() + timedelta(seconds=timeout))


def get_channel(channels, s, name_matching=False, only_text=True):
    channel = get_channel_id(s)
    if channel:
        channel = disnake.utils.find(lambda c: c.id == s, channels)
        if channel:
            return channel

    try:
        s = int(s)
    except ValueError:
        pass
    else:
        channel = disnake.utils.find(lambda c: c.id == s, channels)

    if not channel and name_matching:
        s = str(s)
        channel = disnake.utils.find(lambda c: c.name == s, channels)
        if not channel:
            return
    else:
        return

    if only_text and not isinstance(channel, disnake.TextChannel):
        return

    return channel


def get_role(role, roles, name_matching=False):
    try:
        role_id = int(role)
    except ValueError:
        role_id = get_role_id(role)

        if role_id is None and name_matching:
            for role_ in roles:
                if role_.name == role:
                    return role_
        elif role_id is None:
            return

    return disnake.utils.find(lambda r: r.id == role_id, roles)


def get_avatar(user: disnake.User):
    return user.display_avatar.url


def get_role_id(s):
    regex = re.compile(r'(?:<@&)?(\d+)>?(?: |$)')
    match = regex.match(s)
    if match:
        return int(match.groups()[0])


def get_channel_id(s):
    regex = re.compile(r'(?:<#)?(\d+)>?')
    match = regex.match(s)
    if match:
        return int(match.groups()[0])


def check_plural(string, i):
    if i != 1:
        return '%s %ss ' % (str(i), string)
    return '%s %s ' % (str(i), string)


def native_format_timedelta(td: timedelta) -> str:
    return disnake.utils.format_dt(utcnow() + td, style='R')


def format_timedelta(td, accuracy=3, include_weeks=False, long_format=True):
    """
    Formats timedelta object or int to string with support for longer durations
    Args:
        td (timedelta or int):
            timedelta object to be formatted or seconds as integer

        accuracy (int or DateAccuracy or slice):
            The accuracy of the function. If set to 1 will give
            most inaccurate result rounded down. If 7 will give out result
            with precision to seconds. So the bigger the number, the more
            verbose the result.
            1-years
            2-months
            (3-weeks if weeks set on all numbers below grow by one)
            3-days
            4-hours
            5-minutes
            6-seconds

            e.g. a timedelta of 13 days would give a result looking something like
            this with an accuracy of 2 and weeks on
            1 week 6 days

            If set to slice will get the specified range. Doesn't support weeks
            e.g. slice(2,3) would give x months y days or get the next largest result
            when accuracy doesnt reach days

            If set to DateAccuracy will only provide accuracy in that format

        include_weeks (bool):
            Whether to include weeks or just count them as days

        long_format (bool):
            Whether to use long names or shortened names for time definitions

    Returns:
        str: formatted time

    """
    if isinstance(td, (int, float)):
        sec = int(td)
    else:
        sec = int(td.total_seconds())

    if sec == 0:
        return '0 seconds' if long_format else '0s'

    if long_format:
        names = ['year', 'month', 'week', 'day', 'hour', 'minute', 'second']
    else:
        names = ['yr', 'mo', 'wk', 'd', 'h', 'min', 's']

    if accuracy == DateAccuracy.Week:
        include_weeks = True

    elif isinstance(accuracy, DateAccuracy) and accuracy != DateAccuracy.Week:
        # Having weeks one for nothing lowers accuracy
        include_weeks = False

    if not include_weeks:
        divs = [60, 60, 24, 30, 12]
        names.pop(2)
    else:
        divs = [60, 60, 24, 7, 30, 12]

    last = sec
    times = []
    is_slice = isinstance(accuracy, slice)
    if is_slice and include_weeks:
        raise NotImplementedError('Weeks dont work with slices')

    if isinstance(accuracy, int):
        for d in divs:
            last, val = divmod(last, d)
            times.insert(0, val)

        # append left
        times.insert(0, last)

        for i, t, in enumerate(times):
            if t == 0:
                continue

            times = times[i:i + accuracy]
            names = names[i:i + accuracy]
            break

    elif isinstance(accuracy, DateAccuracy) or is_slice:
        idx = 0
        if is_slice:
            old_acc = accuracy
            accuracy = DateAccuracy(cast(slice, accuracy).stop)

        # Week is an exception and we want to keep it out of calculations
        # unless it is the requested accuracy. We use day here since we count
        # weeks using days in the end
        if include_weeks:
            accuracy = DateAccuracy.Day

        for d in divs:
            last, val = divmod(last, d)
            times.append(val)

            if len(times) - 1 >= accuracy.value:
                last = last * d + val
                times[-1] = last
                break

            if last == 0:
                break

            idx += 1

        # Exception. We want to exclude weeks when possible to increase accuracy
        # of years and months. When using DateAccuracy include_weeks will be
        # True only when week is the requested format
        if include_weeks and len(times) - 1 >= accuracy.value:
            val = last // 7
            if val == 0:
                names.pop(2)  # Index of week
                val = last
            else:
                names.pop(3)  # Index of day

        else:
            val = last

        # Fallback to the closest non-zero value
        if val == 0:
            val = times[-1]

        if is_slice:
            old_acc = cast(slice, old_acc)
            # Slices are given in the format of from int to int inclusive
            # when slices from exclusive at the end, so we have to recreate the slice
            old_acc = slice(old_acc.start, old_acc.stop + 1)
            # Extend times so every accuracy has a unit attached to it
            # This allows us to slice the list like normal
            times.extend([0] * (len(names) - len(times)))
            # times = list(reversed(times))[old_acc]
            times = times[old_acc]
            names = list(reversed(names))

            # When all times in the slice are 0 fall back to the last value found
            if max(times) == 0:
                times = [val]
                names = [names[idx]]
            else:
                names = names[old_acc]
                # We need to reverse them or the order will be
                # from seconds onwards
                names = list(reversed(names))
                times = list(reversed(times))
        else:
            names = [names[len(names) - 1 - idx]]
            times = [val]

    else:
        raise TypeError('Accuracy must be of instance int or DateAccuracy')

    s = ''
    for i, t in enumerate(times):
        if t == 0:
            continue

        if long_format:
            s += check_plural(names[i], t)
        else:
            s += f'{t}{names[i]} '

    return s.strip()


def seconds2str(seconds, long_def=True):
    seconds_ = int(round(seconds, 0))
    if not seconds_:
        return f'{round(seconds, 2)}s'

    seconds = seconds_
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    if long_def:
        d = check_plural('day', d) if d else ''
        h = check_plural('hour', h) if h else ''
        m = check_plural('minute', m) if m else ''
        s = check_plural('second', s) if s else ''
    else:
        d = str(d) + 'd ' if d else ''
        h = str(h) + 'h ' if h else ''
        m = str(m) + 'm ' if m else ''
        s = str(s) + 's' if s else ''

    return (d + h + m + s).strip()


def is_image_url(url):
    if url is None:
        return

    if not test_url(url):
        return False

    mimetype, _ = mimetypes.guess_type(url)
    is_image = mimetype and mimetype.startswith('image')
    if not is_image:
        # This is needed because some images like from twitter
        # are usually in the format of someimage.jpg:large or someimage.jpg?size=1
        # and mimetypes doesn't recognize that
        url = re.sub(r'(:\w+|\?\w+=\w+)$', '', url)

        mimetype, _ = mimetypes.guess_type(url)
        is_image = mimetype and mimetype.startswith('image')

    return is_image


def format_message(d):
    for k in FORMAT_BLACKLIST:
        d.pop(k, None)

    for k in d:
        v = d[k]
        if isinstance(v, str):
            continue

        if isinstance(v, disnake.MessageType):
            d[k] = str(v.name)

        else:
            d[k] = str(v)

    return d


def format_on_edit(before, after, message, check_equal=True):
    bef_content = before.content
    aft_content = after.content
    if check_equal:
        if bef_content == aft_content:
            return

    user = before.author

    d = format_member(user)
    d['user_id'] = d['id']
    d = slots2dict(after, d)
    d['channel_id'] = d.pop('id', None)
    d = format_message(d)
    for e in ['name', 'before', 'after']:
        d.pop(e, None)

    d['channel'] = after.channel.mention
    message = message.format(name=str(user), **d,
                             before=bef_content, after=aft_content)

    return message


def test_message(msg, is_edit=False):
    d = format_member(msg.author)
    d = slots2dict(msg, d)
    d = format_message(d)
    removed = ['name', 'before', 'after'] if is_edit else ['name', 'message']
    for e in removed:
        d.pop(e, None)

    d['channel'] = msg.channel.mention
    d['name'] = str(msg.author)
    d['system_content'] = d['system_content'][:10]
    d['clean_content'] = d['clean_content'][:10]
    if is_edit:
        d['before'] = msg.content[:10]
        d['after'] = msg.content[:10]
    else:
        d['message'] = msg.content[:10]

    s = ''
    for k, v in d.items():
        s += '{%s}: %s\n' % (k, v)

    return remove_everyone(s)


def remove_everyone(s):
    return re.sub(r'@(everyone|here)', '@\u200b\\1', s)


def format_activity(activity):
    # Maybe put more advanced formatting here in future
    return activity.name


def format_member(member):
    d = slots2dict(member)
    d['user'] = str(member)
    d.pop('roles', None)
    d.pop('voice', None)
    d.pop('dm_channel', None)
    d.pop('mutual_guilds', None)
    d.pop('activity', None)
    d.pop('pending', None)
    d.pop('desktop_status', None)
    d.pop('mobile_status', None)
    d.pop('web_status', None)
    d.pop('activities', None)

    for k in d:
        v = d[k]
        if isinstance(v, disnake.Activity):
            d[k] = format_activity(v)

        elif isinstance(v, disnake.Permissions):
            d[k] = str(v.value)

        else:
            d[k] = str(v)

    return d


def format_join_leave(member, message):
    d = format_member(member)
    message = message.format(**d)
    return message


def test_member(member):
    d = format_member(member)
    s = ''
    for k, v in d.items():
        s += '{%s}: %s\n' % (k, v)

    return s


def format_on_delete(msg, message):
    content = msg.content
    user = msg.author

    d = format_member(user)
    d['user_id'] = d['id']
    d = slots2dict(msg, d)
    d['channel_id'] = d.pop('id', None)
    d = format_message(d)
    for e in ['name', 'message']:
        d.pop(e, None)

    d['channel'] = msg.channel.mention
    message = message.format(name=str(user), message=content, **d)
    return message


# https://stackoverflow.com/a/14178717/6046713
def find_coeffs(pa, pb):
    """
    Args:
        pa: Coordinates of the created image edges rotating clockwise from
            the top left corner
        pb: Size of the image being transformed
    """
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])

    A = numpy.matrix(matrix, dtype=float)
    B = numpy.array(pb).reshape(8)

    res = numpy.dot(numpy.linalg.inv(A.T * A) * A.T, B)
    return numpy.array(res).reshape(8)


def check_perms(values, return_raw=False):
    # checks if the command can be used based on what rows are given
    # ONLY GIVE this function rows of one command or it won't work as intended
    smallest = 18
    for value in values:
        if value['type'] == BlacklistTypes.WHITELIST:
            v1 = PermValues.VALUES['whitelist']
        else:
            v1 = PermValues.VALUES['blacklist']

        if value['uid'] is not None:
            v2 = PermValues.VALUES['user']
        elif value['role'] is not None:
            v2 = PermValues.VALUES['role']
        elif value['channel'] is not None:
            v2 = PermValues.VALUES['channel']
        else:
            v2 = PermValues.VALUES['guild']

        v = v1 | v2
        if v < smallest:
            smallest = v

    return PermValues.RETURNS.get(smallest, False) if not return_raw else smallest


def is_owner(ctx):
    if ctx.bot.owner_id != ctx.original_user.id:
        raise NotOwner

    ctx.skip_check = True

    return True


async def check_blacklist(ctx: Union[ApplicationCommandInteraction, 'Context']):
    if getattr(ctx, 'skip_check', False):
        return True

    bot: 'BotBase' = cast('BotBase', ctx.bot)
    if not hasattr(bot, 'check_auth'):
        # No database blacklisting detected
        return True

    if not await bot.check_auth(ctx):
        return False

    command = ctx.application_command if isinstance(ctx, ApplicationCommandInteraction) else ctx.command

    overwrite_perms = await bot.dbutil.check_blacklist(
        "(command='%s' OR command IS NULL)" % command.name, ctx.author, ctx,
        True)
    msg, full_msg = PermValues.BLACKLIST_MESSAGES.get(overwrite_perms,
                                                      (None, None))
    if isinstance(overwrite_perms, int):
        if ctx.guild and ctx.guild.owner_id == ctx.author.id:
            overwrite_perms = True
        else:
            overwrite_perms = PermValues.RETURNS.get(overwrite_perms, False)

    setattr(ctx, 'override_perms', overwrite_perms)

    if overwrite_perms is False:
        if msg is not None or full_msg is not None:
            raise CommandBlacklisted(msg, full_msg)
        return False

    return True


def basic_check(author=None, channel=None):
    def check(msg):
        if author and author.id != msg.author.id:
            return False

        if channel and channel.id != msg.channel.id:
            return False

        return True

    return check


def parse_seek(s):
    match = seek_regex.match(s)
    if not match:
        return

    return {k: v or '0' for k, v in match.groupdict().items()}


def seek_to_sec(seek_dict):
    return int(seek_dict['h']) * 3600 + int(seek_dict['m']) * 60 + int(seek_dict['s'])


def check_import(module_name):
    """
    This function is responsible for checking for errors in python code
    It does not check imports

    Returns:
        Empty string if nothing was found. Otherwise the error
    """
    module_name = module_name.split('.')
    module_name[-1] = module_name[-1] + '.py'
    module_name = os.path.join(os.getcwd(), *module_name)
    py_compile.compile(module_name, doraise=True)


def check_botperm(*perms, ctx=None, channel=None, guild=None, me=None,
                  raise_error=None):
    if not perms:
        return True

    if not me:
        if not guild and ctx:
            guild = ctx.guild

        me = guild.me if guild is not None else ctx.bot.user

    channel = channel if channel else ctx.channel
    permissions = channel.permissions_for(me)

    missing = [perm for perm in perms if
               getattr(permissions, perm) is False]

    if not missing:
        return True

    if raise_error:
        raise raise_error(missing)

    return False


async def wait_for_yes(ctx, timeout=60):
    _check = basic_check(ctx.author, ctx.channel)

    def check(msg):
        return _check(msg) and bool_check(msg.content)

    try:
        msg = await ctx.bot.wait_for('message', check=check, timeout=timeout)
    except asyncio.TimeoutError:
        await ctx.send('Took too long')
        return

    if not y_check(msg.content):
        await ctx.send('Cancelling')
        return

    return msg


async def wait_for_words(ctx, words, timeout=60):
    _check = basic_check(ctx.author, ctx.channel)

    def check(msg):
        return _check(msg) and msg.content.strip('\n ').lower() in words

    try:
        msg = await ctx.bot.wait_for('message', check=check, timeout=timeout)
    except asyncio.TimeoutError:
        await ctx.send('Took too long')
        return

    return msg


def seek_from_timestamp(timestamp) -> dict:
    m, s = divmod(timestamp, 60)
    h, m = divmod(m, 60)
    s, ms = divmod(s, 1)

    h, m, s = str(int(h)), str(int(m)), str(int(s))
    ms = str(round(ms, 3))[2:]

    return {
        'h': h,
        'm': m,
        's': s,
        'ms': ms
    }


async def wants_to_be_noticed(member, guild, remove=True):
    role = guild.get_role(318762162552045568)
    if not role:
        return

    name = member.name if not member.nick else member.nick
    if ord(name[0]) <= 46:
        if role in member.roles:
            return

        await retry(member.add_roles, role, break_on=disnake.Forbidden,
                    reason="Wants attention")
        return True

    elif remove and role in member.roles:
        await retry(member.remove_roles, role, break_on=disnake.Forbidden,
                    reason="Doesn't want attention")
        return False


def get_filename_from_url(url):
    return os.path.basename(urlparse(url).path)

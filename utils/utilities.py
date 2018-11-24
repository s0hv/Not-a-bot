"""
MIT License

Copyright (c) 2017 s0hvaperuna

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
import re
import shlex
import subprocess
import sys
import time
from collections import OrderedDict, Iterable
from datetime import timedelta, datetime
from random import randint

import discord
import numpy
from discord import abc
from discord.ext.commands.errors import MissingPermissions
from sqlalchemy.exc import SQLAlchemyError
from validators import url as test_url

from bot.exceptions import NoCachedFileException, CommandBlacklisted, NotOwner
from bot.globals import BlacklistTypes, PermValues
from bot.paged_message import PagedMessage

# Support for recognizing webp images used in many discord avatars
mimetypes.add_type('image/webp', '.webp')
logger = logging.getLogger('debug')
audio = logging.getLogger('audio')
terminal = logging.getLogger('terminal')

# https://stackoverflow.com/a/4628148/6046713
# Added days and and aliases for names
# Also fixed any string starting with the first option (e.g. 10dd would count as 10 days) being accepted
time_regex = re.compile(r'((?P<days>\d+?) ?(d|days)( |$))?((?P<hours>\d+?) ?(h|hours)( |$))?((?P<minutes>\d+?) ?(m|min|minutes)( |$))?((?P<seconds>\d+?) ?(s|sec|seconds)( |$))?')
timeout_regex = re.compile(r'((?P<days>\d+?) ?(d|days)( |$))?((?P<hours>\d+?) ?(h|hours)( |$))?((?P<minutes>\d+?) ?(m|min|minutes)( |$))?((?P<seconds>\d+?) ?(s|sec|seconds)( |$))?(?P<reason>.*)+?',
                           re.DOTALL)
timedelta_regex = re.compile(r'((?P<days>\d+?) )?(?P<hours>\d+?):(?P<minutes>\d+?):(?P<seconds>\d+?)')
seek_regex = re.compile(r'((?P<h>\d+)*(?:h ?))?((?P<m>\d+)*(?:m[^s]? ?))?((?P<s>\d+)*(?:s ?))?((?P<ms>\d+)*(?:ms ?))?')
FORMAT_BLACKLIST = ['mentions', 'channel_mentions', 'reactions', 'call',
                    'embeds', 'attachments', 'role_mentions', 'application',
                    'raw_channel_mentions', 'raw_role_mentions', 'raw_mentions']


class Object:
    # Empty class to store variables
    def __init__(self):
        pass


class CallLater:
    def __init__(self, future, runs_at):
        self._future = future
        self.runs_at = runs_at

    @property
    def future(self):
        return self._future

    def cancel(self):
        self.future.cancel()


# Made so only ids can be used
class Snowflake(abc.Snowflake):
    def __init__(self, id):
        self.id = id

    @property
    def created_at(self):
        return discord.utils.snowflake_time(self.id)


def split_string(to_split, list_join='', maxlen=2000, splitter=' ', max_word: int=None):
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
            if len(chunk) + len(s) <= maxlen:
                chunk += list_join + s
            elif chunk:
                splits.append(chunk)
                if len(s) > maxlen:
                    s = s[:maxlen-3] + '...'

                splits.append(s)
                chunk = ''
            elif not chunk:
                splits.append(s[:maxlen-3] + '...')

        if chunk:
            splits.append(chunk)

        return splits

    logger.debug('Could not split string {}'.format(to_split))
    raise NotImplementedError('This only works with dicts and strings for now')


async def mean_volume(file, loop, threadpool, avconv=False, duration=0):
    """Gets the mean volume from"""
    audio.debug('Getting mean volume')
    ffmpeg = 'ffmpeg' if not avconv else 'avconv'
    file = '"{}"'.format(file)

    if not duration:
        start, stop = 0, 180
    else:
        start = int(duration * 0.2)
        stop = start + 180
    cmd = '{0} -i {1} -ss {2} -t {3} -filter:a "volumedetect" -vn -sn -f null /dev/null'.format(ffmpeg, file, start, stop)
    audio.debug(cmd)
    args = shlex.split(cmd)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = await loop.run_in_executor(threadpool, process.communicate)
    out += err

    matches = re.findall('mean_volume: [\-\d.]+ dB', str(out))

    if not matches:
        return
    try:
        volume = float(matches[0].split(' ')[1])
        audio.debug('Parsed volume is {}'.format(volume))
        return volume
    except ValueError:
        return


def get_cached_song(name):
    if os.path.isfile(name):
        return name
    else:
        raise NoCachedFileException


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


def timestamp():
    return time.strftime('%d-%m-%Y--%H-%M-%S')


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
        terminal.error('{0}\n{1} value is not {2}. {1} set to {3}'.format(e, option, str(option_type), str(fallback)))
        return fallback


def write_wav(stdout, filename):
    with open(filename, 'wb') as f:
        f.write(stdout.read(36))

        # ffmpeg puts metadata that breaks bpm detection. We are going to remove that
        stdout.read(34)

        while True:
            data = stdout.read(100000)
            if len(data) == 0:
                break
            f.write(data)

    return filename


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
    return s in ['y', 'yes', 'true', 'on']


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


def emote_url_from_id(id):
    return 'https://cdn.discordapp.com/emojis/%s.png' % id


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
    matches = re.findall('<:\w+:\d+>', s)

    for match in matches:
        s = s.replace(match, match.split(':')[1])

    # matches = re.findall('<@\d+>')
    return s


def slots2dict(obj, d: dict=None, replace=True):
    # Turns slots and @properties to a dict

    if d is None:
        d = {k: getattr(obj, k, None) for k in obj.__slots__ if not k.startswith('_')}
    else:
        for k in obj.__slots__:
            if k.startswith('_'):
                continue

            if not replace and k in d:
                continue

            d[k] = getattr(obj, k, None)

    for k in dir(obj):
        if k.startswith('_'):  # We don't want any private variables
            continue

        v = getattr(obj, k, None)
        if not callable(v):    # Don't need methods here
            if not replace and k in d:
                continue

            d[k] = v

    return d


async def retry(f, *args, retries_=3, break_on=(), **kwargs):
    e = None
    for i in range(0, retries_):
        try:
            retval = await f(*args, **kwargs)
        except break_on as e:
            break

        except Exception as e_:
            e = e_
        else:
            return retval

    return e


def get_emote_id(s):
    emote = re.match('(?:<(a)?:\w+:)(\d+)(?=>)', s)
    if emote:
        return emote.groups()

    return None, None


def get_emote_name(s):
    emote = re.match('(?:<(a)?:)(\w+)(?::\d+)(?=>)', s)
    if emote:
        return emote.groups()

    return None, None


def get_emote_name_id(s):
    emote = re.match('(?:<(a)?:)(\w+)(?::)(\d+)(?=>)', s)
    if emote:
        return emote.groups()

    return None, None, None


async def get_image_from_message(ctx, *messages):
    image = None
    if len(ctx.message.attachments) > 0 and isinstance(ctx.message.attachments[0].width, int):
        image = ctx.message.attachments[0].url
    elif messages and messages[0] is not None:
        image = str(messages[0])
        if not test_url(image):
            if re.match('<@!?\d+>', image) and ctx.message.mentions:
                image = get_avatar(ctx.message.mentions[0])
            elif get_emote_id(image)[1]:
                image = get_emote_url(image)
            else:
                try:
                    image = int(image)
                except ValueError:
                    pass
                else:
                    user = discord.utils.find(lambda u: u.id == image, ctx.bot.get_all_members())
                    if user:
                        image = get_avatar(user)

    dbutil = ctx.bot.dbutil
    if image is None or not isinstance(image, str):
        if isinstance(image, int):
            sql = 'SELECT attachment FROM `messages` WHERE message_id=%s' % image
        else:
            channel = ctx.channel
            guild = channel.guild
            sql = 'SELECT attachment FROM `messages` WHERE guild={} AND channel={} ORDER BY `message_id` DESC LIMIT 25'.format(guild.id, channel.id)
        try:
            rows = (await dbutil.execute(sql)).fetchall()
            for row in rows:
                attachment = row['attachment']
                if not attachment:
                    continue

                if is_image_url(attachment):
                    image = attachment
                    break

                # This is needed because some images like from twitter
                # are usually in the format of someimage.jpg:large
                # and mimetypes doesn't recognize that
                elif is_image_url(':'.join(attachment.split(':')[:-1])):
                    image = attachment
                    break

        except SQLAlchemyError:
            pass

    if image is not None:
        image = None if not test_url(image) else image
    return image


def random_color():
    """
    Create a random color to be used in discord
    Returns:
        discord.Color
    """

    return discord.Color(randint(0, 16777215))


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


def datetime2sql(datetime):
    return '{0.year}-{0.month}-{0.day} {0.hour}:{0.minute}:{0.second}'.format(datetime)


def timedelta2sql(timedelta):
    return f'{timedelta.days} {timedelta.seconds//3600}:{(timedelta.seconds//60)%60}:{timedelta.seconds%60}'


def sql2timedelta(value):
    return timedelta(**{k: int(v) if v else 0 for k, v in timedelta_regex.match(value).groupdict().items()})


def call_later(func, loop, timeout, *args, after=None, **kwargs):
    """
    Call later for async functions
    Args:
        func: async function
        loop: asyncio loop
        timeout: how long to wait
        after: Func to pass to future.add_done_callback

    Returns:
        asyncio.Task
    """
    async def wait():
        if timeout > 0:
            try:
                await asyncio.sleep(timeout, loop=loop)
            except asyncio.CancelledError:
                return

        await func(*args, **kwargs)

    fut = asyncio.run_coroutine_threadsafe(wait(), loop)
    if callable(after):
        fut.add_done_callback(after)

    return CallLater(fut, datetime.utcnow() + timedelta(seconds=timeout))


def get_users_from_ids(guild, *ids):
    users = []
    for i in ids:
        user = guild.get_member(i)
        if user:
            users.append(user)

    return users


def check_channel_mention(msg, word):
    if msg.channel_mentions:
        if word != msg.channel_mentions[0].mention:
            return False
        return True
    return False


def get_channel(channels, s, name_matching=False, only_text=True):
    channel = get_channel_id(s)
    if channel:
        channel = discord.utils.find(lambda c: c.id == s, channels)
        if channel:
            return channel

    try:
        s = int(s)
    except ValueError:
        pass
    else:
        channel = discord.utils.find(lambda c: c.id == s, channels)

    if not channel and name_matching:
        s = str(s)
        channel = discord.utils.find(lambda c: c.name == s, channels)
        if not channel:
            return
    else:
        return

    if only_text and not isinstance(channel, discord.TextChannel):
        return

    return channel


def check_role_mention(msg, word, guild):
    if msg.raw_role_mentions:
        id = msg.raw_role_mentions[0]
        if str(id) not in word:
            return False
        role = list(filter(lambda r: r.id == id, guild.roles))
        if not role:
            return False
        return role[0]
    return False


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

    return discord.utils.find(lambda r: r.id == role_id, roles)


def check_user_mention(msg, word):
    if msg.mentions:
        if word != msg.mentions[0].mention:
            return False
        return True
    return False


def get_avatar(user):
    return user.avatar_url or user.default_avatar_url


def get_role_id(s):
    regex = re.compile(r'(?:<@&)?(\d+)(?:>)?(?: |$)')
    match = regex.match(s)
    if match:
        return int(match.groups()[0])


def get_user_id(s):
    regex = re.compile(r'(?:<@!?)?(\d+)(?:>)?(?: |$)')
    match = regex.match(s)
    if match:
        return int(match.groups()[0])


def get_channel_id(s):
    regex = re.compile(r'(?:<#)?(\d+)(?:>)?')
    match = regex.match(s)
    if match:
        return int(match.groups()[0])


def seconds2str(seconds, long_def=True):
    seconds_ = int(round(seconds, 0))
    if not seconds_:
        return f'{round(seconds, 2)}s'

    seconds = seconds_
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)

    def check_plural(string, i):
        if i != 1:
            return '%s %ss ' % (str(i), string)
        return '%s %s ' % (str(i), string)

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


def find_user(s, members, case_sensitive=False, ctx=None):
    if not s:
        return
    if ctx:
        # if ctx is present check mentions first
        if ctx.message.mentions and ctx.message.mentions[0].mention.replace('!', '') == s.replace('!', ''):
            return ctx.message.mentions[0]

        try:
            uid = int(s)
        except ValueError:
            pass
        else:
            for user in members:
                if user.id == uid:
                    return user

    def filter_users(predicate):
        for member in members:
            if predicate(member):
                return member

            if member.nick and predicate(member.nick):
                return member

    p = lambda u: str(u).startswith(s) if case_sensitive else lambda u: str(u).lower().startswith(s)
    found = filter_users(p)
    s = '`<@!{}>` {}'
    if found:
        return found

    p = lambda u: s in str(u) if case_sensitive else lambda u: s in str(u).lower()
    found = filter_users(p)

    return found


def is_image_url(url):
    if url is None:
        return

    if not test_url(url):
        return False

    mimetype, encoding = mimetypes.guess_type(url)
    return mimetype and mimetype.startswith('image')


def msg2dict(msg):
    d = {}
    attachments = [attachment.url for attachment in msg.attachments]
    d['attachments'] = ', '.join(attachments)
    return d


def format_message(d):
    for k in FORMAT_BLACKLIST:
        d.pop(k, None)

    for k in d:
        v = d[k]
        if isinstance(v, str):
            continue

        if isinstance(v, discord.MessageType):
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
    d.pop('roles')
    d.pop('voice')
    d.pop('dm_channel')

    for k in d:
        v = d[k]
        if isinstance(v, discord.Activity):
            d[k] = format_activity(v)

        elif isinstance(v, discord.Permissions):
            d[k] = str(v.value)

        else:
            d[k] = str(v)

    return d


def format_join_leave(member, message):
    d = format_member(member)
    message = message.format(**d)
    return remove_everyone(message)


def test_member(member):
    d = format_member(member)
    s = ''
    for k, v in d.items():
        s += '{%s}: %s\n' % (k, v)

    return remove_everyone(s)


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
    matrix = []
    for p1, p2 in zip(pa, pb):
        matrix.append([p1[0], p1[1], 1, 0, 0, 0, -p2[0]*p1[0], -p2[0]*p1[1]])
        matrix.append([0, 0, 0, p1[0], p1[1], 1, -p2[1]*p1[0], -p2[1]*p1[1]])

    A = numpy.matrix(matrix, dtype=numpy.float)
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

        if value['user'] is not None:
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


def is_superset(ctx):
    if ctx.override_perms is None and ctx.command.required_perms is not None:
        perms = ctx.message.channel.permissions_for(ctx.message.author)

        if not perms.is_superset(ctx.command.required_perms):
            req = [r[0] for r in ctx.command.required_perms if r[1]]
            raise MissingPermissions(req)

    return True


async def send_paged_message(ctx, pages, embed=False, starting_idx=0, page_method=None):
    bot = ctx.bot
    try:
        if callable(page_method):
            page = page_method(pages[starting_idx], starting_idx)
        else:
            page = pages[starting_idx]
    except IndexError:
        return await ctx.channel.send(f'Page index {starting_idx} is out of bounds')

    if embed:
        message = await ctx.channel.send(embed=page)
    else:
        message = await ctx.channel.send(page)
    if len(pages) == 1:
        return

    await message.add_reaction('◀')
    await message.add_reaction('▶')

    paged = PagedMessage(pages, starting_idx=starting_idx)

    if callable(page_method):
        async def send():
            if embed:
                await message.edit(embed=page_method(page, paged.index))
            else:
                await message.edit(content=page_method(page, paged.index))
    else:
        async def send():
            if embed:
                await message.edit(embed=page)
            else:
                await message.edit(content=page)

    def check(reaction, user):
        return paged.check(reaction, user) and ctx.author.id == user.id and reaction.message.id == message.id

    while True:
        try:
            result = await bot.wait_for('reaction_changed', check=check, timeout=60)
        except asyncio.TimeoutError:
            return

        page = paged.reaction_changed(*result)
        if page is None:
            continue

        try:
            await send()
            # Wait for a bit so the bot doesn't get ratelimited from reaction spamming
            await asyncio.sleep(1)
        except discord.HTTPException:
            return


async def get_all_reaction_users(reaction, limit=100):
    users = []
    limits = [100 for i in range(limit // 100)]
    remainder = limit % 100
    if remainder > 0:
        limits.append(remainder)

    for limit in limits:
        if users:
            user = users[-1]
        else:
            user = None
        _users = await reaction.users(limit=limit, after=user)
        users.extend(_users)

    return users


async def create_custom_emoji(guild, name, image, already_b64=False, reason=None, **kwargs):
    """Same as the base method but supports giving your own b64 encoded data"""
    if not already_b64:
        img = discord.utils._bytes_to_base64_data(image)
    else:
        img = image

    data = await guild._state.http.create_custom_emoji(guild.id, name, img, reason=reason, **kwargs)
    return guild._state.store_emoji(guild, data)


def is_owner(ctx):
    if ctx.command.owner_only and ctx.bot.owner_id != ctx.original_user.id:
        raise NotOwner

    ctx.skip_check = True

    return True


async def check_blacklist(ctx):
    if getattr(ctx, 'skip_check', False):
        return True

    bot = ctx.bot
    if not hasattr(bot, 'check_auth'):
        # No database blacklisting detected
        return True

    if not await bot.check_auth(ctx):
        return False

    overwrite_perms = await bot.dbutil.check_blacklist('(command="%s" OR command IS NULL)' % ctx.command, ctx.author, ctx, True)
    msg = PermValues.BLACKLIST_MESSAGES.get(overwrite_perms, None)
    if isinstance(overwrite_perms, int):
        if ctx.guild and ctx.guild.owner.id == ctx.author.id:
            overwrite_perms = True
        else:
            overwrite_perms = PermValues.RETURNS.get(overwrite_perms, False)
    ctx.override_perms = overwrite_perms

    if overwrite_perms is False:
        if msg is not None:
            raise CommandBlacklisted(msg)
        return False

    return True


async def search(s, ctx, site, downloader, on_error=None):
    search_keys = {'yt': 'ytsearch', 'sc': 'scsearch'}
    urls = {'yt': 'https://www.youtube.com/watch?v=%s'}
    max_results = 20
    search_key = search_keys.get(site, 'ytsearch')
    channel = ctx.channel
    query = '{0}{1}:{2}'.format(search_key, max_results, s)

    info = await downloader.extract_info(ctx.bot.loop, url=query,
                                         on_error=on_error,
                                         download=False)
    if info is None or 'entries' not in info:
        return await channel.send('Search gave no results', delete_after=60)

    url = urls.get(site, 'https://www.youtube.com/watch?v=%s')

    def get_page(page, index):
        id = page.get('id')
        if id is None:
            return page.get('url')
        return url % id

    await send_paged_message(ctx, info['entries'], page_method=get_page)


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
    return int(seek_dict['h'])*3600 + int(seek_dict['m'])*60 + int(seek_dict['s'])


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
    cmd = f'"{sys.executable}" -m compileall "{module_name}"'
    p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
    out, _ = p.communicate()
    out = out.decode('utf-8')
    if out.lower().startswith('compiling'):
        out = '\n'.join(out.split('\n')[1:]).strip('* ')
    return out


def check_botperm(*perms, ctx=None, channel=None, guild=None, me=None):
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

    return False


def no_dm(ctx):
    if ctx.guild is None:
        raise discord.ext.commands.NoPrivateMessage('This command cannot be used in private messages.')
    return True


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

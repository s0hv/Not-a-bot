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

import logging
import os
import re
import shlex
import subprocess
from collections import OrderedDict
import time

from validators import url as test_url

from bot.exceptions import NoCachedFileException


logger = logging.getLogger('debug')


def split_string(to_split, list_join='', maxlen=1900, splitter=' '):
    if isinstance(to_split, str):
        if len(to_split) < maxlen:
            return [to_split]

        to_split = to_split.split(splitter)
        length = 0
        split = ''
        splits = []
        for s in to_split:
            if length + len(s) > maxlen:
                splits += [split]
                split = ''
                length = 0
            else:
                split += s
                length += len(s)

        return splits

    if isinstance(to_split, dict):
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

    raise NotImplementedError('This only works with dicts and strings for now')


def mean_volume(file, avconv=False):
    logger.debug('Getting mean volume')
    ffmpeg = 'ffmpeg' if not avconv else 'avconv'
    file = '"{}"'.format(file)

    cmd = '{0} -i {1} -t 00:10:00 -filter:a "volumedetect" -vn -sn -f null /dev/null'.format(ffmpeg, file)

    args = shlex.split(cmd)
    process = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    out, err = process.communicate()
    out += err

    matches = re.findall('mean_volume: [\-\d\.]+ dB', str(out))

    if not matches:
        return
    try:
        volume = float(matches[0].split(' ')[1])
        logger.debug('Parsed volume is {}'.format(volume))
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
        print('[ERROR] {0}\n{1} value is not {2}. {1} set to {3}'.format(e, option, str(option_type), str(fallback)))
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


def check_negative(n):
    if n < 0:
        return -1
    else:
        return 1


def emote_url_from_id(id):
    return 'https://cdn.discordapp.com/emojis/%s.png' % id


def get_picture_from_msg(msg):
    if msg is None:
        return

    if len(msg.attachments) > 0:
        return msg.attachments[0]['url']

    words = msg.content.split(' ')
    for word in words:
        if test_url(word):
            return word


def normalize_text(s):
    # Get cleaned emotes
    matches = re.findall('<:\w+:\d+>', s)

    for match in matches:
        s = s.replace(match, match.split(':')[1])

    #matches = re.findall('<@\d+>')
    return s


def slots2dict(obj):
    # Turns slots and @properties to a dict
    d = {k: getattr(obj, k) for k in obj.__slots__}
    for k in dir(obj):
        if k.startswith('_'):
            # We don't want any private methods
            continue

        v = getattr(obj, k)
        if not callable(v):
            # Don't need methods here
            d[k] = v

    return d
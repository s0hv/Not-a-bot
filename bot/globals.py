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
import shutil
from os.path import join
from pathlib import Path


terminal = logging.getLogger('terminal')

try:
    _wd = Path(__file__).parent.parent.__str__()
except OSError:
    _wd = os.getcwd()

DATA = join(_wd, 'data')
PLAYLISTS = join(_wd, 'data', 'playlists')
AUTOPLAYLIST = join(PLAYLISTS, 'autoplaylist.txt')
ADD_AUTOPLAYLIST = join(PLAYLISTS, 'add_autoplaylist.txt')
DELETE_AUTOPLAYLIST = join(PLAYLISTS, 'delete_autoplaylist.txt')
SFX_FOLDER = join(_wd, 'data', 'audio', 'sfx')
TTS = join(_wd, 'data', 'audio', 'tts')
CACHE = join(_wd, 'data', 'audio', 'cache')
WORKING_DIR = _wd
IMAGES_PATH = os.path.join(_wd, 'data', 'images')

PERMISSION_OPTIONS = {'name': None, 'ban_commands': False, 'master_override': False,
                      'playlists': True, 'max_playlist_length': 10, 'edit_autoplaylist': False,
                      'edit_permissions': False, 'level': 0, 'whitelist': None, 'blacklist': None}


def _create_folder(path):
    if not os.path.exists(path):
        os.makedirs(path)


def create_folders():
    _create_folder(join(_wd, 'data'))

    if not os.path.exists(PLAYLISTS):
        terminal.error(f'Path {PLAYLISTS} does not exist')
        raise FileNotFoundError(f'Path {PLAYLISTS} does not exist')

    _create_folder(SFX_FOLDER)

    _create_folder(IMAGES_PATH)


create_folders()

if not os.path.exists(AUTOPLAYLIST) and os.path.exists(join(PLAYLISTS, '_autoplaylist.txt')):
    try:
        shutil.copyfile(join(PLAYLISTS, '_autoplaylist.txt'), AUTOPLAYLIST)
    except OSError:
        terminal.exception('Autoplaylist copying failed')


class BlacklistTypes:
    GLOBAL = 0
    WHITELIST = 1
    BLACKLIST = 2

    OPPOSITES = {WHITELIST: BLACKLIST, BLACKLIST: WHITELIST}

    @classmethod
    def get_opposite(cls, value):
        return cls.OPPOSITES.get(value, 0)


# TODO please fix these they make no sense
class PermValues:
    VALUES = {'user': 0x1, 'whitelist': 0x0, 'blacklist': 0x2, 'role': 0x4,
              'channel': 0x8, 'guild': 0x10}
    RETURNS = {1: True, 3: False, 4: True, 6: False, 8: True, 10: False,
               16: True, 18: False}
    BLACKLIST_MESSAGES = {3: ('Command has been blacklisted for you', None),
                          6: ('Command has been blacklisted for a role you have', None),
                          10: (None, 'Command has been blacklisted in this channel'),
                          18: (None, 'Command has been blacklisted from the guild')}


class Auth:
    NONE = 0
    BOT_MOD = 1
    BOT_ADMIN = 2

    TO_STRING = {2: "Bot admin", 1: "Bot moderator", 0: "None"}

    @classmethod
    def to_string(cls, i):
        return cls.TO_STRING.get(i)

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

import os
from pathlib import Path

try:
    _wd = Path(__file__).parent.parent.__str__()
except:
    _wd = os.getcwd()

PLAYLISTS = os.path.join(_wd, 'data', 'playlists')
AUTOPLAYLIST = os.path.join(PLAYLISTS, 'autoplaylist.txt')
ADD_AUTOPLAYLIST = os.path.join(PLAYLISTS, 'add_autoplaylist.txt')
DELETE_AUTOPLAYLIST = os.path.join(PLAYLISTS, 'delete_autoplaylist.txt')
SFX_FOLDER = os.path.join(_wd, 'data', 'audio', 'sfx')
TTS = os.path.join(_wd, 'data', 'audio', 'tts')
CACHE = os.path.join(_wd, 'data', 'audio', 'cache')


def create_folders():
    if not os.path.exists(os.path.join(_wd, 'data')):
        os.mkdir(os.path.join(_wd, 'data'))

    if not os.path.exists(PLAYLISTS):
        print('[ERROR] Path %s does not exist' % PLAYLISTS)
        raise FileNotFoundError('Path %s does not exist' % PLAYLISTS)

    if not os.path.exists(SFX_FOLDER):
        os.mkdir(SFX_FOLDER)

create_folders()

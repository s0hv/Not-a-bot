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
import os
import time
from typing import Optional

import aiohttp
import disnake
from aiohttp.web_exceptions import HTTPException

logger = logging.getLogger('audio')
terminal = logging.getLogger('terminal')


class PartialSong:
    """For use with playlists"""
    __slots__ = ['title', 'webpage_url', 'duration']

    def __init__(self, title, webpage_url, duration):
        self.title = title
        self.webpage_url = webpage_url
        self.duration = duration

    def __dict__(self):
        return {'webpage_url': self.webpage_url, 'title': self.title,
                'duration': self.duration}


class Song:
    __slots__ = ['title', 'url', 'webpage_url', 'id', 'duration', 'default_duration',
                 'uploader', 'playlist', 'seek', 'success', 'filename', 'before_options',
                 '_options', '_downloading', 'on_ready', 'volume',
                 'logger', 'bpm', 'config', 'requested_by', 'last_update', 'is_live',
                 'rms', 'filters', 'bitrate']

    def __init__(self, playlist=None, filename=None, config=None, **kwargs):
        self.title = kwargs.pop('title', 'Untitled')
        self.url = kwargs.pop('url', 'None')
        self.webpage_url = kwargs.pop('webpage_url', None)
        self.id = kwargs.pop('id', None)
        self.duration = kwargs.pop('duration', 0)
        self.default_duration = self.duration  # Used when speed is changed
        self.uploader = kwargs.pop('uploader', 'None')
        self.requested_by: Optional[disnake.Member | disnake.User] = kwargs.pop('requested_by', None)
        self.is_live = kwargs.pop('is_live', False)
        self.playlist = playlist
        self.seek = False
        self.success = None  # False when download error
        self.config = config
        self.filename = filename
        self.before_options = kwargs.pop('before_options', '')
        if '-nostdin' not in self.before_options:
            self.before_options = ' '.join(('-nostdin', self.before_options)).strip()

        self.bitrate = kwargs.pop('bitrate', 128)

        self._options = kwargs.pop('options', '')
        if '-vn -b:a' not in self._options:
            self._options = ' '.join((self._options, '-vn -b:a {bitrate}k -bufsize {bitrate}K')).strip()

        self.filters = kwargs.pop('filters', {})

        self._downloading = False
        self.on_ready = asyncio.Event()
        self.bpm = None
        self.last_update = 0
        self.volume = None
        self.rms = kwargs.pop('rms', None)

    @classmethod
    def from_song(cls, song, **kwargs):
        s = Song(**{k: getattr(song, k, None) for k in song.__slots__})
        s.bpm = song.bpm
        s._options = song._options
        s.last_update = song.last_update
        s.volume = song.volume
        s.success = song.success
        for k in kwargs:
            if k in song.__slots__:
                setattr(s, k, kwargs[k])

        return s

    def __str__(self):
        string = '**{0.title}**'
        return string.format(self)

    @property
    def options(self):
        fa = ''
        if self.filters:
            fa = ' -filter:a "' + ', '.join(
                map(lambda kv: f'{kv[0]}={kv[1]}', self.filters.items())
            ) + '"'

        return self._options.format(bitrate=self.bitrate) + fa

    def set_filter(self, filter_, value):
        self.filters[filter_] = value

    def remove_filter(self, filter_):
        self.filters.pop(filter_, None)

    def has_filter(self, filter_):
        return filter_ in self.filters

    @property
    def long_str(self):
        string = '**{0.title}**'
        if self.requested_by:
            string += ' enqueued by {0.requested_by.mention}'
        return string.format(self)

    @classmethod
    def from_partial(cls, playlist, config, partial_song: PartialSong):
        return cls(playlist, config=config, webpage_url=partial_song.webpage_url,
                   title=partial_song.title, duration=partial_song.duration)

    def info_from_dict(self, **kwargs):
        self.title = kwargs.get('title', self.title)
        self.url = kwargs.get('url', self.url)
        self.webpage_url = kwargs.get('webpage_url', self.webpage_url)
        self.id = kwargs.get('id', self.id)
        self.duration = kwargs.get('duration', self.duration)
        self.default_duration = self.duration
        self.uploader = kwargs.get('uploader', self.uploader)
        self.before_options = kwargs.get('before_options', self.before_options)
        self._options = kwargs.get('options', self._options)
        self.filters = kwargs.get('filters', self.filters)
        self.is_live = kwargs.pop('is_live', True)

        if 'url' in kwargs:
            self.last_update = time.time()
            self.success = True
            self.playlist.bot.loop.call_soon_threadsafe(self.on_ready.set)

        if self.playlist.bot.config.download:
            self.filename = self.playlist.downloader.safe_ytdl.prepare_filename(**kwargs)
        else:
            self.filename = self.url

    @property
    def downloading(self):
        return self._downloading

    async def validate_url(self):
        if time.time() - self.last_update <= 1800:
            return True  # If link is under 30min old it probably still works

        if not self.url:
            return True

        try:
            async with aiohttp.ClientSession() as client:
                async with client.head(self.url) as r:
                    if r.status != 200:
                        self.last_update = 0  # Reset last update so we dont end up in recursion loop
                        await self.download()
            return True
        except HTTPException:
            logger.exception('Failed to validate url')
            return False

    async def download(self, return_if_downloading=True):
        """
        Downloads the song and returns a 3 state boolean representing 3 possible
        outcomes of the method

        Args:
            return_if_downloading:
                Tells whether to wait for an ongoing download to finish
                if one exists

        Returns:
            (bool or None):
                Returns bool when download was attempted. True meaning download
                succeeded and False meaning download failed.
                If None is returned no download attempt was made since
                download has been done earlier
        """

        if self.success is False:
            self.playlist.bot.loop.call_soon_threadsafe(self.on_ready.set)
            return False

        # First check if download is unnecessary and return if any of them
        # conditions are True
        if self.downloading:
            if not return_if_downloading:
                await self.on_ready.wait()
            return

        if time.time() - self.last_update <= 1800:
            self.playlist.bot.loop.call_soon_threadsafe(self.on_ready.set)
            return

        if self.last_update > 0 and await self.validate_url():
            self.last_update = time.time()
            return

        self._downloading = True
        self.on_ready.clear()
        logger.debug(f'Started downloading {self.long_str}')
        try:
            loop = self.playlist.bot.loop

            logger.debug(f'Getting info and downloading {self.webpage_url}')
            info = await self.playlist.downloader.extract_info(loop, url=self.webpage_url, download=False)
            logger.debug('Got info')

            self.info_from_dict(**info)
            terminal.info(f'Downloaded {self.webpage_url}')
            logger.debug(f'Filename set to {self.webpage_url}')
            self.success = True

        except Exception as e:
            if self.success is not False:
                logger.exception(f'Download error: {e}')
                try:
                    await self.playlist.channel.send(f'Failed to download {self.title}\nlink: <{self.webpage_url}>')
                except disnake.HTTPException:
                    pass

            self.success = False

        finally:
            self._downloading = False
            self.playlist.bot.loop.call_soon_threadsafe(self.on_ready.set)
            return self.success

    async def delete_file(self):
        for _ in range(0, 2):
            try:
                if not os.path.exists(self.filename):
                    return

                os.remove(self.filename)
                terminal.info(f'Deleted {self.filename}')
                break
            except PermissionError:
                await asyncio.sleep(1)

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
import functools
import logging
import discord
import os
import time
from collections import deque
from random import shuffle, choice

from validators import url as valid_url

try:
    from numpy import delete
except ImportError:
    delete = None
    print('[EXCEPTION] Numpy is not installed. Playlist can now only be cleared completely. No deletion by indexes')

from bot.downloader import Downloader
from bot.song import Song
from bot.globals import CACHE, PLAYLISTS
from utils.utilities import read_lines, write_playlist, timestamp, seconds2str


logger = logging.getLogger('audio')


class Playlist:
    def __init__(self, bot, download=False):
        self.bot = bot
        self.channel = None
        self.download = download
        self.playlist = deque()
        self.downloader = Downloader(CACHE)
        self.not_empty = asyncio.Event()
        self.playlist_path = PLAYLISTS
        self.adding_songs = False

    def __iter__(self):
        return iter(self.playlist)

    async def shuffle(self):
        shuffle(self.playlist)
        await self.download_next()

    def peek(self):
        if self.playlist:
            return self.playlist[0]

    async def next_song(self):
        if self.playlist:
            song = self.playlist.popleft()
            if not song:
                return

            if not song.success:
                print('[INFO] downloading from next_song')
                await song.download()

            return song

    async def download_next(self):
        next_song = self.peek()
        if next_song is not None:
            await next_song.download()
        return next_song

    async def clear(self, indexes=None, channel=None):
        if indexes is None:
            self.playlist.clear()
        else:
            if delete is not None:
                songs_left = delete(list(self.playlist), indexes)
                self.playlist.clear()
                for song in songs_left:
                    self.playlist.append(song)
            else:
                print('[ERROR] Numpy is not installed. Cannot delete songs by index')
                await self.say('Clearing by indices is not supported', channel=channel)

            await self.say('Playlist cleared', channel=channel)

    async def search(self, name, ctx, site='yt', priority=False, in_vc=True):
        search_keys = {'yt': 'ytsearch', 'sc': 'scsearch'}
        urls = {'yt': 'https://www.youtube.com/watch?v=%s'}
        max_results = 20
        search_key = search_keys.get(site, 'ytsearch')

        query = '{0}{1}:{2}'.format(search_key, max_results, name)
        info = await self.downloader.extract_info(self.bot.loop, url=query, on_error=self.failed_info, download=False)
        if info is None or 'entries' not in info:
            return await self.say('Search gave no results', 60, ctx.message.channel)

        channel = ctx.message.channel

        async def _say(msg):
            nonlocal ctx, self
            return await self.say(msg, channel=channel)

        def check(msg):
            msg = msg.content.lower().strip()
            return msg in ['y', 'yes', 'n', 'no', 'stop']

        async def _wait_for_message():
            nonlocal ctx, self
            return await self.bot.wait_for_message(timeout=60, author=ctx.message.author,
                                                   channel=channel,
                                                   check=check)

        url = urls.get(site, 'https://www.youtube.com/watch?v=%s')
        message = None
        for entry in info['entries']:
            if entry.get('id') is None:
                new_url = entry.get('url')
            else:
                new_url = url % entry['id']

            s = 'Is this the right one? (`Y`/`N`/`STOP`) {}'.format(new_url)
            if message is not None:
                try:
                    await self.bot.edit_message(message, s)
                except:
                    message = await _say(s)
            else:
                message = await _say(s)

            returned = await _wait_for_message()
            if returned is None or returned.content.lower() in 'stop':
                try:
                    await self.bot.delete_message(message)
                    await _say('Cancelling search')
                except:
                    pass
                return

            if returned.content.lower().strip() in ['n', 'no']:
                continue

            if in_vc:
                await self.bot.delete_message(message)
                await self._add_url(new_url, priority=priority, channel=channel)
            return True

        await _say('That was all of them. Max amount of results is %s' % max_results)

    async def _add_from_info(self, channel=None, priority=False, no_message=False, metadata=None, **info):
        try:
            if not channel:
                channel = self.channel
            if metadata is None:
                metadata = {}

            fname = self.downloader.safe_ytdl.prepare_filename(info)
            song = Song(playlist=self, filename=fname, config=self.bot.config, **metadata)
            song.info_from_dict(**info)
            await self._append_song(song, priority)

            if not no_message:
                await self.say('Enqueued %s' % song.title, 20, channel=channel)

        except Exception as e:
            logger.exception('Could not add song')
            return await self.say('Error\n%s' % e, channel=channel)

    async def _add_url(self, url, channel=None, no_message=False, priority=False, **metadata):
        if not channel:
            channel = self.channel

        on_error = functools.partial(self.failed_info, channel=channel)
        info = await self.downloader.extract_info(self.bot.loop, url=url, download=False, on_error=on_error)
        if info is None:
            return
        await self._add_from_info(channel=channel, priority=priority,
                                  no_message=no_message, metadata=metadata, **info)

    async def add_song(self, name, no_message=False, maxlen=10, priority=False,
                       channel=None, **metadata):

        on_error = functools.partial(self.failed_info, channel=channel)

        try:
            self.adding_songs = True
            if valid_url(name):
                info = await self.downloader.extract_info(self.bot.loop, url=name, on_error=on_error, download=False)
            else:
                info = await self._search(name, on_error=on_error)
            if info is None:
                if not no_message:
                    return await self.say('No songs found or a problem with YoutbeDL that I cannot fix :(', channel=channel)
                return

            if 'entries' in info:
                entries = info['entries']
                size = len(entries)
                if size > maxlen >= 0:  # Max playlist size
                    await self.say('Playlist is too big. Max size is %s' % maxlen, channel=channel)
                    return

                if entries[0]['ie_key'].lower() != 'youtube':
                    await self.say('Only youtube playlists are currently supported', channel=channel)
                    return

                url = 'https://www.youtube.com/watch?v=%s'
                title = info['title']
                if priority:
                    await self.say('Playlists queued with playnow will be reversed except for the first song', 60, channel=channel)

                message = await self.say('Processing %s songs' % size, channel=channel)
                t = time.time()
                songs = deque()
                first = True
                progress = 0

                async def progress_info():
                    nonlocal message

                    while progress <= size:
                        try:
                            await asyncio.sleep(3)
                            t2 = time.time() - t
                            eta = progress/t2
                            if eta == 0:
                                eta = 'Undefined'
                            else:
                                eta = seconds2str(max(size/eta - t2, 0))

                            s = 'Loading playlist. Progress {}/{}\nETA {}'.format(progress, size, eta)
                            message = await self.bot.edit_message(message, s)
                        except asyncio.CancelledError:
                            await self.bot.delete_message(message)
                        except:
                            return

                    await self.bot.delete_message(message)

                task = discord.compat.create_task(progress_info(), loop=self.bot.loop)
                async def _on_error(err):
                    try:
                        if not no_message:
                            await self.say('Failed to process %s' % entry.get('title', entry.get['id']) + '\n%s' % e, channel=channel)
                    except:
                        pass

                    return False

                for entry in entries:
                    progress += 1

                    info = await self.downloader.extract_info(self.bot.loop, url=url % entry['id'], download=False,
                                                              on_error=_on_error)
                    if info is False:
                        continue

                    if info is None:
                        try:
                            if not no_message:
                                await self.say('Failed to process %s' % entry.get('title', entry['id']), channel=channel)
                        except:
                            pass
                        continue

                    song = Song(playlist=self, config=self.bot.config, **metadata)
                    song.info_from_dict(**info)

                    if not priority:
                        await self._append_song(song)
                    else:
                        if first:
                            await self._append_song(song, priority=priority)
                            first = False
                        else:
                            songs.append(song)

                task.cancel()

                if songs:
                    await self._append_song(songs.popleft(), priority=priority)
                    songs.reverse()
                    for song in songs:
                        self.playlist.appendleft(song)

                if not no_message:
                    if priority:
                        msg = 'Enqueued playlist %s to the top' % title
                    else:
                        msg = 'Enqueued playlist %s' % title
                    return await self.say(msg, 60, channel=channel)

            else:
                await self._add_from_info(priority=priority, channel=channel,
                                          no_message=no_message, metadata=metadata, **info)

        finally:
            self.adding_songs = False

    async def add_from_song(self, song, priority=False, channel=None):
        await self._append_song(song, priority)
        if priority:
            await self.say('Enqueued {} to the top of the queue'.format(song), channel=channel)
        else:
            await self.say('Enqueued {}'.format(song), channel=channel)

    async def add_from_playlist(self, name, channel=None):
        lines = read_lines(os.path.join(self.playlist_path, name))
        if lines is None:
            return await self.say('Invalid playlist name')

        await self.say('Processing %s songs' % lines, 60, channel=channel)
        for line in lines:
            await self._add_url(line, no_message=True)

        await self.say('Enqueued %s' % name, channel=channel)

    async def current_to_file(self, name=None, channel=None):
        if name == 'autoplaylist.txt':
            return await self.say('autoplaylist.txt is not a valid name')

        if not self.playlist:
            return await self.say('Empty playlist', 60, channel=channel)
        lines = [song.webpage_url for song in self.playlist]

        if not name:
            name = 'playlist-{}'.format(timestamp())
        file = os.path.join(self.playlist_path, name)
        write_playlist(file, lines)
        await self.say('Playlist %s created' % name, 90, channel=channel)

    async def _search(self, name, **kwargs):
        info = await self.downloader.extract_info(self.bot.loop, extract_flat=False, url=name, download=False, **kwargs)
        if 'entries' in info:
            return info['entries'][0]

    def on_stop(self):
        if self.peek() is not None:
            self.bot.loop.call_soon_threadsafe(self.not_empty.set)
        else:
            self.not_empty.clear()

    async def extract_info(self, name, on_error=None):
        return await self.downloader.extract_info(self.bot.loop, url=name, download=False, on_error=on_error)

    async def process_playlist(self, info, channel=None):
        if 'entries' in info:
            entries = info['entries']

            if entries[0]['ie_key'].lower() != 'youtube':
                await self.say('Only youtube playlists are currently supported', channel=channel)
                return

            links = []
            url = 'https://www.youtube.com/watch?v=%s'
            for entry in entries:
                links.append(url % entry['id'])

            return links

    async def failed_info(self, e, channel=None):
        await self.say("Couldn't get the requested video\n%s" % e, channel=channel)

    async def _append_song(self, song, priority=False):
        if not self.playlist or priority:
            print('[INFO] Downloading %s' % song.webpage_url)
            await song.download()

            if priority:
                self.playlist.appendleft(song)
            else:
                self.playlist.append(song)

            logger.debug('Song appended. Name: {}'.format(song.webpage_url))
            self.bot.loop.call_soon_threadsafe(self.not_empty.set)
        else:
            self.playlist.append(song)
            self.bot.loop.call_soon_threadsafe(self.not_empty.set)

    async def get_from_autoplaylist(self):
        song = self.get_random_song('autoplaylist')
        if song is None:
            return

        song = Song(self, webpage_url=song, config=self.bot.config)
        print('[INFO] Downloading %s' % song.webpage_url)
        await song.download()
        await song.on_ready.wait()
        if not song.success:
            return
        return song

    def get_random_song(self, playlist):
        songs = self._get_playlist(playlist + '.txt')
        if songs is None:
            return
        return choice(songs)

    def _get_playlist(self, name):
        playlist = os.path.join(self.playlist_path, name)
        lines = read_lines(playlist)
        return lines

    def in_list(self, webpage_url):
        items = list(self.playlist)
        for item in items:
            try:
                if item.webpage_url == webpage_url:
                    return True
            except Exception as e:
                print('[EXCEPTION] Error while checking playlist %s' % e)

        return False

    async def say(self, message, duration=None, channel=None):
        if channel is None:
            channel = self.channel

        try:
            return await self.bot.send_message(channel, message, delete_after=duration)
        except:
            pass

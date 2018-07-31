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
import os
import time
from collections import deque
from random import shuffle, choice

import discord
from validators import url as valid_url

from bot.downloader import Downloader
from bot.globals import CACHE, PLAYLISTS
from bot.paged_message import PagedMessage
from bot.song import Song
from utils.utilities import (read_lines, write_playlist, timestamp, seconds2str)

terminal = logging.getLogger('terminal')

try:
    from numpy import delete as delete_by_indices
except ImportError:
    delete_by_indices = None
    terminal.warning('Numpy is not installed. Playlist can now only be cleared completely. No deletion by indexes')

logger = logging.getLogger('audio')


class Playlist:
    def __init__(self, bot, download=False, channel=None):
        self.bot = bot
        self.channel = channel
        self.download = download
        self.playlist = deque()
        self.history = deque(maxlen=5)
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
                terminal.debug('downloading from next_song')
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
            if delete_by_indices is not None:
                songs_left = delete_by_indices(list(self.playlist), indexes)
                self.playlist.clear()
                for song in songs_left:
                    self.playlist.append(song)
            else:
                terminal.warning('Numpy is not installed. Cannot delete songs by index')
                await channel.send('Clearing by indices is not supported')
            if channel:
                await channel.send('Playlist cleared')

    async def search(self, name, ctx, site='yt', priority=False, in_vc=True):
        search_keys = {'yt': 'ytsearch', 'sc': 'scsearch'}
        urls = {'yt': 'https://www.youtube.com/watch?v=%s'}
        max_results = 20
        search_key = search_keys.get(site, 'ytsearch')
        channel = ctx.message.channel
        query = '{0}{1}:{2}'.format(search_key, max_results, name)

        info = await self.downloader.extract_info(self.bot.loop, url=query, on_error=self.failed_info, download=False)
        if info is None or 'entries' not in info:
            return await channel.send('Search gave no results', delete_after=60)

        url = urls.get(site, 'https://www.youtube.com/watch?v=%s')
        entries = info['entries']
        length = len(entries)
        paged = PagedMessage(entries)
        emoji = ('◀', '▶', '✅', '❌')

        def get_url(entry):
            if entry.get('id') is None:
                new_url = entry.get('url')
            else:
                new_url = url % entry['id']

            return new_url

        def get_page(entry, idx):
            new_url = get_url(entry)
            return f'Send `Y` to confirm or `STOP` to stop\n{new_url} {idx+1}/{length}'

        entry = entries[0]
        message = await ctx.channel.send(get_page(entry, 0))
        await message.add_reaction('◀')
        await message.add_reaction('▶')
        await message.add_reaction('✅')
        await message.add_reaction('❌')

        def check(reaction, user):
            return reaction.emoji in emoji and ctx.author.id == user.id and reaction.message.id == message.id

        while True:
            try:
                result = await self.bot.wait_for('reaction_changed', check=check,
                                                 timeout=60)
            except asyncio.TimeoutError:
                return await ctx.send('Took too long.')

            reaction = result[0]
            if reaction.emoji == '✅':
                if in_vc:
                    await message.delete()
                    await self._add_url(get_url(entry), priority=priority,
                                        channel=channel)

                return

            if reaction.emoji == '❌':
                return

            entry = paged.reaction_changed(*result)
            if entry is None:
                continue

            try:
                await message.edit(content=get_page(entry, paged.index))
                # Wait for a bit so the bot doesn't get ratelimited from reaction spamming
                await asyncio.sleep(1)
            except discord.HTTPException:
                return

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
                await channel.send(f'Enqueued {song.title}', delete_after=20)

        except Exception as e:
            logger.exception('Could not add song')
            return await channel.send(f'Error\n{e}')

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
                    return await channel.send('No songs found or a problem with YoutbeDL that I cannot fix :(')
                return

            if 'entries' in info:
                entries = info['entries']
                size = len(entries)
                if size > maxlen >= 0:  # Max playlist size
                    await channel.send(f'Playlist is too big. Max size is {maxlen}')
                    return

                if entries[0]['ie_key'].lower() != 'youtube':
                    await channel.send('Only youtube playlists are currently supported')
                    return

                url = 'https://www.youtube.com/watch?v=%s'
                title = info['title']
                if priority:
                    await channel.send('Playlists queued with playnow will be reversed except for the first song', delete_after=60)

                message = await channel.send(f'Processing {size} songs')
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
                            message = await message.edit(s)
                        except asyncio.CancelledError:
                            await self.bot.delete_message(message)
                        except:
                            return

                    await message.delete()

                task = self.bot.loop.create_task(progress_info())

                async def _on_error(e):
                    try:
                        if not no_message:
                            await channel.send('Failed to process {}\n{}'.format(entry.get('title', entry.get['id']), e))
                    except discord.HTTPException:
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
                                await channel.send('Failed to process {}'.format(entry.get('title', entry['id'])))
                        except discord.HTTPException:
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
                    return await channel.send(msg, delete_after=60)

            else:
                await self._add_from_info(priority=priority, channel=channel,
                                          no_message=no_message, metadata=metadata, **info)

        finally:
            self.adding_songs = False

    async def add_from_song(self, song, priority=False, channel=None):
        await self._append_song(song, priority)
        if priority:
            await channel.send('Enqueued {} to the top of the queue'.format(song))
        else:
            await channel.send('Enqueued {}'.format(song))

    async def add_from_playlist(self, name, channel=None):
        if channel is None:
            channel = self.channel

        lines = read_lines(os.path.join(self.playlist_path, name))
        if lines is None:
            return await channel.send('Invalid playlist name')

        await channel.send('Processing {} songs'.format(len(lines)), delete_after=60)
        for line in lines:
            await self._add_url(line, no_message=True)

        await channel.send('Enqueued %s' % name)

    async def current_to_file(self, name=None, channel=None):
        if channel is None:
            channel = self.channel

        if name == 'autoplaylist.txt':
            return await channel.send('autoplaylist.txt is not a valid name')

        if not self.playlist:
            return await channel.send('Empty playlist', delete_after=60)
        lines = [song.webpage_url for song in self.playlist]

        if not name:
            name = 'playlist-{}'.format(timestamp())
        file = os.path.join(self.playlist_path, name)
        write_playlist(file, lines)
        await channel.send(f'Playlist {name} created')

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
        if channel is None:
            channel = self.channel

        if 'entries' in info:
            entries = info['entries']

            if entries[0]['ie_key'].lower() != 'youtube':
                await channel.send('Only youtube playlists are currently supported')
                return

            links = []
            url = 'https://www.youtube.com/watch?v=%s'
            for entry in entries:
                links.append(url % entry['id'])

            return links

    async def failed_info(self, e, channel=None):
        if channel is None:
            channel = self.channel
        await channel.send(f"Couldn't get the requested video\n{e}")

    async def _append_song(self, song, priority=False):
        if not self.playlist or priority:
            terminal.debug(f'Downloading {song.webpage_url}')
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

    async def get_from_url(self, url):
        song = Song(self, webpage_url=url, config=self.bot.config)
        terminal.debug(f'Downloading {song.webpage_url} from url')
        await song.download()
        await song.on_ready.wait()
        if not song.success:
            return
        return song

    async def get_from_autoplaylist(self):
        song = self.get_random_song('autoplaylist')
        if song is None:
            return

        song = Song(self, webpage_url=song, config=self.bot.config)
        terminal.debug(f'Downloading {song.webpage_url}')
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
            except AttributeError:
                terminal.exception('Error while checking playlist')

        return False

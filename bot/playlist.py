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
import json
import logging
import os
import random
import re
import time
from collections import deque

import discord
from validators import url as valid_url

from bot.downloader import Downloader
from bot.globals import CACHE, PLAYLISTS
from bot.paged_message import PagedMessage
from bot.song import Song
from utils.utilities import (read_lines, seconds2str)

terminal = logging.getLogger('terminal')

try:
    from numpy import delete as delete_by_indices
except ImportError:
    delete_by_indices = None
    terminal.warning('Numpy is not installed. Playlist can now only be cleared completely. No deletion by indexes')

logger = logging.getLogger('audio')


def validate_playlist_name(name):
    if not re.match(r'^[a-zA-Z0-9 ]*$', name):
        return False

    if len(name) > 100:
        return False

    return True


def validate_playlist(name, user_id):
    if not validate_playlist_name(name):
        return False

    p = os.path.join(PLAYLISTS, str(user_id), name)
    if not os.path.exists(p):
        return False

    return p


def load_playlist(name, user_id):
    p = validate_playlist(name, user_id)
    if not p:
        return False

    with open(p, 'r', encoding='utf-8') as f:
        songs = json.load(f)

    return songs


def write_playlist(data, name, user_id, overwrite=False):
    file = os.path.join(PLAYLISTS, str(user_id))
    if not os.path.exists(file):
        os.mkdir(file)
    file = os.path.join(file, name)

    if not overwrite and os.path.exists(file):
        return f'Filename {name} is already in use'

    with open(file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    if overwrite:
        return f'Playlist {name} edited'

    return f'Playlist {name} created'


async def create_playlist(songs, user, name, channel):
    if not validate_playlist_name(name):
        return await channel.send(f"{name} doesn't follow naming rules. Allowed characters are a-Z and 0-9 and max length is 100")

    if not songs:
        return await channel.send('Empty playlist. Playlist not created', delete_after=60)

    new_songs = []
    added = 0
    for song in songs:
        if not song.duration:
            await song.download(return_if_downloading=False)

            if not song.success:
                continue

        added += 1
        new_songs.append({'webpage_url': song.webpage_url, 'title': song.title,
                          'duration': song.duration})

    await channel.send(write_playlist(new_songs, name, user.id))


class Playlist:
    def __init__(self, bot, download=False, channel=None, downloader: Downloader=None):
        self.bot = bot
        self.channel = channel
        self.download = download
        self.playlist = deque()
        self.history = deque(maxlen=5)
        self.downloader = Downloader(CACHE) if not downloader else downloader
        self.not_empty = asyncio.Event()
        self.playlist_path = PLAYLISTS
        self.adding_songs = False

    def __iter__(self):
        return iter(self.playlist)

    async def shuffle(self):
        random.shuffle(self.playlist)
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

    async def cache_songs(self, amount_to_cache=4):
        cached = 0
        for idx, song in enumerate(self.playlist.copy()):
            if idx == 0:
                continue

            if cached >= amount_to_cache:
                break

            if song not in self.playlist:
                continue

            await song.download()
            if song.success is False:
                try:
                    # Song download failed completely. Remove it from the queue
                    self.playlist.remove(song)
                except ValueError:
                    pass

            cached += 1

    async def download_next(self):
        next_song = self.peek()
        if next_song is not None:
            await next_song.download()
            self.bot.loop.create_task(self.cache_songs())
        return next_song

    async def clear(self, indexes=None, channel=None):
        if indexes is None:
            self.playlist.clear()
            await self.send('Playlist cleared completely', channel)
            return True
        else:
            if delete_by_indices is not None:
                songs_left = delete_by_indices(list(self.playlist), indexes)
                self.playlist.clear()
                for song in songs_left:
                    self.playlist.append(song)
            else:
                terminal.warning('Numpy is not installed. Cannot delete songs by index')
                await self.send('Clearing by indices is not supported', channel)

            await self.send('Playlist cleared', channel)
            await self.cache_songs()
            return True

    def select_by_predicate(self, predicate):
        """
        Selects all songs that match the given predicate
        """
        selected = []
        for song in self.playlist:
            if predicate(song):
                selected.append(song)

        return selected

    def clear_by_predicate(self, predicate):
        """Clears songs from queue that match a predicate.
        Returns the amount of songs removed"""
        removed = self.select_by_predicate(predicate)
        for song in removed:
            try:
                self.playlist.remove(song)
            except ValueError:
                pass

        return len(removed)

    async def search(self, name, ctx, site='yt', priority=False, in_vc=True):
        search_keys = {'yt': 'ytsearch', 'sc': 'scsearch'}
        urls = {'yt': 'https://www.youtube.com/watch?v=%s'}
        max_results = 20
        search_key = search_keys.get(site, 'ytsearch')
        channel = ctx.message.channel
        query = '{0}{1}:{2}'.format(search_key, max_results, name)

        info = await self.downloader.extract_info(self.bot.loop, url=query, on_error=self.failed_info, download=False)
        if info is None or 'entries' not in info:
            return await self.send('Search gave no results', delete_after=60, channel=channel)

        url = urls.get(site, 'https://www.youtube.com/watch?v=%s')
        entries = info['entries']
        length = len(entries)
        paged = PagedMessage(entries, stop='❌', accept='✅')
        emoji = ('◀', '▶', '✅', '❌')

        def get_url(entry):
            if entry.get('id') is None:
                new_url = entry.get('url')
            else:
                new_url = url % entry['id']

            return new_url

        def get_page(entry, idx):
            new_url = get_url(entry)
            return f'{new_url} {idx+1}/{length}'

        entry = entries[0]
        try:
            message = await ctx.channel.send(get_page(entry, 0))
        except discord.HTTPException:
            return

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

            entry = paged.reaction_changed(*result)
            if entry is PagedMessage.INVALID:
                continue

            if entry is PagedMessage.DELETE:
                await message.delete()
                return

            if entry is PagedMessage.VALID:
                if in_vc:
                    entry = paged.current_page
                    await message.delete()
                    await self._add_url(get_url(entry), priority=priority,
                                        channel=channel, requested_by=ctx.author)

                return

            try:
                await message.edit(content=get_page(entry, paged.index))
                # Wait for a bit so the bot doesn't get ratelimited from reaction spamming
                await asyncio.sleep(1)
            except discord.HTTPException:
                return

    async def _add_from_info(self, channel=None, priority=False, no_message=False, metadata=None, **info):
        try:
            if metadata is None:
                metadata = {}

            fname = self.downloader.safe_ytdl.prepare_filename(info)
            song = Song(playlist=self, filename=fname, config=self.bot.config, **metadata)
            song.info_from_dict(**info)
            await self._append_song(song, priority)

            if not no_message:
                await self.send(f'Enqueued {song.title}', delete_after=20, channel=channel)

        except Exception as e:
            logger.exception('Could not add song')
            return await self.send(f'Error\n{e}', channel=channel)

    async def _add_url(self, url, channel=None, no_message=False, priority=False, **metadata):
        on_error = functools.partial(self.failed_info, channel=channel)
        info = await self.downloader.extract_info(self.bot.loop, url=url, download=False, on_error=on_error)
        if info is None:
            return
        await self._add_from_info(channel=channel, priority=priority,
                                  no_message=no_message, metadata=metadata, **info)

    async def add_songs(self, entries, title, maxlen, priority=False, channel=None,
                        no_message=False, base_url='https://www.youtube.com/watch?v=%s', **metadata):
        """
        Add multiple songs to the queue
        entries must be a list of dicts with id set to the part that will be
        formatted to base url. if you want to provide arbitrary links you can
        use "%s" as base url and entries is a list of dicts with the id key
        set to the wanted url
        """
        size = len(entries)
        if size > maxlen >= 0:  # Max playlist size
            await self.send(f'Playlist is too big. Max size is {maxlen}', channel=channel)
            return

        url = base_url
        if priority:
            await self.send('Playlists queued with playnow will be reversed except for the first song',
                            delete_after=60, channel=channel)

        message = await self.send(f'Processing {size} songs', channel=channel)
        t = time.time()
        songs = deque()
        first = True
        progress = 0

        async def progress_info():
            nonlocal message
            if message is None:
                return

            while progress <= size:
                try:
                    await asyncio.sleep(3)
                    t2 = time.time() - t
                    eta = progress / t2
                    if eta == 0:
                        eta = 'Undefined'
                    else:
                        eta = seconds2str(max(size / eta - t2, 0))

                    s = 'Loading playlist. Progress {}/{} {:.02%} \nETA {}'.format(progress, size, progress/size, eta)
                    await message.edit(content=s)
                except asyncio.CancelledError:
                    await message.delete()
                    return
                except discord.ClientException:
                    logger.exception('Failed to post progress')
                    return

            await message.delete()

        task = self.bot.loop.create_task(progress_info())

        async def _on_error(e):
            try:
                if not no_message:
                    await channel.send('Failed to process {}'.format(entry.get('id')))
            except discord.HTTPException:
                pass

            return False

        for entry in entries:
            progress += 1

            info = await self.downloader.extract_info(self.bot.loop,
                                                      url=url % entry['id'],
                                                      download=False,
                                                      on_error=_on_error)
            if info is False or info is None:
                continue

            if not info:
                try:
                    if not no_message:
                        await channel.send('Failed to process {}'.format(entry.get('id')))
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
            return await self.send(msg, delete_after=60, channel=channel)

    async def add_song(self, name, no_message=False, maxlen=30, priority=False,
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
                    return await self.send('No songs found or a problem with YoutbeDL that I cannot fix :(', channel=channel)
                return

            if 'entries' in info:
                if info['entries'][0]['ie_key'].lower() != 'youtube':
                    await self.send('Only youtube playlists are currently supported',
                                    channel=channel)
                    return

                await self.add_songs(info['entries'], info['title'], maxlen, priority, channel, no_message, **metadata)

            else:
                await self._add_from_info(priority=priority, channel=channel,
                                          no_message=no_message, metadata=metadata, **info)

        finally:
            self.adding_songs = False

    async def add_from_song(self, song, priority=False, channel=None):
        await self._append_song(song, priority)
        if priority:
            await self.send('Enqueued {} to the top of the queue'.format(song), channel=channel)
        else:
            await self.send('Enqueued {}'.format(song), channel=channel)

    async def add_from_partials(self, songs, user, channel):
        await self.send('Processing {} songs'.format(len(songs)), delete_after=60, channel=channel)
        added = 0
        for song in songs:
            song = Song.from_partial(self, self.bot.config, song)
            song.requested_by = user
            if await self._append_song(song) is not False:
                added += 1

        return added

    async def add_from_playlist(self, user, name, channel=None, shuffle=True, author=None):
        if channel is None:
            channel = self.channel

        songs = load_playlist(name, user.id)
        if songs is False:
            return False

        await self.send('Processing {} songs'.format(len(songs)), delete_after=60, channel=channel)
        added = 0

        if shuffle:
            random.shuffle(songs)

        requested_by = author or user
        for song in songs:
            song = Song(self, config=self.bot.config, **song, requested_by=requested_by)
            if await self._append_song(song) is not False:
                added += 1

        await self.send(f'Enqueued {added} songs from playlist {name}', channel=channel)
        return True

    async def _search(self, name, **kwargs):
        info = await self.downloader.extract_info(self.bot.loop, extract_flat=False, url=name, download=False, **kwargs)
        if info and 'entries' in info:
            return info['entries'][0]

    def on_stop(self):
        if self.peek() is not None:
            self.bot.loop.call_soon_threadsafe(self.not_empty.set)
        else:
            self.not_empty.clear()

    async def extract_info(self, name, on_error=None):
        return await self.downloader.extract_info(self.bot.loop, url=name, download=False, on_error=on_error)

    @staticmethod
    async def process_playlist(info, channel=None):
        if 'entries' in info:
            entries = info['entries']

            if entries[0]['ie_key'].lower() != 'youtube':
                if channel:
                    await channel.send('Only youtube playlists are currently supported')
                return

            links = []
            url = 'https://www.youtube.com/watch?v=%s'
            for entry in entries:
                links.append(url % entry['id'])

            return links

    async def failed_info(self, e, channel=None):
        await self.send(f"Couldn't get the requested video\n{e}", channel=channel)

    async def _append_song(self, song, priority=False):
        if not self.playlist or priority:
            terminal.debug(f'Downloading {song.webpage_url}')
            success = await song.download()

            # When success is None the song was already downloaded
            if success is False:
                return False

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
            return False
        return song

    def get_random_song(self, playlist):
        songs = self._get_playlist(playlist + '.txt')
        if songs is None:
            return
        return random.choice(songs)

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

    async def send(self, message, channel=None, **kwargs):
        if channel is None:
            channel = self.channel

        try:
            return await channel.send(message, **kwargs)
        except discord.HTTPException:
            pass

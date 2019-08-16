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
import random
import re
import shutil
from collections import deque
from functools import partial
from math import floor
from random import choice
from typing import Optional

import discord
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType

from bot import player
from bot.bot import command, cooldown, group
from bot.converters import TimeDelta
from bot.downloader import Downloader
from bot.globals import ADD_AUTOPLAYLIST, DELETE_AUTOPLAYLIST
from bot.globals import Auth
from bot.player import get_track_pos, MusicPlayer, format_time
from bot.playlist import (Playlist, validate_playlist_name, load_playlist,
                          create_playlist, validate_playlist, write_playlist,
                          PLAYLISTS)
from bot.song import Song, PartialSong
from utils.utilities import (mean_volume, search, parse_seek,
                             seek_from_timestamp,
                             send_paged_message, basic_check,
                             format_timedelta, test_url, wait_for_words)

try:
    import aubio
except ImportError:
    aubio = None


logger = logging.getLogger('audio')
terminal = logging.getLogger('terminal')


def check_who_queued(user):
    """
    Returns a function that checks if the song was requested by user
    """
    def pred(song):
        if song.requested_by and song.requested_by.id == user.id:
            return True

        return False

    return pred


def check_duration(sec, larger=True):
    """
    Creates a function you can use to check songs
    Args:
        sec:
            duration that we compare to in seconds
        larger:
            determines if we do a larger than operation

    Returns:
        Function that can be used to check songs
    """
    def pred(song):
        if larger:
            if song.duration > sec:
                return True
        else:
            if song.duration < sec:
                return True

        return False

    return pred


def select_by_predicate(songs, pred):
    selected = []
    for song in songs:
        if pred(song):
            selected.append(song)

    return selected


def playlist2partialsong(songs):
    return [PartialSong(**song) for song in songs]


class MusicPlayder:
    def __init__(self, bot, stop_state):
        raise NotImplementedError('Deprecated')
        self.play_next_song = asyncio.Event()  # Trigger for next song
        self.right_version = asyncio.Event()  # Determines if right version be played
        self.right_version_playing = asyncio.Event()
        self.voice = None  # Voice channel that this is connected to
        self.current = None  # Current song
        self.channel = None  # Channel where all the automated messages will be posted to
        self.server = None
        self.activity_check = None
        self.gachi = bot.config.gachi
        self.bot = bot
        self.audio_player = None  # Main audio loop. Gets set when summon is called in :create_audio_task:
        self.volume = self.bot.config.default_volume
        self.playlist = Playlist(bot, download=True)
        self.autoplaylist = bot.config.autoplaylist
        self.volume_multiplier = bot.config.volume_multiplier
        self.messages = deque()
        self.stop = stop_state

    def is_playing(self):
        if self.voice is None or self.current is None or self.player is None:
            return False

        return not self.player.is_done()

    def reload_voice(self, voice_client):
        self.voice = voice_client
        if self.player:
            self.player.player = voice_client.play_audio
            self.player._resumed.clear()
            self.player._connected.set()

    async def websocket_check(self):
        terminal.debug("Creating websocket check loop")
        logger.debug("Creating websocket check loop")

        while self.voice is not None:
            try:
                self.voice.ws.ensure_open()
                assert self.voice.ws.open
            except:
                terminal.debug("Voice websocket is %s, reconnecting" % self.voice.ws.state_name)
                logger.debug("Voice websocket is %s, reconnecting" % self.voice.ws.state_name)
                await self.bot.reconnect_voice_client(self.voice.channel.server)
                await asyncio.sleep(4)
            finally:
                await asyncio.sleep(1)

    def create_audio_task(self):
        self.audio_player = self.bot.loop.create_task(self.play_audio())
        self.activity_check = self.bot.loop.create_task(self._activity_check())
        # self.bot.loop.create_task(self.websocket_check())

    @property
    def player(self):
        return self.current.player

    def on_stop(self):
        if self.right_version.is_set():
            if self.current.seek:
                return
            elif not self.current.seek:
                self.bot.loop.call_soon_threadsafe(self.right_version_playing.set)
            return
        elif self.current.seek:
            return

        self.bot.loop.create_task(self.delete_current())

        self.bot.loop.call_soon_threadsafe(self.play_next_song.set)
        self.playlist.on_stop()

    async def delete_current(self):
        if self.current is not None and self.bot.config.delete_after and not self.playlist.in_list(self.current.webpage_url):
            await self.current.delete_file()

    async def wait_for_right_version(self):
        await self.right_version_playing.wait()

    async def wait_for_not_empty(self):
        await self.playlist.not_empty.wait()

    async def set_mean_volume(self, file):
        try:
            db = await asyncio.wait_for(mean_volume(file, self.bot.loop, self.bot.threadpool,
                                        duration=self.current.duration), timeout=20, loop=self.bot.loop)
            if db is not None and abs(db) >= 0.1:
                volume = self._get_volume_from_db(db)
                self.current.player.volume = volume

        except asyncio.TimeoutError:
            logger.debug('Mean volume timed out')
        except asyncio.CancelledError:
            pass

    async def _wait_for_next_song(self):
        try:
            await asyncio.wait_for(self.wait_for_not_empty(), 1, loop=self.bot.loop)
            logger.debug('Play was called on empty playlist. Waiting for download')
            self.current = await self.playlist.next_song()
            if self.current is not None:
                logger.debug(str(self.current.__dict__))
            else:
                logger.debug('Current is None')

        except asyncio.TimeoutError:
            logger.debug('Got TimeoutError. adding_songs = {}'.format(self.playlist.adding_songs))
            if self.autoplaylist and not self.playlist.adding_songs:
                song_ = await self.playlist.get_from_autoplaylist()

                if song_ is None:
                    terminal.warning('None returned from get_from_autoplaylist. Waiting for next song')
                    return None

                else:
                    self.current = song_

            else:
                try:
                    await asyncio.wait_for(self.wait_for_not_empty(), 5, loop=self.bot.loop)
                except asyncio.TimeoutError:
                    return None

                await self.playlist.not_empty.wait()
                self.current = await self.playlist.next_song()

        return self.current

    def _get_volume_from_db(self, db):
        rms = pow(10, db / 20) * 32767
        return 1 / rms * self.volume_multiplier

    async def _activity_check(self):
        async def stop():
            await self.stop(self)
            self.voice = None

        while True:
            await asyncio.sleep(60)
            if self.voice is None:
                return await stop()

            users = self.voice.channel.voice_members
            users = list(filter(lambda x: not x.bot, users))
            if not users:
                await self.say('No voice activity. Disconnecting')
                await stop()
                return

    async def play_audio(self):
        while True:
            self.play_next_song.clear()
            if self.voice is None:
                break

            if self.current is None or not self.current.seek:
                if self.playlist.peek() is None:
                    if self.autoplaylist:
                        self.current = await self.playlist.get_from_autoplaylist()
                    else:
                        continue
                else:
                    self.current = await self.playlist.next_song()

                if self.current is None:
                    continue

                logger.debug('Next song is {}'.format(self.current))
                logger.debug('Waiting for dl')

                try:
                    await asyncio.wait_for(self.current.on_ready.wait(), timeout=6,
                                           loop=self.bot.loop)
                except asyncio.TimeoutError:
                    self.playlist.playlist.appendleft(self.current)
                    continue

                logger.debug('Done waiting')
                if not self.current.success:
                    terminal.error('Download unsuccessful')
                    continue

                if self.current.filename is not None:
                    file = self.current.filename
                elif self.current.url != 'None':
                    file = self.current.url
                else:
                    terminal.error('No valid file to be played')
                    continue

                logger.debug('Opening file with the name "{0}" and options "{1.before_options}" "{1.options}"'.format(file, self.current))

                self.current.player = self.voice.create_ffmpeg_player(file,
                                                                      after=self.on_stop,
                                                                      before_options=self.current.before_options,
                                                                      options=self.current.options)

            if self.bot.config.auto_volume and not self.current.seek and isinstance(file, str) and not self.current.is_live:
                volume_task = asyncio.ensure_future(self.set_mean_volume(file))
            else:
                volume_task = None

            self.current.player.volume = self.volume

            if not self.current.seek:
                dur = get_track_pos(self.current.duration, 0)
                s = 'Now playing **{0.title}** {1} with volume at {2:.0%}'.format(self.current, dur, self.current.player.volume)
                if self.current.requested_by:
                    s += ' enqueued by %s' % self.current.requested_by
                await self.say(s, self.current.duration)

            logger.debug(self.player)
            self.current.player.start()
            logger.debug('Started player')
            await self.change_status(self.current.title)
            logger.debug('Downloading next')
            await self.playlist.download_next()

            if self.gachi and not self.current.seek and random.random() < 0.01:
                await self.prepare_right_version()

            self.current.seek = False
            await self.play_next_song.wait()
            if volume_task is not None:
                volume_task.cancel()
                volume_task = None
            self.right_version_playing.clear()

    async def prepare_right_version(self):
        if self.gachi:
            return

        self.bot.loop.call_soon_threadsafe(self.right_version.set)

        try:
            await asyncio.wait_for(self.wait_for_right_version(), self.current.duration * 0.8)
        except asyncio.TimeoutError:
            pass

        file = self._get_right_version()
        if file is None:
            return

        vol = self._get_volume_from_db(await mean_volume(file, self.bot.loop, self.bot.threadpool, duration=self.current.duration))
        self.current.player.stop()
        self.current.player = self.voice.create_ffmpeg_player(file,
                                                              after=self.on_stop,
                                                              options=self.current.options)

        self.current.player.volume = vol + 0.05
        await self.change_status('Right version gachiGASM')
        self.current.player.start()
        self.right_version.clear()

    @staticmethod
    def _get_right_version():
        path = os.path.join(os.getcwd(), 'data', 'audio', 'right_versions')
        files = os.listdir(path)
        return os.path.join(path, random.choice(files))

    async def change_status(self, name):
        if self.bot.config.now_playing:
            await self.bot.change_presence(game=Game(name=name))

    async def skip(self, author):
        if self.is_playing():

            if self.right_version.is_set():
                self.bot.loop.call_soon_threadsafe(self.right_version_playing.set)
                return

            if self.right_version_playing.is_set():
                author = author.mention
                await ctx.send('FUCK YOU! %s' % author)
                return

            self.player.stop()

    async def say(self, message, timeout=None, channel=None):
        if channel is None:
            channel = self.channel

        return await self.bot.send_message(channel, message, delete_after=timeout)


class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.musicplayers = self.bot.playlists
        self.viewed_playlists = self.bot.viewed_playlists
        self.downloader = Downloader()

    def get_musicplayer(self, guild_id: int, is_on: bool=True):
        """
        Gets the musicplayer for the guild if it exists
        Args:
            guild_id (int): id the the guild
            is_on (bool):
                If set on will only accept a musicplayer which has been initialized
                and is ready to play without work. If it finds unsuitable target
                it will destroy it and recursively call this function again

        Returns:
            MusicPlayer: If musicplayer was found
                         else None
        """
        musicplayer = self.musicplayers.get(guild_id)
        if musicplayer is None:
            musicplayer = self.find_musicplayer_from_garbage(guild_id)

            if is_on and musicplayer is not None and not musicplayer.is_alive():
                MusicPlayer.__instances__.discard(musicplayer)
                musicplayer.selfdestruct()
                del musicplayer
                return self.get_musicplayer(guild_id)

        return musicplayer

    def find_musicplayer_from_garbage(self, guild_id):
        for obj in MusicPlayer.get_instances():
            if obj.channel.guild.id == guild_id:
                self.musicplayers[guild_id] = obj
                return obj

    async def check_player(self, ctx):
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer is None:
            terminal.error('Playlist not found even when voice is playing')
            await ctx.send(f'No playlist found. Use {ctx.prefix}force_stop to reset voice state')

        return musicplayer

    @staticmethod
    def parse_seek(string: str):
        """Kept for archival purposes"""
        raise NotImplementedError('Use utils.utilities.parse_seek instead')
        hours = '00'
        minutes = '00'
        seconds = '00'
        ms = '00'

        # If we have m or s 2 time in the string this doesn't work so
        # we replace the ms with a to circumvent this.
        string = string.replace('ms', 'a')

        if 'h' in string:
            hours = string.split('h')[0]
            string = ''.join(string.split('h')[1:])
        if 'm' in string:
            minutes = string.split('m')[0].strip()
            string = ''.join(string.split('m')[1:])
        if 's' in string:
            seconds = string.split('s')[0].strip()
            string = ''.join(string.split('s')[1:])
        if 'a' in string:
            ms = string.split('a')[0].strip()

        return '-ss {0}:{1}:{2}.{3}'.format(hours.zfill(2), minutes.zfill(2),
                                            seconds.zfill(2), ms)

    @staticmethod
    def _parse_filters(options: str, filter_name: str, value: str, remove=False):
        logger.debug('Parsing filters: {0}, {1}, {2}'.format(options, filter_name, value))
        if remove:
            matches = re.findall(r'("|^|, )({}=.+?)(, |"|$)'.format(filter_name), options)
        else:
            matches = re.findall(r'(?: |"|^|,)({}=.+?)(?:, |"|$)'.format(filter_name), options)
        logger.debug('Filter matches: {}'.format(matches))

        if remove:
            if not matches:
                return options
            matches = matches[0]
            if matches.count(' ,') == 2:
                options = options.replace(''.join(matches), ', ')

            elif matches[0] == '"':
                options = options.replace(''.join(matches[1]), '')
            elif matches[2] == '"':
                options = options.replace(''.join(matches[:2]), '')
            else:
                options = options.replace(''.join(matches), '')
            if '-filter:a ""' in options:
                options = options.replace('-filter:a ""', '')

            return options

        if matches:
            return options.replace(matches[0].strip(), '{0}={1}'.format(filter_name, value))

        else:
            filt = '{0}={1}'.format(filter_name, value)
            logger.debug('Filter value set to {}'.format(filt))
            if '-filter:a "' in options:
                bef_filt, aft_filt = options.split('-filter:a "', 2)
                logger.debug('before and after filter. "{0}", "{1}"'.format(bef_filt, aft_filt))
                options = '{0}-filter:a "{1}, {2}'.format(bef_filt, filt, aft_filt)

            else:
                options += ' -filter:a "{0}"'.format(filt)

            return options

    @staticmethod
    async def check_voice(ctx, user_connected=True):
        if ctx.voice_client is None:
            await ctx.send('Not connected to a voice channel')
            return False

        if user_connected and not ctx.author.voice:
            await ctx.send("You aren't connected to a voice channel")
            return False

        elif user_connected and ctx.author.voice.channel.id != ctx.voice_client.channel.id:
            await ctx.send("You aren't connected to this bot's voice channel")
            return False

        return True

    async def get_player_and_check(self, ctx):
        if not await self.check_player(ctx):
            return

        musicplayer = await self.check_player(ctx)

        return musicplayer

    @command(no_pm=True, aliases=['a'])
    @cooldown(1, 4, type=BucketType.guild)
    async def again(self, ctx):
        """Queue the currently playing song to the end of the queue"""
        await self._again(ctx)

    @command(aliases=['q', 'queue_np'], no_pm=True)
    @cooldown(1, 3, type=BucketType.guild)
    async def queue_now_playing(self, ctx):
        """Queue the currently playing song to the start of the queue"""
        await self._again(ctx, True)

    async def _again(self, ctx, priority=False):
        """
        Args:
            ctx: class Context
            priority: If true song is added to the start of the playlist

        Returns:
            None
        """
        if not await self.check_voice(ctx):
            return

        if not ctx.voice_client.is_playing():
            return await ctx.send('Not playing anything')

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        await musicplayer.playlist.add_from_song(Song.from_song(musicplayer.current), priority,
                                              channel=ctx.channel)

    @commands.cooldown(2, 3, type=BucketType.guild)
    @command(no_pm=True)
    async def seek(self, ctx, *, where: str):
        """
        If the video is cached you can seek it using this format h m s ms,
        where at least one of them is required. Milliseconds must be zero padded
        so to seek only one millisecond put 001ms. Otherwise the song will just
        restart. e.g. 1h 4s and 2m1s3ms both should work.
        """

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None or not ctx.voice_client.is_playing():
            return await ctx.send('Not playing anything')

        seek = parse_seek(where)
        if seek is None:
            return ctx.send('Invalid time string')

        await self._seek(musicplayer, current, seek)

    async def _seek(self, musicplayer, current, seek_dict, options=None,
                    speed=None):
        """
        
        Args:
            current: The song that we want to seek

            seek_dict: A command that is passed to before_options

            options: passed to create_ffmpeg_player options
        Returns:
            None
        """
        if options is None:
            options = current.options

        logger.debug('Seeking with dict {0} and these options: before_options="{1}", options="{2}"'.format(seek_dict, current.before_options, options))

        await current.validate_url(self.bot.aiohttp_client)
        musicplayer.player.seek(current.filename, seek_dict, before_options=current.before_options, options=options, speed=speed)

    async def _parse_play(self, string, ctx, metadata=None):
        options = {}
        filters = []
        if metadata and 'filter' in metadata:
            fltr = metadata['filter']
            if isinstance(fltr, str):
                filters.append(fltr)
            else:
                filters.extend(fltr)

        song_name = string

        if filters:
            options['options'] = '-filter:a "{}"'.format(', '.join(filters))

        if metadata is not None:
            for key in options:
                if key in metadata:
                    logger.debug('Setting metadata[{0}] to {1} from {2}'.format(key, options[key], metadata[key]))
                    metadata[key] = options[key]
                else:
                    logger.debug('Added {0} with value {1} to metadata'.format(key, options[key]))
                    metadata[key] = options[key]
        else:
            metadata = options

        if 'requested_by' not in metadata:
            metadata['requested_by'] = ctx.author

        logger.debug('Parse play returned {0}, {1}'.format(song_name, metadata))
        return song_name, metadata

    @command(enabled=False, hidden=True)
    async def sfx(self, ctx):
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        musicplayer.player.source2 = player.FFmpegPCMAudio('file', reconnect=False)

    @command(no_pm=True)
    @commands.cooldown(1, 3, type=BucketType.user)
    async def play(self, ctx, *, song_name: str):
        """Put a song in the playlist. If you put a link it will play that link and
        if you put keywords it will search youtube for them"""
        return await self.play_song(ctx, song_name)

    async def summon_checks(self, ctx):
        if not ctx.author.voice:
            await ctx.send('Not connected to a voice channel')
            return None, None

        if ctx.voice_client and ctx.voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send('Not connected to the same channel as the bot')
            return None, None

        success = False
        if ctx.voice_client is None:
            success = await self._summon(ctx, create_task=False)
            if not success:
                terminal.debug('Failed to join vc')
                return None, None

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return None, None

        return musicplayer, success

    async def play_song(self, ctx, song_name, priority=False, **metadata):
        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        song_name, metadata = await self._parse_play(song_name, ctx, metadata)

        maxlen = -1 if ctx.author.id == self.bot.owner_id else 20
        await musicplayer.playlist.add_song(song_name, maxlen=maxlen,
                                            channel=ctx.message.channel,
                                            priority=priority, **metadata)
        if success:
            musicplayer.start_playlist()

    @command(no_pm=True, aliases=['play_p', 'pp'])
    @cooldown(1, 10, BucketType.user)
    async def play_playlist(self, ctx, user: Optional[discord.User], *, name):
        """Queue a saved playlist in random order"""
        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        user = user if user else ctx.author
        if not await musicplayer.playlist.add_from_playlist(user, name, ctx.channel):
            await ctx.send(f"Couldn't find playlist {name} of user {user} or playlist was empty")

        if success:
            musicplayer.start_playlist()

    @command(no_pm=True, aliases=['prp', 'pr'])
    @cooldown(1, 5, BucketType.user)
    async def play_random_playlist(self, ctx, user: Optional[discord.User], *, name):
        """Queue a random song from given playlist"""
        songs = await self.get_playlist(ctx, user, name)
        if songs is False:
            return

        song = choice(songs)
        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        song = Song(musicplayer.playlist, config=self.bot.config, **song,
                    requested_by=ctx.author)

        await musicplayer.playlist.add_from_song(song, channel=ctx.channel)
        if success:
            musicplayer.start_playlist()

    @command(no_pm=True, aliases=['pvp', 'pv'])
    @cooldown(1, 5)
    async def play_viewed_playlist(self, ctx):
        """
        Enqueues all the songs from the last playlist you viewed.
        You can use this to filter playlist and add songs based on that filter
        """
        songs = self.viewed_playlists.get(ctx.author.id, None)
        if not songs:
            await ctx.send("You haven't viewed any playlists. Use `view_playlist` "
                           "or any of it's subcommands then use this command to add those songs to the list")
            return

        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        self.viewed_playlists.pop(ctx.author.id, None)

        songs[1].cancel()
        name = songs[2]
        songs = songs[0]

        added = await musicplayer.playlist.add_from_partials(songs, ctx.author, ctx.channel)

        await ctx.send(f'Enqueued {added} songs from {name}')

        if success:
            musicplayer.start_playlist()

    async def _process_links(self, ctx, links, max_size=30):
        max_size = max_size if ctx.author.id != self.bot.owner_id else 999
        songs = links
        failed = []
        new_songs = []
        song = None

        def on_error(_):
            nonlocal song
            failed.append(song.replace('@', '@\u200b'))

        for song in songs:
            if len(new_songs) >= max_size:
                await ctx.send(f'Playlist filled (max size {max_size}) before all songs could be processed. Latest processed song was {new_songs[-1].webpage_url}')
                break

            if not test_url(song):
                failed.append(song.replace('@', '@\u200b'))
                continue

            info = await self.downloader.extract_info(self.bot.loop,
                                                      url=song,
                                                      download=False,
                                                      on_error=on_error)
            if not info:
                await ctx.send('Nothing found or error')
                return

            if 'entries' in info:
                # Link was a playlist so we process it as one
                entries = await Playlist.process_playlist(info, channel=ctx.channel)
                if not entries:
                    failed.append(song.replace('@', '@\u200b'))
                    continue

                def error(_):
                    nonlocal entry
                    failed.append(entry)

                infos = []
                for entry in entries:
                    info = await self.downloader.extract_info(self.bot.loop,
                                                              url=entry,
                                                              download=False,
                                                              on_error=error)
                    if info is None:
                        continue

                    infos.append(info)

                    # If total amount of songs after adding this is more
                    # than max we stop adding them. This is because you could
                    # bypass max_size by using playlists.
                    if len(new_songs) + len(infos) >= max_size:
                        break

            else:
                infos = [info]

            for info in infos:
                new_songs.append(Song(webpage_url=info['webpage_url'],
                                      title=info.get('title'),
                                      duration=info.get('duration')))

        return new_songs, failed

    # TODO Add subcommands to add from queue but with a filter
    @command(no_pm=True, aliases=['atp'])
    @cooldown(1, 20, BucketType.user)
    async def add_to_playlist(self, ctx, playlist_name, *, song_links):
        """
        Adds songs to the given playlist.
        If the keyword queue is given as in `{prefix}{name} queue` it will
        add the current queue to the playlist. There is no limit to the max added
        songs with this method.

        Otherwise you can give it links to songs or playlists and it'll add
        those to the playlist. Max amount of songs added this way is 30
        """
        songs = load_playlist(playlist_name, ctx.author.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name}")
            ctx.command.reset_cooldown(ctx)
            return

        if song_links.lower().strip(' \n') == 'queue':
            musicplayer = self.get_musicplayer(ctx.guild.id)
            if not musicplayer or musicplayer.player is None or musicplayer.current is None:
                ctx.command.reset_cooldown(ctx)
                await ctx.send('No songs currently in queue')
                return

            new_songs = list(musicplayer.playlist.playlist)
            if musicplayer.current:
                new_songs.append(musicplayer.current)

            await ctx.send('Getting song infos for playlist')
            added = 0
            for song in new_songs:
                if not song.duration:
                    await song.download(return_if_downloading=False)

                if not song.success:
                    continue

                added += 1
                songs.append({'webpage_url': song.webpage_url, 'title': song.title,
                              'duration': song.duration})

        else:
            await ctx.send('Getting song infos for playlist')
            new_songs, failed = await self._process_links(ctx, song_links.replace('\n', ' ').split(' '))

            if failed:
                await ctx.send('Failed to add %s' % ', '.join(failed))

            if not new_songs:
                return

            added = len(new_songs)
            for song in new_songs:
                songs.append({'webpage_url': song.webpage_url, 'title': song.title,
                              'duration': song.duration})

        s = write_playlist(songs, playlist_name, ctx.author.id, overwrite=True)
        await ctx.send(f'{s}\nAdded {added} songs')

    @command(no_pm=True, aliases=['dp', 'drp'])
    @cooldown(1, 5, BucketType.user)
    async def delete_from_playlist(self, ctx, playlist_name, *song_links):
        """Delete the given links from the playlist.
        If no links are given will delete the currently playing song.
        There is no limit to how many links can be deleted from a playlist at once
        other than discords maximum character limit"""

        songs = load_playlist(playlist_name, ctx.author.id)

        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name}")
            ctx.command.reset_cooldown(ctx)
            return

        if not song_links:
            musicplayer = self.get_musicplayer(ctx.guild.id)
            if not musicplayer or musicplayer.player is None or musicplayer.current is None:
                ctx.command.reset_cooldown(ctx)
                await ctx.send('No songs currently in queue')
                return

            song_links = [musicplayer.current.webpage_url]

        song_links = set(song_links)
        old_len = len(songs)  # Used to check how many songs were deleted
        songs = list(filter(lambda song: song['webpage_url'] not in song_links, songs))

        deleted = old_len - len(songs)
        s = write_playlist(songs, playlist_name, ctx.author.id, overwrite=True)
        await ctx.send(f'{s}\nDeleted {deleted} song(s)')

    @command(no_pm=True, aliases=['crp'])
    @cooldown(1, 20, BucketType.user)
    async def create_playlist(self, ctx, *, name):
        """
        Create a playlist from the current queue or from links you pass after the prompt.
        When creating a playlist from current queue there is no limit to song amount
        """
        if not validate_playlist_name(name):
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(f"{name} doesn't follow naming rules. Allowed characters are a-Z and 0-9 and max length is 100")

        await ctx.send('What would you like the contents of the playlist to be\nFor current music queue say `yes` otherwise post all the links you want in your playlist. Max amount of self posted links is 30')

        try:
            msg = await self.bot.wait_for('message', check=basic_check(ctx.author, ctx.channel), timeout=60)
        except asyncio.TimeoutError:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send('Took too long.')

        if msg.content.lower() == 'yes':
            musicplayer = self.get_musicplayer(ctx.guild.id)
            if not musicplayer or musicplayer.player is None or musicplayer.current is None:
                ctx.command.reset_cooldown(ctx)
                await ctx.send('No songs currently in queue')

            songs = list(musicplayer.playlist.playlist)
            if musicplayer.current:
                songs.append(musicplayer.current)

            await ctx.send('Getting song infos for playlist')
            await create_playlist(songs, ctx.author, name, channel=ctx.channel)

        else:
            await ctx.send('Getting song infos for playlist')
            new_songs, failed = await self._process_links(ctx, msg.content.replace('\n', ' ').split(' '))

            if new_songs:
                await create_playlist(new_songs, ctx.author, name, ctx.channel)

            if failed:
                await ctx.send('Failed to add %s' % ', '.join(failed))

    @command(no_pm=True, aliases=['cop'])
    @cooldown(1, 20, BucketType.user)
    async def copy_playlist(self, ctx, user: Optional[discord.User], name, *, new_name):
        """
        Copy a playlist to your own playlists with a name
        Usage:
        `{prefix}{name} User#1234 "name of playlist" name of new playlist`
        """

        user = user if user else ctx.author
        src = validate_playlist(name, user.id)
        if src is False:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"Couldn't find playlist {name} of user {user}")
            return

        if not validate_playlist_name(new_name):
            ctx.command.reset_cooldown(ctx)
            return await ctx.send(f"{new_name} doesn't follow naming rules. Allowed characters are a-Z and 0-9 and max length is 100")

        dst = os.path.join(PLAYLISTS, str(user.id))
        if not os.path.exists(dst):
            os.mkdir(dst)
        dst = os.path.join(dst, new_name)

        if os.path.exists(dst):
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f'Filename {name} is already in use')
            return

        try:
            shutil.copyfile(src, dst)
        except OSError:
            logger.exception('failed to copy playlist')
            await ctx.send('Failed to copy playlist. Try again later')
            return

        await ctx.send(f'Successfully copied playlist {name} to {new_name}')

    @staticmethod
    async def get_playlist(ctx, user, name):
        user = user if user else ctx.author
        songs = load_playlist(name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {name} of user {user}")

        return songs

    def add_viewed_playlist(self, user, playlist, name):
        async def pop_list():
            await asyncio.sleep(60)
            self.viewed_playlists.pop(user.id, None)

        if user.id in self.viewed_playlists:
            self.viewed_playlists[user.id][1].cancel()

        task = asyncio.run_coroutine_threadsafe(pop_list(), loop=self.bot.loop)
        self.viewed_playlists[user.id] = (playlist, task, name)

    @command(no_pm=True, aliases=['lp'])
    @cooldown(1, 5, BucketType.user)
    async def list_playlists(self, ctx, *, user: discord.User = None):
        """
        List all the names of the playlists a user own.
        If user is not provided defaults to you
        """
        user = user if user else ctx.author
        p = os.path.join(PLAYLISTS, str(user.id))

        if not os.path.exists(p):
            return await ctx.send(f"{user} doesn't have any playlists")

        try:
            playlists = os.listdir(p)
        except OSError:
            logger.exception(f'Failed to list playlists of {user.id}')
            await ctx.send('Failed to get playlists because of an error')
            return

        if not playlists:
            return await ctx.send(f"{user} doesn't have any playlists")

        await ctx.send(f'Playlists of {user}\n\n' + '\n'.join(playlists))

    @group(no_pm=True, aliases=['vp'], invoke_without_command=True)
    @cooldown(1, 5, BucketType.user)
    async def view_playlist(self, ctx, user: Optional[discord.User], *, name):
        """
        Get the contents of one of your playlists or someone else's playlists
        Usage
        `{prefix}{name} [user] name of playlist`
        where [user] is replaced with the user who owns the playlist.
        User is an optional parameter and when not given will default to your playlists
        """
        # This is needed for add_viewed_playlist to work when no user is provided
        user = user if user else ctx.author
        songs = await self.get_playlist(ctx, user, name)
        if songs is False:
            return

        songs = playlist2partialsong(songs)
        self.add_viewed_playlist(user, songs, name)
        await self.send_playlist(ctx, songs, None, partial=True, accurate_indices=False)

    @view_playlist.group(no_pm=True, name='length', aliases=['time', 'duration', 'dur'], invoke_without_command=True)
    @cooldown(1, 5, BucketType.user)
    async def playlist_by_time(self, ctx, user: Optional[discord.User], name, longer_than: Optional[bool], *, duration: TimeDelta):
        """Filters playlist by song duration.
        Longer than param is optional.
        Usage:
        `{prefix}{name} [User#1234] "playlist name" no 10m` will select all songs under 10min and
        `{prefix}{name} [User#1234] "playlist name" 10m` will select songs over 10min"""
        user = user if user else ctx.author
        songs = load_playlist(name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {name} of user {user}")
            return

        longer_than = True if longer_than is None else longer_than

        selected = select_by_predicate(playlist2partialsong(songs), check_duration(duration.total_seconds(), longer_than))
        if not selected:
            await ctx.send(f'No songs {"longer" if longer_than else "shorter"} than {duration}')
            return

        self.add_viewed_playlist(user, selected, name)
        await self.send_playlist(ctx, selected, None, partial=True, accurate_indices=False)

    @playlist_by_time.command(name='clear', pass_context=True)
    @cooldown(1, 5, BucketType.user)
    async def clear_playlist_time(self, ctx, name, longer_than: Optional[bool], *, duration: TimeDelta):
        """
        See `{prefix}help vp dur` for argument usage.
        Clears a playlist by song duration.
        Arguments are the same as the parent commands
        """
        user = ctx.author
        songs = load_playlist(name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {name} of user {user}")
            return

        longer_than = True if longer_than is None else longer_than

        selected = select_by_predicate(playlist2partialsong(songs), check_duration(duration.total_seconds(), not longer_than))
        if not selected:
            await ctx.send(f'No songs {"longer" if longer_than else "shorter"} than {duration}')
            return

        length = len(songs)

        s = write_playlist([song.__dict__() for song in selected], name, user.id, overwrite=True)
        s += f'\n{length-len(selected)} songs deleted'
        await ctx.send(s)

    @view_playlist.group(no_pm=True, name='name', invoke_without_command=True)
    @cooldown(1, 5, BucketType.user)
    async def playlist_by_name(self, ctx, user: Optional[discord.User], playlist_name, *, song_name):
        """Filter playlist by song name. Regex can be used for this.
        Trying to kill the bot with regex will get u botbanned tho"""
        user = user if user else ctx.author
        songs = load_playlist(playlist_name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name} of user {user}")
            return

        songs = playlist2partialsong(songs)
        matches = await self.prepare_regex_search(ctx, songs, song_name)
        if matches is False:
            return

        if not matches:
            return await ctx.send(f'No songs found with `{song_name}`')

        def pred(song):
            return song.title in matches

        selected = select_by_predicate(songs, pred)
        if not selected:
            # We have this 2 times in case the playlist changes while we are checking
            await ctx.send(f'No songs found with `{song_name}`')
            return

        self.add_viewed_playlist(user, selected, playlist_name)
        await self.send_playlist(ctx, selected, None, partial=True, accurate_indices=False)

    @playlist_by_name.command(name='clear')
    @cooldown(1, 5, BucketType.user)
    async def clear_playlist_name(self, ctx, name, *, song_name):
        """
        Clears songs from a playlist based on it's name
        For parameters see help for `{prefix}vp name`
        """
        user = ctx.author
        songs = load_playlist(name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {name} of user {user}")
            return

        songs = playlist2partialsong(songs)
        matches = await self.prepare_regex_search(ctx, songs, song_name)
        if matches is False:
            return

        if not matches:
            return await ctx.send(f'No songs found with `{song_name}`')

        def pred(song):
            return song.title not in matches

        selected = select_by_predicate(songs, pred)

        if not selected:
            await ctx.send(f'No songs found with `{song_name}`')
            return

        length = len(songs)

        s = write_playlist([song.__dict__() for song in selected], name, user.id, overwrite=True)
        s += f'\n{length-len(selected)} songs deleted'
        await ctx.send(s)

    @command(no_pm=True)
    @cooldown(1, 10, BucketType.user)
    async def delete_playlist(self, ctx, *, name):
        """
        Delete a playlist with the given name
        """
        src = validate_playlist(name, ctx.author.id)
        if not src:
            ctx.command.reset_cooldown(ctx)
            await ctx.send(f"Couldn't find playlist with name {name}")
            return

        await ctx.send(f"You're about to delete your playlist \"{name}\". Type `confirm` for confirmation")
        if not await wait_for_words(ctx, ['confirm'], timeout=60):
            return

        try:
            os.remove(src)
        except OSError:
            logger.exception(f'Failed to remove playlist {src}')
            await ctx.send('Failed to delete playlist because of an error')
            return

        await ctx.send(f'Successfully deleted playlist {name}')

    async def _search(self, ctx, name):
        vc = True if ctx.author.voice else False
        if name.startswith('-yt '):
            site = 'yt'
            name = name.split('-yt ', 1)[1]
        elif name.startswith('-sc '):
            site = 'sc'
            name = name.split('-sc ', 1)[1]
        else:
            site = 'yt'

        if vc:
            musicplayer = self.get_musicplayer(ctx.guild.id)
            success = False
            if not musicplayer:
                success = await self._summon(ctx, create_task=False)
                if not success:
                    terminal.debug('Failed to join vc')
                    return await ctx.send('Failed to join vc')

            musicplayer = await self.check_player(ctx)
            if not musicplayer:
                return

            await musicplayer.playlist.search(name, ctx, site)
            if success:
                musicplayer.start_playlist()
        else:
            def on_error(_):
                pass

            await search(name, ctx, site, self.downloader, on_error=on_error)

    @command()
    @commands.cooldown(1, 5, type=BucketType.user)
    async def search(self, ctx, *, name):
        """Search for songs. Default site is youtube
        Supported sites: -yt Youtube, -sc Soundcloud
        To use a different site start the search with the site prefix
        e.g. {prefix}{name} -sc a cool song"""
        await self._search(ctx, name)

    async def _summon(self, ctx, create_task=True, change_channel=False, channel=None):
        if not ctx.author.voice:
            await ctx.send("You aren't connected to a voice channel")
            return False

        if not channel:
            channel = ctx.author.voice.channel

        musicplayer = self.get_musicplayer(ctx.guild.id, is_on=False)
        if musicplayer is None:
            musicplayer = MusicPlayer(self.bot, self.disconnect_voice, channel=ctx.channel,
                                      downloader=self.downloader)
            self.musicplayers[ctx.guild.id] = musicplayer
        else:
            musicplayer.change_channel(ctx.channel)

        if musicplayer.voice is None:
            try:
                if ctx.voice_client and ctx.voice_client.channel:
                    await ctx.voice_client.disconnect(force=True)

                musicplayer.voice = await channel.connect()
            except (discord.HTTPException, asyncio.TimeoutError) as e:
                await ctx.send(f'Failed to join vc because of an error\n{e}')
                return False
            except discord.ClientException:
                await ctx.send(f'Bot is having some difficulties joining voice. You should probably use `{ctx.prefix}force_stop`')
                return False

            if create_task:
                musicplayer.start_playlist()
        else:
            try:
                if channel.id != musicplayer.voice.channel.id:
                    if change_channel:
                        await musicplayer.voice.move_to(channel)
                    else:
                        await ctx.send("You aren't allowed to change channels")
                elif not musicplayer.voice.is_connected():
                    await musicplayer.voice.channel.connect()
            except (discord.HTTPException, asyncio.TimeoutError) as e:
                await ctx.send(f'Failed to join vc because of an error\n{e}')
                return False

        return True

    @command(no_pm=True, aliases=['summon1'])
    @cooldown(1, 3, type=BucketType.guild)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        return await self._summon(ctx)

    @command(no_pm=True)
    @cooldown(1, 3, type=BucketType.guild)
    async def move(self, ctx, channel: discord.VoiceChannel=None):
        """Moves the bot to your current voice channel or the specified voice channel"""
        return await self._summon(ctx, change_channel=True, channel=channel)

    @cooldown(2, 5, BucketType.guild)
    @command(no_pm=True)
    async def repeat(self, ctx, value: bool=None):
        """If set on the current song will repeat until this is set off"""
        if not await self.check_voice(ctx):
            return
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        if value is None:
            musicplayer.repeat = not musicplayer.repeat

        if musicplayer.repeat:
            s = 'Repeat set on :recycle:'

        else:
            s = 'Repeat set off'

        await ctx.send(s)

    @cooldown(1, 5, BucketType.guild)
    @command(no_pm=True)
    async def speed(self, ctx, value: str):
        """Change the speed of the currently playing song.
        Values must be between 0.5 and 2"""
        try:
            v = float(value)
            if v > 2 or v < 0.5:
                return await ctx.send('Value must be between 0.5 and 2', delete_after=20)
        except ValueError as e:
            return await ctx.send('{0} is not a number\n{1}'.format(value, e), delete_after=20)

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)
        current.set_filter('atempo', value)
        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        musicplayer._speed_mod = v
        await self._seek(musicplayer, current, seek, options=current.options, speed=v)

    @commands.cooldown(2, 5, BucketType.guild)
    @command(no_pm=True, aliases=['cs', 'removesilence'])
    async def cutsilence(self, ctx, is_enabled: bool=None):
        """
        Cut the silence at the end of audio
        """

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)

        if is_enabled is None:
            is_enabled = musicplayer.persistent_filters.get('silenceremove') is None

        if is_enabled:
            value = '1:0:-60dB:1:5:-50dB'
            if current:
                current.set_filter('silenceremove', value)

            musicplayer.persistent_filters['silenceremove'] = value
            s = 'Silence will be now cut at the end of the song.\n' \
                'Duration shows uncut length of the song so it might cut out before reaching the specified end'
        else:
            if current:
                current.remove_filter('silenceremove')

            musicplayer.persistent_filters.pop('silenceremove', None)
            s = 'No more cutting silence at the end of the song'

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)

        await ctx.send(s)

    @command(no_pm=True, name='filter')
    @commands.is_owner()
    async def custom_filter(self, ctx, name, *, value=None):
        """Set custom filter and value. owner only"""
        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)

        if value:
            current.set_filter(name, value)
        else:
            current.remove_filter(name)

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)

    @commands.cooldown(1, 5, BucketType.guild)
    @command(no_pm=True)
    async def bass(self, ctx, value: int):
        """Add or decrease the amount of bass boost. Value will persists for every song until set back to 0
        Value can range between -60 and 60"""
        if not (-60 <= value <= 60):
            return await ctx.send('Value must be between -60 and 60', delete_after=20)

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)

        if value:
            value = 'g=%s' % value
            current.set_filter('bass', value)
            musicplayer.persistent_filters['bass'] = value
        else:
            current.remove_filter('bass')
            musicplayer.persistent_filters.pop('bass', None)

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)

    @cooldown(1, 5, BucketType.guild)
    @command(no_pm=True)
    async def stereo(self, ctx, mode='sine'):
        """Works almost the same way {prefix}play does
        Default stereo type is sine.
        All available modes are `sine`, `triangle`, `square`, `sawup`, `sawdown`, `left`, `right`, `off`, `none`
        left and right work independently of the other modes so you can have both
        on at the same time. e.g. calling `{prefix}{name} left` and `{prefix}{name} sine` after that
        would make the sinewave effect only on the left channel.
        """

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        mode = mode.lower()
        modes = ("sine", "triangle", "square", "sawup", "sawdown", 'off', 'left', 'right', 'none')
        if mode not in modes:
            ctx.command.reset_cooldown(ctx)
            return await ctx.send('Incorrect mode specified')

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)
        if mode in ('left', 'right'):
            # https://trac.ffmpeg.org/wiki/AudioChannelManipulation
            # For more info on channel manipulation with ffmpeg
            mode = 'FR=FR' if mode == 'right' else 'FL=FL'
            current.set_filter('pan', f'stereo|{mode}')

        elif mode in ('off', 'none'):
            current.remove_filter('pan')
            current.remove_filter('apulsator')
        else:
            current.set_filter('apulsator', f'mode={mode}')

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)

    @group(no_pm=True, invoke_without_command=True)
    @cooldown(1, 4, type=BucketType.guild)
    async def clear(self, ctx, *, items=None):
        """
        Clear the selected indexes from the playlist.
        "!clear all" empties the whole playlist
        usage:
            {prefix}{name} 1-4 7-9 5
            would delete songs at positions 1 to 4, 5 and 7 to 9
        """
        if not items:
            await ctx.send('No arguments given. To clear playlist completely give all'
                           'as an argument. Otherwise the indexes of the songs')
            return

        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            return

        if items != 'all':
            indexes = items.split(' ')
            index = []
            for idx in indexes:
                if '-' in idx:
                    idx = idx.split('-')
                    a = int(idx[0])
                    b = int(idx[1])
                    index += range(a - 1, b)
                else:
                    index.append(int(idx) - 1)
        else:
            index = None

        await musicplayer.playlist.clear(index, ctx.channel)

    @clear.command(no_pm=True, name='from')
    @cooldown(2, 5)
    async def from_(self, ctx, *, user: discord.User):
        """Clears all songs from the specified user"""
        musicplayer = await self.get_player_and_check(ctx)
        if not musicplayer:
            return

        cleared = musicplayer.playlist.clear_by_predicate(check_who_queued(user))
        await ctx.send(f'Cleared {cleared} songs from user {user}')

    @clear.command(no_pm=True, aliases=['dur', 'duration', 'lt'])
    @cooldown(2, 5)
    async def longer_than(self, ctx, *, duration: TimeDelta):
        """Delete all songs from queue longer than specified duration
        Duration is a time strin in the format of 1d 1h 1m 1s"""
        musicplayer = await self.get_player_and_check(ctx)
        if not musicplayer:
            return

        sec = duration.total_seconds()
        cleared = musicplayer.playlist.clear_by_predicate(check_duration(sec))
        await ctx.send(f'Cleared {cleared} songs longer than {duration}')

    async def prepare_regex_search(self, ctx, songs, song_name):
        """
        Prepare regex for use in playlist filtering
        """
        matches = set()

        try:
            r = re.compile(song_name, re.IGNORECASE)
        except re.error as e:
            await ctx.send('Failed to compile regex\n' + str(e))
            return False

        # This needs to be run in executor in case someone decides to use
        # an evil regex
        def get_matches():
            for song in list(songs):
                if not song.title:
                    continue

                if r.search(song.title):
                    matches.add(song.title)

        try:
            await asyncio.wait_for(self.bot.loop.run_in_executor(self.bot.threadpool, get_matches),
                             timeout=1.5, loop=self.bot.loop)
        except asyncio.TimeoutError:
            logger.warning(f'{ctx.author} {ctx.author.id} timeouted regex. Used regex was {song_name}')
            await ctx.send('Search timed out')
            return False

        return matches

    @clear.command(no_pm=True, name='name')
    @cooldown(2, 4)
    async def by_name(self, ctx, *, song_name):
        """Clear queue by song name. Regex can be used for this.
        Trying to kill the bot with regex will get u botbanned tho"""
        musicplayer = await self.get_player_and_check(ctx)
        if not musicplayer:
            return

        matches = await self.prepare_regex_search(ctx, musicplayer.playlist.playlist, song_name)
        if matches is False:
            return

        def pred(song):
            return song.title in matches

        cleared = musicplayer.playlist.clear_by_predicate(pred)
        await ctx.send(f'Cleared {cleared} songs matching {song_name}')

    @cooldown(2, 3, type=BucketType.guild)
    @command(no_pm=True, aliases=['vol'])
    async def volume(self, ctx, value: int=-1):
        """
        Sets the volume of the currently playing song.
        If no parameters are given it shows the current volume instead
        Effective values are between 0 and 200
        """
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not await self.check_voice(ctx):
            return

        # If value is smaller than zero or it hasn't been given this shows the current volume
        if value < 0:
            await ctx.send('Volume is currently at {:.0%}'.format(musicplayer.current_volume))
            return

        musicplayer.current_volume = value / 100
        await ctx.send('Set the volume to {:.0%}'.format(musicplayer.current_volume))

    @commands.cooldown(2, 3, type=BucketType.guild)
    @command(no_pm=True, aliases=['default_vol', 'd_vol'])
    async def default_volume(self, ctx, value: int=-1):
        """
        Sets the default volume of the player that will be used when song specific volume isn't set.
        If no parameters are given it shows the current default volume instead
        Effective values are between 0 and 200
        """
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not await self.check_voice(ctx):
            return

        # If value is smaller than zero or it hasn't been given this shows the current volume
        if value < 0:
            await ctx.send('Default volume is currently at {:.0%}'.format(musicplayer.volume))
            return

        musicplayer.volume = min(value / 100, 2)
        await ctx.send('Set the default volume to {:.0%}'.format(musicplayer.volume))

    @commands.cooldown(1, 4, type=BucketType.guild)
    @command(no_pm=True, aliases=['np'])
    async def playing(self, ctx):
        """Gets the currently playing song"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer or musicplayer.player is None or musicplayer.current is None:
            await ctx.send('No songs currently in queue')
        else:
            duration = musicplayer.current.duration
            tr_pos = get_track_pos(duration, musicplayer.duration)
            s = musicplayer.current.long_str + f' {tr_pos}'
            s += ' 🔁\n' if musicplayer.repeat else '\n'
            if duration:
                pos = round(20 * min(1, musicplayer.duration/duration))
                slider = f'00:00 {"─"*pos}●{"─"*(20-pos-1)}  {format_time(duration)}'
            else:
                slider = f'00:00 {"─"*19}●  {format_time(musicplayer.duration)}'

            s += slider
            await ctx.send(s)

    @cooldown(1, 3, type=BucketType.user)
    @command(name='playnow', no_pm=True)
    async def play_now(self, ctx, *, song_name: str):
        """
        Sets a song to the priority queue which is played as soon as possible
        after the other songs in that queue.
        """
        musicplayer = self.get_musicplayer(ctx.guild.id)
        success = False
        if musicplayer is None or musicplayer.voice is None:
            success = await self._summon(ctx, create_task=False)
            if not success:
                return

        await self.play_song(ctx, song_name, priority=True)
        if success:
            musicplayer.start_playlist()

    @cooldown(1, 3, type=BucketType.guild)
    @command(no_pm=True, aliases=['p'])
    async def pause(self, ctx):
        """Pauses the currently played song."""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer:
            musicplayer.pause()

    @cooldown(1, 60, type=BucketType.guild)
    @command(enabled=False, hidden=True)
    async def save_playlist(self, ctx, *name):
        if name:
            name = ' '.join(name)

        musicplayer = self.get_musicplayer(ctx.guild.id)
        await musicplayer.playlist.current_to_file(name, ctx.message.channel)

    @cooldown(1, 3, type=BucketType.guild)
    @command(no_pm=True, aliases=['r'])
    async def resume(self, ctx):
        """Resumes the currently played song."""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return
        await musicplayer.resume()

    @command(name='bpm', no_pm=True)
    @cooldown(1, 8, BucketType.guild)
    async def bpm(self, ctx):
        """Gets the currently playing songs bpm using aubio"""
        if not aubio:
            return await ctx.send('BPM is not supported', delete_after=60)

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        song = musicplayer.current
        if not musicplayer.is_playing() or not song:
            return

        if song.bpm:
            return await ctx.send('BPM for {} is about **{}**'.format(song.title, round(song.bpm, 1)))

        if song.duration == 0:
            return await ctx.send('Cannot determine bpm because duration is 0', delete_after=90)

        import subprocess
        import shlex
        file = song.filename
        tempfile = os.path.join(os.getcwd(), 'data', 'temp', 'tempbpm.wav')
        cmd = 'ffmpeg -i "{}" -f wav -t 00:10:00 -map_metadata -1 -loglevel warning pipe:1'.format(file)
        args = shlex.split(cmd)
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE)
        except Exception:
            terminal.exception('Failed to get bpm')
            return await ctx.send('Error while getting bpm', delete_after=20)

        from utils.utilities import write_wav

        await self.bot.loop.run_in_executor(self.bot.threadpool, partial(write_wav, p.stdout, tempfile))

        try:
            win_s = 512  # fft size
            hop_s = win_s // 2  # hop size

            s = aubio.source(tempfile, 0, hop_s, 2)
            samplerate = s.samplerate
            o = aubio.tempo("default", win_s, hop_s, samplerate)

            # tempo detection delay, in samples
            # default to 4 blocks delay to catch up with
            delay = 4. * hop_s

            # list of beats, in samples
            beats = []

            # total number of frames read
            total_frames = 0
            while True:
                samples, read = s()
                is_beat = o(samples)
                if is_beat:
                    this_beat = int(total_frames - delay + is_beat[0] * hop_s)
                    beats.append(this_beat)
                total_frames += read
                if read < hop_s:
                    break

            bpm = len(beats) / song.duration * 60
            song.bpm = bpm
            return await ctx.send('BPM for {} is about **{}**'.format(song.title, round(bpm, 1)))
        finally:
            try:
                s.close()
            except:
                pass
            os.remove(tempfile)

    @cooldown(1, 4, type=BucketType.guild)
    @command(no_pm=True)
    async def shuffle(self, ctx):
        """Shuffles the current playlist"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return
        await musicplayer.playlist.shuffle()
        await ctx.send('Playlist shuffled')

    async def shutdown(self):
        self.clear_cache()

    @staticmethod
    async def close_player(musicplayer):
        if musicplayer is None:
            return

        if musicplayer.player:
            musicplayer.player.after = None

        if musicplayer.is_playing():
            musicplayer.stop()

        try:
            if musicplayer.audio_player is not None:
                musicplayer.audio_player.cancel()

            if musicplayer.voice is not None:
                await musicplayer.voice.disconnect(force=True)
                musicplayer.voice = None

        except Exception:
            terminal.exception('Error while stopping voice')

    async def disconnect_voice(self, musicplayer):
        try:
            del self.musicplayers[musicplayer.channel.guild.id]
        except:
            pass

        await self.close_player(musicplayer)
        if not self.musicplayers:
            await self.bot.change_presence(activity=discord.Activity(**self.bot.config.default_activity))

    @command(no_pm=True)
    @cooldown(1, 6, BucketType.guild)
    async def force_stop(self, ctx):
        """
        Forces voice to be stopped no matter what state the bot is in
        as long as it's connected to voice and the internal state is in sync.
        Not meant to be used for normal disconnecting
        """
        try:
            res = await self.stop.callback(self, ctx)
        except Exception as e:
            print(e)
            res = False

        # Just to be sure, delete every single musicplayer related to this server
        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        while musicplayer is not None:
            try:
                self.musicplayers.pop(ctx.guild.id)
            except KeyError:
                pass

            MusicPlayer.__instances__.discard(musicplayer)
            musicplayer.selfdestruct()
            del musicplayer

            musicplayer = self.get_musicplayer(ctx.guild.id, False)

        del musicplayer

        import gc
        gc.collect()

        if res is False:
            if not ctx.voice_client:
                return await ctx.send('Not connected to voice')

            await ctx.voice_client.disconnect(force=True)
            await ctx.send('Forced disconnect')
        else:
            await ctx.send('Disconnected')

    @commands.cooldown(1, 6, BucketType.user)
    @command(no_pm=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            if ctx.voice_client:
                await ctx.voice_client.disconnect(force=True)
                return

        await self.disconnect_voice(musicplayer)

        # Legacy code
        if not self.musicplayers:
            self.clear_cache()

    @command(no_pm=True, aliases=['vs'])
    async def votestop(self, ctx):
        """Stops the bot if enough people vote for it. Votes expire in 60s"""
        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            if ctx.voice_client:
                await ctx.voice_client.disconnect()
                return

        resp = await musicplayer.votestop(ctx.author)

        if resp is True:
            await self.disconnect_voice(musicplayer)
            await ctx.send('Votes reached disconnecting')
        else:
            await ctx.send(f'{resp} votes until disconnect')

    @cooldown(1, 5, type=BucketType.user)
    @command(no_pm=True, aliases=['skipsen', 'skipperino', 's'])
    async def skip(self, ctx):
        """Skips the current song"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        if not await self.check_voice(ctx):
            return

        if not musicplayer.is_playing():
            await ctx.send('Not playing any music right now...')
            return

        await musicplayer.skip(ctx.author, ctx.channel)

    @cooldown(1, 5, type=BucketType.user)
    @command(no_pm=True, aliases=['force_skipsen', 'force_skipperino', 'fs'])
    async def force_skip(self, ctx):
        """Force skips this song no matter who queued it without requiring any votes
        For public servers it's recommended you blacklist this from your server
        and only give some people access to it"""
        if not await self.check_voice(ctx):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        if not musicplayer.is_playing():
            await ctx.send('Not playing any music right now...')
            return

        await musicplayer.skip(None, ctx.channel)

    async def send_playlist(self, ctx, playlist, musicplayer, page_index=0, accurate_indices=True, partial=False):
        """
        Sends a paged message containing all playlist songs.
        When accurate_indices is set to True we will check the index of each
        song manually by checking it's position in the guilds playlist.
        When false will use values based on page index.

        If partial is set to true we will assume PartialSong is being used
        """
        if partial and accurate_indices:
            raise ValueError('Cant have partial and accurate indices set to True at the same time')

        if not playlist:
            return await ctx.send('Empty playlist')

        pages = []
        for i in range(0, len(playlist), 10):
            pages.append(playlist[i:i + 10])

        if not pages:
            pages.append([])

        def add_song(song, idx, dur):
            title = song.title.replace('*', '\\*')
            if partial:
                return f'\n{idx}. **{title}** (Duration: {format_timedelta(dur, 3, long_format=False)}) <{song.webpage_url}>'
            else:
                return f'\n{idx}. **{title}** {song.requested_by} (ETA: {format_timedelta(dur, 3, long_format=False)})'

        def get_page(page, idx):
            response = ''
            if not partial:
                full_playlist = list(musicplayer.playlist.playlist)  # good variable naming
                if not full_playlist and musicplayer.current is None:
                    return 'Nothing playing atm'

                if musicplayer.current is not None:
                    dur = get_track_pos(musicplayer.current.duration, musicplayer.duration)
                    response = f'Currently playing **{musicplayer.current.title}** {dur}'
                    if musicplayer.current.requested_by:
                        response += f' enqueued by {musicplayer.current.requested_by}\n'

            if accurate_indices:
                # This block is never reached if partial is true se we dont have
                # to worry about variables being undefined
                songs = []
                indices = []
                redo_pages = False
                for song in page:
                    try:
                        idx = full_playlist.index(song)
                    except ValueError:
                        redo_pages = True
                        playlist.remove(song)
                        continue

                    songs.append(song)
                    indices.append(idx)

                if not songs:
                    return 'Nothing playing atm'

                if redo_pages:
                    # If these songs have been cleared or otherwise passed by we remove them
                    # and recreate the list
                    pages.clear()
                    for i in range(0, len(playlist), 10):
                        pages[i] = playlist[i:i + 10]

                durations = self.song_durations(musicplayer, until=max(indices) + 1)

                for song, idx in zip(songs, indices):
                    dur = int(durations[idx])
                    response += add_song(song, idx + 1, dur)

            elif partial:
                for _idx, song in enumerate(page):
                    response += add_song(song, _idx + 1 + 10 * idx, song.duration)
            else:
                durations = self.song_durations(musicplayer, until=idx * 10 + 10)
                durations = durations[-10:]

                for _idx, song_dur in enumerate(zip(page, durations)):
                    song, dur = song_dur
                    dur = int(dur)
                    response += add_song(song, _idx + 1 + 10 * idx, dur)

            return response

        await send_paged_message(ctx, pages, starting_idx=page_index, page_method=get_page)

    @cooldown(1, 5, type=BucketType.guild)
    @group(name='queue', no_pm=True, aliases=['playlist'], invoke_without_command=True)
    async def playlist(self, ctx, page_index: int=0):
        """Get a list of the current queue in 10 song chunks
        To skip to a certain page set the page_index argument"""

        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        playlist = list(musicplayer.playlist.playlist)  # good variable naming
        if not playlist and musicplayer.current is None:
            return await ctx.send('Nothing playing atm')

        await self.send_playlist(ctx, playlist, musicplayer, page_index, accurate_indices=False)

    @playlist.command(no_pm=True, name='from', aliases=['user', 'u', 'by'])
    @cooldown(1, 5)
    async def queue_by_user(self, ctx, user: discord.User, page_index: int=0):
        """Filters playlist to the songs queued by user"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        selected = musicplayer.playlist.select_by_predicate(check_who_queued(user))
        if not selected:
            await ctx.send(f'No songs enqueued by {user}')
            return

        await self.send_playlist(ctx, selected, musicplayer, page_index)

    @playlist.command(no_pm=True, name='length', aliases=['time', 'duration', 'dur'])
    @cooldown(1, 5)
    async def queue_by_time(self, ctx, longer_than: Optional[bool], *, duration: TimeDelta):
        """Filters playlist by song duration.
        Longer than param is optional.
        Usage:
        `{prefix}{name} no 10m` will select all songs under 10min and
        `{prefix}{name} 10m` will select songs over 10min"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        longer_than = True if longer_than is None else longer_than

        selected = musicplayer.playlist.select_by_predicate(check_duration(duration.total_seconds(), longer_than))
        if not selected:
            await ctx.send(f'No songs {"longer" if longer_than else "shorter"} than {duration}')
            return

        await self.send_playlist(ctx, selected, musicplayer)

    @playlist.command(no_pm=True, name='name')
    @cooldown(1, 5)
    async def queue_by_name(self, ctx, *, song_name):
        """Filter playlist by song name. Regex can be used for this.
        Trying to kill the bot with regex will get u botbanned tho"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        matches = await self.prepare_regex_search(ctx, musicplayer.playlist.playlist, song_name)
        if matches is False:
            return

        if not matches:
            return await ctx.send(f'No songs found with `{song_name}`')

        def pred(song):
            return song.title in matches

        selected = musicplayer.playlist.select_by_predicate(pred)
        if not selected:
            # We have this 2 times in case the playlist changes while we are checking
            await ctx.send(f'No songs found with `{song_name}`')
            return

        await self.send_playlist(ctx, selected, musicplayer)

    @cooldown(1, 3, type=BucketType.guild)
    @command(no_pm=True, aliases=['len'])
    async def length(self, ctx):
        """Gets the length of the current queue"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return
        if musicplayer.current is None or not musicplayer.playlist.playlist:
            return await ctx.send('No songs in queue')

        time_left = self.list_length(musicplayer)
        minutes, seconds = divmod(floor(time_left), 60)
        hours, minutes = divmod(minutes, 60)

        return await ctx.send('The length of the playlist is about {0}h {1}m {2}s'.format(hours, minutes, seconds))

    @command(no_pm=True, auth=Auth.BOT_MOD)
    async def ds(self, ctx):
        """Delete song from autoplaylist and skip it"""
        await ctx.invoke(self.delete_from_ap)
        await ctx.invoke(self.skip)

    @staticmethod
    def list_length(musicplayer, index=None):
        playlist = musicplayer.playlist
        if not playlist:
            return
        time_left = musicplayer.current.duration - musicplayer.duration
        for song in list(playlist)[:index]:
            time_left += song.duration

        return time_left

    @staticmethod
    def song_durations(musicplayer, until=None):
        playlist = musicplayer.playlist
        if not playlist:
            return None

        durations = []
        if musicplayer.current:
            time_left = musicplayer.current.duration - musicplayer.duration
        else:
            time_left = 0

        for song in list(playlist)[:until]:
            durations.append(time_left)
            time_left += song.duration

        return durations

    @cooldown(1, 5, type=BucketType.user)
    @command(no_pm=True, aliases=['dur'])
    async def duration(self, ctx):
        """Gets the duration of the current song"""
        if not await self.check_voice(ctx):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return
        if musicplayer.is_playing():
            dur = musicplayer.current.duration
            msg = get_track_pos(dur, musicplayer.duration)
            await ctx.send(msg)
        else:
            await ctx.send('No songs are currently playing')

    @command(no_pm=True)
    @cooldown(2, 6)
    async def autoplay(self, ctx, value: bool=None):
        """Determines if youtube autoplay should be emulated
        If no value is passed current value is output"""
        musicplayer = await self.check_player(ctx)

        if not musicplayer:
            return await ctx.send('Not playing any music right now')

        if not await self.check_voice(ctx):
            return

        if value is None:
            return await ctx.send(f'Autoplay currently {"on" if musicplayer.autoplay else "off"}')

        musicplayer.autoplay = value
        s = f'Autoplay set {"on" if value else "off"}'
        await ctx.send(s)

    @command(name='volm', no_pm=True)
    @cooldown(1, 4, type=BucketType.guild)
    async def vol_multiplier(self, ctx, value=None):
        """The multiplier that is used when dynamically calculating the volume"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not value:
            return await ctx.send('Current volume multiplier is %s' % str(musicplayer.volume_multiplier))
        try:
            value = float(value)
            musicplayer.volume_multiplier = value
            await ctx.send(f'Volume multiplier set to {value}')
        except ValueError:
            await ctx.send('Value is not a number', delete_after=60)

    @command(no_pm=True, aliases=['avolm'])
    @cooldown(2, 4, type=BucketType.guild)
    async def auto_volm(self, ctx):
        """Automagically set the volm value based on current volume"""
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        if not await self.check_voice(ctx):
            return

        current = musicplayer.current
        if not current:
            return await ctx.send('Not playing anything right now')

        old = musicplayer.volume_multiplier
        if not current.rms:
            for h in musicplayer.history:
                if not h.rms:
                    continue

                new = round(h.rms * h.volume, 1)
                await ctx.send("Current song hadn't been processed yet so used song history to determine volm\n"
                               f"{old} -> {new}")
                return

        new = round(current.rms * musicplayer.current_volume, 1)
        musicplayer.volume_multiplier = new
        await ctx.send(f'volm changed automagically {old} -> {new}')

    @command(no_pm=True)
    @cooldown(1, 10, type=BucketType.guild)
    async def link(self, ctx):
        """Link to the current song"""
        if not await self.check_voice(ctx):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer is None:
            return

        current = musicplayer.current
        if not current:
            return await ctx.send('Not playing anything')
        await ctx.send('Link to **{0.title}** {0.webpage_url}'.format(current))

    @command(name='delete', no_pm=True, aliases=['del', 'd'], auth=Auth.BOT_MOD)
    async def delete_from_ap(self, ctx, *name):
        """Puts a song to the queue to be deleted from autoplaylist"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not name:
            if not musicplayer or not musicplayer.current:
                await ctx.send('Nothing playing and no link given')
                return

            name = [musicplayer.current.webpage_url]

            if name is None:
                terminal.debug('No name specified in delete_from')
                await ctx.send('No song to delete', delete_after=60)
                return

        with open(DELETE_AUTOPLAYLIST, 'a', encoding='utf-8') as f:
            f.write(' '.join(name) + '\n')

        terminal.info('Added entry %s to the deletion list' % name)
        await ctx.send('Added entry %s to the deletion list' % ' '.join(name), delete_after=60)

    @command(name='add', no_pm=True, auth=Auth.BOT_MOD)
    async def add_to_ap(self, ctx, *name):
        """Puts a song to the queue to be added to autoplaylist"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if name:
            name = ' '.join(name)
        if not name:
            if not musicplayer:
                return

            current = musicplayer.current
            if current is None or current.webpage_url is None:
                terminal.debug('No name specified in add_to')
                await ctx.send('No song to add', delete_after=30)
                return

            data = current.webpage_url
            name = data

        elif 'playlist' in name or 'channel' in name:
            async def on_error(e):
                await ctx.send('Failed to get playlist %s' % e)

            info = await self.downloader.extract_info(self.bot.loop, url=name, download=False,
                                                      on_error=on_error)
            if info is None:
                return

            links = await Playlist.process_playlist(info, channel=ctx.message.channel)
            if links is None:
                await ctx.send('Incompatible playlist')

            data = '\n'.join(links)

        else:
            data = name

        with open(ADD_AUTOPLAYLIST, 'a', encoding='utf-8') as f:
            f.write(data + '\n')

        terminal.info('Added entry %s to autoplaylist' % name)
        await ctx.send('Added entry %s' % name, delete_after=60)

    @command(no_pm=True)
    @cooldown(1, 5, type=BucketType.guild)
    async def autoplaylist(self, ctx, option: bool):
        """Set the autoplaylist on or off"""
        musicplayer = self.get_musicplayer(ctx.guild.id)

        if option:
            musicplayer.autoplaylist = True
        else:
            musicplayer.autoplaylist = False

        await ctx.send(f'Autoplaylist set {"on" if option else "off"}')

    def clear_cache(self):
        songs = []
        for musicplayer in self.musicplayers.values():
            for song in musicplayer.playlist.playlist:
                songs += [song.id]
        cachedir = os.path.join(os.getcwd(), 'data', 'audio', 'cache')
        try:
            files = os.listdir(cachedir)
        except (OSError, FileNotFoundError):
            return

        def check_list(string):
            if song.id is not None and song.id in string:
                return True
            return False

        dont_delete = []
        for song in songs:
            file = list(filter(check_list, files))
            if file:
                dont_delete += file

        for file in files:
            if file not in dont_delete:
                try:
                    os.remove(os.path.join(cachedir, file))
                except os.error:
                    pass


def setup(bot):
    bot.add_cog(Audio(bot))

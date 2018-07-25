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
from collections import deque
from functools import partial
from math import ceil
from math import floor

from discord.activity import Activity, ActivityType
from discord.errors import HTTPException
from discord.ext import commands
from discord.ext.commands.cooldowns import BucketType
from discord.ext.commands import cooldown
from discord.player import PCMVolumeTransformer

from bot import player
from bot.bot import command
from bot.downloader import Downloader
from bot.globals import ADD_AUTOPLAYLIST, DELETE_AUTOPLAYLIST
from bot.globals import Auth
from bot.playlist import Playlist
from bot.song import Song
from utils.utilities import mean_volume, search, parse_seek, send_paged_message
import weakref

try:
    import aubio
except ImportError:
    aubio = None


logger = logging.getLogger('audio')
terminal = logging.getLogger('terminal')


def get_track_pos(duration, current_pos):
    mm, ss = divmod(duration, 60)
    hh, mm = divmod(mm, 60)
    m, s = divmod(floor(current_pos), 60)
    h, m = divmod(m, 60)
    m = str(m)
    mm = str(mm)
    if h > 0:
        m = '{}:{}'.format(str(h), m.zfill(2))
    if hh > 0:
        mm = '{}:{}'.format(str(hh), mm.zfill(2))

    return '`[{0}:{1}/{2}:{3}]`'.format(m, str(s).zfill(2), mm, str(ss).zfill(2))


class MusicPlayer:
    __instances__ = weakref.WeakSet()

    @classmethod
    def get_instances(cls):
        for inst in cls.__instances__:
            yield inst

    def __init__(self, bot, disconnect, channel=None):
        self.__instances__.add(self)
        self.bot = bot
        self.play_next = asyncio.Event()
        self.voice = None
        self.current = None
        self.channel = channel
        self.repeat = False
        self._disconnect = disconnect

        self.playlist = Playlist(bot, download=True, channel=self.channel)
        self.autoplaylist = bot.config.autoplaylist
        self.volume = self.bot.config.default_volume
        self.volume_multiplier = bot.config.volume_multiplier
        self.audio_player = None
        self.activity_check = None
        self._speed_mod = 1
        self._skip_votes = set()

    def change_channel(self, channel):
        self.channel = channel
        self.playlist.channel = channel

    def start_playlist(self):
        self.audio_player = self.bot.loop.create_task(self._play_audio())
        self.activity_check = self.bot.loop.create_task(self._activity_check())

    @property
    def source(self):
        if self.player:
            return self.player.source

    @property
    def player(self):
        if self.voice:
            return self.voice._player

    @property
    def duration(self):
        if self.player:
            return self.player.duration

        return 0

    @property
    def current_volume(self):
        if self.source:
            return self.source.volume
        return 0

    @current_volume.setter
    def current_volume(self, vol):
        if vol < 0:
            return
        vol = min(2, vol)
        if self.source:
            self.source.volume = vol
        if self.current:
            self.current.volume = vol

    def _get_volume_from_db(self, db):
        rms = pow(10, db / 20) * 32767
        return 1 / rms * self.volume_multiplier

    async def set_mean_volume(self, file):
        try:
            db = await asyncio.wait_for(mean_volume(file, self.bot.loop, self.bot.threadpool,
                                        duration=self.current.duration), timeout=20, loop=self.bot.loop)
            if db is not None and abs(db) >= 0.1:
                volume = self._get_volume_from_db(db)
                logger.debug(f'parsed volume {volume}')
                self.current_volume = volume

        except asyncio.TimeoutError:
            logger.debug('Mean volume timed out')
        except asyncio.CancelledError:
            pass

    async def _activity_check(self):
        async def stop():
            await self._disconnect(self)
            self.voice = None

        while True:
            await asyncio.sleep(60)
            if self.voice is None:
                return await stop()

            users = self.voice.channel.members
            users = list(filter(lambda x: not x.bot, users))
            if not users:
                await self.send('No voice activity. Disconnecting')
                await stop()
                return

    async def _play_audio(self):
        while self.voice and self.voice.is_connected():
            self.play_next.clear()
            if self.current is None:
                if self.playlist.peek() is None:
                    if self.autoplaylist:
                        self.current = await self.playlist.get_from_autoplaylist()
                    else:
                        # If autoplaylist not enabled wait until playlist is populated
                        await self.playlist.not_empty.wait()
                        continue

                else:
                    self.current = await self.playlist.next_song()

            if self.current is None:
                if not self.autoplaylist:
                    await self.playlist.not_empty.wait()
                continue

            if self.repeat:
                speed = self._speed_mod
            else:
                speed = 1

            logger.debug(f'Next song is {self.current}')
            logger.debug('Waiting for dl')

            try:
                await asyncio.wait_for(self.current.on_ready.wait(), timeout=15,
                                       loop=self.bot.loop)
            except asyncio.TimeoutError:
                logger.debug(f'Song {self.current.webpage_url} download timed out')
                await self.send(f'Failed to download {self.current}')
                self.current = None
                continue

            logger.debug('Done waiting')
            if not self.current.success:
                terminal.error(f'Download of {self.current.webpage_url} unsuccessful')
                await self.send(f'Download of {self.current.webpage_url} was unsuccessful')
                continue

            if self.current.filename is not None:
                file = self.current.filename
            elif self.current.url != 'None':
                file = self.current.url
            else:
                terminal.error('No valid file to be played')
                await self.send('No valid file to be played')
                continue

            logger.debug(f'Opening file with the name "{file}" and options "{self.current.before_options}" "{self.current.options}"')
            source = player.FFmpegPCMAudio(file, before_options=self.current.before_options,
                                                 options=self.current.options)
            source = PCMVolumeTransformer(source)
            if self.current.volume is None and self.bot.config.auto_volume and isinstance(file, str) and not self.current.is_live:
                volume_task = asyncio.ensure_future(self.set_mean_volume(file))
            else:
                volume_task = None

            source.volume = self.current.volume or self.volume

            dur = get_track_pos(self.current.duration, 0)
            s = 'Now playing **{0.title}** {1} with volume at {2:.0%}'.format(self.current, dur, source.volume)
            if self.current.requested_by:
                s += f' enqueued by {self.current.requested_by}'
            await self.send(s, delete_after=self.current.duration)

            await self.skip(None)
            player.play(self.voice, source, after=self.on_stop, speed=speed)
            logger.debug('Started player')
            await self.change_status(self.current.title)
            logger.debug('Downloading next')
            await self.playlist.download_next()
            await self.play_next.wait()

            if not self.repeat:
                self.current = None
                if volume_task is not None:
                    volume_task.cancel()

            self._skip_votes = set()

    def on_stop(self, e):
        if e:
            logger.debug(f'Player caught an error {e}')
        self.bot.loop.call_soon_threadsafe(self.play_next.set)
        self.playlist.on_stop()

    async def change_status(self, s):
        activity = Activity(type=ActivityType.listening, name=s)
        await self.bot.change_presence(activity=activity)

    async def send(self, msg, channel=None, **kwargs):
        channel = self.channel if not channel else channel
        if channel is None:
            return
        try:
            await channel.send(msg, **kwargs)
        except HTTPException:
            pass

    def is_playing(self):
        if self.voice is None or not self.voice.is_connected():
            return False

        return True

    def pause(self):
        if self.is_playing():
            self.voice.pause()

    def resume(self):
        if self.is_playing():
            self.voice.resume()

    async def skip(self, author, messageable=None):
        if self.is_playing():
            if author is None:
                self.voice.stop()
                return

            if self.current:
                if self.current.requested_by and self.current.requested_by.id == author.id:
                    self.voice.stop()
                else:
                    self._skip_votes.add(author.id)
                    users = self.voice.channel.members
                    users = len(list(filter(lambda x: not x.bot, users)))
                    required_votes = ceil(users/2)
                    if len(self._skip_votes) >= required_votes:
                        await self.send(f'{required_votes} votes reached, skipping', channel=messageable)
                        return self.voice.stop()

                    await self.send(f'{len(self._skip_votes)}/{required_votes} until skip')

            else:
                self.voice.stop()

    def stop(self):
        if self.voice:
            self.voice.stop()


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
        # TODO Create heartbeat that will be checked to know if the task has died
        self.audio_player = self.bot.loop.create_task(self.play_audio())
        self.activity_check = self.bot.loop.create_task(self._activity_check())
        self.bot.loop.create_task(self.websocket_check())

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


class Audio:
    def __init__(self, bot):
        self.bot = bot
        self.musicplayers = self.bot.playlists
        self.downloader = Downloader()

    def get_musicplayer(self, guild_id):
        musicplayer = self.musicplayers.get(guild_id)
        return musicplayer

    def find_musicplayer_from_garbage(self, guild):
        for obj in MusicPlayer.get_instances():
            if obj.channel.guild.id == guild.id:
                self.musicplayers[guild.id] = obj
                return obj

        return False

    async def check_player(self, ctx):
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer is None:
            musicplayer = self.find_musicplayer_from_garbage(ctx.guild)
            if not musicplayer:
                terminal.error('Playlist not found even when voice is playing')
                await ctx.send(f'No playlist found. Use {ctx.prefix}force_stop to reset voice state')

        return musicplayer

    @staticmethod
    def parse_seek(string: str):
        t = re.compile(r'(?P<days>\d+)*?(?:-)?(?P<hours>\d\d)?:?(?P<minutes>\d\d):(?P<seconds>\d\d)')
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
    def _seek_from_timestamp(timestamp):
        m, s = divmod(timestamp, 60)
        h, m = divmod(m, 60)
        s, ms = divmod(s, 1)

        h, m, s = str(int(h)), str(int(m)), str(int(s))
        ms = str(round(ms, 3))[2:]

        return {'h': h, 'm': m, 's': s, 'ms': ms}

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

    @command(no_pm=True, aliases=['a'], ignore_extra=True)
    @cooldown(1, 4, type=BucketType.guild)
    async def again(self, ctx):
        """Queue the currently playing song to the end of the queue"""
        await self._again(ctx)

    @command(aliases=['q', 'queue_np'], no_pm=True, ignore_extra=True)
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
            ctx: :class:`Context`

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

    async def play_song(self, ctx, song_name, priority=False, **metadata):
        success = False
        if ctx.voice_client is None:
            success = await self._summon(ctx, create_task=False)
            if not success:
                terminal.debug('Failed to join vc')
                return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        song_name, metadata = await self._parse_play(song_name, ctx, metadata)

        maxlen = -1 if ctx.author.id == self.bot.owner_id else 10
        await musicplayer.playlist.add_song(song_name, maxlen=maxlen,
                                            channel=ctx.message.channel,
                                            priority=priority, **metadata)
        if success:
            musicplayer.start_playlist()

    @command(no_pm=True, enabled=False, hidden=True)
    async def play_playlist(self, ctx, *, musicplayer):
        """Queue a saved playlist"""
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return
        await musicplayer.playlist.add_from_playlist(musicplayer, ctx.message.channel)

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
            await search(name, ctx, site, self.downloader)

    @command()
    @commands.cooldown(1, 5, type=BucketType.user)
    async def search(self, ctx, *, name):
        """Search for songs. Default site is youtube
        Supported sites: -yt Youtube, -sc Soundcloud
        To use a different site start the search with the site prefix
        e.g. {prefix}{name} -sc a cool song"""
        await self._search(ctx, name)

    async def _summon(self, ctx, create_task=True):
        if not ctx.author.voice:
            ctx.send("You aren't connected to a voice channel")
            return False

        channel = ctx.author.voice.channel

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer is None:
            musicplayer = MusicPlayer(self.bot, self.disconnect_voice, channel=ctx.channel)
            self.musicplayers[ctx.guild.id] = musicplayer
        else:
            musicplayer.change_channel(ctx.channel)

        if musicplayer.voice is None:
            musicplayer.voice = await channel.connect()
            if create_task:
                musicplayer.start_playlist()
        else:
            if channel.id != musicplayer.voice.channel.id:
                await musicplayer.voice.move_to(channel)
            elif musicplayer.voice.is_connected():
                await musicplayer.voice.channel.connect()

        return True

    @command(no_pm=True, ignore_extra=True, aliases=['summon1'])
    @cooldown(1, 3, type=BucketType.guild)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        return await self._summon(ctx)

    @cooldown(2, 5, BucketType.guild)
    @command(ignore_extra=True, no_pm=True)
    async def repeat(self, ctx, value: bool=None):
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
    @command(ignore_extra=True, no_pm=True)
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
        seek = self._seek_from_timestamp(sec)
        options = self._parse_filters(current.options, 'atempo', value)
        logger.debug('Filters parsed. Returned: {}'.format(options))
        current.options = options
        musicplayer._speed_mod = v
        await self._seek(musicplayer, current, seek, options=options, speed=v)

    @commands.cooldown(1, 5, BucketType.guild)
    @command(ignore_extra=True, no_pm=True)
    async def bass(self, ctx, value: int):
        """Add bass boost or decrease to a song.
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
        seek = self._seek_from_timestamp(sec)
        value = 'g=%s' % value
        options = self._parse_filters(current.options, 'bass', value)
        logger.debug('Filters parsed. Returned: {}'.format(options))
        current.options = options
        await self._seek(musicplayer, current, seek, options=options)

    @cooldown(1, 5, BucketType.guild)
    @command(no_pm=True, ignore_extra=True)
    async def stereo(self, ctx, mode='sine'):
        """Works almost the same way {prefix}play does
        Default stereo type is sine.
        All available modes are `sine`, `triangle`, `square`, `sawup`, `sawdown`, `left`, `right`, `off`
        To set a different mode start your command parameters with -mode song_name
        e.g. `{prefix}{name} -square stereo cancer music` would use the square mode
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
        modes = ("sine", "triangle", "square", "sawup", "sawdown", 'off', 'left', 'right')
        if mode not in modes:
            return await ctx.send('Incorrect mode specified')

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = self._seek_from_timestamp(sec)
        if mode in ('left', 'right'):
            mode = 'FL-FR' if mode == 'right' else 'FR-FL'
            options = self._parse_filters(current.options, 'channelmap', 'map={}'.format(mode))
        else:
            options = self._parse_filters(current.options, 'apulsator', 'mode={}'.format(mode), remove=(mode == 'off'))
        current.options = options
        await self._seek(musicplayer, current, seek, options=options)

    @command(no_pm=True)
    @cooldown(1, 4, type=BucketType.guild)
    async def clear(self, ctx, *, items):
        """
        Clear the selected indexes from the playlist.
        "!clear all" empties the whole playlist
        usage:
            {prefix}{name} 1-4 7-9 5
            would delete songs at positions 1 to 4, 5 and 7 to 9
        """
        musicplayer = self.get_musicplayer(ctx.guild.id)
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
        if not musicplayer or musicplayer.player is None:
            await ctx.send('No songs currently in queue')
        else:
            tr_pos = get_track_pos(musicplayer.current.duration, musicplayer.duration)
            await ctx.send(musicplayer.current.long_str + ' {0}'.format(tr_pos))

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

    @commands.cooldown(1, 60, type=BucketType.guild)
    @command(enabled=False)
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
        musicplayer.resume()

    @command(name='bpm', no_pm=True, ignore_extra=True)
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

        if musicplayer.is_playing():
            musicplayer.stop()

        try:
            if musicplayer.audio_player is not None:
                musicplayer.audio_player.cancel()

            if musicplayer.voice is not None:
                await musicplayer.voice.disconnect()
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
            await self.bot.change_presence(**self.bot.config.default_activity)

    @command(no_pm=True, ignore_extra=True)
    @cooldown(1, 6, BucketType.guild)
    async def force_stop(self, ctx):
        """
        Forces voice to be stopped no matter what state the bot is in
        as long as it's connected to voice and the internal state is in sync
        """
        try:
            res = await self.stop.callback(ctx)
        except Exception:
            res = False

        if res is False:
            if not ctx.voice_client:
                return await ctx.send('Not connected to voice')

            await ctx.voice_client.disconnect()
            await ctx.send('Disconnected')
        else:
            await ctx.send('Disconnected')

    @commands.cooldown(1, 6, BucketType.user)
    @command(no_pm=True, aliases=['stop1'], ignore_extra=True)
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return False

        await self.disconnect_voice(musicplayer)

        if not self.musicplayers:
            self.clear_cache()

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

    @cooldown(1, 5, type=BucketType.guild)
    @command(name='queue', no_pm=True, aliases=['playlist'])
    async def playlist(self, ctx, page_index: int=0):
        """Get a list of the current queue in 10 song chunks
        To skip to a certain page set the page_index arg"""

        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        playlist = list(musicplayer.playlist.playlist)  # good variable naming
        if not playlist and musicplayer.current is None:
            return await ctx.send('Nothing playing atm')

        dur = get_track_pos(musicplayer.current.duration, 0)
        response = f'Currently playing **{musicplayer.current.title}** {dur}'
        if musicplayer.current.requested_by:
            response += f' enqueued by {musicplayer.current.requested_by}\n'

        if not playlist:
            return await ctx.send(response)

        pages = []
        for i in range(0, len(playlist), 10):
            pages.append(playlist[i:i+10])

        def get_page(page, idx):
            nonlocal response
            durations = self.song_durations(musicplayer, until=idx*10+10)
            durations = durations[-10:]
            for _idx, song, dur in enumerate(zip(page, durations)):
                response += '\n{0}. **{1.title}** {0.requested_by}'.format(_idx + 1, song)
                response += ' (ETA: {0[0]}m {0[1]}s)'.format(divmod(dur, 60))

            return response

        await send_paged_message(self.bot, ctx, pages, starting_idx=page_index, page_method=get_page)

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

    @command(no_pm=True, ignore_extra=True, auth=Auth.BOT_MOD)
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
        time_left = musicplayer.current.duration - musicplayer.duration
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
            dur = musicplayer.duration
            msg = get_track_pos(musicplayer.current.duration, dur)
            await ctx.send(msg)
        else:
            await ctx.send('No songs are currently playing')

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

        elif 'playlist' in name:
            async def on_error(e):
                await ctx.send('Failed to get playlist %s' % e)

            info = await musicplayer.playlist.extract_info(name, on_error=on_error)
            if info is None:
                return

            links = await musicplayer.playlist.process_playlist(info, channel=ctx.message.channel)
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
    async def autoplaylist(self, ctx, option: str):
        """Set the autoplaylist on or off"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        option = option.lower().strip()
        if option != 'on' and option != 'off':
            await ctx.send('Autoplaylist state needs to be on or off')
            return

        if option == 'on':
            musicplayer.autoplaylist = True
        elif option == 'off':
            musicplayer.autoplaylist = False

        await ctx.send('Autoplaylist set %s' % option)

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

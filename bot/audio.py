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
import time
from collections import deque
from math import floor
import argparse

try:
    import aubio
except ImportError:
    aubio = None

from discord import Game
from discord.ext import commands

from bot.exceptions import NoCachedFileException
from bot.playlist import Playlist
from bot.globals import ADD_AUTOPLAYLIST, DELETE_AUTOPLAYLIST
from bot.song import Song
from bot.bot import command
from bot.permissions import command_usable
from utils.utilities import mean_volume, get_cached_song

logger = logging.getLogger('debug')


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
    def __init__(self, bot):
        self.play_next_song = asyncio.Event()  # Trigger for next song
        self.right_version = asyncio.Event()  # Determines if right version be played
        self.right_version_playing = asyncio.Event()
        self.voice = None  # Voice channel that this is connected to
        self.current = None  # Current song
        self.channel = None  # Channel where all the automated messages will be posted to
        self.gachi = bot.config.gachi
        self.bot = bot
        self.audio_player = None  # Main audio loop. Gets set when summon is called in :create_audio_task:
        self.volume = self.bot.config.default_volume
        self.playlist = Playlist(bot, download=True)
        self.autoplaylist = bot.config.autoplaylist
        self.volume_multiplier = bot.config.volume_multiplier
        self.messages = deque()
        self.bot.loop.create_task(self.websocket_check())

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
        print("[Debug] Creating websocket check loop")
        logger.debug("[Debug] Creating websocket check loop")

        while self.voice is not None:
            try:
                self.voice.ws.ensure_open()
                assert self.voice.ws.open
            except:
                print("[Debug] Voice websocket is %s, reconnecting" % self.voice.ws.state_name)
                logger.debug("[Debug] Voice websocket is %s, reconnecting" % self.voice.ws.state_name)
                await self.bot.reconnect_voice_client(self.voice.channel.server)
                await asyncio.sleep(4)
            finally:
                await asyncio.sleep(1)

    def create_audio_task(self):
        self.audio_player = self.bot.loop.create_task(self.play_audio())

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
        print()

    async def delete_current(self):
        if self.current is not None and self.bot.config.delete_after and not self.playlist.in_list(self.current.webpage_url):
            await self.current.delete_file()

    async def wait_for_right_version(self):
        await self.right_version_playing.wait()

    async def wait_for_not_empty(self):
        await self.playlist.not_empty.wait()

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
                song = await self.playlist.get_from_autoplaylist()

                if song is None:
                    print('[ERROR] None returned from get_from_autoplaylist. Waiting for next song')
                    return None

                else:
                    self.current = song

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

    async def play_audio(self):
        while True:
            self.play_next_song.clear()
            if self.voice is None:
                break

            if self.current is None or not self.current.seek:
                """
                users = self.voice.channel.voice_members
                users = list(filter(lambda x: not x.bot, users))
                if not users:
                    await self.voice.disconnect()
                    self.change_status(self.bot.config.game)
                    self.voice = None
                    break
                """

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
                    print('[EXCEPTION] Download unsuccessful')
                    continue

                if self.current.filename is not None:
                    file = self.current.filename
                elif self.current.url != 'None':
                    file = self.current.url
                else:
                    print('[ERROR] No valid file to be played')
                    continue

                logger.debug('Opening file with the name "{0}" and options "{1.before_options}" "{1.options}"'.format(file, self.current))

                self.current.player = self.voice.create_ffmpeg_player(file,
                                                                      after=self.on_stop,
                                                                      before_options=self.current.before_options,
                                                                      options=self.current.options)

            if self.bot.config.auto_volume and not self.current.seek and isinstance(file, str):
                db = mean_volume(file)
                if db is None or abs(db) < 0.1:
                    volume = self.volume
                else:
                    volume = self._get_volume_from_db(db)
            else:
                volume = self.volume

            self.current.player.volume = volume
            if not self.current.seek:
                dur = get_track_pos(self.current.duration, 0)
                await self.say('Now playing **{0.title}** {1} with volume at {2:.0%}'.format(self.current, dur, self.current.player.volume), self.current.duration)

            print(self.player)
            logger.debug(self.player)
            self.current.player.start()
            print('started')
            logger.debug('Started player')
            await self.change_status(self.current.title)
            logger.debug('Downloading next')
            await self.playlist.download_next()

            if self.gachi and not self.current.seek and random.random() < 0.01:
                await self.prepare_right_version()

            self.current.seek = False
            await self.play_next_song.wait()
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

        vol = self._get_volume_from_db(mean_volume(file))
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
                await self.bot.say('FUCK YOU! %s' % author)
                return

            self.player.stop()

    async def say(self, message, timeout, channel=None):
        if channel is None:
            channel = self.channel

        return await self.bot.say_timeout(message, channel, timeout)

    def pause(self):
        if self.is_playing():
            self.player.pause()

    def resume(self):
        if self.is_playing():
            self.player.resume()


class Audio:
    def __init__(self, bot, client):
        self.bot = bot
        self.voice_states = bot.voice_clients_
        self.client = client
        self.owner = bot.owner
        self.arguments = []
        options = [('-speed', {'help': 'Speeds up the audio. Value must be between 0.5 and 2'}),
                   ('-stereo', {'help': 'Plays the song with a stereo effect'})]

        self.argparser = argparse.ArgumentParser(description='Arguments that can be passed to the different play functions')
        for arg, kwargs in options:
            self.arguments.append(arg)
            self.argparser.add_argument(arg, **kwargs)

    def get_voice_state(self, server):
        state = self.voice_states.get(server.id)
        if state is None:
            state = MusicPlayer(self.bot)
            self.voice_states[server.id] = state

        return state

    @staticmethod
    def parse_seek(string: str):
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

        return '-ss {0}:{1}:{2}.{3}'.format(h.zfill(2), m.zfill(2), s.zfill(2), ms)

    @staticmethod
    def _parse_filters(options: str, filter_name: str, value: str):
        logger.debug('Parsing filters: {0}, {1}, {2}'.format(options, filter_name,value))
        matches = re.findall('%s=\w*' % filter_name, options)
        logger.debug('Filter matches: {}'.format(matches))
        if matches:
            options.replace(matches[0].strip(), '{0}={1}'.format(filter_name, value))
            return options

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

    @command(pass_context=True, no_pm=True, aliases=['a'], ignore_extra=True, level=1)
    async def again(self, ctx):
        """Queue the currently playing song to the end of the queue"""
        await self._again(ctx)

    @command(name='q', pass_context=True, no_pm=True, ignore_extra=True, level=2)
    async def queue_np(self, ctx):
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
        state = self.get_voice_state(ctx.message.server)
        if state is None or not state.is_playing():
            return

        await state.playlist.add_from_song(Song.from_song(state.current), priority)

    @commands.cooldown(4, 4)
    @command(pass_context=True, level=1)
    async def seek(self, ctx, *, where: str):
        """
        If the video is cached you can seek it using this format h m s ms,
        where at least one of them is required. Milliseconds are 100 times bigger
        so to seek only one millisecond put 001ms. Otherwise the song will just
        restart. e.g. 1h 4s and 2m1s3ms both should work.
        """
        state = self.get_voice_state(ctx.message.server)
        if state.right_version_playing.is_set():
            return

        current = state.current
        if current is None or not state.is_playing():
            return

        seek_time = self.parse_seek(where)
        run_loops = time.strptime(seek_time.split('.')[0], '-ss %H:%M:%S')[3:6]
        run_loops = int(((run_loops[0] * 60 + run_loops[1]) * 60 + run_loops[2]) * current.player.loops_per_second)
        await self._seek(ctx, state, current, seek_time, run_loops=run_loops)

    async def _seek(self, ctx, state, current, seek_command, options=None, run_loops=None):
        """
        
        Args:
            ctx: :class:`Context`
            
            state: :class:`MusicPlayer` The current MusicPlayer
            
            current: The song that we want to seek
            
            seek_command: A command that is passed to before_options
            
            options: passed to create_ffmpeg_player options
            
            run_loops: How many audio loops have we gone through. 
                       If None current.player.run_loops is used.
                       This is makes duration work after seeking.
                        
        Returns:
            None
        """
        try:
            file = get_cached_song(current.filename)
        except NoCachedFileException:
            pass
            #await self.bot.send_message(ctx.message.channel, "Cannot seek songs that haven't been cached")
            #current.seek = False
            #return

        if options is None:
            options = current.options

        if not isinstance(run_loops, int):
            run_loops = current.player.run_loops

        before_options = '-nostdin ' + seek_command
        logger.debug(':seek: Changing before options from {0} to {1}'.format(current.before_options, before_options))
        logger.debug('Seeking with command {0} and these options: before_options="{1}", options="{2}"'.format(seek_command, before_options, options))
        current.seek = True
        volume = current.player.volume
        current.player.stop()

        new_player = state.voice.create_ffmpeg_player(current.filename, after=state.on_stop,
                                                      before_options=before_options,
                                                      options=options,
                                                      run_loops=run_loops)

        state.current.player = new_player
        state.current.player.volume = volume
        state.current.player.start()
        state.current.seek = False

    @command(pass_context=True, ignore_extra=True, no_pm=True, level=2)
    async def speed(self, ctx, value: str):
        channel = ctx.message.channel
        try:
            v = float(value)
            if v > 2 or v < 0.5:
                return await self.bot.say_timeout('Value must be between 0.5 and 2',
                                                  channel, 60)
        except ValueError as e:
            return await self.bot.say_timeout('{0} is not a number\n{1}'.format(value, e),
                                              channel, 60)

        state = self.get_voice_state(ctx.message.server)
        current = state.current
        if current is None:
            return await self.bot.say_timeout('Not playing anything right now',
                                              channel, 60)
        sec = state.player.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = self._seek_from_timestamp(sec)
        options = self._parse_filters(current.options, 'atempo', value)
        logger.debug('Filters parsed. Returned: {}'.format(options))

        await self._seek(ctx, state, current, seek, options=options)

    def get_args(self, s):
        args = []
        if not s.startswith('-'):
            return args, s

        s = s.split(' ')
        is_option = False
        for word in s:
            if word.startswith('-') and word in self.arguments:
                is_option = True
                args.append(word)
                continue
            elif is_option:
                is_option = False
                args.append(word)
                continue
            break

        return args, s[len(args):]

    async def _parse_play(self, string, ctx, metadata=None, permissions=None):
        options = {}
        filters = []
        channel = ctx.message.channel
        if metadata and 'filter' in metadata:
            filters.append(metadata['filter'])

        args, s = self.get_args(string)
        args, unknown = self.argparser.parse_known_args(args)
        song_name = ' '.join(unknown) + s
        if args.speed:
            try:
                speed = float(args.speed)
                if not 0.5 <= speed >= 2.0:
                    filters.append('atempo={}'.format(args.speed))
                else:
                    await self.bot.say_timeout('Speed value must be between 0.5 and 2', channel, 90)
            except ValueError as e:
                await self.bot.say_timeout('%s\nIgnoring options -speed' % e, channel, 90)

        if args.stereo:
            if permissions is None:
                filters.append('apulsator')

        if filters:
            options['filter'] = '-filter:a "{}"'.format(', '.join(filters))

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

        logger.debug('Parse play returned {0}, {1}'.format(song_name, metadata))
        return song_name, metadata

    @command(pass_context=True, no_pm=True, level=1)
    @commands.cooldown(4, 4)
    async def play(self, ctx, *, song_name: str):
        """Put a song in the playlist. If you put a link it will play that link and
        if you put keywords it will search youtube for them"""
        return await self.play_song(ctx, song_name)

    async def play_song(self, ctx, song_name, **metadata):
        state = self.get_voice_state(ctx.message.server)

        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        song_name, metadata = await self._parse_play(song_name, ctx, metadata)
        return await state.playlist.add_song(song_name, maxlen=ctx.user_permissions.max_playlist_length, **metadata)

    @command(pass_context=True, no_pm=True, level=2)
    async def play_playlist(self, ctx, *, playlist):
        """Queue a saved playlist"""
        state = self.get_voice_state(ctx.message.server)
        await state.playlist.add_from_playlist(playlist, ctx.message.channel)

    @command(pass_context=True, level=1)
    async def search(self, ctx, *, name):
        """Search for songs. Default site is youtube
        Supported sites: -yt Youtube, -sc Soundcloud"""
        state = self.get_voice_state(ctx.message.server)

        if name.startswith('-yt '):
            site = 'yt'
            name = name.split('-yt ', 1)[1]
        elif name.startswith('-sc '):
            site = 'sc'
            name = name.split('-sc ', 1)[1]
        else:
            site = 'yt'

        result = await state.playlist.search(name, ctx, site)

        if result and state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

    @command(pass_context=True, no_pm=True, ignore_extra=True, aliases=['summon1'], level=1)
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.send_message(ctx.message.channel, 'You are not in a voice channel')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            state.voice = await self.bot.join_voice_channel(summoned_channel)
            state.create_audio_task()
        else:
            await state.voice.move_to(summoned_channel)

        state.channel = ctx.message.channel
        state.playlist.channel = ctx.message.channel
        return True

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, level=2)
    async def stereo(self, ctx, *, song_name: str):
        """
        Works the same way !play does
        <<--
         -->>
         <<--
         -->>
         """
        options = {'filter': 'apulsator'}
        await self.play_song(ctx, song_name, **options)

    @command(pass_context=True, no_pm=True, level=4)
    async def clear(self, ctx, *, items):
        """
        Clear the selected indexes from the playlist.
        "!clear all" empties the whole playlist
        """
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

        state = self.get_voice_state(ctx.message.server)
        await state.playlist.clear(index)

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, aliases=['vol'], level=1)
    async def volume(self, ctx, value: int=-1):
        """
        Sets the volume of the currently playing song.
        If no parameters are given it shows the current volume instead
        """
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            player = state.player

            # If value is smaller than zero or it hasn't been given this shows the current volume
            if value < 0:
                await self.bot.say('Volume is currently at {:.0%}'.format(player.volume))
                return

            player.volume = value / 100
            state.volume = value / 100
            await self.bot.say_timeout('Set the volume to {:.0%}'.format(player.volume), ctx.message.channel, 60)

    @commands.cooldown(1, 4)
    @command(pass_context=True, no_pm=True, aliases=['np'])
    async def playing(self, ctx):
        """Gets the currently playing song"""
        state = self.get_voice_state(ctx.message.server)
        if state.current is None:
            await self.bot.say('No songs currently in queue')
        else:
            tr_pos = get_track_pos(state.current.duration, state.player.duration)
            await self.bot.say_timeout(str(state.current) + ' {0}'.format(tr_pos),
                                       ctx.message.channel, state.current.duration)

    @commands.cooldown(4, 4)
    @command(name='playnow', pass_context=True, no_pm=True, level=2)
    async def play_now(self, ctx, *, song_name: str):
        """
        Sets a song to the priority queue which is played as soon as possible
        after the other songs in that queue.
        """
        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        song_name, metadata = await self._parse_play(song_name, ctx)
        await state.playlist.add_song(song_name, priority=True,
                                      maxlen=ctx.user_permission.max_playlist_length,
                                      **metadata)

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, aliases=['p'])
    async def pause(self, ctx):
        """Pauses the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        state.pause()

    @commands.cooldown(1, 60)
    @command(pass_context=True, level=1)
    async def save_playlist(self, ctx, *name):
        if name:
            name = ' '.join(name)

        state = self.get_voice_state(ctx.message.server)
        await state.playlist.current_to_file(name, ctx.message.channel)

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, aliases=['r'])
    async def resume(self, ctx):
        """Resumes the currently played song."""
        state = self.get_voice_state(ctx.message.server)
        state.resume()

    @command(name='bpm', pass_context=True, no_pm=True, ignore_extra=True, level=1)
    async def bpm(self, ctx):
        """Gets the currently playing songs bpm using aubio"""
        if not aubio:
            return await self.bot.say_timeout('BPM is not supported', ctx.message.channel, 100)

        state = self.get_voice_state(ctx.message.server)
        song = state.current
        channel = ctx.message.channel
        if not state.is_playing() or not song:
            return

        if song.bpm:
            return await self.bot.say_timeout('BPM for {} is about **{}**'.format(song.title, song.bpm), channel, 90)

        if song.duration == 0:
            return await self.bot.say_timeout('Cannot determine bpm because duration is 0', channel, 90)

        import subprocess
        import shlex
        file = song.filename
        tempfile = os.path.join(os.getcwd(), 'data', 'temp', 'tempbpm.wav')
        cmd = 'ffmpeg -i "{}" -f wav -t 00:10:00 -map_metadata -1 -loglevel warning pipe:1'.format(file)
        args = shlex.split(cmd)
        try:
            p = subprocess.Popen(args, stdout=subprocess.PIPE)
        except Exception as e:
            print(e)
            return await self.bot.say_timeout('Error while getting bpm', channel, 60)

        from utils.utilities import write_wav

        write_wav(p.stdout, tempfile)

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
            return await self.bot.say('BPM for {} is about **{}**'.format(song.title, round(bpm, 1)))
        finally:
            try:
                s.close()
            except:
                pass
            os.remove(tempfile)

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, level=1)
    async def shuffle(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        await state.playlist.shuffle()
        await self.bot.send_message(state.channel, 'Playlist shuffled')

    async def shutdown(self):
        keys = list(self.voice_states.keys())
        for key in keys:
            state = self.voice_states[key]
            await self.stop_state(state)
            del self.voice_states[key]

        self.clear_cache()

    @staticmethod
    async def stop_state(state):
        if state is None:
            return

        if state.is_playing():
            player = state.player
            player.stop()

        try:
            state.autoplaylist = False
            if state.audio_player is not None:
                state.audio_player.cancel()

            if state.voice is not None:
                await state.voice.disconnect()
                state.voice = None

        except Exception as e:
            print('[ERROR] Error while stopping voice.\n%s' % e)

    @command(pass_context=True, no_pm=True, aliases=['stop1'])
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        state = self.get_voice_state(ctx.message.server)

        await self.stop_state(state)
        await self.bot.change_presence(game=Game(name=self.bot.config.game))
        del self.voice_states[ctx.message.server.id]
        self.clear_cache()

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, aliases=['skipsen', 'skipperino', 's'], level=1)
    async def skip(self, ctx):
        """Skips the current song"""
        state = self.get_voice_state(ctx.message.server)
        if not state.is_playing():
            await self.bot.send_message(ctx.message.channel,
                                        'Not playing any music right now...')
            return

        await state.skip(ctx.message.author)

    @commands.cooldown(1, 3)
    @command(pass_context=True, no_pm=True)
    async def playlist(self, ctx, index=None):
        """Get a list of the 10 next songs in the playlist or how long it will take to reach a certain song
        Usage !playlist or !playlist [song index]"""
        state = self.get_voice_state(ctx.message.server)
        playlist = list(state.playlist.playlist)
        channel = ctx.message.channel

        if index is not None:
            try:
                index = int(index)
            except ValueError:
                return self.bot.say_timeout('Index must be an integer', channel, 60)

            time_left = self.list_length(state, index)
            if not time_left:
                return await self.bot.say_timeout('Empty playlist')

            try:
                song = playlist[index - 1]
            except IndexError:
                return await self.bot.say_timeout('No songs at that index', channel, 60)

            message = 'Time until **{0.title}** is played: {1[0]}m {1[1]}s'.format(song, divmod(floor(time_left), 60))
            return await self.bot.send_message(channel, message)

        response = 'No songs in queue'
        expected_time = 0
        if state.current is not None:
            response = 'Currently playing **%s**\n' % state.current.title
            if state.player:
                expected_time = state.current.duration - state.player.duration

        if not playlist:
            return await self.bot.send_message(channel, response)

        for idx, song in enumerate(playlist[:10]):
            response += '\n{0}. **{1.title}**'.format(idx + 1, song)
            if song.duration > 0 and expected_time is not None:
                response += ' (ETA: {0[0]}m {0[1]}s)'.format(divmod(floor(expected_time), 60))
                expected_time += song.duration
            else:
                expected_time = None

        other = len(playlist) - 10
        if other > 0:
            response += '\nand **%s** more' % other

        return await self.bot.send_message(channel, response)

    @commands.cooldown(1, 3)
    @command(pass_context=True, no_pm=True, aliases=['len'])
    async def length(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if state.current is None or not state.playlist.playlist:
            return await self.bot.send_message(ctx.message.channel, 'No songs in queue')

        time_left = self.list_length(state)
        minutes, seconds = divmod(floor(time_left), 60)
        hours, minutes = divmod(minutes, 60)

        return await self.bot.send_message(ctx.message.channel, 'The length of the playlist is about {0}h {1}m {2}s'.format(hours, minutes, seconds))

    @command(pass_context=True, no_pm=True, ignore_extra=True, level=2)
    async def ds(self, ctx):
        perms = ctx.user_permissions
        if command_usable(perms, self.skip) and command_usable(perms, self.delete_from_ap):
            await ctx.invoke(self.skip)
            await ctx.invoke(self.delete_from_ap)

    @staticmethod
    def list_length(state, index=None):
        playlist = state.playlist
        if not playlist:
            return
        time_left = state.current.duration - state.player.duration
        for song in list(playlist)[:index]:
            time_left += song.duration

        return time_left

    @commands.cooldown(4, 4)
    @command(pass_context=True, no_pm=True, aliases=['dur'])
    async def duration(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            dur = state.player.duration
            msg = get_track_pos(state.current.duration, dur)
            await self.bot.send_message(ctx.message.channel, msg)
        else:
            await self.bot.send_message(ctx.message.channel, 'No videos are currently playing')

    @command(name='volm', pass_context=True, no_pm=True, level=1)
    async def vol_multiplier(self, ctx, value=None):
        state = self.get_voice_state(ctx.message.server)
        if not value:
            return await self.bot.say('Current volume multiplier is %s' % str(state.volume_multiplier))
        try:
            value = float(value)
            state.volume_multiplier = value
            await self.bot.say('Volume multiplier set to %s' % str(value))
        except ValueError:
            await self.bot.say_timeout('Value is not a number', ctx.message.channel, 30)

    @command(pass_context=True, no_pm=True)
    async def link(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        current = state.current
        await self.bot.send_message(ctx.message.channel, 'Link to **{0.title}**: {0.webpage_url}'.format(current))

    @commands.cooldown(1, 4)
    @command(name='delete', pass_context=True, no_pm=True, aliases=['del', 'd'], level=2)
    async def delete_from_ap(self, ctx, *name):
        state = self.get_voice_state(ctx.message.server)
        if not name:
            name = [state.current.webpage_url]

            if name is None:
                print('[INFO] No name specified in delete_from')
                await state.say('No song to delete', 30, ctx.message.channel)
                return

        with open(DELETE_AUTOPLAYLIST, 'a', encoding='utf-8') as f:
            f.write(' '.join(name) + '\n')

        print('[INFO] Added entry %s to the deletion list' % name)
        await state.say('Added entry %s to the deletion list' % ' '.join(name), 30, ctx.message.channel)

    @commands.cooldown(1, 4)
    @command(name='add', pass_context=True, no_pm=True, level=2)
    async def add_to_ap(self, ctx, *name):
        state = self.get_voice_state(ctx.message.server)
        if name:
            name = ' '.join(name)
        if not name:
            current = state.current
            if current is None or current.webpage_url is None:
                print('[INFO] No name specified in add_to')
                await state.say('No song to add', 30, ctx.message.channel)
                return

            data = current.webpage_url
            name = data

        elif 'playlist' in name:
            info = await state.playlist.extract_info(name)
            if info is None:
                return

            links = await state.playlist.process_playlist(info)
            if links is None:
                await self.bot.say_timeout('Incompatible playlist')

            data = '\n'.join(links)

        else:
            data = name

        with open(ADD_AUTOPLAYLIST, 'a', encoding='utf-8') as f:
            f.write(data + '\n')

        print('[INFO] Added entry %s' % name)
        await state.say('Added entry %s' % name, 30, ctx.message.channel)

    @command(pass_context=True, no_pm=True, level=1)
    async def autoplaylist(self, ctx, option: str):
        """Set the autoplaylist on or off"""
        state = self.get_voice_state(ctx.message.server)
        option = option.lower().strip()
        if option != 'on' and option != 'off':
            await self.bot.send_message(ctx.message.channel, 'Autoplaylist state needs to be on or off')

        if option == 'on':
            state.autoplaylist = True
        elif option == 'off':
            state.autoplaylist = False

        return await self.bot.send_message(ctx.message.channel, 'Autoplaylist set %s' % option)

    def clear_cache(self):
        songs = []
        for state in self.voice_states.values():
            for song in state.playlist.playlist:
                songs += [song.id]
        cachedir = os.path.join(os.getcwd(), 'data', 'audio', 'cache')
        files = os.listdir(cachedir)

        def check_list(string):
            global song
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
                except Exception:
                    pass

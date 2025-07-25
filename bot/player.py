import asyncio
import logging
import shlex
import time
import weakref
from collections import deque
from math import ceil, floor
from typing import Optional, override

import disnake
from disnake import AllowedMentions, opus, player
from disnake.activity import Activity
from disnake.enums import ActivityType
from disnake.errors import ClientException, HTTPException
from disnake.ext.commands.cooldowns import BucketType, CooldownMapping
from disnake.opus import Encoder as OpusEncoder
from disnake.player import PCMVolumeTransformer

from bot.playlist import Playlist
from bot.song import Song
from bot.youtube import get_related_vids, id2url, url2id
from utils.timedset import TimedSet
from utils.utilities import mean_volume, seek_from_timestamp, seek_to_sec

log = logging.getLogger('discord')
logger = logging.getLogger('audio')
terminal = logging.getLogger('terminal')


def format_time(duration):
    m, s = divmod(floor(duration), 60)
    h, m = divmod(m, 60)
    m = str(m)

    if h > 0:
        m = '{}:{}'.format(str(h), m.zfill(2))

    return f'{m}:{str(s).zfill(2)}'


def get_track_pos(duration, current_pos):
    return f'`[{format_time(current_pos)}/{format_time(duration)}]`'


class MusicPlayer:
    __instances__ = weakref.WeakSet()

    @classmethod
    def get_instances(cls):
        for inst in cls.__instances__:
            yield inst

    def __init__(self, bot, disconnect, channel, downloader=None):
        self.__instances__.add(self)
        self.bot = bot
        self.play_next = asyncio.Event()
        self.voice: Optional[disnake.VoiceClient] = None
        self.current = None
        self.channel = channel
        self.guild = channel.guild
        self.repeat = False
        self._disconnect = disconnect

        # With BucketType.default we can call get_bucket with msg param set to None
        # Determines an error rate at which we disconnect
        self._spam_detector = CooldownMapping.from_cooldown(3, 10, BucketType.default)

        self.playlist: Playlist = Playlist(bot, channel=self.channel, downloader=downloader)
        self.autoplaylist = bot.config.autoplaylist
        self.autoplay = False  # Youtube autoplay
        self.volume = self.bot.config.default_volume
        self.volume_multiplier = bot.config.volume_multiplier
        self.audio_player = None
        self.activity_check = None
        self._speed_mod = 1
        self._skip_votes = set()
        self._stop_votes = TimedSet(loop=self.bot.loop)
        self.persistent_filters = {}
        self.gapless = False

    def __del__(self):
        self.close_tasks()
        if self.voice:
            asyncio.ensure_future(self.voice.disconnect(), loop=self.bot.loop)

    def change_channel(self, channel):
        self.channel = channel
        self.playlist.channel = channel

    def close_tasks(self):
        """Kills the running tasks"""
        if self.audio_player:
            self.audio_player.cancel()
        if self.activity_check:
            self.activity_check.cancel()

        self._stop_votes.clear()

    def is_alive(self):
        return self.is_playing() or self.voice is not None or (self.audio_player and not self.audio_player.done())

    def start_playlist(self):
        self.close_tasks()

        self.audio_player = self.bot.loop.create_task(self._play_audio())
        self.activity_check = self.bot.loop.create_task(self._activity_check())

    def selfdestruct(self):
        self.repeat = False
        self.autoplay = False
        self.gapless = False
        self.stop()
        if self.voice:
            asyncio.ensure_future(self.voice.disconnect(force=True), loop=self.bot.loop)
        self.close_tasks()
        self.voice = None
        self.playlist.playlist.clear()

    @property
    def history(self):
        return self.playlist.history

    @property
    def last(self):
        if self.history:
            return self.history[-1]

    @property
    def speed_mod(self):
        return self.player._speed_mod

    @property
    def source(self):
        if self.player:
            return self.player.source

    @property
    def player(self) -> Optional['AudioPlayer']:
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
        # vol = volm/rms
        return rms, self.volume_multiplier/rms

    async def assert_functionality(self):
        """
        Returns:
            Boolean determining if we are getting songs correctly or if we are getting too many errors
        """
        retry_after = self._spam_detector.update_rate_limit(None)
        if retry_after:
            await self.send('Looks like something is wrong with playback. Disconnecting.\n'
                            'If this continues contact owner lol')

            async def stop():
                if self.activity_check:
                    self.activity_check.cancel()
                await self._disconnect(self)
                self.voice = None

            # We need the background task because calling disconnect will
            # cancel audio loop which will stop every function called inside it
            # this one and disconnect included
            self.bot.loop.create_task(stop())
            return False

        return True

    async def set_mean_volume(self, file):
        try:
            # Don't want mean volume from livestreams
            if self.current.is_live:
                return

            db = await asyncio.wait_for(mean_volume(file, self.bot.loop, self.bot.threadpool,
                                        duration=self.current.duration), timeout=20)
            if db is not None and abs(db) >= 0.1:
                rms, volume = self._get_volume_from_db(db)
                logger.debug(f'parsed volume {volume}')
                self.current_volume = volume
                self.current.rms = rms

        except asyncio.TimeoutError:
            logger.debug('Mean volume timed out')
        except asyncio.CancelledError:
            pass

    async def _activity_check(self):
        async def stop():
            self.__instances__.discard(self)
            if self.audio_player:
                self.audio_player.cancel()
            await self._disconnect(self)
            self.voice = None

        while True:
            await asyncio.sleep(60)
            if self.voice is None or self.audio_player is None or self.audio_player.done():
                return await stop()

            users = self.voice.channel.members
            users = list(filter(lambda x: not x.bot, users))
            if not users:
                await stop()
                await self.send('No voice activity. Disconnecting')
                return

    async def _play_audio(self):
        while self.voice and self.voice.is_connected():
            self.play_next.clear()
            if self.current is None:
                if self.playlist.peek() is None:
                    if self.autoplay and self.last:
                        vid_id = url2id(self.last.webpage_url)
                        history = [url2id(s.webpage_url) for s in self.history]
                        vid_id = await get_related_vids(vid_id, filtered=history)
                        if not vid_id:
                            self.autoplay = False
                            await self.send("Couldn't find autoplay video. Stopping autoplay")
                            continue

                        self.current = await self.playlist.get_from_url(id2url(vid_id))
                        if not self.current.success:
                            self.autoplay = False
                            await self.send('Failed to dl video. Stopping autoplay')
                            self.current = None
                            continue

                    elif self.autoplaylist:
                        self.current = await self.playlist.get_from_autoplaylist()
                        # Autoplaylist was empty?
                        if self.current is None:
                            self.autoplaylist = False
                            await self.send("Couldn't get video from autoplaylist. Setting it off")
                            continue

                        if self.current is False:
                            self.current = None
                            # Failed to download autoplaylist song. Check that we are functioning
                            if not await self.assert_functionality():
                                continue

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

            if not self.current.downloading and not self.current.success:
                await self.current.download()

            logger.debug(f'Next song is {self.current}')
            logger.debug('Waiting for dl')

            logger.info(f'{self.bot.loop} : {asyncio.get_running_loop()}')

            try:
                await asyncio.wait_for(self.current.on_ready.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.debug(f'Song {self.current.webpage_url} download timed out')
                await self.send(f'Download timed out for {self.current}')
                self.current = None
                continue

            logger.debug('Done waiting')
            if not self.current.success:
                terminal.error(f'Download of {self.current.webpage_url} unsuccessful')
                self.current = None
                if not await self.assert_functionality():
                    return
                continue

            if self.current.filename is not None:
                file = self.current.filename
            elif self.current.url != 'None':
                file = self.current.url
            else:
                # This block doesn't really need to have the functionality check
                # since it's a rare error
                terminal.error('No valid file to be played')
                await self.send('No valid file to be played')
                continue

            logger.debug(f'Opening file with the name "{file}" and options "{self.current.before_options}" "{self.current.options}"')
            # Dynamically set bitrate based on channel bitrate
            self.current.bitrate = max(self.voice.channel.bitrate//1000, 128)

            for k, v in self.persistent_filters.items():
                self.current.set_filter(k, v)

            options = self.current.options
            logger.debug(f'Starting song with options {options}')
            source = FFmpegPCMAudio(file, before_options=self.current.before_options,
                                          options=options)
            source = PCMVolumeTransformer(source, volume=self.volume)
            if self.current.volume is None and self.bot.config.auto_volume and isinstance(file, str) and not self.current.is_live:
                volume_task = asyncio.ensure_future(self.set_mean_volume(file))
            else:
                volume_task = None

            if not self.current.volume:
                self.current_volume = self.volume
            else:
                source.volume = self.current.volume

            dur = get_track_pos(self.current.duration, 0)
            s = 'Now playing **{0.title}** {1} with volume at {2:.0%}'.format(self.current, dur, source.volume)
            if self.current.requested_by:
                s += f' enqueued by {self.current.requested_by.mention}'
            await self.send(s, delete_after=self.current.duration)

            if not self.gapless or not self.player or not self.player.is_gapless:
                await self.skip(None)
                play(self.voice, source, after=self.on_stop, speed=speed,
                     bitrate=self.current.bitrate)

            logger.debug('Started player')
            await self.change_status(self.current.title)
            logger.debug('Downloading next')

            nxt = await self.playlist.download_next()
            if self.gapless and nxt and self.player:
                if not await self.assert_functionality():
                    return

                self.player.is_gapless = True
                nxt.volume = self.current_volume
                self.player.sources.append(self.create_source(nxt))

            await self.play_next.wait()

            self.history.append(self.current)
            if not self.repeat:
                self.current = None
                if volume_task is not None:
                    volume_task.cancel()

            self._skip_votes = set()

    def create_source(self, song: Song):
        for k, v in self.persistent_filters.items():
            song.set_filter(k, v)

        file = song.url
        options = song.options
        logger.debug(f'Creating source with options {options}')
        source = FFmpegPCMAudio(file,
                                before_options=song.before_options,
                                options=options)
        return PCMVolumeTransformer(source, volume=self.volume)

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
            await channel.send(msg, allowed_mentions=AllowedMentions.none(), **kwargs)
        except HTTPException:
            pass

    def is_playing(self):
        if self.voice is None or not self.voice.is_connected():
            return False

        return True

    def pause(self):
        if self.is_playing():
            self.voice.pause()

    async def resume(self):
        if self.is_playing() and self.voice.is_paused():
            url = self.current.url
            await self.current.validate_url()
            if url != self.current.url:
                # If url changed during validation reconnect
                seek = seek_from_timestamp(self.duration)
                self.player.seek(self.current.filename, seek,
                                 before_options=self.current.before_options,
                                 options=self.current.options)

            self.voice.resume()

    async def votestop(self, author):
        """
        Checks if the bot will be stopped by vote
        """
        self._stop_votes.add(author.id)
        users = self.voice.channel.members
        users = len(list(filter(lambda x: not x.bot, users)))
        required_votes = ceil(users*0.6)
        if len(self._stop_votes) >= required_votes:
            return True

        return f'{len(self._stop_votes)}/{required_votes}'

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

                    await self.send(f'{len(self._skip_votes)}/{required_votes} until skip', channel=messageable)

            else:
                self.voice.stop()

    def stop(self):
        if self.voice:
            self.voice.stop()

    async def reset_gapless(self):
        if not self.gapless:
            if self.player:
                self.player.is_gapless = False
            return

        nxt = await self.playlist.download_next()
        if nxt and self.player:
            self.player.sources.clear()

            self.player.is_gapless = True
            nxt.volume = self.current_volume
            self.player.sources.append(self.create_source(nxt))


class FFmpegPCMAudio(player.FFmpegPCMAudio):
    """An audio source from FFmpeg (or AVConv).

    This launches a sub-process to a specific input file given.

    .. warning::

        You must have the ffmpeg or avconv executable in your path environment
        variable in order for this to work.

    Parameters
    ------------
    source: Union[str, BinaryIO]
        The input that ffmpeg will take and convert to PCM bytes.
        If ``pipe`` is True then this is a file-like object that is
        passed to the stdin of ffmpeg.
    executable: str
        The executable name (and path) to use. Defaults to ``ffmpeg``.
    pipe: bool
        If true, denotes that ``source`` parameter will be passed
        to the stdin of ffmpeg. Defaults to ``False``.
    stderr: Optional[BinaryIO]
        A file-like object to pass to the Popen constructor.
        Could also be an instance of ``subprocess.PIPE``.
    options: Optional[str]
        Extra command line arguments to pass to ffmpeg after the ``-i`` flag.
    before_options: Optional[str]
        Extra command line arguments to pass to ffmpeg before the ``-i`` flag.
    after_input: Optional[str]
        Extra command line arguments to pass to ffmpeg right after the ``-i source`` flag.
    reconnect: Optional[bool]
        Makes ffmpeg try reconnecting when connection to network stream is lost

    Raises
    --------
    ClientException
        The subprocess failed to be created.
    """
    def __init__(self, source, *, executable='ffmpeg', pipe=False, stderr=None,
                 before_options=None, after_input=None, options=None,
                 reconnect: bool = True):

        args = []
        subprocess_kwargs = {'stdin': source if pipe else None, 'stderr': stderr}

        if reconnect:
            args.extend(('-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5'))

        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))

        args.append('-i')
        args.append('-' if pipe else source)

        if isinstance(after_input, str):
            args.extend(shlex.split(after_input))

        args.extend(('-f', 's16le',
                     '-ar', '48000',
                     '-ac', '2',
                     '-loglevel', 'warning'))

        if isinstance(options, str):
            args.extend(shlex.split(options))

        args.append('pipe:1')

        # skipcq: PYL-E1003
        # This is an intentional choice since we don't wanna call the parent
        # init but instead the init of its parent
        super(player.FFmpegPCMAudio, self).__init__(source, executable=executable,
                                                    args=args, **subprocess_kwargs)

    @override
    def read(self) -> bytes:
        ret = self._stdout.read(OpusEncoder.FRAME_SIZE)
        if len(ret) != OpusEncoder.FRAME_SIZE:
            logger.info(f'FFmpegPCMAudio read returned less than expected, probably EOF. length: {len(ret)}, expected: {OpusEncoder.FRAME_SIZE}')
            return b""
        return ret


class AudioPlayer(player.AudioPlayer):
    DELAY = OpusEncoder.FRAME_LENGTH / 1000.0
    BUFFER_SIZE = 5

    def __init__(self, source, client, *, after=None, run_loops=0, frameskip=3, speed_mod=1):
        self.sources = []
        if isinstance(source, list):
            self.sources = source
            source = self.sources.pop(0)

        super().__init__(source, client, after=after)
        self._run_loops = run_loops
        self.frameskip = frameskip
        self._speed_mod = speed_mod
        self.sfx_source = None

        self.bitrate = OpusEncoder.FRAME_SIZE / self.DELAY

        self.is_gapless = bool(self.sources)
        self._data_buffer = deque()
        self._loop_offset = 0

    def _read(self):
        # If gapless mode is not activated just read from stream normally
        if not self.is_gapless:
            return self.source.read()

        # If gapless mode is on we want to have a buffer to have a smooth switch
        # to the other track. Thus we need to manage the buffer here.
        while len(self._data_buffer) < self.BUFFER_SIZE:
            data = self.source.read()
            if not data:
                if not self.sources:
                    if self._data_buffer:
                        return self._data_buffer.popleft()
                    return

                self._loop_offset = self.BUFFER_SIZE
                self.source = self.sources.pop(0)
                continue
            self._data_buffer.append(data)

        if self._loop_offset > 0:
            self._loop_offset -= 1
            if self._loop_offset == 0:
                self._run_loops = 0
                self.after(None)

        if self._data_buffer:
            return self._data_buffer.popleft()
        return

    def _do_run(self):
        self.loops = 0
        self._start = time.perf_counter()
        frameskip = 0
        # getattr lookup speed ups
        play_audio = self.client.send_audio_packet
        self._speak(True)

        while not self._end.is_set():
            # are we paused?
            if not self._resumed.is_set():
                # wait until we aren't
                self._resumed.wait()
                continue

            # are we disconnected from voice?
            if not self._connected.is_set():
                # wait until we are connected
                self._connected.wait()
                # reset our internal data
                self.loops = 0
                self._start = time.perf_counter()

            self.loops += 1
            data = self._read()

            """
            # sfx in one audio loop
            if self.sfx_source:
                data2 = self.sfx_source.read()
                if not data2:
                    self.sfx_source.cleanup()
                    self.sfx_source = None
                    data2 = None
                    
            if data2:
                data = audioop.add(data, data2, 2)
            """

            if frameskip > 0:
                frameskip -= 1
                self._run_loops += 1
                continue

            if not data:
                self.stop()
                break

            play_audio(data, encode=not self.source.is_opus())
            self._run_loops += 1
            next_time = self._start + self.DELAY * self.loops
            delay = max(0, self.DELAY + (next_time - time.perf_counter()))
            if delay < 0:
                frameskip = min(self.frameskip, abs(int(delay/self.DELAY)))
                continue
            time.sleep(delay)

    def _call_after(self):
        if self.after is not None:
            try:
                self.after(self._current_error)
            except Exception:
                log.exception('Calling the after function failed.')

    @property
    def run_loops(self):
        return self._run_loops * self._speed_mod

    @property
    def duration(self):
        return self.run_loops * self.DELAY

    @property
    def loops_per_second(self):
        return self.bitrate / OpusEncoder.FRAME_SIZE

    def seek(self, f, seek_dict, before_options='', options='', speed=None):
        seek_dict = {k: v.zfill(2) if k != 'ms' else v for k, v in seek_dict.items()}
        seek_time = ' -ss {0[h]}:{0[m]}:{0[s]}.{0[ms]}'.format(seek_dict)

        if not before_options:
            before_options = f'-nostdin {seek_time}'
        else:
            before_options += seek_time

        new_source = FFmpegPCMAudio(f, before_options=before_options,
                                    options=options)

        volume = getattr(self.source, 'volume', 0.15)
        new_source = player.PCMVolumeTransformer(new_source, volume=volume)

        run_loops = seek_to_sec(seek_dict) * self.loops_per_second
        if speed:
            run_loops = run_loops // speed
        elif self._speed_mod != 1:
            run_loops = run_loops // self._speed_mod

        self.set_source(new_source, run_loops, speed)

    def _set_source(self, source, run_loops=None, speed=None):  # skipcq: PYL-W0221
        with self._lock:
            self.pause()
            if run_loops is not None:
                self._run_loops = run_loops

            if speed:
                self._speed_mod = speed

            self.source = source
            self.resume()

    def set_source(self, source, run_loops=None, speed=None):
        old = self.source
        self._set_source(source, run_loops, speed)
        del old


def play(voice_client, source, *, after=None, speed=1, bitrate=128):
    """Plays an :class:`AudioSource`.
    Uses a custom AudioPlayer class

    The finalizer, ``after`` is called after the source has been exhausted
    or an error occurred.

    If an error happens while the audio player is running, the exception is
    caught and the audio player is then stopped.

    Parameters
    -----------
    voice_client: :class:`VoiceClient`
        The voice_client we are working with
    source: :class:`AudioSource`
        The audio source we're reading from.
    after
        The finalizer that is called after the stream is exhausted.
        All exceptions it throws are silently discarded. This function
        must have a single parameter, ``error``, that denotes an
        optional exception that was raised during playing.
    speed
        The speed at which the audio is playing
    bitrate
        Bitrate of the audio playing

    Raises
    -------
    ClientException
        Already playing audio or not connected.
    TypeError
        source is not a :class:`AudioSource` or after is not a callable.
    """

    if not voice_client._connected:
        raise ClientException('Not connected to voice.')

    if voice_client.is_playing():
        raise ClientException('Already playing audio.')

    if not isinstance(source, player.AudioSource):
        raise TypeError('source must an AudioSource not {0.__class__.__name__}'.format(source))

    if not voice_client.encoder and not source.is_opus():
        voice_client.encoder = opus.Encoder()

    voice_client.encoder.set_bitrate(bitrate)

    voice_client._player = AudioPlayer(source, voice_client, after=after, speed_mod=speed)
    voice_client._player.start()

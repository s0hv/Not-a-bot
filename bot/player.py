import logging
import shlex
import subprocess
import time

from discord import player
from discord.errors import ClientException
from discord.opus import Encoder as OpusEncoder

log = logging.getLogger('discord')


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
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def create_ffmpeg_player(self, source, *, executable='ffmpeg', pipe=False, stderr=None,
                             before_options=None, after_input=None, options=None, reconnect=True):
        stdin = None if not pipe else source
        args = [executable]
        if reconnect:
            args.extend(('-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5'))

        if isinstance(before_options, str):
            args.extend(shlex.split(before_options))

        args.append('-i')
        args.append('-' if pipe else source)

        if isinstance(after_input, str):
            args.extend(shlex.split(after_input))

        args.extend(('-f', 's16le', '-ar', '48000', '-ac', '2', '-loglevel', 'error'))

        if isinstance(options, str):
            args.extend(shlex.split(options))

        args.append('pipe:1')

        self._process = None
        try:
            self._process = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr)
            self._stdout = self._process.stdout
        except FileNotFoundError:
            raise ClientException(executable + ' was not found.') from None
        except subprocess.SubprocessError as e:
            raise ClientException('Popen failed: {0.__class__.__name__}: {0}'.format(e)) from e

    def read(self):
        ret = self._stdout.read(OpusEncoder.FRAME_SIZE)
        if len(ret) != OpusEncoder.FRAME_SIZE:
            return b''
        return ret

    def cleanup(self):
        proc = self._process
        if proc is None:
            return

        log.info('Preparing to terminate ffmpeg process %s.', proc.pid)
        proc.kill()
        if proc.poll() is None:
            log.info('ffmpeg process %s has not terminated. Waiting to terminate...', proc.pid)
            proc.communicate()
            log.info('ffmpeg process %s should have terminated with a return code of %s.', proc.pid, proc.returncode)
        else:
            log.info('ffmpeg process %s successfully terminated with return code of %s.', proc.pid, proc.returncode)

        self._process = None


class AudioPlayer(player.AudioPlayer):
    DELAY = OpusEncoder.FRAME_LENGTH / 1000.0

    def __init__(self, source, client, *, after=None, run_loops=0, frameskip=3, speed_mod=1):
        super().__init__(source, client, after=after)
        self._run_loops = run_loops
        self.frameskip = frameskip
        self._speed_mod = speed_mod

        self.bitrate = OpusEncoder.FRAME_SIZE / self.DELAY

    def _do_run(self):
        self.loops = 0
        self._start = time.time()
        frameskip = 0
        # getattr lookup speed ups
        play_audio = self.client.send_audio_packet

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
                self._start = time.time()

            self.loops += 1
            data = self.source.read()

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
            delay = max(0, self.DELAY + (next_time - time.time()))
            if delay < 0:
                frameskip = min(self.frameskip, abs(int(delay/self.DELAY)))
                continue
            time.sleep(delay)

    @property
    def duration(self):
        # TODO Make compatible with the speed command
        return self._run_loops * self.DELAY * self._speed_mod

    @property
    def loops_per_second(self):
        return self.bitrate / OpusEncoder.FRAME_SIZE

    def seek(self, t):
        pass
        # TODO

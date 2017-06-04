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

import copy
import asyncio
import shlex
import sys
import traceback
import logging
import subprocess
import threading
from collections import deque
from functools import wraps
import time
import audioop

import discord
from discord import Object, InvalidArgument, ChannelType, ClientException, voice_client, Reaction
from discord.ext import commands
from discord.ext.commands import CommandNotFound, CommandError
from discord.ext.commands.view import StringView
from discord import state
from aiohttp import ClientSession


try:
    import uvloop
    asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
except ImportError:
    pass


from bot import exceptions
from bot.message import TimeoutMessage
from bot.permissions import check_permission

log = logging.getLogger('discord')


class Command(commands.Command):
    def __init__(self, name, callback, level=0, owner_only=False, **kwargs):
        super().__init__(name, callback, **kwargs)
        self.level = level
        self.owner_only = owner_only


class ConnectionState(state.ConnectionState):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def parse_message_reaction_add(self, data):
        message = self._get_message(data['message_id'])
        if message is not None:
            emoji = self._get_reaction_emoji(**data.pop('emoji'))
            reaction = discord.utils.get(message.reactions, emoji=emoji)

            is_me = data['user_id'] == self.user.id

            if not reaction:
                reaction = Reaction(
                    message=message, emoji=emoji, me=is_me, **data)
                message.reactions.append(reaction)
            else:
                reaction.count += 1
                if is_me:
                    reaction.me = True

            channel = self.get_channel(data['channel_id'])
            member = self._get_member(channel, data['user_id'])

            self.dispatch('reaction_add', reaction, member)

        else:
            self.dispatch('raw_reaction_add', **data)

    def parse_message_update(self, data):
        message = self._get_message(data.get('id'))
        if message is not None:
            older_message = copy.copy(message)
            if 'call' in data:
                # call state message edit
                message._handle_call(data['call'])
            elif 'content' not in data:
                # embed only edit
                message.embeds = data['embeds']
            else:
                message._update(channel=message.channel, **data)

            self.dispatch('message_edit', older_message, message)

        else:
            self.dispatch('uncached_message_edit', data)


class Client(discord.Client):
    def __init__(self, loop=None, **options):
        super().__init__(loop=loop, **options)

        max_messages = options.get('max_messages')
        if max_messages is None or max_messages < 100:
            max_messages = 5000

        self.connection = ConnectionState(self.dispatch, self.request_offline_members,
                                          self._syncer, max_messages, loop=self.loop)


class Bot(commands.Bot):
    def __init__(self, command_prefix, config, permissions=None, aiohttp_client=None, **options):
        super().__init__(command_prefix, **options)
        log.debug('Using loop {}'.format(self.loop))
        if aiohttp_client is None:
            aiohttp_client = ClientSession(loop=self.loop)

        self.aiohttp_client = aiohttp_client
        self.config = config
        self.permissions = permissions
        self.timeout_messages = deque()
        self.owner = config.owner
        self.voice_clients_ = {}

    async def on_command_error(self, exception, context):
        """|coro|

        The default command error handler provided by the bot.

        By default this prints to ``sys.stderr`` however it could be
        overridden to have a different implementation.

        This only fires if you do not specify any listeners for command error.
        """
        if self.extra_events.get('on_command_error', None):
            return
        if hasattr(context.command, "on_error"):
            return

        if type(exception) is commands.errors.CommandNotFound or type(exception) is commands.errors.CommandOnCooldown:
            return

        if isinstance(exception.__cause__, exceptions.BotException):
            await self.say_timeout(exception.__cause__.message, context.message.channel, 30)
            return

        if isinstance(exception.__cause__, commands.errors.MissingRequiredArgument):
            return await self.say_timeout('Missing arguments. {}'.format(str(exception.__cause__)),
                                          context.message.channel, 60)

        print('Ignoring exception in command {}'.format(context.command), file=sys.stderr)
        traceback.print_exception(type(exception), exception,
                                  exception.__traceback__, file=sys.stderr)

    def command(self, *args, **kwargs):
        """A shortcut decorator that invokes :func:`command` and adds it to
        the internal command list via :meth:`add_command`.
        """
        def decorator(func):
            result = commands.command(*args, cls=Command, **kwargs)(func)
            self.add_command(result)
            return result

        return decorator

    async def say_timeout(self, message, channel, timeout=None):
        """
        Say something with a timeout if delete_messages is True

        Args:
            message: The message that the bot will send
            channel: the channel the message will be sent to
            timeout: How long will be waited before the message is deleted

        Returns:
            If timeout is None this returns the default message
            returned by bot.send_message. Else a custom TimeoutMessage class will be returned
        """
        if not self.config.delete_messages:
            timeout = None

        message = await self.send_message(channel, message)
        if timeout is not None:
            message = TimeoutMessage(message, timeout, self, self.timeout_messages)
            self.timeout_messages.append(message)

        return message

    @staticmethod
    def get_role_members(role, server):
        members = []
        for member in server.members:
            if role in member.roles:
                members.append(member)

        return members

    async def process_commands(self, message):
        _internal_channel = message.channel
        _internal_author = message.author

        view = StringView(message.content)
        if self._skip_check(message.author, self.user):
            return

        prefix = await self._get_prefix(message)
        invoked_prefix = prefix

        if not isinstance(prefix, (tuple, list)):
            if not view.skip_string(prefix):
                return
        else:
            invoked_prefix = discord.utils.find(view.skip_string, prefix)
            if invoked_prefix is None:
                return

        invoker = view.get_word()
        tmp = {
            'bot': self,
            'invoked_with': invoker,
            'message': message,
            'view': view,
            'prefix': invoked_prefix,
            'user_permissions': None
        }
        if self.permissions:
            tmp['user_permissions'] = self.permissions.get_permissions(id=message.author.id)
        ctx = Context(**tmp)
        del tmp

        if invoker in self.commands:
            command = self.commands[invoker]
            if command.owner_only and self.owner != message.author.id:
                command.dispatch_error(exceptions.PermissionError('Only the owner can use this command'), ctx)
                return

            if self.permissions:
                try:
                    check_permission(ctx, command)
                except Exception as e:
                    await self.on_command_error(e, ctx)
                    return

            self.dispatch('command', command, ctx)
            try:
                await command.invoke(ctx)
            except discord.ext.commands.errors.MissingRequiredArgument as e:
                command.dispatch_error(exceptions.MissingRequiredArgument(e), ctx)
            except CommandError as e:
                ctx.command.dispatch_error(e, ctx)
            else:
                self.dispatch('command_completion', command, ctx)
        elif invoker:
            exc = CommandNotFound('Command "{}" is not found'.format(invoker))
            self.dispatch('command_error', exc, ctx)

    async def join_voice_channel(self, channel):
        if isinstance(channel, Object):
            channel = self.get_channel(channel.id)

        if getattr(channel, 'type', ChannelType.text) != ChannelType.voice:
            raise InvalidArgument('Channel passed must be a voice channel')

        server = channel.server

        if self.is_voice_connected(server):
            raise discord.ClientException('Already connected to a voice channel in this server')

        log.info('attempting to join voice channel {0.name}'.format(channel))

        def session_id_found(data):
            user_id = data.get('user_id')
            guild_id = data.get('guild_id')
            return user_id == self.user.id and guild_id == server.id

        # register the futures for waiting
        session_id_future = self.ws.wait_for('VOICE_STATE_UPDATE', session_id_found)
        voice_data_future = self.ws.wait_for('VOICE_SERVER_UPDATE', lambda d: d.get('guild_id') == server.id)

        # request joining
        await self.ws.voice_state(server.id, channel.id)
        session_id_data = await asyncio.wait_for(session_id_future, timeout=10.0, loop=self.loop)
        data = await asyncio.wait_for(voice_data_future, timeout=10.0, loop=self.loop)

        kwargs = {
            'user': self.user,
            'channel': channel,
            'data': data,
            'loop': self.loop,
            'session_id': session_id_data.get('session_id'),
            'main_ws': self.ws
        }

        voice = VoiceClient(**kwargs)
        try:
            await voice.connect()
        except asyncio.TimeoutError as e:
            try:
                await voice.disconnect()
            except:
                # we don't care if disconnect failed because connection failed
                pass
            raise e  # re-raise

        self.connection._add_voice_client(server.id, voice)
        return voice

    async def reconnect_voice_client(self, server):
        if server.id not in self.voice_clients:
            return

        vc = self.voice_clients.pop(server.id)
        _paused = False

        player = vc.player
        if vc.is_playing:
            vc.pause()
            _paused = True

        try:
            await vc.disconnect()
        except:
            print("Error disconnecting during reconnect")
            traceback.print_exc()

        await asyncio.sleep(0.1)

        if player:
            new_vc = await self.join_voice_channel(vc.channel)
            vc.reload_voice(new_vc)

            if not vc.is_playing and _paused:
                player.resume()


class VoiceClient(discord.VoiceClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def create_ffmpeg_player(self, filename, *, use_avconv=False, pipe=False,
                             stderr=None, after_input=None, options=None,
                             before_options=None, headers=None, after=None,
                             run_loops=0, reconnect=True, **kwargs):

        command_ = 'ffmpeg' if not use_avconv else 'avconv'
        input_name = '-' if pipe else shlex.quote(filename)

        before_args = ''
        if reconnect:
            before_args = " -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5"

        if isinstance(headers, dict):
            for key, value in headers.items():
                before_args += "{}: {}\r\n".format(key, value)
            before_args = ' -headers ' + shlex.quote(before_args)

        if isinstance(before_options, str):
            before_args += ' ' + before_options

        input_args = ''
        if isinstance(after_input, str):
            input_args += ' ' + after_input

        cmd = command_ + '{} -i {}{} -f s16le -ar {} -ac {} -loglevel error'
        cmd = cmd.format(before_args, input_name, input_args, self.encoder.sampling_rate, self.encoder.channels)

        if isinstance(options, str):
            cmd = cmd + ' ' + options

        cmd += ' pipe:1'

        stdin = None if not pipe else filename
        args = shlex.split(cmd)
        try:
            p = subprocess.Popen(args, stdin=stdin, stdout=subprocess.PIPE, stderr=stderr)
            return ProcessPlayer(p, self, after, run_loops=run_loops, **kwargs)
        except FileNotFoundError as e:
            raise ClientException('ffmpeg/avconv was not found in your PATH environment variable') from e
        except subprocess.SubprocessError as e:
            raise ClientException('Popen failed: {0.__name__} {1}'.format(type(e), str(e))) from e


class Deque(deque):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def full(self):
        return len(self) == self.maxlen


class StreamPlayer(voice_client.StreamPlayer):
    def __init__(self, *args, run_loops=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.bitrate = self.frame_size / self.delay
        self.audio_buffer = Deque(maxlen=100)
        self._stream_finished = threading.Event()
        self.run_loops = run_loops

    def buffer_audio(self):
        if not self._stream_finished.is_set() and not self.audio_buffer.full():
            d = self.buff.read(self.frame_size)
            self.audio_buffer.append(d)
            if not len(d) > 0:
                self._stream_finished.set()

    def _do_run(self):
        self.loops = 0
        self._start = time.time()
        while not self._end.is_set():
            # are we paused?
            if not self._resumed.is_set():
                # wait until we aren't
                self._resumed.wait()

            if not self._connected.is_set():
                self.stop()
                break

            self.loops += 1
            if self.audio_buffer:
                data = self.audio_buffer.popleft()
                self.buffer_audio()
            else:
                data = self.buff.read(self.frame_size)
                while not self.audio_buffer.full() and not self._stream_finished.is_set() and not self._end.is_set():
                    self.buffer_audio()

            if self._volume != 1.0:
                data = audioop.mul(data, 2, min(self._volume, 2.0))

            if len(data) != self.frame_size:
                self.stop()
                break

            self.player(data)
            self.run_loops += 1
            next_time = self._start + self.delay * self.loops
            delay = max(0, self.delay + (next_time - time.time()))
            time.sleep(delay)

    @property
    def duration(self):
        return self.run_loops * self.frame_size / self.bitrate

    @property
    def loops_per_second(self):
        return self.bitrate / self.frame_size


class ProcessPlayer(StreamPlayer):
    def __init__(self, process, client, after, **kwargs):
        super().__init__(process.stdout, client.encoder,
                         client._connected, client.play_audio, after, **kwargs)
        self.process = process

    def run(self):
        super().run()

        self.process.kill()
        if self.process.poll() is None:
            self.process.communicate()


def command(*args, **kwargs):
    kwargs.pop('cls', None)
    return commands.command(*args, cls=Command, **kwargs)


class Context(commands.context.Context):
    __slots__ = ['user_permissions']

    def __init__(self, **attrs):
        super().__init__(**attrs)
        self.user_permissions = attrs.pop('user_permissions', None)
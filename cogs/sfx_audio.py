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
import os
from numpy import random
from collections import deque, OrderedDict
import shlex
import discord
from bot.formatter import Paginator

from discord.ext import commands
try:
    from gtts import gTTS
except ImportError:
    gTTS = None

from bot.bot import command
from bot.globals import TTS, SFX_FOLDER


class SFX:
    def __init__(self, name, after_input='', options=''):
        self.name = name
        self.after_input = after_input
        self.before_options = '-nostdin'
        self.options = '-vn -b:a 128k' + options


class Playlist:
    def __init__(self, bot):
        self.voice = None
        self.bot = bot
        self.queue = deque(maxlen=6)
        self.not_empty = asyncio.Event()
        self.next = asyncio.Event()
        self.random_loop = None
        self.sfx_loop = None
        self.player = None
        self.random_sfx_on = self.bot.config.random_sfx

    def on_stop(self):
        self.bot.loop.call_soon_threadsafe(self.next.set)
        return

    def create_tasks(self):
        if self.random_loop:
            self.random_loop.cancel()
        if self.sfx_loop:
            self.sfx_loop.cancel()
        self.random_loop = self.bot.loop.create_task(self.random_sfx())
        self.sfx_loop = self.bot.loop.create_task(self.audio_player())

    async def random_sfx(self):
        while True:
            users = self.voice.channel.voice_members
            users = list(filter(lambda x: not x.bot, users))
            if not users:
                await self.voice.disconnect()
                self.sfx_loop.cancel()
                break

            if self.random_sfx_on and random.random() < 0.1 and self.voice is not None:

                path = SFX_FOLDER
                files = os.listdir(path)

                sfx = os.path.join(path, random.choice(files))
                if random.random() < 0.5:
                    sfx2 = os.path.join(path, random.choice(files))
                    options = '-i "{}" '.format(sfx2)
                    options += '-filter_complex "[0:a0] [1:a:0] concat=n=2:v=0:a=1 [a]" -map "[a]"'
                    self.add_to_queue(sfx, options)
                else:
                    self.add_to_queue(sfx)

            await asyncio.sleep(60)

    async def audio_player(self):
        while True:
            self.next.clear()
            self.not_empty.clear()
            sfx = self._get_next()
            if sfx is None:
                await self.not_empty.wait()
                sfx = self._get_next()

            self.player = self.voice.create_ffmpeg_player(sfx.name,
                                                          before_options=sfx.before_options,
                                                          after=self.on_stop,
                                                          after_input=sfx.after_input,
                                                          options=sfx.options,
                                                          reconnect=False)

            self.player.start()

            await self.next.wait()

    def is_playing(self):
        if self.voice is None or self.player is None:
            return False

        return not self.player.is_done()

    def add_to_queue(self, entry, after_input=''):
        self.queue.append(SFX(entry, after_input=after_input))
        self.bot.loop.call_soon_threadsafe(self.not_empty.set)

    def add_next(self, entry, options=''):
        self.queue.appendleft(SFX(entry, options))
        self.bot.loop.call_soon_threadsafe(self.not_empty.set)

    def _get_next(self):
        if self.queue:
            return self.queue.popleft()


class Audio:
    def __init__(self, bot, queue):
        self.bot = bot
        self.voice_states = {}
        self.queue = queue

    def get_voice_state(self, server):
        playlist = self.voice_states.get(server.id)
        if playlist is None:
            playlist = Playlist(self.bot)
            self.voice_states[server.id] = playlist

        return playlist

    @command(pass_context=True, no_pm=True, ignore_extra=True, aliases=['summon2'])
    async def summon(self, ctx):
        """Summons the bot to join your voice channel."""
        summoned_channel = ctx.message.author.voice_channel
        if summoned_channel is None:
            await self.bot.send_message(ctx.message.channel, 'You are not in a voice channel')
            return False

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            try:
                state.voice = await self.bot.join_voice_channel(summoned_channel)
            except discord.ClientException as e:
                print(e)
                if ctx.message.server.id in self.bot.connection._voice_clients:
                    state.voice = self.bot.connection._voice_clients.get(ctx.message.server.id)
            except:
                return False
            state.create_tasks()
        else:
            await state.voice.move_to(summoned_channel)

        file = self._search_sfx('attention')
        if file:
            state.add_to_queue(file[0])

        return True

    @command(pass_context=True, no_pm=True, ignore_extra=True, aliases=['s'])
    async def stop_sfx(self, ctx):
        state = self.get_voice_state(ctx.message.server)
        if state.is_playing():
            state.player.stop()

    async def shutdown(self):
        for key in list(self.voice_states.keys()):
            state = self.voice_states[key]
            await self.stop_state(state)
            del self.voice_states[key]

    @staticmethod
    async def stop_state(state):
        if state is None:
            return

        if state.player is not None:
            state.player.stop()

        try:
            if state.sfx_loop is not None:
                state.sfx_loop.cancel()

            if state.voice is not None:
                await state.voice.disconnect()

        except Exception as e:
            print('[ERROR] Error while stopping sfx_bot.\n%s' % e)

    @command(pass_context=True, no_pm=True)
    @commands.cooldown(2, 4, type=commands.BucketType.user)
    async def sfx(self, ctx, *, name):
        file = self._search_sfx(name)
        if not file:
            return await self.bot.say('Invalid sound effect name')

        file = file[0]

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        state.add_to_queue(file)

    @command(name='max_combo', no_pm=True)
    @commands.check(lambda ctx, cmd: ctx.message.author.id in ['117256618617339905', '123050803752730624'])
    async def change_combo(self, max_combo=None):
        if max_combo is None:
            return await self.bot.say(self.bot.config.max_combo)
        try:
            max_combo = int(max_combo)
        except ValueError:
            return await self.bot.say('Integer needed')

        self.bot.config.max_combo = max_combo
        await self.bot.say('Max combo set to %s' % str(max_combo))

    async def _combine_sfx(self, *effects, search=True):
        max_combo = self.bot.config.max_combo
        silences = []
        silenceidx = 0
        sfx_list = []
        for idx, name in enumerate(effects):
            if name.startswith('-') and name != '-':
                silence = name.split('-')[1]
                try:
                    silence = float(silence)
                except ValueError as e:
                    await self.bot.say('Silence duration needs to be a number\n%s' % e, delete_after=20)
                    continue

                silences.append(('aevalsrc=0:d={}[s{}]'.format(silence, str(silenceidx)), idx))
                silenceidx += 1
                continue

            elif name.endswith('-') and name != '-':
                try:
                    bpm = int(''.join(name.split('-')[:-1]))
                    if bpm <= 0:
                        await self.bot.say('BPM needs to be bigger than 0', delete_after=20)
                        continue

                    silence = 60 / bpm
                    silences.append(('aevalsrc=0:d={}[s{}]'.format(silence, str(silenceidx)), idx))
                    silenceidx += 1
                    continue
                except ValueError:
                    pass

            if search:
                sfx = self._search_sfx(name)
                if not sfx:
                    await self.bot.say("Couldn't find %s. Skipping it" % name, delete_after=30)
                    continue

                sfx_list.append(sfx[0])
            else:
                sfx_list.append(name)

        if not sfx_list:
            return await self.bot.say('No sfx found', delete_after=30)

        if len(sfx_list) > max_combo:
            return await self.bot.say('Cannot combine more effects than the current combo limit of %s' % max_combo)

        entry = sfx_list.pop(0)
        if not sfx_list:
            return entry

        options = ''
        filter_complex = '-filter_complex "'

        for s in silences:
            filter_complex += s[0] + ';'

        audio_order = ['[0:a:0]']
        for idx, sfx in enumerate(sfx_list):
            options += '-i "{}" '.format(sfx)
            audio_order.append('[{}:a:0] '.format(idx + 1))

        for idx, silence in enumerate(silences):
            audio_order.insert(silence[1], '[s{}]'.format(idx))

        filter_complex += ' '.join(audio_order)
        options += filter_complex
        options += 'concat=n={}:v=0:a=1 [a]" -map "[a]"'.format(len(audio_order))
        return entry, options

    @command(pass_context=True, aliases=['r'], no_pm=True)
    async def random_sfx(self, ctx, combo=1):
        if combo > self.bot.config.max_combo:
            return await self.bot.say('Cannot go over max combo  {}>{}'.format(combo, self.bot.config.max_combo))

        if combo <= 0:
            return await self.bot.say('Number cannot be smaller than one')

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        sfx = os.listdir(SFX_FOLDER)
        try:
            sfx.remove('-.mp3')
        except:
            pass

        effects = [os.path.join(SFX_FOLDER, f) for f in random.choice(sfx, combo)]
        entry = await self._combine_sfx(*effects, search=False)
        if isinstance(entry, tuple):
            state.add_to_queue(entry[0], entry[1])
        elif isinstance(entry, str):
            state.add_to_queue(entry)

    @command(name='combo', pass_context=True, no_pm=True, aliases=['concat', 'c'])
    async def combine(self, ctx, *, names):
        max_combo = self.bot.config.max_combo
        names = shlex.split(names)
        if len(names) > max_combo:
            return await self.bot.say('Max %s sfx can be combined' % str(max_combo))

        state = self.get_voice_state(ctx.message.server)
        if state.voice is None:
            success = await ctx.invoke(self.summon)
            if not success:
                return

        entry = await self._combine_sfx(*names)
        if isinstance(entry, tuple):
            state.add_to_queue(entry[0], entry[1])
        elif isinstance(entry, str):
            state.add_to_queue(entry)
        'ffmpeg -i audio1.mp3 -i audio2.mp3 -filter_complex "[0:a:0] [1:a:0] concat=n=2:v=0:a=1 [a]" -map "[a]" out.mp3'

    @staticmethod
    def _search_sfx(name):
        sfx = sorted(os.listdir(SFX_FOLDER))

        # A very advanced searching algorithm
        file = [x for x in sfx if '.'.join(x.split('.')[:-1]) == name]
        if not file:
            file = [x for x in sfx if '.'.join(x.split('.')[:-1]).lower().startswith(name)]
            if not file:
                file = [x for x in sfx if name in x.lower()]
                if not file:
                    file = [x for x in sfx if name.replace(' ', '').lower() in x.lower()]

        return [os.path.join(SFX_FOLDER, f) for f in file]

    @command(pass_context=True, no_pm=True, aliases=['srs'])
    async def set_random_sfx(self, ctx, value):
        value = value.lower().strip()
        values = {'on': True, 'off': False}
        values_rev = {v: k for k, v in values.items()}

        value = values.get(value, False)
        state = self.get_voice_state(ctx.message.server)
        state.random_sfx_on = value

        await self.bot.say('Random sfx set to %s' % values_rev.get(value))

    @command(pass_context=True)
    async def sfxlist(self, ctx):
        """List of all the sound effects"""
        sfx = os.listdir(SFX_FOLDER)
        if not sfx:
            return await self.bot.say('No sfx found')

        sfx.sort(key=str.lower)
        sorted_sfx = OrderedDict()
        curr_add = []
        start = sfx[0][0].lower()
        title = 'SFX list'
        p = Paginator(title=title)
        p.add_field(start)

        for item in sfx:
            padding = ' '
            if not item[0].lower().startswith(start):
                sorted_sfx[start] = curr_add
                start = item[0].lower()
                p.add_field(start)
                padding = ''

            p.add_to_field('{}`{}`'.format(padding, '.'.join(item.split('.')[:-1])))

        p.finalize()
        for embed in p.pages:
            await self.bot.send_message(ctx.message.channel, embed=embed)

    @command(pass_context=True, no_pm=True, aliases=['stop2'])
    async def stop(self, ctx):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        server = ctx.message.server
        state = self.get_voice_state(server)

        await self.stop_state(state)

        del self.voice_states[ctx.message.server.id]

    async def on_voice_state_update(self, before, after):
        if before == self.bot.user:
            return

        try:
            if before.voice.voice_channel == after.voice.voice_channel:
                return

            if after.voice.voice_channel == self.bot.voice_client_in(
                    after.server).channel:
                await self.on_join(after)

            elif before.voice.voice_channel != after.voice.voice_channel and before.voice.voice_channel == self.bot.voice_client_in(
                    after.server).channel:
                await self.on_leave(after)
        except:
            pass

    async def on_join(self, member):
        string = '%s joined the channel' % member.name
        path = os.path.join(TTS, 'join.mp3')
        self._add_tts(path, string, member.server)

    async def on_leave(self, member):
        string = '%s left the channel' % member.name
        path = os.path.join(TTS, 'leave.mp3')
        self._add_tts(path, string, member.server)

    def _add_tts(self, path, string, server):
        if gTTS is None:
            return

        gtts = gTTS(string, lang='en-us')
        gtts.save(path)
        state = self.get_voice_state(server)

        state.add_next(path)


def setup(bot):
    bot.add_cog(Audio(bot, None))

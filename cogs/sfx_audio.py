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
import shlex
from collections import deque, OrderedDict

import disnake
from disnake import ApplicationCommandInteraction
from disnake.ext import commands
from disnake.ext.commands import Cog, cooldown, slash_command
from numpy import random

from bot.formatter import EmbedPaginator
from bot.player import FFmpegPCMAudio, play

try:
    from gtts import gTTS
except ImportError:
    gTTS = None

from bot.globals import TTS, SFX_FOLDER

terminal = logging.getLogger('terminal')


class SFX:
    def __init__(self, name, after_input='', options=''):
        self.name = name
        self.after_input = after_input
        self.before_options = '-nostdin'
        self.options = '-vn -b:a 128k' + options


class Playlist:
    def __init__(self, bot, disconnect, guild):
        self.voice = None
        self.bot = bot
        self.guild = guild
        self._disconnect = disconnect
        self.queue = deque(maxlen=6)
        self.not_empty = asyncio.Event()
        self.next = asyncio.Event()
        self.random_loop = None
        self.sfx_loop = None
        self.source = None
        self.random_sfx_on = self.bot.config.random_sfx
        self.on_join = True

    @property
    def player(self):
        if self.voice:
            return self.voice._player

    def on_stop(self, e):
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
            if self.voice is not None:
                users = self.voice.channel.members
                users = list(filter(lambda x: not x.bot, users))
                if not users:
                    await self._disconnect(self)
                    return

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

            self.source = FFmpegPCMAudio(sfx.name, before_options=sfx.before_options,
                                         after_input=sfx.after_input, options=sfx.options,
                                         reconnect=False)

            play(self.voice, self.source, after=self.on_stop)

            await self.next.wait()

    def is_playing(self):
        if self.voice is None or not self.voice.is_connected():
            return False

        return True

    def add_to_queue(self, entry, after_input=''):
        self.queue.append(SFX(entry, after_input=after_input))
        self.bot.loop.call_soon_threadsafe(self.not_empty.set)

    def add_next(self, entry, options=''):
        self.queue.appendleft(SFX(entry, options))
        self.bot.loop.call_soon_threadsafe(self.not_empty.set)

    def _get_next(self):
        if self.queue:
            return self.queue.popleft()

    def skip(self, author):
        if self.is_playing():
            self.voice.stop()


class Audio(Cog):
    def __init__(self, bot, queue):
        self.bot = bot
        self.music_players: dict[int, Playlist] = self.bot.music_players
        self.queue = queue
        self._lang = 'en-us'
        self._sfx_list = sorted(f.rsplit('.', 1)[0] for f in os.listdir(SFX_FOLDER) if '.' in f)

    def get_voice_state(self, guild):
        playlist = self.music_players.get(guild.id)
        if playlist is None:
            playlist = Playlist(self.bot, self.disconnect_voice, guild)
            self.music_players[guild.id] = playlist

        return playlist

    @slash_command(dm_permission=False)
    async def summon(self, ctx: ApplicationCommandInteraction):
        """Summons the bot to join your voice channel."""
        if not ctx.author.voice:
            await ctx.send("You aren't connected to a voice channel")
            return False

        channel = ctx.author.voice.channel
        state = self.get_voice_state(ctx.guild)

        if state.voice is None:
            try:
                state.voice = await channel.connect()
            except (disnake.HTTPException, asyncio.TimeoutError) as e:
                await ctx.send(f'Failed to join vc because of an error\n{e}')
                return False
            except disnake.ClientException:
                await ctx.send(f'Bot is having some difficulties joining voice. You should probably use `/force_stop`')
                return False
            state.create_tasks()
        else:
            await state.voice.move_to(channel)

        file = self._search_sfx('attention')
        if file:
            state.add_to_queue(file[0])

        return True

    @slash_command(dm_permission=False)
    async def stop_sfx(self, ctx: ApplicationCommandInteraction):
        """Stop the current sfx"""
        state = self.get_voice_state(ctx.guild)
        if state:
            state.skip(ctx.author)

    async def shutdown(self):
        for key in list(self.music_players.keys()):
            state = self.music_players[key]
            await self.close_player(state)
            del self.music_players[key]

    @staticmethod
    async def close_player(musicplayer: Playlist):
        if musicplayer is None:
            return

        musicplayer.skip(None)

        try:
            if musicplayer.sfx_loop is not None:
                musicplayer.sfx_loop.cancel()

            if musicplayer.voice is not None:
                await musicplayer.voice.disconnect()
                musicplayer.voice = None

        except Exception:
            terminal.exception('Error while stopping voice')

    async def disconnect_voice(self, musicplayer: Playlist):
        await self.close_player(musicplayer)
        try:
            del self.music_players[musicplayer.guild.id]
        except:
            pass

    async def autocomplete_sfx(self, _: disnake.ApplicationCommandInteraction, string: str):
        count = 0
        max_count = 25
        names = []
        for n in self._sfx_list:
            if string.lower() in n.lower():
                names.append(n)
                count += 1

                if count >= max_count:
                    break

        return names

    @slash_command(dm_permission=False)
    @cooldown(2, 4, type=commands.BucketType.user)
    async def sfx(self, ctx: ApplicationCommandInteraction, name: str):
        """Play a sound effect"""
        await ctx.response.defer()
        file = self._search_sfx(name)
        if not file:
            return await ctx.send('Invalid sound effect name')

        file = file[0]

        state = self.get_voice_state(ctx.guild)
        if state.voice is None:
            await self.summon.invoke(ctx)

        state.add_to_queue(file)
        await ctx.send('Queued', ephemeral=True)

    sfx.autocomplete('name')(autocomplete_sfx)

    @slash_command(name='max_combo', guild_ids=[128248421130698752])
    async def change_combo(self, ctx: ApplicationCommandInteraction, max_combo: int=None):
        """Change how many sound effects you can combine with {prefix}combo"""
        if max_combo is None:
            return await ctx.send(self.bot.config.max_combo or 'no max combo')

        self.bot.config.max_combo = max_combo
        await ctx.send(f'Max combo set to {max_combo}')

    async def _combine_sfx(self, ctx: ApplicationCommandInteraction, *effects, search=True):
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
                    await ctx.send('Silence duration needs to be a number\n%s' % e, delete_after=20)
                    continue

                silences.append(('aevalsrc=0:d={}[s{}]'.format(silence, str(silenceidx)), idx))
                silenceidx += 1
                continue

            elif name.endswith('-') and name != '-':
                try:
                    bpm = int(''.join(name.split('-')[:-1]))
                    if bpm <= 0:
                        await ctx.send('BPM needs to be bigger than 0', delete_after=20)
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
                    name = name.replace('@', '\u200b@')
                    await ctx.send(f"{ctx.author.mention} Couldn't find {name}. Skipping it", delete_after=30)
                    continue

                sfx_list.append(sfx[0])
            else:
                sfx_list.append(name)

        if not sfx_list:
            return await ctx.send('No sfx found', delete_after=30)

        if len(sfx_list) > max_combo:
            return await ctx.send('Cannot combine more effects than the current combo limit of %s' % max_combo)

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

    @slash_command(dm_permission=False)
    async def random_sfx(self, ctx: ApplicationCommandInteraction, combo: int=1):
        """Set how many sfx random sfx will combine if it's on"""
        await ctx.response.defer()
        if combo > self.bot.config.max_combo:
            return await ctx.send('Cannot go over max combo  {}>{}'.format(combo, self.bot.config.max_combo))

        if combo <= 0:
            return await ctx.send('Number cannot be smaller than one')

        state = self.get_voice_state(ctx.guild)
        if state.voice is None:
            await self.summon.invoke(ctx)

        sfx = os.listdir(SFX_FOLDER)
        try:
            sfx.remove('-.mp3')
        except:
            pass

        effects = [os.path.join(SFX_FOLDER, f) for f in random.choice(sfx, combo)]
        entry = await self._combine_sfx(ctx, *effects, search=False)
        if isinstance(entry, tuple):
            state.add_to_queue(entry[0], entry[1])
        elif isinstance(entry, str):
            state.add_to_queue(entry)

        await ctx.send('Queued', ephemeral=True)

    @slash_command(name='combo', dm_permission=False)
    @cooldown(2, 4, type=commands.BucketType.user)
    async def combine(self, ctx: ApplicationCommandInteraction, names: str):
        """Play multiple sfx in a row"""
        await ctx.response.defer()
        max_combo = self.bot.config.max_combo
        names = shlex.split(names)
        if len(names) > max_combo:
            return await ctx.send('Max %s sfx can be combined' % max_combo)

        state = self.get_voice_state(ctx.guild)
        if state.voice is None:
            await self.summon.invoke(ctx)

        entry = await self._combine_sfx(ctx, *names)
        if isinstance(entry, tuple):
            state.add_to_queue(entry[0], entry[1])
        elif isinstance(entry, str):
            state.add_to_queue(entry)

        await ctx.send('Queued', ephemeral=True)

        'ffmpeg -i audio1.mp3 -i audio2.mp3 -filter_complex "[0:a:0] [1:a:0] concat=n=2:v=0:a=1 [a]" -map "[a]" out.mp3'

    @staticmethod
    def _search_sfx(name: str):
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

    @slash_command(dm_permission=False)
    async def set_random_sfx(self, ctx: ApplicationCommandInteraction, value: bool):
        """Set random sfx on or off"""
        state = self.get_voice_state(ctx.guild)
        state.random_sfx_on = value

        await ctx.send('Random sfx set to %s' % value)

    @slash_command()
    @cooldown(1, 4, type=commands.BucketType.user)
    async def sfxlist(self, ctx: ApplicationCommandInteraction):
        """List of all the sound effects"""


        sfx = list(sorted(filter(lambda f: '.' in f, os.listdir(SFX_FOLDER)), key=str.lower))
        if not sfx:
            return await ctx.send('No sfx found')

        sorted_sfx = OrderedDict()
        curr_add = []
        start = sfx[0][0].lower()
        title = 'SFX list'
        p = EmbedPaginator(title=title)
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
            await ctx.send(embed=embed)

    @slash_command(name='on_join', dm_permission=False)
    @cooldown(2, 4, type=commands.BucketType.user)
    async def _on_join(self, ctx: ApplicationCommandInteraction, val: bool=None):
        guild = ctx.guild
        state = self.get_voice_state(guild)
        if not state:
            return

        if val is None:
            return await ctx.send(f'Current on join value {state.on_join}')

        state.on_join = val
        await ctx.send(f'On join set to {val}')

    @slash_command(dm_permission=False)
    @cooldown(2, 4, type=commands.BucketType.user)
    async def stop(self, ctx: ApplicationCommandInteraction):
        """Stops playing audio and leaves the voice channel.
        This also clears the queue.
        """
        guild = ctx.guild
        state = self.get_voice_state(guild)
        if not state:
            return
        await self.disconnect_voice(state)

    #@Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        # disabled for now
        return
        if member == self.bot.user:
            return

        state = self.music_players.get(member.guild.id)
        if not state:
            return

        if not state.on_join:
            return

        if not member.guild.me.voice:
            return

        channel = member.guild.me.voice.channel
        if not channel:
            return

        try:
            if not before and after:
                if after.channel == channel:
                    await self.on_join(member)
            elif before and not after:
                if before.channel == channel:
                    await self.on_leave(member)
            elif before and after and before.channel != after.channel:
                if before.channel == channel:
                    await self.on_leave(member)
                elif after.channel == channel:
                    await self.on_join(member)
        except:
            terminal.exception('Failed to say join leave voice')

    @Cog.listener()
    async def on_join(self, member: disnake.Member):
        string = '%s joined the channel' % member.name
        path = os.path.join(TTS, 'join.mp3')
        self._add_tts(path, string, member.guild)

    @Cog.listener()
    async def on_leave(self, member: disnake.Member):
        string = '%s left the channel' % member.name
        path = os.path.join(TTS, 'leave.mp3')
        self._add_tts(path, string, member.guild)

    def _add_tts(self, path: str, string: str, guild: int):
        if gTTS is None:
            return

        gtts = gTTS(string, lang=self._lang)
        gtts.save(path)
        state = self.get_voice_state(guild)
        if not state:
            return

        state.add_next(path)


def setup(bot):
    bot.add_cog(Audio(bot, None))

#!/usr/bin/env python
# -*-coding=utf-8 -*-

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

import aiohttp
import discord
import threading
import asyncio

from bot import sfx_audio
from bot.bot import Bot


class SfxBot(threading.Thread):
    def __init__(self, config, permissions=None, **kwargs):
        super().__init__(**kwargs)
        self.config = config
        self.permissions = permissions

    def _start(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        sfx_bot = Bot(prefix='!!', config=self.config, perms=self.permissions)
        if self.permissions:
            self.permissions.sfx_bot = sfx_bot

        audio = sfx_audio.Audio(sfx_bot, None)

        @sfx_bot.event
        async def on_ready():
            print('[INFO] Logged in as {0.user.name}'.format(sfx_bot))
            await sfx_bot.change_presence(
                game=discord.Game(name=sfx_bot.config.sfx_game))

        @sfx_bot.event
        async def on_voice_state_update(before, after):
            if before == sfx_bot.user:
                return

            try:
                if before.voice.voice_channel == after.voice.voice_channel:
                    return

                if after.voice.voice_channel == sfx_bot.voice_client_in(
                        after.server).channel:
                    await audio.on_join(after)

                elif before.voice.voice_channel != after.voice.voice_channel and before.voice.voice_channel == sfx_bot.voice_client_in(
                        after.server).channel:
                    await audio.on_leave(after)
            except:
                pass

        @sfx_bot.command(pass_context=True, aliases=['shutdown2'], owner_only=True)
        async def shutdown(ctx):
            try:
                await audio.shutdown()
                for message in sfx_bot.timeout_messages.copy():
                    message.delete_now()
                    message.cancel_tasks()

                await sfx_bot.close()
                sfx_bot.aiohttp_client.close()
            except Exception as e:
                print('SFX bot shutdown error: %s' % e)
            finally:
                await sfx_bot.close()

        sfx_bot.add_cog(audio)
        sfx_bot.run(self.config.sfx_token)

    def run(self):
        self._start()

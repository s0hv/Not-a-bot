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

import asyncio
import threading
import time

import discord

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

        @sfx_bot.event
        async def on_ready():
            print('[INFO] Logged in as {0.user.name}'.format(sfx_bot))
            await sfx_bot.change_presence(
                game=discord.Game(name=sfx_bot.config.sfx_game))

            sfx_bot.load_extension('cogs.sfx_audio')
            sfx_bot.load_extension('cogs.utils')
            sfx_bot.load_extension('cogs.botadmin')

        @sfx_bot.command(owner_only=True)
        async def reload(*, name):
            t = time.time()
            try:
                cog_name = 'cogs.%s' % name if not name.startswith('cogs.') else name
                sfx_bot.unload_extension(cog_name)
                sfx_bot.load_extension(cog_name)
            except Exception as e:
                    return await sfx_bot.say('Could not reload %s because of an error\n%s' % (name, e))

            await sfx_bot.say('Reloaded {} in {:.0f}ms'.format(name, (time.time() - t) * 1000))

        @sfx_bot.command(pass_context=True, aliases=['shutdown2'], owner_only=True)
        async def shutdown(ctx):
            try:
                audio = sfx_bot.get_cog('Audio')
                if audio:
                    await audio.shutdown()

                pending = asyncio.Task.all_tasks(loop=sfx_bot.loop)
                gathered = asyncio.gather(*pending, loop=sfx_bot.loop)
                try:
                    gathered.cancel()
                    sfx_bot.loop.run_until_complete(gathered)

                    # we want to retrieve any exceptions to make sure that
                    # they don't nag us about it being un-retrieved.
                    gathered.exception()
                except:
                    pass

            except Exception as e:
                print('SFX bot shutdown error: %s' % e)
            finally:
                sfx_bot.loop.run_until_complete(sfx_bot.close())

        @sfx_bot.command(pass_context=True)
        async def test(ctx):
            await sfx_bot.send_message(ctx.message.channel, 'test')

        sfx_bot.run(sfx_bot.config.sfx_token)

    def run(self):
        self._start()

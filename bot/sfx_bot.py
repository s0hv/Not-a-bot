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
import time
from bot.bot import command

import discord

from bot.bot import Bot


class Ganypepe(Bot):
    def __init__(self, prefix, conf, aiohttp=None, **options):
        super().__init__(prefix, conf, aiohttp, **options)

    async def on_ready(self):
        print('[INFO] Logged in as {0.user.name}'.format(self))
        await self.change_presence(game=discord.Game(name=self.config.sfx_game))

        self.load_extension('cogs.sfx_audio')
        self.load_extension('cogs.utils')
        self.load_extension('cogs.botadmin')
        try:
            self.add_command(self.test)
        except (TypeError, discord.ClientException):
            pass

    @command(pass_context=True)
    async def test(self, ctx):
        await self.send_message(ctx.message.channel, 'test')

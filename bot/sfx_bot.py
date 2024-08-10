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

import logging
from concurrent.futures import ThreadPoolExecutor

import disnake

from bot.bot import Bot

terminal = logging.getLogger('terminal')


initial_cogs = ['cogs.sfx_audio',
                'cogs.botadmin']


class Ganypepe(Bot):
    def __init__(self, prefix, conf, test_mode=False, **options):
        super().__init__(prefix, conf, **options)
        self.test_mode = test_mode
        self.threadpool = ThreadPoolExecutor(max_workers=4)
        self.music_players = {}
        self._exit_code = 0

    async def _load_cogs(self, print_err=True):
        for cog in initial_cogs:
            try:
                self.load_extension(cog)
            except Exception as e:
                if print_err:
                    terminal.warning('Failed to load extension {}\n{}: {}'.format(cog, type(e).__name__, e))
                else:
                    pass

    async def on_ready(self):
        terminal.info(f'Logged in as {self.user}')
        await self.change_presence(activity=disnake.Game(name=self.config.sfx_game))
        await self._load_cogs()

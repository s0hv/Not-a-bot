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

import discord
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from bot.bot import Bot, command
from bot.dbutil import DatabaseUtils

terminal = logging.getLogger('terminal')


initial_cogs = ['cogs.sfx_audio',
                'cogs.utils',
                'cogs.botadmin',
                'cogs.last_seen']


class Ganypepe(Bot):
    def __init__(self, prefix, conf, aiohttp=None, test_mode=False, **options):
        super().__init__(prefix, conf, aiohttp, **options)
        self.test_mode = test_mode
        self._setup()
        self.threadpool = ThreadPoolExecutor(max_workers=4)
        self._dbutil = DatabaseUtils(self)
        self.music_players = {}

    def _setup(self):
        db = 'discord' if not self.test_mode else 'test'
        engine = create_engine('mysql+pymysql://{0.sfx_db_user}:{0.sfx_db_pass}@{0.db_host}:{0.db_port}/{1}?charset=utf8mb4'.format(self.config, db),
                               encoding='utf8')
        session_factory = sessionmaker(bind=engine)
        Session = scoped_session(session_factory)
        self._Session = Session

    @property
    def get_session(self):
        return self._Session()

    @property
    def dbutil(self):
        return self._dbutil

    @property
    def dbutils(self):
        return self._dbutil

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
        terminal.info('Logged in as {0.user.name}'.format(self))
        await self.change_presence(activity=discord.Game(name=self.config.sfx_game))
        await self._load_cogs()
        try:
            cmd = command('test')(self.test)
            self.add_command(cmd)
        except (TypeError, discord.ClientException) as e:
            pass

    async def test(self, ctx):
        await ctx.send('test')

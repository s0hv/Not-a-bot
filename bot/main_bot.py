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

from aiohttp import ClientSession

from bot.bot import Bot
from bot.cooldown import CooldownManager
from bot.globals import *
from cogs import jojo, hearthstone, audio
from cogs.emotes import Emotes
from cogs.management import Management
from cogs.search import Search
from cogs.voting import VoteManager

logger = logging.getLogger('debug')


def start(config, permissions):
    client = ClientSession()
    bot = Bot(command_prefix='!', config=config, aiohttp=client, pm_help=True, permissions=permissions)
    cdm = CooldownManager()
    cdm.add_cooldown('oshit', 3, 8)
    cdm.add_cooldown('imnew', 3, 8)

    permissions.bot = bot
    hi_new = {ord(c): '' for c in ", '"}

    sound = audio.Audio(bot, client)
    search = Search(bot, client)
    management = Management(bot)
    votes = VoteManager(bot)


    @bot.command(pass_context=True, ignore_extra=True)
    async def playlists(ctx):
        p = os.path.join(os.getcwd(), 'data', 'playlists')
        files = os.listdir(p)
        sort = filter(lambda f: os.path.isfile(os.path.join(p, f)), files)
        await bot.say_timeout('Playlists: {}'.format(', '.join(sort)), ctx.message.channel)


    bot.add_cog(search)
    bot.add_cog(sound)
    bot.add_cog((hearthstone.Hearthstone(bot, config.mashape_key, bot.aiohttp_client)))
    bot.add_cog(jojo.JoJo(bot))
    bot.add_cog(management)
    bot.add_cog(Emotes(bot))
    bot.add_cog(votes)

    bot.run(config.token)

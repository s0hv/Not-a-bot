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
import os
import sys

import discord

from bot.audio_bot import AudioBot
from bot.config import Config, is_test_mode, get_test_guilds
from bot.formatter import LoggingFormatter

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
terminal.addHandler(handler)

logger = logging.getLogger('audio')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='audio.log', encoding='utf-8-sig', mode='a')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s:[%(module)s]: %(message)s'))
logger.addHandler(handler)

terminal.info('testing colors')
terminal.debug('test')
terminal.warning('test')
terminal.error('test')
terminal.critical('test')
try:
    int('d')
except:
    terminal.exception('test exception')

config = Config()

initial_cogs = [
    # 'audio',
    'basic_logging',
    'botadmin',
    'command_blacklist'
]
initial_cogs = list(map('cogs.'.__add__, initial_cogs))

terminal.info('Main bot starting up')
logger.info('Starting bot')
config.default_activity = {'type': 1, 'name': 'Music'}

intents = discord.Intents.default()
# Required for seeing voice channel members on startup
intents.members = True

intents.invites = False
intents.integrations = False
intents.webhooks = False
intents.bans = False
intents.emojis_and_stickers = False
intents.typing = False
intents.scheduled_events = False


bot = AudioBot(prefix=sorted(['Alexa ', 'alexa ', 'ä', 'a', 'pls', 'as'], reverse=True),
               conf=config, max_messages=100, cogs=initial_cogs, intents=intents,
               debug_guilds=get_test_guilds(), test_mode=is_test_mode())

bot.load_extension('cogs.audio')
bot.run(os.getenv('TOKEN'))

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
sys.exit(bot._exit_code)


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
import sys

import discord

from bot.Not_a_bot import NotABot
from bot.config import Config
from bot.formatter import LoggingFormatter

discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
discord_logger.addHandler(handler)

logger = logging.getLogger('debug')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='debug.log', encoding='utf-8', mode='a')
handler.setFormatter(logging.Formatter('[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
logger.addHandler(handler)

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
terminal.addHandler(handler)

logger = logging.getLogger('audio')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='audio.log', encoding='utf-8', mode='a')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
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

if not discord.opus.is_loaded():
    discord.opus.load_opus('opus')

initial_cogs = [
    'admin',
    'autoresponds',
    'autoroles',
    'botadmin',
    'botmod',
    'colors',
    'command_blacklist',
    'dbl',
    'emotes',
    'gachiGASM',
    'hearthstone',
    'images',
    'jojo',
    'last_seen',
    'logging',
    'misc',
    'moderator',
    'neural_networks',
    'pokemon',
    'privacy',
    'search',
    'server',
    'server_specific',
    'settings',
    'stats',
    'utils',
    'voting']

terminal.info('Main bot starting up')
logger.info('Starting bots')

# Initialize tensorflow for text cmd
try:
    raise Exception('Not loading tensorflow for a speedup')
    poke_model = init_tf.init_poke_tf()  # Will increase ram usage by around 100mb
    model = init_tf.init_tf()
except:
    terminal.exception('Failed to initialize tensorflow')
    model = None
    poke_model = None

#bot=Ganypepe(prefix='-', conf=config, pm_help=False, max_messages=10000, test_mode=True)
bot = NotABot(prefix='-', conf=config, pm_help=False, max_messages=10000, test_mode=True, cogs=initial_cogs, model=model, poke_model=poke_model)
bot.run(config.test_token)

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
sys.exit(bot._exit_code)

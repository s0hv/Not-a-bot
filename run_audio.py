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

from bot.audio_bot import AudioBot
from bot.config import Config
from bot.formatter import LoggingFormatter

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
    'audio',
    'botadmin',
    'command_blacklist']

terminal.info('Main bot starting up')
logger.info('Starting bot')
bot = AudioBot(prefix=sorted(['alexa ', 'ä', 'a', 'pls', 'as'], reverse=True), conf=config, pm_help=False, max_messages=100, cogs=initial_cogs)
bot.run(config.audio_token)


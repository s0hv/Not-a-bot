#!/usr/bin/env python
# -*-coding=utf-8 -*-

import logging
import sys

import discord

from bot.Not_a_bot import NotABot
from bot.config import Config
from bot.formatter import LoggingFormatter

discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8-sig', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
discord_logger.addHandler(handler)

logger = logging.getLogger('debug')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='debug.log', encoding='utf-8-sig', mode='a')
handler.setFormatter(logging.Formatter('[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
logger.addHandler(handler)

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
terminal.addHandler(handler)

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
logger.info('Starting bot')
bot = NotABot(prefix='!', conf=config, pm_help=False, max_messages=10000, cogs=initial_cogs)
bot.run(config.token)


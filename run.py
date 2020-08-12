#!/usr/bin/env python
# -*-coding=utf-8 -*-

import logging
import os
import subprocess
import sys

from bot.Not_a_bot import NotABot
from bot.config import Config
from bot.formatter import LoggingFormatter
from utils import init_tf

discord_logger = logging.getLogger('discord')
discord_logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8-sig', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
discord_logger.addHandler(handler)

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
terminal.addHandler(handler)
error_handler = logging.FileHandler(filename='error.log', encoding='utf-8', mode='a')
error_handler.setFormatter(logging.Formatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
error_handler.setLevel(logging.ERROR)
terminal.addHandler(error_handler)

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

# check whether convert is invoked with 'magick convert' or just convert
if not os.environ.get('MAGICK_PREFIX'):
    try:
        subprocess.call(['magick'], timeout=3, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.environ['MAGICK_PREFIX'] = 'magick '
    except FileNotFoundError:
        os.environ['MAGICK_PREFIX'] = ''

# Initialize tensorflow for text cmd
try:
    model = init_tf.init_tf()
except:
    terminal.exception('Failed to initialize tensorflow')
    model = None


bot = NotABot(prefix='!', conf=config, max_messages=5000, cogs=initial_cogs, model=model, shard_count=2)
bot.run(config.token)

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
sys.exit(bot._exit_code)

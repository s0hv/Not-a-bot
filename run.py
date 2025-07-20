#!/usr/bin/env python
# -*-coding=utf-8 -*-
import asyncio
import logging
import os
import subprocess
import sys
from typing import Optional

import disnake
from disnake.ext.commands import CommandSyncFlags

from bot.Not_a_bot import NotABot
from bot.config import Config, get_test_guilds, is_test_mode
from bot.formatter import LoggingFormatter
from utils import init_tf

test_mode = is_test_mode()

discord_logger = logging.getLogger('disnake')
discord_logger.setLevel(logging.DEBUG if test_mode else logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='a')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
discord_logger.addHandler(handler)

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter(
    '{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}',
    datefmt='%Y-%m-%d %H:%M:%S',
    style='{'))
terminal.addHandler(handler)
error_handler = logging.FileHandler(filename='error.log', encoding='utf-8', mode='a')
error_handler.setFormatter(logging.Formatter(
    '{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}',
    datefmt='%Y-%m-%d %H:%M:%S',
    style='{'))
error_handler.setLevel(logging.ERROR)
terminal.addHandler(error_handler)

config = Config()

initial_cogs = [
    'autoresponds',
    'autoroles',
    'botadmin',
    'basic_logging',
    'botmod',
    'colors',
    'command_blacklist',
    'dbl',
    'emotes',
    'gachiGASM',
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
initial_cogs = list(map('cogs.'.__add__, initial_cogs))

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
except ModuleNotFoundError:
    model = None
except:
    terminal.exception('Failed to initialize tensorflow')
    model = None


intents = disnake.Intents.default()
intents.members = True
intents.message_content = True

intents.invites = False
intents.voice_states = False

bot: Optional[NotABot] = None


async def main():
    global bot
    if test_mode:
        bot = NotABot(prefix='-',
                      conf=config,
                      max_messages=5000,
                      test_mode=True,
                      cogs=initial_cogs,
                      model=model,
                      intents=intents,
                      test_guilds=get_test_guilds(),
                      command_sync_flags=CommandSyncFlags.all())
    else:
        bot = NotABot(prefix='!',
                      conf=config,
                      max_messages=5000,
                      cogs=initial_cogs,
                      model=model,
                      shard_count=2,
                      intents=intents,
                      chunk_guilds_at_startup=False)

    await bot.async_init()
    bot.load_default_cogs()

    await bot.start(os.getenv('TOKEN'))


asyncio.run(main(), debug=test_mode)

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
if bot:
    sys.exit(bot.exit_code)

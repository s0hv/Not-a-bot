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
import logging
import os
import sys

import disnake
from disnake.ext.commands import CommandSyncFlags, Param

from bot.audio_bot import AudioBot
from bot.config import Config, get_test_guilds, is_test_mode
from bot.converters import autocomplete_command
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

discord_logger = logging.getLogger('disnake')
discord_logger.setLevel(logging.INFO)
handler = logging.FileHandler(filename='discord.log', encoding='utf-8-sig', mode='w')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
discord_logger.addHandler(handler)

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
    'audio',
    'basic_logging',
    'botadmin',
    'command_blacklist'
]
initial_cogs = list(map('cogs.'.__add__, initial_cogs))

terminal.info('Main bot starting up')
logger.info('Starting bot')
config.default_activity = {'type': 1, 'name': 'Music'}

intents = disnake.Intents.default()
# Required for seeing voice channel members on startup
intents.members = True

intents.invites = False
intents.integrations = False
intents.webhooks = False
intents.bans = False
intents.emojis_and_stickers = False
intents.typing = False
intents.message_content = True

test_mode = is_test_mode()
bot: AudioBot = None


async def main():
    global bot
    bot = AudioBot(prefix=sorted(['Alexa ', 'alexa ', 'ä', 'a', 'pls ', 'as', 'asunto'], reverse=True),
                   conf=config,
                   max_messages=100,
                   cogs=initial_cogs,
                   intents=intents,
                   test_guilds=get_test_guilds(),
                   test_mode=test_mode,
                   command_sync_flags=CommandSyncFlags.all() if test_mode else CommandSyncFlags.default()
                   )

    await bot.async_init()
    bot.load_default_cogs()

    @bot.slash_command(name='help')
    async def help_slash(inter: disnake.ApplicationCommandInteraction, command: str = Param(autocomplete=autocomplete_command)):
        cmd = inter.bot.get_command(command)
        slash_cmd = inter.bot.get_slash_command(command)

        description = (cmd and cmd.description) or \
                      (slash_cmd and (slash_cmd.docstring.get('description') or slash_cmd.body.description))
        embed = disnake.Embed(title=command, description=description)
        await inter.send(embed=embed)

    await bot.start(os.getenv('TOKEN'))

asyncio.run(main())

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
sys.exit(bot.exit_code)

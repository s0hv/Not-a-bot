#!/usr/bin/env python
# -*-coding=utf-8 -*-
import asyncio
import logging
import os
import sys
from typing import Optional

import disnake
from disnake.ext.commands import Param

from bot.config import Config, is_test_mode
from bot.converters import autocomplete_command
from bot.formatter import LoggingFormatter
from bot.sfx_bot import Ganypepe

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
terminal.addHandler(handler)
error_handler = logging.FileHandler(filename='error.log', encoding='utf-8', mode='a')
error_handler.setFormatter(logging.Formatter('{color}[{module}][{asctime}] [Thread: {thread}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
error_handler.setLevel(logging.ERROR)
terminal.addHandler(error_handler)

config = Config()
test_mode = is_test_mode()

intents = disnake.Intents.none()
bot: Optional[Ganypepe] = None


async def main():
    global bot
    terminal.info('SFX bot starting up')
    bot = Ganypepe(prefix=disnake.ext.commands.when_mentioned, conf=config, max_messages=100)

    @bot.slash_command(name='help')
    async def help_slash(inter: disnake.ApplicationCommandInteraction, command: str = Param(autocomplete=autocomplete_command)):
        cmd = inter.bot.get_command(command)
        slash_cmd = inter.bot.get_slash_command(command)

        description = (cmd and (cmd.description or cmd.help)) or \
                      (slash_cmd and (slash_cmd.docstring.get('description') or slash_cmd.body.description))
        embed = disnake.Embed(title=command, description=description)
        await inter.send(embed=embed)

    await bot.start(os.getenv('TOKEN'))


asyncio.run(main(), debug=test_mode)

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
if bot:
    sys.exit(bot.exit_code)

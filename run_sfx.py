import logging
import sys

import discord

from bot.config import Config
from bot.formatter import LoggingFormatter
from bot.sfx_bot import Ganypepe

logger = logging.getLogger('debug')
logger.setLevel(logging.DEBUG)
handler = logging.FileHandler(filename='debug.log', encoding='utf-8-sig', mode='a')
handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
logger.addHandler(handler)

terminal = logging.getLogger('terminal')
terminal.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(LoggingFormatter('{color}[{module}][{asctime}] [{levelname}]:{colorend} {message}', datefmt='%Y-%m-%d %H:%M:%S', style='{'))
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


terminal.info('SFX bot starting up')
bot = Ganypepe(prefix='!!', conf=config, max_messages=100)
bot.run(config.sfx_token)

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
sys.exit(bot._exit_code)

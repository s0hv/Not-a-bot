import logging
import sys

import disnake

from bot.config import Config
from bot.formatter import LoggingFormatter
from bot.sfx_bot import Ganypepe

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

if not disnake.opus.is_loaded():
    disnake.opus.load_opus('opus')


terminal.info('SFX bot starting up')
bot = Ganypepe(prefix='!!', conf=config, max_messages=100)
bot.run(config.sfx_token)

# We have systemctl set up in a way that different exit codes
# have different effects on restarting behavior
import sys
sys.exit(bot._exit_code)

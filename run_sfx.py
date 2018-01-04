from bot.sfx_bot import Ganypepe
import discord

from bot.config import Config

config = Config()

if not discord.opus.is_loaded():
    discord.opus.load_opus('opus')


print('[INFO] SFX bot starting up')
bot = Ganypepe(prefix='!!', conf=config, pm_help=False, max_messages=1000)
bot.run(config.sfx_token)

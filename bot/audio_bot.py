import discord

from bot.botbase import BotBase
from bot.youtube import YTApi


class AudioBot(BotBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.playlists = {}
        self.viewed_playlists = {}
        self.prefix = self.get_command_prefix
        self.yt_api = YTApi(self.config.youtube_api_key)

    async def on_ready(self):
        await super().on_ready()
        if self.config.default_activity:
            await self.change_presence(activity=discord.Activity(**self.config.default_activity))

    # The prefix function is defined to take bot as it's first parameter
    # no matter what so in order to not have the same object added in twice
    # I made this a staticmethod instead
    @staticmethod
    def get_command_prefix(self, message):  # skipcq: PYL-W0211
        return self.default_prefix

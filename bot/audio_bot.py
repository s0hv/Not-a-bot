import discord

from bot.botbase import BotBase


class AudioBot(BotBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.playlists = {}
        self.viewed_playlists = {}
        self.prefix = self.get_command_prefix

    async def on_ready(self):
        await super().on_ready()
        if self.config.default_activity:
            await self.change_presence(activity=discord.Activity(**self.config.default_activity))

    @staticmethod
    def get_command_prefix(self, message):
        return self.default_prefix

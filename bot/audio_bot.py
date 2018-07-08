from bot.botbase import BotBase


class AudioBot(BotBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.playlists = {}
        self.prefix = self.get_command_prefix

    @staticmethod
    def get_command_prefix(self, message):
        guild = message.guild
        return self.default_prefix, self.guild_cache.prefixes(guild.id)

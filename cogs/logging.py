from cogs.cog import Cog


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.session = bot.mysql.session

    async def on_message(self, message):
        sql = "INSERT INTO `messages` (`server`, `server_name`, `channel`, `channel_name`, `user`, `user_id`, `message_id`) VALUES (%s, %s, %s, %s, %s, %s, %s)"

from cogs.cog import Cog


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.session = bot.mysql.session

    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        sql = "INSERT INTO `messages` (`shard`, `server`, `server_name`, `channel`, `channel_name`, `user`, `user_id`, `message`, `message_id`, `attachment`) " \
              "VALUES (:shard, :server, :server_name, :channel, :channel_name, :user, :user_id, :message, :message_id, :attachment)"
        is_pm = message.channel.is_private
        shard = self.bot.shard_id
        server = int(message.server.id) if not is_pm else None
        server_name = message.server.name if not is_pm else 'DM'
        channel = int(message.channel.id) if not is_pm else None
        channel_name = message.channel.name if not is_pm else None
        user = str(message.author)
        user_id = int(message.author.id)
        message_id = int(message.id)
        attachment = message.attachments[0].get('url') if message.attachments else None
        # print((shard, server, server_name, channel, channel_name, user, user_id, message.content, message_id, attachment))

        self.session.execute(sql, {'shard': shard,
                                   'server': server,
                                   'server_name': server_name,
                                   'channel': channel,
                                   'channel_name': channel_name,
                                   'user': user,
                                   'user_id': user_id,
                                   'message': message.content,
                                   'message_id': message_id,
                                   'attachment': attachment})

        self.session.commit()


def setup(bot):
    bot.add_cog(Logger(bot))

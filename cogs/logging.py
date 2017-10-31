from cogs.cog import Cog


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.session = bot.mysql.session

    async def on_message(self, message):
        if message.author == self.bot.user:
            return

        sql = "INSERT INTO `messages` (`shard`, `server`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`) " \
              "VALUES (:shard, :server, :channel, :user, :user_id, :message, :message_id, :attachment)"
        is_pm = message.channel.is_private
        shard = self.bot.shard_id
        server = int(message.server.id) if not is_pm else None
        # server_name = message.server.name if not is_pm else 'DM'
        channel = int(message.channel.id) if not is_pm else None
        # channel_name = message.channel.name if not is_pm else None
        user = str(message.author)
        user_id = int(message.author.id)
        message_id = int(message.id)
        message_content = None if not is_pm else message.content  # BOI I need to know if my bot is abused in dms
        attachment = message.attachments[0].get('url') if message.attachments else None
        # print((shard, server, server_name, channel, channel_name, user, user_id, message.content, message_id, attachment))

        try:
            self.session.execute(sql, {'shard': shard,
                                       'server': server,
                                       'channel': channel,
                                       'user': user,
                                       'user_id': user_id,
                                       'message': message_content,
                                       'message_id': message_id,
                                       'attachment': attachment})

            self.session.commit()
        except:
            self.session.rollback()
            self.session.close()
            self.session = self.bot.get_session

    async def on_member_join(self, member):
        sql = "INSERT INTO `join_leave` (`user_id`, `server`, `value`) VALUES " \
              "(:user_id, :server, :value) ON DUPLICATE KEY UPDATE value=1"

        try:
            self.session.execute(sql, {'user_id': member.id,
                                       'server': member.server.id,
                                       'value': 1})
            self.session.commit()
        except:
            self.session.rollback()

    async def on_member_remove(self, member):
        sql = "INSERT INTO `join_leave` (`user_id`, `server`, `value`) VALUES " \
              "(:user_id, :server, :value) ON DUPLICATE KEY UPDATE value=-1"

        try:
            self.session.execute(sql, {'user_id': member.id,
                                       'server': member.server.id,
                                       'value': -1})
            self.session.commit()
        except:
            self.session.rollback()


def setup(bot):
    bot.add_cog(Logger(bot))

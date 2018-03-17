from cogs.cog import Cog
from utils.utilities import (split_string, is_image_url, format_on_delete, format_on_edit,
                             format_join_leave)
import logging
from discord import errors
from random import choice
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.session = bot.mysql.session

    def format_for_db(self, message):
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

        # Only save image links for later use in image commands
        attachment = message.attachments[0].get('url') if message.attachments else None
        if attachment and not is_image_url(attachment):
            attachment = None

        if attachment is None:
            attachment = self.get_image_from_embeds(message.embeds)

        return {'shard': shard,
                'server': server,
                'channel': channel,
                'user': user,
                'user_id': user_id,
                'message': message_content,
                'message_id': message_id,
                'attachment': attachment,
                'time': message.timestamp}

    @staticmethod
    def get_image_from_embeds(embeds):
        for embed in embeds:
            embed_type = embed.get('type', None)
            if embed_type == 'video':
                attachment = embed.get('thumbnail', {}).get('url')
                if attachment:
                    return attachment
                else:
                    continue

            elif embed_type == 'rich':
                attachment = embed.get('image', {}).get('url')
            elif embed_type == 'image':
                attachment = embed.get('url')
            else:
                continue

            return attachment

    async def on_message(self, message):
        sql = "INSERT INTO `messages` (`shard`, `server`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`, `time`) " \
              "VALUES (:shard, :server, :channel, :user, :user_id, :message, :message_id, :attachment, :time)"

        d = self.format_for_db(message)

        # terminal.info(str((shard, server, server_name, channel, channel_name, user, user_id, message.content, message_id, attachment)))

        try:
            self.session.execute(sql, d)

            self.session.commit()
        except:
            self.session.rollback()
            self.session.close()
            self.session = self.bot.get_session

    async def on_member_join(self, member):
        server = member.server
        sql = "INSERT INTO `join_leave` (`user_id`, `server`, `value`) VALUES " \
              "(:user_id, :server, :value) ON DUPLICATE KEY UPDATE value=1"

        try:
            self.session.execute(sql, {'user_id': member.id,
                                       'server': server.id,
                                       'value': 1})
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

        channel = self.bot.guild_cache.join_channel(server.id)
        channel = server.get_channel(channel)
        if channel is None:
            return

        message = self.bot.guild_cache.join_message(server.id, default_message=True)
        if not message:
            return

        perms = channel.permissions_for(channel.server.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        if member.id == '287664210152783873':
            message = 'Cease the tag %s' % member.mention
        else:
            message = format_join_leave(member, message)

        await self.bot.send_message(channel, message)

    async def on_member_remove(self, member):
        server = member.server
        sql = "INSERT INTO `join_leave` (`user_id`, `server`, `value`) VALUES " \
              "(:user_id, :server, :value) ON DUPLICATE KEY UPDATE value=-1"

        try:
            self.session.execute(sql, {'user_id': member.id,
                                       'server': server.id,
                                       'value': -1})
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

        channel = self.bot.guild_cache.leave_channel(server.id)
        channel = server.get_channel(channel)
        if channel is None:
            return

        message = self.bot.guild_cache.leave_message(server.id, default_message=True)
        if not message:
            return

        perms = channel.permissions_for(channel.server.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        message = format_join_leave(member, message)
        await self.bot.send_message(channel, message)

    async def on_message_delete(self, msg):
        if msg.author.bot or msg.channel.id == '336917918040326166':
            return

        channel = self.bot.guild_cache.on_delete_channel(msg.server.id)
        channel = self.bot.get_channel(channel)
        if channel is None:
            return

        perms = channel.permissions_for(channel.server.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        message = self.bot.guild_cache.on_delete_message(msg.server.id, default_message=True)
        message = format_on_delete(msg, message)
        message = split_string(message, splitter='\n')
        if len(message) > 2:
            m = '{0.id}: {0.name} On delete message had to post over 2 messages'.format(msg.server)
            logger.info(m)
            terminal.warning(m)

        for m in message:
            try:
                await self.bot.send_message(channel, m)
            except errors.HTTPException:
                await self.bot.send_message(self.bot.get_channel('252872751319089153'), '{} posted spam string'.format(msg.author))

    async def on_message_edit(self, before, after):
        if before.content == after.content:
            image = self.get_image_from_embeds(after.embeds)
            if not image:
                return

            sql = "INSERT INTO `messages` (`shard`, `server`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`, `time`) " \
                  "VALUES (:shard, :server, :channel, :user, :user_id, :message, :message_id, :attachment, :time) ON DUPLICATE KEY UPDATE attachment=IFNULL(attachment, :attachment)"
            session = self.bot.get_session
            d = self.format_for_db(after)
            try:
                session.execute(sql, d)
                session.commit()
            except SQLAlchemyError:
                pass

        if before.author.bot or before.channel.id == '336917918040326166':
            return

        channel = self.bot.guild_cache.on_edit_channel(before.server.id)
        channel = self.bot.get_channel(channel)
        if not channel:
            return

        message = self.bot.guild_cache.on_edit_message(before.server.id, default_message=True)
        if message is None:
            return

        message = format_on_edit(before, after, message)
        if message is None:
            return

        perms = channel.permissions_for(channel.server.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        message = split_string(message, maxlen=2000)
        if len(message) > 4:
            m = '{0.id}: {0.name} On edit message had to post over 4 messages'.format(before.server)
            logger.info(m)
            terminal.warning(m)

        for m in message:
            await self.bot.send_message(channel, m)

    async def on_server_role_delete(self, role):
            self.bot.dbutil.delete_role(role.id, role.server.id)

    async def on_server_role_create(self, role):
        self.bot.dbutil.add_roles(role.server.id, role.id)

    async def on_command_completion(self, cmd, ctx):
        entries = []
        command = cmd
        while command.parent is not None:
            command = command.parent
            entries.append(command.name)
        entries = list(reversed(entries))
        entries.append(cmd.name)
        parent = entries[0]
        self.bot.dbutil.command_used(parent, entries[1:] or 0)


def setup(bot):
    bot.add_cog(Logger(bot))

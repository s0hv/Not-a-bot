from cogs.cog import Cog
from utils.utilities import (split_string, is_image_url, format_on_delete, format_on_edit,
                             format_join_leave)
import logging
from discord import errors
from random import choice
from discord.abc import PrivateChannel
from sqlalchemy.exc import SQLAlchemyError
from discord.embeds import EmptyEmbed
logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.session = bot.get_session

    def format_for_db(self, message):
        is_pm = isinstance(message.channel, PrivateChannel)
        shard = self.bot.shard_id
        guild = message.guild.id if not is_pm else None
        # guild_name = message.guild.name if not is_pm else 'DM'
        channel = message.channel.id if not is_pm else None
        # channel_name = message.channel.name if not is_pm else None
        user = str(message.author)
        user_id = message.author.id
        message_id = message.id
        message_content = None if not is_pm else message.content  # BOI I need to know if my bot is abused in dms

        # Only save image links for later use in image commands
        attachment = message.attachments[0].url if message.attachments else None
        if attachment and not message.attachments[0].width:
            attachment = None

        if attachment is None:
            attachment = self.get_image_from_embeds(message.embeds)

        return {'shard': shard,
                'guild': guild,
                'channel': channel,
                'user': user,
                'user_id': user_id,
                'message': message_content,
                'message_id': message_id,
                'attachment': attachment,
                'time': message.created_at}

    @staticmethod
    def get_image_from_embeds(embeds):
        for embed in embeds:
            embed_type = embed.type
            if embed_type == 'video':
                attachment = embed.thumbnail.url
                if attachment:
                    return attachment
                else:
                    continue

            elif embed_type == 'rich':
                attachment = embed.image.url
            elif embed_type == 'image':
                attachment = embed.url
            else:
                continue

            return attachment if attachment != EmptyEmbed else None

    async def on_message(self, message):
        sql = "INSERT INTO `messages` (`shard`, `guild`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`, `time`) " \
              "VALUES (:shard, :guild, :channel, :user, :user_id, :message, :message_id, :attachment, :time)"

        d = self.format_for_db(message)

        # terminal.info(str((shard, guild, guild_name, channel, channel_name, user, user_id, message.content, message_id, attachment)))

        try:
            self.session.execute(sql, d)

            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()
            self.session.close()
            self.session = self.bot.get_session

    async def on_member_join(self, member):
        guild = member.guild
        sql = "INSERT INTO `join_leave` (`user_id`, `guild`, `value`) VALUES " \
              "(:user_id, :guild, :value) ON DUPLICATE KEY UPDATE value=1"

        try:
            self.session.execute(sql, {'user_id': member.id,
                                       'guild': guild.id,
                                       'value': 1})
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

        channel = self.bot.guild_cache.join_channel(guild.id)
        channel = guild.get_channel(channel)
        if channel is None:
            return

        message = self.bot.guild_cache.join_message(guild.id, default_message=True)
        if not message:
            return

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        if member.id == 287664210152783873:
            message = 'Cease the tag %s' % member.mention
        else:
            message = format_join_leave(member, message)

        await channel.send(message)

    async def on_member_remove(self, member):
        guild = member.guild
        sql = "INSERT INTO `join_leave` (`user_id`, `guild`, `value`) VALUES " \
              "(:user_id, :guild, :value) ON DUPLICATE KEY UPDATE value=-1"

        try:
            self.session.execute(sql, {'user_id': member.id,
                                       'guild': guild.id,
                                       'value': -1})
            self.session.commit()
        except SQLAlchemyError:
            self.session.rollback()

        channel = self.bot.guild_cache.leave_channel(guild.id)
        channel = guild.get_channel(channel)
        if channel is None:
            return

        message = self.bot.guild_cache.leave_message(guild.id, default_message=True)
        if not message:
            return

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        message = format_join_leave(member, message)
        await channel.send(message)

    async def on_message_delete(self, msg):
        if msg.author.bot or msg.channel.id == 336917918040326166:
            return

        channel = self.bot.guild_cache.on_delete_channel(msg.guild.id)
        channel = self.bot.get_channel(channel)
        if channel is None:
            return

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        message = self.bot.guild_cache.on_delete_message(msg.guild.id, default_message=True)
        message = format_on_delete(msg, message)
        message = split_string(message, splitter='\n')
        if len(message) > 2:
            m = '{0.id}: {0.name} On delete message had to post over 2 messages'.format(msg.guild)
            logger.info(m)
            terminal.warning(m)

        for m in message:
            try:
                await channel.send(m)
            except errors.HTTPException:
                await self.bot.get_channel(252872751319089153).send('{} posted spam string'.format(msg.author))

    async def on_message_edit(self, before, after):
        if before.content == after.content:
            image = self.get_image_from_embeds(after.embeds)
            if not image:
                return

            sql = "INSERT INTO `messages` (`shard`, `guild`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`, `time`) " \
                  "VALUES (:shard, :guild, :channel, :user, :user_id, :message, :message_id, :attachment, :time) ON DUPLICATE KEY UPDATE attachment=IFNULL(attachment, :attachment)"
            session = self.bot.get_session
            d = self.format_for_db(after)
            try:
                session.execute(sql, d)
                session.commit()
            except SQLAlchemyError:
                pass

        if before.author.bot or before.channel.id == 336917918040326166:
            return

        channel = self.bot.guild_cache.on_edit_channel(before.guild.id)
        channel = self.bot.get_channel(channel)
        if not channel:
            return

        message = self.bot.guild_cache.on_edit_message(before.guild.id, default_message=True)
        if message is None:
            return

        message = format_on_edit(before, after, message)
        if message is None:
            return

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        if not perms.send_messages:
            return

        message = split_string(message, maxlen=2000)
        if len(message) > 4:
            m = '{0.id}: {0.name} On edit message had to post over 4 messages'.format(before.guild)
            logger.info(m)
            terminal.warning(m)

        for m in message:
            await channel.send(m)

    async def on_guild_role_delete(self, role):
        self.bot.dbutil.delete_role(role.id, role.guild.id)

    async def on_guild_role_create(self, role):
        self.bot.dbutil.add_roles(role.guild.id, role.id)

    async def on_command_completion(self, ctx):
        entries = []
        cmd = ctx.command
        command = cmd
        while command.parent is not None:
            command = command.parent
            entries.append(command.name)
        entries = list(reversed(entries))
        entries.append(cmd.name)
        self.bot.dbutil.command_used(entries[0], ' '.join(entries[1:]) or "")


def setup(bot):
    bot.add_cog(Logger(bot))

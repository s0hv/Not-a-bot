import asyncio
import logging
from queue import Queue

from asyncio import tasks

import discord
from discord.abc import PrivateChannel
from discord.embeds import EmptyEmbed
from sqlalchemy import exc
from sqlalchemy.exc import SQLAlchemyError

from cogs.cog import Cog
from utils.utilities import (split_string, format_on_delete, format_on_edit,
                             format_join_leave, get_avatar)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._q = Queue()
        self._logging = asyncio.ensure_future(tasks._wrap_awaitable(self.bot.loop.run_in_executor(self.bot.threadpool, self._logging_loop)), loop=self.bot.loop)
        self._stop_log = asyncio.Event(loop=self.bot.loop)
        asyncio.ensure_future()
        import inspect
        inspect.isawaitable()

    def __unload(self):
        self.bot.loop.call_soon_threadsafe(self._stop_log.set)
        self._q.put_nowait(1)  # Cause TypeError inside the loop
        try:
            self._logging.result()
        except asyncio.TimeoutError:
            self._logging.cancel()

    def _logging_loop(self):
        while hasattr(self, '_stop_log') and not self._stop_log.is_set():
            try:
                sql, params = self._q.get()
            except (ValueError, TypeError):
                continue

            session = self.bot.get_session

            try:
                session.execute(sql, params)

                session.commit()
            except exc.DBAPIError as e:
                if e.connection_invalidated:
                    self.bot.engine.connect()
            except SQLAlchemyError:
                session.rollback()

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

    def check_mentions(self, message):
        if message.guild is None:
            return

        if not message.raw_role_mentions:
            return

        roles = []
        guild = message.guild
        for role_id in set(message.raw_role_mentions):
            role = guild.get_role(role_id)
            if role:
                roles.append(role)

        if not roles:
            return

        sql = 'INSERT INTO `mention_stats` (`guild`, `role`, `role_name`) ' \
              'VALUES (:guild, :role, :role_name)'

        data = []
        for idx, role in enumerate(roles):
            data.append({'guild': guild.id, 'role': role.id, 'role_name': role.name})

        sql += ' ON DUPLICATE KEY UPDATE amount=amount+1, role_name=VALUES(role_name)'
        self._q.put_nowait((sql, data))

    async def on_message(self, message):
        self.check_mentions(message)
        sql = "INSERT INTO `messages` (`shard`, `guild`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`, `time`) " \
              "VALUES (:shard, :guild, :channel, :user, :user_id, :message, :message_id, :attachment, :time)"

        d = self.format_for_db(message)

        # terminal.info(str((shard, guild, guild_name, channel, channel_name, user, user_id, message.content, message_id, attachment)))
        self._q.put_nowait((sql, d))

    async def on_member_join(self, member):
        guild = member.guild
        sql = "INSERT INTO `join_leave` (`user_id`, `guild`, `value`) VALUES " \
              "(:user_id, :guild, :value) ON DUPLICATE KEY UPDATE value=1, at=CURRENT_TIMESTAMP"

        self._q.put_nowait((sql, {'user_id': member.id,
                                  'guild': guild.id,
                                  'value': 1}))

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
              "(:user_id, :guild, :value) ON DUPLICATE KEY UPDATE value=-1, at=CURRENT_TIMESTAMP"

        self._q.put_nowait((sql, {'user_id': member.id,
                                  'guild': guild.id,
                                  'value': -1}))

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

        is_embed = self.bot.guild_cache.on_delete_embed(msg.guild.id)

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        if not perms.send_messages or (is_embed and not perms.embed_links):
            return

        message = self.bot.guild_cache.on_delete_message(msg.guild.id, default_message=True)
        message = format_on_delete(msg, message)
        message = split_string(message, splitter='\n', maxlen=2048 if is_embed else 2000)
        if len(message) > 2:
            m = '{0.id}: {0.name} On delete message had to post over 2 messages'.format(msg.guild)
            logger.info(m)
            terminal.warning(m)

        for m in message:
            if is_embed:
                await channel.send(embed=self.create_embed(msg,
                                                           f'Message deleted in #{msg.channel.name} {msg.channel.id}',
                                                           m,
                                                           msg.created_at))
            else:
                await channel.send(m)

    async def on_message_edit(self, before, after):
        if before.content == after.content:
            image = self.get_image_from_embeds(after.embeds)
            if not image:
                return

            sql = "INSERT INTO `messages` (`shard`, `guild`, `channel`, `user`, `user_id`, `message`, `message_id`, `attachment`, `time`) " \
                  "VALUES (:shard, :guild, :channel, :user, :user_id, :message, :message_id, :attachment, :time) ON DUPLICATE KEY UPDATE attachment=IFNULL(attachment, :attachment)"

            d = self.format_for_db(after)
            self._q.put_nowait((sql, d))

        if before.author.bot or before.channel.id == 336917918040326166:
            return

        channel = self.bot.guild_cache.on_edit_channel(before.guild.id)
        channel = self.bot.get_channel(channel)
        if not channel:
            return

        message = self.bot.guild_cache.on_edit_message(before.guild.id, default_message=True)
        if message is None:
            return

        is_embed = self.bot.guild_cache.on_edit_embed(before.guild.id)

        message = format_on_edit(before, after, message)
        if message is None:
            return

        perms = channel.permissions_for(channel.guild.get_member(self.bot.user.id))
        if not perms.send_messages or (is_embed and not perms.embed_links):
            return

        message = split_string(message, maxlen=2048 if is_embed else 2000)
        if len(message) > 4:
            m = '{0.id}: {0.name} On edit message had to post over 4 messages'.format(before.guild)
            logger.info(m)
            terminal.warning(m)

        for m in message:
            if is_embed:
                await channel.send(embed=self.create_embed(after,
                                                           f'Message edited in #{after.channel.name} {after.channel.id}',
                                                           m,
                                                           after.edited_at))
            else:
                await channel.send(m)

    @staticmethod
    def create_embed(message, title, description, timestamp):
        embed = discord.Embed(title=title, description=description, timestamp=timestamp)
        embed.set_author(name=str(message.author), icon_url=get_avatar(message.author))
        return embed

    async def on_guild_role_delete(self, role):
        await self.bot.dbutil.delete_role(role.id, role.guild.id)

    async def on_guild_role_create(self, role):
        await self.bot.dbutil.add_roles(role.guild.id, role.id)

    async def on_command_completion(self, ctx):
        entries = []
        cmd = ctx.command
        command = cmd
        while command.parent is not None:
            command = command.parent
            entries.append(command.name)
        entries = list(reversed(entries))
        entries.append(cmd.name)
        await self.bot.dbutil.command_used(entries[0], ' '.join(entries[1:]) or "")


def setup(bot):
    bot.add_cog(Logger(bot))

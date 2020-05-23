import logging

import discord
from discord.abc import PrivateChannel

from cogs.cog import Cog
from utils.utilities import (split_string, format_on_delete, format_on_edit,
                             format_join_leave, get_avatar,
                             get_image_from_embeds,
                             is_image_url)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class Logger(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @staticmethod
    def format_for_db(message):
        is_pm = isinstance(message.channel, PrivateChannel)
        guild = message.guild.id if not is_pm else None
        # guild_name = message.guild.name if not is_pm else 'DM'
        channel = message.channel.id if not is_pm else None
        # channel_name = message.channel.name if not is_pm else None
        user_id = message.author.id
        message_id = message.id

        # Only save image links for later use in image commands
        attachment = message.attachments[0].url if message.attachments else None
        if attachment and not message.attachments[0].width:
            attachment = None

        if attachment is None:
            attachment = get_image_from_embeds(message.embeds)

        if not is_image_url(attachment):
            attachment = None

        return (guild,
                channel,
                user_id,
                message_id), attachment

    async def check_mentions(self, message):
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

        sql = 'INSERT INTO mention_stats AS ms (guild, role, role_name) ' \
              'VALUES %s' % self.bot.dbutil.create_bind_groups(len(roles), 3)

        data = []
        for role in roles:
            data.extend((guild.id, role.id, role.name))

        sql = sql.rstrip(',')
        sql += ' ON CONFLICT (guild, role) DO UPDATE SET amount=ms.amount+1, role_name=EXCLUDED.role_name'
        await self.bot.dbutil.execute(sql, data)

    @Cog.listener()
    async def on_message(self, message):
        await self.check_mentions(message)
        d, attachment = self.format_for_db(message)

        if message.guild and message.guild.id in (217677285442977792,475623556164878347):
            sql = "INSERT INTO messages (guild, channel, user_id, message_id) " \
                  "VALUES ($1, $2, $3, $4)"

            await self.bot.dbutil.execute(sql, d)

        # Channel index is 1
        if attachment and d[1]:
            sql = 'INSERT INTO attachments (channel, attachment) ' \
                  'VALUES ($1, $2) ON CONFLICT (channel) DO UPDATE SET attachment=$2'
            await self.bot.dbutil.execute(sql, (d[1], attachment))

    @Cog.listener()
    async def on_member_join(self, member):
        guild = member.guild
        sql = "INSERT INTO join_leave (uid, guild, value) VALUES " \
              "($1, $2, $3) ON CONFLICT (guild, uid) DO UPDATE SET value=1, at=CURRENT_TIMESTAMP"

        await self.bot.dbutil.execute(sql, (member.id, guild.id, 1))

        sql = "INSERT INTO join_dates (uid, guild, first_join) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING"
        await self.bot.dbutil.execute(sql, (member.id, guild.id, member.joined_at))

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

    @Cog.listener()
    async def on_member_remove(self, member):
        guild = member.guild
        sql = "INSERT INTO join_leave (uid, guild, value) VALUES " \
              "($1, $2, $3) ON CONFLICT (guild, uid) DO UPDATE SET value=-1, at=CURRENT_TIMESTAMP"

        await self.bot.dbutil.execute(sql, (member.id, guild.id, -1))

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

    @Cog.listener()
    async def on_message_delete(self, msg):
        if isinstance(msg.channel, discord.DMChannel):
            return

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

    @Cog.listener()
    async def on_message_edit(self, before, after):
        if isinstance(before.channel, discord.DMChannel):
            return

        if before.content == after.content:
            image = get_image_from_embeds(after.embeds)
            if not image:
                return

            sql = 'INSERT INTO attachments (channel, attachment) ' \
                  'VALUES ($1, $2) ON CONFLICT (channel) DO UPDATE SET attachment=$2'
            await self.bot.dbutil.execute(sql, (after.channel.id, image))

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
                await channel.send(
                    embed=self.create_embed(after,
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

    @Cog.listener()
    async def on_guild_role_delete(self, role):
        await self.bot.dbutil.delete_role(role.id, role.guild.id)

    @Cog.listener()
    async def on_guild_role_create(self, role):
        await self.bot.dbutil.add_roles(role.guild.id, role.id)

    @Cog.listener()
    async def on_command_completion(self, ctx):
        entries = []
        cmd = ctx.command
        command = cmd
        while command.parent is not None:
            command = command.parent
            entries.append(command.name)
        entries = list(reversed(entries))
        entries.append(cmd.name)
        guild = ctx.guild.id if ctx.guild else None
        await self.bot.dbutil.command_used(entries[0], ' '.join(entries[1:]) or "",
                                           ctx.message.created_at, ctx.author.id,
                                           guild)


def setup(bot):
    bot.add_cog(Logger(bot))

import logging

import discord
from discord.ext.commands import cooldown, BucketType
from sqlalchemy import text
from sqlalchemy.dialects import mysql
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command
from cogs.cog import Cog
from utils.utilities import check_user_mention

logger = logging.getLogger('debug')


class Stats(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    async def on_message(self, message):
        if message.server is None:
            return

        if not message.raw_role_mentions:
            return

        roles = []
        server = message.server
        for role_id in set(message.raw_role_mentions):
            role = self.bot.get_role(server, role_id)
            if role:
                roles.append(role)

        if not roles:
            return

        sql = 'INSERT INTO `mention_stats` (`server`, `role`, `role_name`) ' \
              'VALUES '

        server_id = int(server.id)
        l = len(roles) - 1
        for idx, role in enumerate(roles):
            # sanitize name
            role_name = str(text(':role').bindparams(role=role.name).compile(dialect=mysql.dialect(), compile_kwargs={"literal_binds": True}))

            sql += '(%s, %s, %s)' % (server_id, int(role.id), role_name)
            if l == idx:
                continue

            sql += ', '

        sql += ' ON DUPLICATE KEY UPDATE amount=amount+1, role_name=VALUES(role_name)'
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to save mention stats')

    @command(pass_context=True, no_pm=True)
    @cooldown(2, 5, type=BucketType.server)
    async def mention_stats(self, ctx, page=None):
        """Get stats on how many times which roles are mentioned on this server"""
        server = ctx.message.server

        if page is not None:
            try:
                # No one probably hasn't created this many roles
                if len(page) > 6:
                    return await self.bot.say('Page out of range')

                page = int(page)
                if page <= 0:
                    page = 1
            except:
                page = 1
        else:
            page = 1

        sql = 'SELECT * FROM `mention_stats` WHERE server={} ORDER BY amount DESC LIMIT {}'.format(server.id, 10*page)
        session = self.bot.get_session
        rows = session.execute(sql).fetchall()
        if not rows:
            return await self.bot.say('No role mentions logged on this server')

        embed = discord.Embed(title='Most mentioned roles in server {}'.format(server.name))
        added = 0
        p = page*10
        for idx, row in enumerate(rows[p-10:p]):
            added += 1
            role = self.bot.get_role(server, row['role'])
            if role:
                role_name, role = role.name, role.id
            else:
                role_name, role = row['role_name'], row['role']

            embed.add_field(name='{}. {}'.format(idx + p-9, role),
                            value='<@&{}>\n{}\nwith {} mentions'.format(role, role_name, row['amount']))

        if added == 0:
            return await self.bot.say('Page out of range')

        await self.bot.send_message(ctx.message.channel, embed=embed)

    @command(pass_context=True, aliases=['seen'])
    @cooldown(1, 5, BucketType.user)
    async def last_seen(self, ctx, *, name):
        """Get when a user was last seen"""
        user_id = None
        try:
            user = int(name)
            user_id = user
            is_id = True
        except ValueError:
            if check_user_mention(ctx.message, name):
                user = ctx.message.mentions[0].id
                user_id = user_id
                name = str(ctx.message.mentions[0])
                is_id = True
            else:
                is_id = False
                user = name

        server = ctx.message.server
        if server is not None:
            server = int(server.id)
            sql = 'SELECT * FROM `last_seen_users` WHERE (server_id=0 OR server_id=:server) AND '
        else:
            server = 0
            sql = 'SELECT * FROM `last_seen_users` WHERE server_id=0 AND'

        if is_id:
            sql += 'user_id=:user ORDER BY last_seen DESC LIMIT 2'
        else:
            sql += 'username=:user ORDER BY last_seen DESC LIMIT 2'

        session = self.bot.get_session
        try:
            rows = session.execute(sql, {'server': server, 'user': user}).fetchall()
        except SQLAlchemyError as e:
            print(e)
            return await self.bot.say('Failed to get user because of an error')

        if len(rows) == 0:
            return await self.bot.say("No users found with {}. Either the bot hasn't had the chance to log activity or the name was wrong."
                                      "Names are case sensitive and must include the discrim".format(name))
        local = None
        global_ = None

        for row in rows:
            if row['server_id'] == 0:
                global_ = row

            else:
                local = row

        if user_id is None:
            if local:
                user_id = local['user_id']
            else:
                user_id = global_['user_id']

        msg = 'User {} `{}`\n'.format(name, user_id)
        if local:
            msg += 'Last seen on this server {} UTC\n'.format(local['last_seen'])
        if global_:
            msg += 'Last seen elsewhere {} UTC'.format(global_['last_seen'])

        await self.bot.say(msg)


def setup(bot):
    bot.add_cog(Stats(bot))

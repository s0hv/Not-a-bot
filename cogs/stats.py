from cogs.cog import Cog
from sqlalchemy.dialects import mysql
from sqlalchemy import text
from bot.bot import command
import discord
from discord.ext.commands import cooldown
import logging
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

        sql += ' ON DUPLICATE KEY UPDATE amount=amount+1, role_name=role_name'
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to save mention stats')

    @command(pass_context=True, no_pm=True)
    @cooldown(10, 1)
    async def mention_stats(self, ctx):
        server = ctx.message.server
        sql = 'SELECT * FROM `mention_stats` WHERE server=%s ORDER BY amount DESC LIMIT 10' % server.id
        session = self.bot.get_session
        rows = session.execute(sql).fetchall()
        if not rows:
            return await self.bot.say('No role mentions logged on this server')

        embed = discord.Embed(title='Most mentioned roles in server {}'.format(server.name))
        for idx, row in enumerate(rows):
            role = self.bot.get_role(server, row['role'])
            if role:
                role_name, role = role.name, role.id
            else:
                role_name, role = row['role_name'], row['role']

            embed.add_field(name='{}. {}'.format(idx + 1, role),
                            value='<@&{}>\n{}\nwith {} mentions'.format(role, role_name, row['amount']))

        await self.bot.send_message(ctx.message.channel, embed=embed)


def setup(bot):
    bot.add_cog(Stats(bot))

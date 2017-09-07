import logging

import discord

from cogs.cog import Cog

logger = logging.getLogger('debug')


class AutoRoles(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @property
    def dbutil(self):
        return self.bot.dbutil

    async def on_message(self, message):
        if message.server and message.server.id == '217677285442977792' and message.author.id != '123050803752730624':
            if discord.utils.find(lambda r: r.id == '323098643030736919', message.role_mentions):
                await self.bot.add_role(message.author, '323098643030736919')

    async def on_member_update(self, before, after):
        server = after.server
        if server.id == '217677285442977792':
            name = before.name if not before.nick else before.nick
            name2 = after.name if not after.nick else after.nick
            if name != name2:
                await self.bot._wants_to_be_noticed(after, server)

        if self.bot.server_cache.keeproles(server.id):
            removed, added = self.compare_roles(before, after)
            if removed:
                self.dbutil.remove_user_roles(removed, before.id)

            if added:
                self.dbutil.add_user_roles(added, before.id, server.id)

    async def on_server_role_delete(self, role):
        if self.bot.server_cache.keeproles(role.server.id):
            self.dbutil.delete_role(role.id, role.server.id)

    async def on_member_join(self, member):
        if not self.bot.server_cache.keeproles(member.server.id):
            return

        'polls LEFT OUTER JOIN pollEmotes ON polls.message = pollEmotes.poll_id LEFT OUTER JOIN emotes ON emotes.emote = pollEmotes.emote_id'

        sql = 'SELECT roles.id FROM `users` LEFT OUTER JOIN `userRoles` ON users.id=userRoles.user_id LEFT OUTER JOIN `roles` ON roles.id=userRoles.role_id ' \
              'WHERE roles.server=%s AND users.id=%s' % (member.server.id, member.id)

        session = self.bot.get_session
        roles = [str(r['id']) for r in session.execute(sql).fetchall()]
        if not roles:
            if not self.dbutil.add_user(member.id):
                return

            return

        try:
            roles.remove(member.server.default_role.id)
        except ValueError:
            pass

        for role in roles:
            try:
                await self.bot.add_role(member, role, reason='Keeproles')
            except discord.errors.Forbidden:
                logger.exception('FailFish')
                pass

    async def on_member_remove(self, member):
        if not self.bot.server_cache.keeproles(member.server.id):
            return

        roles = [r.id for r in member.roles]

        if not roles:
            self.dbutil.delete_user_roles(member.id)

        else:
            self.dbutil.add_user_roles(roles, member.id, member.server.id)

    @staticmethod
    def compare_roles(before, after):
        before = set(map(lambda r: r.id, before.roles))
        after = set(map(lambda r: r.id, after.roles))
        removed = before.difference(after)
        added = after.difference(before)
        return removed, added


def setup(bot):
    bot.add_cog(AutoRoles(bot))

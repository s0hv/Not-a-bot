import logging
from random import choice

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
        if self.bot.test_mode:
            return

        # Autogrant @every
        if message.server and message.server.id == '217677285442977792' and message.author.id != '123050803752730624':
            if discord.utils.find(lambda r: r.id == '323098643030736919', message.role_mentions):
                if not discord.utils.get(message.author.roles, id='323098643030736919'):
                    await self.bot.add_role(message.author, '323098643030736919')

    async def on_member_update(self, before, after):
        if self.bot.test_mode:
            return

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

    async def add_random_color(self, member):
        if self.bot.server_cache.random_color(member.server.id) and hasattr(self.bot, 'colors'):
            colors = self.bot.colors.get(member.server.id, {}).values()
            color_ids = {r.role_id for r in colors}
            if not color_ids:
                return

            if {r.id for r in list(member.roles)}.intersection(color_ids):
                return
            await self.bot.add_role(member, choice(list(color_ids)))

    async def on_member_join(self, member):
        server = member.server

        bot_member = server.get_member(self.bot.user.id)
        perms = bot_member.server_permissions

        # If bot doesn't have manage roles no use in trying to add roles
        if not perms.administrator and not perms.manage_roles:
            return

        roles = set()
        if self.bot.server_cache.keeproles(server.id):
            'polls LEFT OUTER JOIN pollEmotes ON polls.message = pollEmotes.poll_id LEFT OUTER JOIN emotes ON emotes.emote = pollEmotes.emote_id'

            sql = 'SELECT roles.id FROM `users` LEFT OUTER JOIN `userRoles` ON users.id=userRoles.user_id LEFT OUTER JOIN `roles` ON roles.id=userRoles.role_id ' \
                  'WHERE roles.server=%s AND users.id=%s' % (server.id, member.id)

            session = self.bot.get_session
            roles = {str(r['id']) for r in session.execute(sql).fetchall()}
            if not roles:
                return await self.add_random_color(member)

            roles.discard(server.default_role.id)

            muted_role = self.bot.server_cache.mute_role(server.id)
            if muted_role in roles:
                try:
                    await self.bot.add_role(member, muted_role)
                    roles.discard(muted_role)
                except:
                    logger.exception('[KeepRoles] Failed to add muted role first')

        if self.bot.server_cache.random_color(server.id) and hasattr(self.bot, 'colors'):
            if not roles:
                await self.add_random_color(member)
            else:
                colors = self.bot.colors.get(server.id, {}).values()
                color_ids = {i.role_id for i in colors}
                if not color_ids.intersection(roles):
                    roles.add(choice(list(color_ids)))

        if not roles:
            return

        try:
            await self.bot.add_roles(member, *roles)
        except:
            for role in roles:
                try:
                    await self.bot.add_role(member, role)
                except discord.errors.Forbidden:
                    pass
                except:
                    logger.exception('Failed to give role on join')

        if server.id == '217677285442977792':
            await self.bot._wants_to_be_noticed(member, server)

    async def on_member_remove(self, member):
        if not self.bot.server_cache.keeproles(member.server.id):
            return

        roles = [r.id for r in member.roles]
        roles.remove(member.server.default_role.id)
        self.dbutil.delete_user_roles(member.server.id, member.id)

        if roles:
            self.dbutil.add_user_roles(roles, member.id, member.server.id)
            logger.debug('{}/{} saved roles {}'.format(member.server.id, member.id, ', '.join(roles)))

    @staticmethod
    def compare_roles(before, after):
        default_role = before.server.default_role.id
        before = set(map(lambda r: r.id, before.roles))
        after = set(map(lambda r: r.id, after.roles))
        removed = before.difference(after)
        added = after.difference(before)

        # No need to keep the default role
        removed.discard(default_role)
        added.discard(default_role)

        return removed, added


def setup(bot):
    bot.add_cog(AutoRoles(bot))

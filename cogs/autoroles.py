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
        # Autogrant @every
        if message.server and message.server.id == '217677285442977792' and message.author.id != '123050803752730624':
            if discord.utils.find(lambda r: r.id == '323098643030736919', message.role_mentions):
                if not discord.utils.get(message.author.roles, id='323098643030736919'):
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
        server = member.server
        if not self.bot.server_cache.keeproles(server.id):
            return

        bot_member = server.get_member(self.bot.user.id)
        perms = bot_member.server_permissions

        # We want to disable keeproles if the bot doesn't have manage roles
        # We'll also inform server owner about this change
        if not perms.administrator and not perms.manage_roles:
            self.bot.server_cache.set_keeproles(server.id, False)
            msg = "{0.owner.mention} I don't have manage roles permission in the server {0.name}. Disabling keeproles there. " \
                  "You can re-enable them after adding manage roles perms to this bot".format(server)
            sent = False
            try:
                await self.bot.send_message(server.owner, msg)
                sent = True
            except:
                pass
            try:
                chn = list(filter(lambda c: c.permissions_for(bot_member).send_messages, server.channels))
                if not chn:
                    if not sent:
                        logger.info("Tried to inform server {0.name} {0.id} of autodisable of keeproles but couldn't send the message".format(server))
                    return

                await self.bot.send_message(chn[0], msg)
                sent = True
            except:
                pass

            if not sent:
                logger.exception("Tried to inform server {0.name} {0.id} of autodisable of keeproles but couldn't send the message".format(server))
            return

        'polls LEFT OUTER JOIN pollEmotes ON polls.message = pollEmotes.poll_id LEFT OUTER JOIN emotes ON emotes.emote = pollEmotes.emote_id'

        sql = 'SELECT roles.id FROM `users` LEFT OUTER JOIN `userRoles` ON users.id=userRoles.user_id LEFT OUTER JOIN `roles` ON roles.id=userRoles.role_id ' \
              'WHERE roles.server=%s AND users.id=%s' % (server.id, member.id)

        session = self.bot.get_session
        roles = [str(r['id']) for r in session.execute(sql).fetchall()]
        if not roles:
            self.dbutil.add_user(member.id)
            return

        try:
            roles.remove(member.server.default_role.id)
        except ValueError:
            pass

        muted_role = self.bot.server_cache.mute_role(server.id)
        if muted_role in roles:
            try:
                await self.bot.add_role(member, muted_role)
                roles.remove(muted_role)
            except:
                logger.exception('[KeepRoles] Failed to add muted role first')

        try:
            await self.bot.add_roles(member, roles)
        except:
            for role in roles:
                try:
                    await self.bot.add_role(member, role, reason='Keeproles')
                except discord.errors.Forbidden:
                    pass
                except:
                    logger.exception('[KeepRoles] Failed to give role')

    async def on_member_remove(self, member):
        if not self.bot.server_cache.keeproles(member.server.id):
            return

        roles = [r.id for r in member.roles]
        roles.remove(member.server.default_role.id)
        if not roles:
            self.dbutil.delete_user_roles(member.id)

        else:
            self.dbutil.add_user_roles(roles, member.id, member.server.id)

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

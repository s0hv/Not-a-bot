import logging
logger = logging.getLogger('debug')
from sqlalchemy.exc import SQLAlchemyError
from discord.errors import InvalidArgument

class DatabaseUtils:
    def __init__(self, bot):
        self._bot = bot

    @property
    def bot(self):
        return self._bot

    async def index_guild_member_roles(self, guild):
        import time
        t = time.time()
        default_role = guild.default_role.id
        session = self.bot.get_session

        def execute(sql_):
            try:
                session.execute(sql_)
            except SQLAlchemyError:
                session.rollback()
                logger.exception('Failed to execute sql')
                return False
            return True

        success = self.index_guild_roles(guild)
        if not success:
            return success

        logger.info('added roles in %s' % (time.time() - t))
        t1 = time.time()

        try:
            await self.bot.request_offline_members(guild)
            logger.info('added offline users in %s' % (time.time() - t1))
        except InvalidArgument:
            pass
        _m = list(guild.members)
        members = list(filter(lambda u: len(u.roles) > 1, _m))
        all_members = [str(u.id) for u in _m]

        t1 = time.time()
        sql = 'DELETE `userRoles` FROM `userRoles` INNER JOIN `roles` ON roles.id=userRoles.role WHERE roles.guild={} AND userRoles.user IN ({})'.format(guild.id, ', '.join(all_members))

        # Deletes all server records
        # sql = 'DELETE `userRoles` FROM `userRoles` INNER JOIN `roles` WHERE roles.server=%s AND userRoles.role_id=roles.id'
        if not execute(sql):
            return False
        logger.info('Deleted old records in %s' % (time.time() - t1))
        t1 = time.time()

        sql = 'INSERT IGNORE INTO `userRoles` (`user`, `role`) VALUES '
        for u in members:
            for r in u.roles:
                if r.id == default_role:
                    continue

                sql += f' ({u.id}, {r.id}),'

        sql = sql.rstrip(',')

        if not execute(sql):
            return False

        session.commit()
        logger.info('added user roles in %s' % (time.time() - t1))
        logger.info('indexed users in %s seconds' % (time.time() - t))
        return True

    def index_guild_roles(self, guild):
        session = self.bot.get_session
        roles = guild.roles
        roles = [{'id': r.id, 'guild': guild.id} for r in roles]
        role_ids = [str(r.id) for r in guild.roles]
        sql = 'INSERT IGNORE INTO `roles` (`id`, `guild`) VALUES (:id, :guild)'
        try:
            session.execute(sql, roles)
            sql = 'DELETE FROM `roles` WHERE guild={} AND NOT id IN ({})'.format(guild.id, ', '.join(role_ids))
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            return False
        return True

    def add_guilds(self, *ids):
        if not ids:
            return
        session = self.bot.get_session
        ids = [{'guild': i} for i in ids]
        sql = 'INSERT IGNORE INTO `guilds` (`guild`) VALUES (:guild)'
        try:
            session.execute(sql, ids)
            sql = 'INSERT IGNORE INTO `prefixes` (`guild`) VALUES (:guild)'
            session.execute(sql, ids)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add new servers to db')
            return False
        return True

    def add_roles(self, guild_id, *role_ids):
        session = self.bot.get_session
        sql = 'INSERT IGNORE INTO `roles` (`id`, `guild`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += f'({r}, {guild_id})'
            if idx != l:
                sql += ', '

        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add roles')
            return False

        return True

    def add_user(self, user_id):
        sql = f'INSERT IGNORE INTO `users` (`id`) VALUES ({user_id})'
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add user')
            return False

        return True

    def add_users(self, *user_ids):
        session = self.bot.get_session
        sql = 'INSERT IGNORE INTO `users` (`id`) VALUES '
        l = len(user_ids) - 1
        for idx, uid in enumerate(user_ids):
            sql += f'({uid})'
            if idx != l:
                sql += ', '

        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add users')
            return False

        return True

    def add_user_roles(self, role_ids, user_id, guild_id):
        if not self.add_roles(guild_id, *role_ids):
            return

        session = self.bot.get_session
        sql = 'INSERT IGNORE INTO `userRoles` (`user`, `role`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += f'({user_id}, {r})'
            if idx != l:
                sql += ', '

        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add roles foreign keys')
            return False

        return True

    def remove_user_roles(self, role_ids, user_id):
        session = self.bot.get_session

        sql = 'DELETE FROM `userRoles` WHERE user=%s and role IN (%s)' % (user_id, ', '.join(map(lambda i: str(i), role_ids)))
        try:
            session.execute(sql)
            session.commit()
            return True
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to delete roles')
            return False

    def add_prefix(self, guild_id, prefix):
        sql = 'INSERT INTO `prefixes` (`guild`, `prefix`) VALUES (:guild, :prefix)'
        session = self.bot.get_session

        try:
            session.execute(sql, params={'guild': guild_id, 'prefix': prefix})
            session.commit()
            return True
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add prefix')
            return False

    def remove_prefix(self, guild_id, prefix):
        sql = 'DELETE FROM `prefixes` WHERE guild=:guild AND prefix=:prefix'
        session = self.bot.get_session

        try:
            session.execute(sql, params={'guild': guild_id, 'prefix': prefix})
            session.commit()
            return True
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to remove prefix')
            return False

    def delete_role(self, role_id, guild_id):
        session = self.bot.get_session
        sql = f'DELETE FROM `roles` WHERE id={role_id} AND guild={guild_id}'
        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception(f'Could not delete role {role_id}')

    def delete_user_roles(self, guild_id, user_id):
        session = self.bot.get_session
        try:
            sql = f'DELETE `userRoles` FROM `userRoles` INNER JOIN `roles` ON roles.id=userRoles.role WHERE roles.guild={guild_id} AND userRoles.user={user_id}'
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Could not delete user roles')

    def add_automute_blacklist(self, guild_id, *channel_ids):
        session = self.bot.get_session

        sql = 'INSERT IGNORE INTO `automute_blacklist` (`guild`, `channel`) VALUES '
        sql += ', '.join(map(lambda cid: f'({guild_id}, {cid})', channel_ids))
        try:
            session.execute(sql)
            session.commit()
            success = True
        except SQLAlchemyError:
            session.rollback()
            success = False

        return success

    def remove_automute_blacklist(self, guild_id, *channel_ids):
        session = self.bot.get_session
        if not channel_ids:
            return True

        channel_ids = ', '.join(map(lambda cid: str(cid), channel_ids))
        sql = f'DELETE FROM `automute_blacklist` WHERE guild={guild_id} AND channel IN ({channel_ids}) '
        try:
            session.execute(sql)
            session.commit()
            success = True
        except SQLAlchemyError:
            session.rollback()
            success = False

        return success

    def add_automute_whitelist(self, guild_id, *role_ids):
        session = self.bot.get_session
        if not role_ids:
            return True

        sql = 'INSERT IGNORE INTO `automute_whitelist` (`guild`, `role`) VALUES '
        sql += ', '.join(map(lambda rid: f'({guild_id}, {rid})', role_ids))
        try:
            session.execute(sql)
            session.commit()
            success = True
        except SQLAlchemyError:
            session.rollback()
            success = False

        return success

    def remove_automute_whitelist(self, guild_id, *role_ids):
        session = self.bot.get_session
        if not role_ids:
            return True

        role_ids = ', '.join(map(lambda r: str(r), role_ids))
        sql = f'DELETE FROM `automute_whitelist` WHERE guild={guild_id} AND role IN ({role_ids})'
        try:
            session.execute(sql)
            session.commit()
            success = True
        except SQLAlchemyError:
            session.rollback()
            success = False

        return success

    def multiple_last_seen(self, user_ids, usernames, guild_id, timestamps):
        sql = 'INSERT INTO `last_seen_users` (`user`, `username`, `guild`, `last_seen`) VALUES (:user, :username, :guild, :time) ON DUPLICATE KEY UPDATE last_seen=VALUES(`last_seen`), username=VALUES(`username`)'
        data = [{'user': uid, 'username': u, 'guild': s, 'time': t} for uid, u, s, t in zip(user_ids, usernames, guild_id, timestamps)]
        session = self.bot.get_session
        try:
            session.execute(sql, data)
            session.commit()
        except SQLAlchemyError:
            logger.exception('Failed to set last seen')
            session.rollback()
            return False

        return True

    def add_command(self, parent, name=0):
        sql = 'INSERT IGNORE INTO `command_stats` (`parent`, `cmd`) VALUES (:parent, :cmd)'
        session = self.bot.get_session
        try:
            session.execute(sql, {'parent': parent, 'cmd': name})
            session.commit()
        except SQLAlchemyError:
            logger.exception('Failed to add command {} {}'.format(parent, name))
            session.rollback()
            return False

        return True

    def add_commands(self, values):
        """
        Inserts multiple commands to the db
        Args:
            values: A list of dictionaries with keys `parent` and `cmd`

        Returns:
            bool based on success
        """
        if not values:
            return
        sql = 'INSERT IGNORE INTO `command_stats` (`parent`, `cmd`) VALUES (:parent, :cmd)'
        session = self.bot.get_session
        try:
            session.execute(sql, values)
            session.commit()
        except SQLAlchemyError:
            logger.exception('Failed to add commands {}'.format(values))
            session.rollback()
            return False

        return True

    def command_used(self, parent, name=""):
        if name is None:
            name = 0
        sql = 'UPDATE `command_stats` SET `uses`=(`uses`+1) WHERE parent=:parent AND cmd=:cmd'
        session = self.bot.get_session
        try:
            session.execute(sql, {'parent': parent, 'cmd': name})
            session.commit()
        except SQLAlchemyError:
            logger.exception('Failed to update command {} {} usage'.format(parent, name))
            session.rollback()
            return False

        return True

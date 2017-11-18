import logging
logger = logging.getLogger('debug')


class DatabaseUtils:
    def __init__(self, bot):
        self._bot = bot

    @property
    def bot(self):
        return self._bot

    async def index_server_member_roles(self, server):
        import time
        t = time.time()
        default_role = server.default_role.id
        role_ids = [r.id for r in server.roles]
        role_ids.remove(default_role)
        session = self.bot.get_session

        def execute(sql):
            try:
                session.execute(sql)
            except:
                session.rollback()
                logger.exception('Failed to execute sql')
                return False
            return True

        sql = 'INSERT IGNORE INTO `roles` (`id`, `server`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += '(%s, %s)' % (r, server.id)
            if idx != l:
                sql += ', '

        if not execute(sql):
            return False

        sql = 'DELETE FROM `roles` WHERE `id` NOT IN (%s)' % ', '.join(role_ids)
        if not execute(sql):
            return False

        print('added roles in %s' % (time.time() - t))
        t1 = time.time()

        await self.bot.request_offline_members(server)
        print('added offline users in %s' % (time.time() - t1))
        _m = list(server.members)
        members = list(filter(lambda u: len(u.roles) > 1, _m))
        all_members = [u.id for u in _m]

        t1 = time.time()
        sql = 'DELETE FROM `userRoles` WHERE `user_id` IN (%s)' % ', '.join(all_members)

        # Deletes all server records
        #sql = 'DELETE `userRoles` FROM `userRoles` INNER JOIN `roles` WHERE roles.server=%s AND userRoles.role_id=roles.id'
        if not execute(sql):
            return False
        print('Deleted old records in %s' % (time.time() - t1))
        t1 = time.time()

        sql = 'INSERT IGNORE INTO `userRoles` (`user_id`, `role_id`) VALUES '
        for u in members:
            for r in u.roles:
                if r.id == default_role:
                    continue

                sql += ' (%s, %s),' % (u.id, r.id)

        sql = sql.rstrip(',')

        if not execute(sql):
            return False

        session.commit()
        print('added user roles in %s' % (time.time() - t1))
        print('indexed users in %s seconds' % (time.time() - t))
        return True

    def add_roles(self, server_id, *role_ids):
        session = self.bot.get_session
        sql = 'INSERT IGNORE INTO `roles` (`id`, `server`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += '(%s, %s)' % (r, server_id)
            if idx != l:
                sql += ', '

        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to add roles')
            return False

        return True

    def add_user(self, user_id):
        sql = 'INSERT IGNORE INTO `users` (`id`) VALUES (%s)' % user_id
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to add user')
            return False

        return True

    def add_users(self, *user_ids):
        session = self.bot.get_session
        sql = 'INSERT IGNORE INTO `users` (`id`) VALUES '
        l = len(user_ids) - 1
        for idx, uid in enumerate(user_ids):
            sql += '(%s)' % uid
            if idx != l:
                sql += ', '

        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to add users')
            return False

        return True

    def add_user_roles(self, role_ids, user_id, server_id):
        if not self.add_roles(server_id, *role_ids):
            return

        session = self.bot.get_session
        sql = 'INSERT IGNORE INTO `userRoles` (`user_id`, `role_id`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += '(%s, %s)' % (user_id, r)
            if idx != l:
                sql += ', '

        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to add roles foreign keys')
            return False

        return True

    def remove_user_roles(self, role_ids, user_id):
        session = self.bot.get_session

        sql = 'DELETE FROM `userRoles` WHERE user_id=%s and role_id IN (%s)' % (user_id, ', '.join(role_ids))
        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Failed to delete roles')

    def delete_role(self, role_id, server_id):
        session = self.bot.get_session
        sql = 'DELETE FROM `roles` WHERE id=%s AND server=%s' % (role_id, server_id)
        try:
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Could not delete role %s' % role_id)

    def delete_user_roles(self, user_id):
        try:
            sql = 'DELETE FROM `userRoles` WHERE user_id=%s' % user_id
            session = self.bot.get_session
            session.execute(sql)
            session.commit()
        except:
            session.rollback()
            logger.exception('Could not delete user roles')

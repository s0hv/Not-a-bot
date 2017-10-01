import logging
logger = logging.getLogger('debug')


class DatabaseUtils:
    def __init__(self, bot):
        self._bot = bot

    @property
    def bot(self):
        return self._bot

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
            logger.exception('Failed to add user')
            return False

        return True

    def add_user_roles(self, role_ids, user_id, server_id):
        if not self.add_roles(server_id, *role_ids):
            return
        if not self.add_user(user_id):
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
            logger.exception('Failed to delete roles')

    def delete_role(self, role_id, server_id):
        session = self.bot.get_session
        sql = 'DELETE FROM `roles` WHERE id=%s AND server=%s' % (role_id, server_id)
        try:
            session.execute(sql)
            session.commit()
        except:
            logger.exception('Could not delete role %s' % role_id)

    def delete_user_roles(self, user_id):
        try:
            sql = 'DELETE FROM `userRoles` WHERE user_id=%s' % user_id
            session = self.bot.get_session
            session.execute(sql)
            session.commit()
        except:
            logger.exception('Could not delete user roles')
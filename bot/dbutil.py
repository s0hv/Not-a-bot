import logging
import time

import discord
from discord.errors import InvalidArgument
from sqlalchemy.exc import SQLAlchemyError, DBAPIError

from bot.globals import BlacklistTypes
from utils.utilities import check_perms

logger = logging.getLogger('debug')


class DatabaseUtils:
    def __init__(self, bot):
        self._bot = bot

    @property
    def bot(self):
        return self._bot

    async def execute(self, sql, *args, commit=False, measure_time=False, **params):
        """
        Asynchronously run an sql query using loop.run_in_executor
        Args:
            sql: sql query
            *args: args passed to execute
            commit: Should we commit after query
            measure_time: Return time it took to run query as well as ResultProxy
            **params: params passed to execute

        Returns:
            ResultProxy or ResultProxy, int depending of the value of measure time
        """
        def _execute():
            session = self.bot.get_session
            try:
                t = time.perf_counter()
                row = session.execute(sql, *args, **params)
                if commit:
                    session.commit()

                if measure_time:
                    return row, time.perf_counter() - t

            except DBAPIError as e:
                if e.connection_invalidated:
                    logger.exception('CONNECTION INVALIDATED')
                    self.bot.engine.connect()

                raise e

            except SQLAlchemyError as e:
                session.rollback()
                raise e

            return row

        return await self.bot.loop.run_in_executor(self.bot.threadpool, _execute)

    async def index_guild_member_roles(self, guild):
        import time
        t = time.time()
        default_role = guild.default_role.id

        async def execute(sql_, commit=True):
            try:
                await self.execute(sql_, commit=commit)
            except SQLAlchemyError:
                logger.exception('Failed to execute sql')
                return False
            return True

        success = await self.index_guild_roles(guild)
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
        if not await execute(sql):
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

        if not await execute(sql):
            return False

        logger.info('added user roles in %s' % (time.time() - t1))
        logger.info('indexed users in %s seconds' % (time.time() - t))
        return True

    async def index_guild_roles(self, guild):
        roles = [{'id': r.id, 'guild': guild.id} for r in guild.roles]
        role_ids = [str(r.id) for r in guild.roles]
        sql = 'INSERT IGNORE INTO `roles` (`id`, `guild`) VALUES (:id, :guild)'
        try:
            await self.execute(sql, roles, commit=True)
            sql = 'DELETE FROM `roles` WHERE guild={} AND NOT id IN ({})'.format(guild.id, ', '.join(role_ids))
            await self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to index guild roles')
            return False
        return True

    async def add_guilds(self, *ids):
        if not ids:
            return

        ids = [{'guild': i} for i in ids]
        sql = 'INSERT IGNORE INTO `guilds` (`guild`) VALUES (:guild)'
        try:
            await self.execute(sql, ids, commit=True)
            sql = 'INSERT IGNORE INTO `prefixes` (`guild`) VALUES (:guild)'
            await self.execute(sql, ids, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add new servers to db')
            return False
        return True

    async def add_roles(self, guild_id, *role_ids):
        sql = 'INSERT IGNORE INTO `roles` (`id`, `guild`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += f'({r}, {guild_id})'
            if idx != l:
                sql += ', '

        try:
            await self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add roles')
            return False

        return True

    async def add_user(self, user_id):
        sql = f'INSERT IGNORE INTO `users` (`id`) VALUES ({user_id})'
        try:
            self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add user')
            return False

        return True

    async def add_users(self, *user_ids):
        sql = 'INSERT IGNORE INTO `users` (`id`) VALUES '
        l = len(user_ids) - 1
        for idx, uid in enumerate(user_ids):
            sql += f'({uid})'
            if idx != l:
                sql += ', '

        try:
            await self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add users')
            return False

        return True

    async def add_user_roles(self, role_ids, user_id, guild_id):
        if not await self.add_roles(guild_id, *role_ids):
            return

        sql = 'INSERT IGNORE INTO `userRoles` (`user`, `role`) VALUES '
        l = len(role_ids) - 1
        for idx, r in enumerate(role_ids):
            sql += f'({user_id}, {r})'
            if idx != l:
                sql += ', '

        try:
            await self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add roles foreign keys')
            return False

        return True

    async def remove_user_roles(self, role_ids, user_id):
        sql = 'DELETE FROM `userRoles` WHERE user=%s and role IN (%s)' % (user_id, ', '.join(map(lambda i: str(i), role_ids)))
        try:
            await self.execute(sql, commit=True)
            return True
        except SQLAlchemyError:
            logger.exception('Failed to delete roles')
            return False

    async def add_prefix(self, guild_id, prefix):
        sql = 'INSERT INTO `prefixes` (`guild`, `prefix`) VALUES (:guild, :prefix)'

        try:
            await self.execute(sql, params={'guild': guild_id, 'prefix': prefix}, commit=True)
            return True
        except SQLAlchemyError:
            logger.exception('Failed to add prefix')
            return False

    async def remove_prefix(self, guild_id, prefix):
        sql = 'DELETE FROM `prefixes` WHERE guild=:guild AND prefix=:prefix'

        try:
            await self.execute(sql, params={'guild': guild_id, 'prefix': prefix}, commit=True)
            return True
        except SQLAlchemyError:
            logger.exception('Failed to remove prefix')
            return False

    async def delete_role(self, role_id, guild_id):
        sql = f'DELETE FROM `roles` WHERE id={role_id} AND guild={guild_id}'
        try:
            await self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception(f'Could not delete role {role_id}')

    async def delete_user_roles(self, guild_id, user_id):
        try:
            sql = f'DELETE `userRoles` FROM `userRoles` INNER JOIN `roles` ON roles.id=userRoles.role WHERE roles.guild={guild_id} AND userRoles.user={user_id}'
            await self.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Could not delete user roles')

    async def add_automute_blacklist(self, guild_id, *channel_ids):
        sql = 'INSERT IGNORE INTO `automute_blacklist` (`guild`, `channel`) VALUES '
        sql += ', '.join(map(lambda cid: f'({guild_id}, {cid})', channel_ids))
        try:
            await self.execute(sql, commit=True)
            success = True
        except SQLAlchemyError:
            success = False

        return success

    async def remove_automute_blacklist(self, guild_id, *channel_ids):
        if not channel_ids:
            return True

        channel_ids = ', '.join(map(str, channel_ids))
        sql = f'DELETE FROM `automute_blacklist` WHERE guild={guild_id} AND channel IN ({channel_ids}) '
        try:
            await self.execute(sql, commit=True)
            success = True
        except SQLAlchemyError:
            success = False

        return success

    async def add_automute_whitelist(self, guild_id, *role_ids):
        if not role_ids:
            return True

        sql = 'INSERT IGNORE INTO `automute_whitelist` (`guild`, `role`) VALUES '
        sql += ', '.join(map(lambda rid: f'({guild_id}, {rid})', role_ids))
        try:
            await self.execute(sql, commit=True)
            success = True
        except SQLAlchemyError:
            success = False

        return success

    async def remove_automute_whitelist(self, guild_id, *role_ids):
        if not role_ids:
            return True

        role_ids = ', '.join(map(str, role_ids))
        sql = f'DELETE FROM `automute_whitelist` WHERE guild={guild_id} AND role IN ({role_ids})'
        try:
            await self.execute(sql, commit=True)
            success = True
        except SQLAlchemyError:
            success = False

        return success

    async def multiple_last_seen(self, user_ids, usernames, guild_id, timestamps):
        sql = 'INSERT INTO `last_seen_users` (`user`, `username`, `guild`, `last_seen`) VALUES (:user, :username, :guild, :time) ON DUPLICATE KEY UPDATE last_seen=VALUES(`last_seen`), username=VALUES(`username`)'
        data = [{'user': uid, 'username': u, 'guild': s, 'time': t} for uid, u, s, t in zip(user_ids, usernames, guild_id, timestamps)]

        try:
            await self.execute(sql, data, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to set last seen')
            return False

        return True

    async def add_command(self, parent, name=""):
        sql = 'INSERT IGNORE INTO `command_stats` (`parent`, `cmd`) VALUES (:parent, :cmd)'
        try:
            await self.execute(sql, params={'parent': parent, 'cmd': name}, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add command {} {}'.format(parent, name))
            return False

        return True

    async def add_commands(self, values):
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
        try:
            await self.execute(sql, values, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to add commands {}'.format(values))
            return False

        return True

    async def command_used(self, parent, name=""):
        if name is None:
            name = ""
        sql = 'UPDATE `command_stats` SET `uses`=(`uses`+1) WHERE parent=:parent AND cmd=:cmd'
        try:
            await self.execute(sql, params={'parent': parent, 'cmd': name}, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to update command {} {} usage'.format(parent, name))
            return False

        return True

    async def get_command_stats(self, parent=None, name=""):
        sql = 'SELECT * FROM command_stats'
        if parent:
            sql += ' WHERE parent=:parent AND cmd=:name'

        sql += ' ORDER BY uses DESC'

        try:
            return (await self.execute(sql, params={'parent': parent, 'name': name})).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to get command stats')
            return False

    async def increment_mute_roll(self, guild: int, user: int, win: bool):
        if win:
            sql = 'INSERT INTO `mute_roll_stats`  (`guild`, `user`, `wins`, `current_streak`, `biggest_streak`) VALUES (:guild, :user, 1, 1, 1)'
            sql += ' ON DUPLICATE KEY UPDATE wins=wins + 1, games=games + 1, current_streak=current_streak + 1, biggest_streak=GREATEST(current_streak, biggest_streak)'
        else:
            sql = 'INSERT INTO `mute_roll_stats`  (`guild`, `user`) VALUES (:guild, :user)'
            sql += ' ON DUPLICATE KEY UPDATE games=games+1, current_streak=0'

        try:
            await self.execute(sql, {'guild': guild, 'user': user}, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to update mute roll stats')
            return False

        return True

    async def get_mute_roll(self, guild: int, sort=None):
        if sort is None:
            # Algorithm based on https://stackoverflow.com/a/27710046
            # Gives priority to games played then wins and then winrate
            sort = '1/SQRT(POW(wins/games-1, 2)*0.7 + POW(1/games, 2)*3 + POW(1/wins, 2)*2)'
        sql = 'SELECT * FROM `mute_roll_stats` WHERE guild=%s ORDER BY %s DESC' % (guild, sort)

        rows = (await self.execute(sql)).fetchall()
        return rows

    async def botban(self, user_id, reason):
        sql = 'INSERT INTO `banned_users` (`user`, `reason`) VALUES (:user, :reason)'
        await self.execute(sql, {'user': user_id, 'reason': reason}, commit=True)

    async def botunban(self, user_id):
        sql = 'DELETE FROM `banned_users` WHERE user=%s' % user_id
        await self.execute(sql, commit=True)

    async def blacklist_guild(self, guild_id, reason):
        sql = 'INSERT INTO `guild_blacklist` (`guild`, `reason`) VALUES (:guild, :reason)'
        await self.execute(sql, {'guild': guild_id, 'reason': reason}, commit=True)

    async def unblacklist_guild(self, guild_id):
        sql = 'DELETE FROM `guild_blacklist` WHERE guild=%s' % guild_id
        await self.execute(sql, commit=True)

    async def is_guild_blacklisted(self, guild_id):
        sql = 'SELECT 1 FROM `guild_blacklist` WHERE guild=%s' % guild_id
        r = await self.execute(sql)
        r = r.first()
        return r is not None and r[0] == 1

    async def add_multiple_activities(self, data):
        """
        data is a list of dicts with each dict containing user, game and time
        """
        sql = 'INSERT INTO `activity_log` (`user`, `game`, `time`) VALUES (:user, :game, :time) ON DUPLICATE KEY UPDATE time=VALUES(`time`)'

        try:
            await self.execute(sql, data, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to log activities')
            return False

        return True

    async def get_activities(self, user):
        sql = 'SELECT * FROM `activity_log` WHERE user=:user ORDER BY time DESC LIMIT 5'
        try:
            rows = await self.execute(sql, {'user': user})
            rows = rows.fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to log activities')
            return False

        return rows

    async def delete_activities(self, user):
        sql = 'DELETE FROM `activity_log` WHERE user=:user'
        try:
            await self.execute(sql, {'user': user}, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to log activities')
            return False

        return True

    async def log_pokespawn(self, name, guild):
        sql = 'INSERT INTO `pokespawns` (`name`, `guild`) VALUES (:name, :guild) ON DUPLICATE KEY UPDATE count=count+1'

        try:
            await self.execute(sql, {'name': name, 'guild': guild}, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to log pokespawn')
            return False

        return True

    async def add_timeout(self, guild, user, expires_on):
        sql = 'INSERT INTO `timeouts` (`guild`, `user`, `expires_on`) VALUES ' \
              '(:guild, :user, :expires_on) ON DUPLICATE KEY UPDATE expires_on=VALUES(expires_on)'

        params = {'guild': guild, 'user': user, 'expires_on': expires_on}
        await self.execute(sql, params=params, commit=True)

    async def add_todo(self, todo, priority=0):
        sql = 'INSERT INTO `todo` (`todo`, `priority`) VALUES (:todo, :priority)'
        rowid = (await self.execute(sql, {'todo': todo, 'priority': priority}, commit=True)).lastrowid
        return rowid

    async def get_todo(self, limit):
        sql = 'SELECT * FROM `todo` WHERE `completed` IS FALSE ORDER BY priority DESC LIMIT %s' % limit
        return await self.execute(sql)

    async def add_temprole(self, user, role, guild, expires_at):
        sql = 'INSERT INTO `temproles` (`user`, `role`, `guild`, `expires_at`) VALUES ' \
              '(:user, :role, :guild, :expires_at) ON DUPLICATE KEY UPDATE expires_at=:expires_at'

        try:
            await self.execute(sql, {'user': user, 'role': role,
                                     'guild': guild, 'expires_at': expires_at})
        except SQLAlchemyError:
            logger.exception('Failed to add temprole')

    async def remove_temprole(self, user: int, role: int):
        sql = 'DELETE FROM `temproles` WHERE user=:user AND role=:role'

        try:
            await self.execute(sql, {'user': user, 'role': role})
        except SQLAlchemyError:
            logger.exception('Failed to remove temprole')

    async def add_changes(self, changes):
        sql = 'INSERT INTO `changelog` (`changes`) VALUES (:changes)'
        rowid = (await self.execute(sql, {'changes': changes}, commit=True)).lastrowid
        return rowid

    async def add_timeout_log(self, guild_id, user_id, author_id, reason, embed=None,
                              timestamp=None, modlog_message_id=None, duration=None):
        try:
            sql = 'INSERT IGNORE INTO `timeout_logs` (`guild`, `user`, `author`, `reason`, `embed`, `message`, `time`, `duration`) VALUES ' \
                  '(:guild, :user, :author, :reason, :embed, :message, :time, :duration) ON DUPLICATE KEY UPDATE ' \
                  'reason=:reason, embed=:embed, author=:author'
            d = {
                'guild': guild_id,
                'user': user_id,
                'author': author_id,
                'reason': reason,
                'embed': embed,
                'message': modlog_message_id,
                'time': timestamp,
                'duration': duration
            }
            await self.bot.dbutils.execute(sql, params=d, commit=True)
        except SQLAlchemyError:
            logger.exception('Fail to log timeout')
            return False

        return True

    async def edit_timeout_log(self, guild_id, user_id, author_id, reason, embed=None):
        # https://stackoverflow.com/a/21683753/6046713
        sql = 'UPDATE `timeout_logs` SET reason=:reason, embed=:embed ' \
              'WHERE id=(SELECT MAX(id) FROM timeout_logs WHERE guild=:guild AND user=:user AND author=:author)'

        try:
            d = {
                'guild': guild_id,
                'user': user_id,
                'author': author_id,
                'reason': reason,
                'embed': embed
            }
            await self.execute(sql, params=d, commit=True)
        except SQLAlchemyError:
            logger.exception('Fail to edit timeout reason')
            return False

        return True

    async def get_latest_timeout_log(self, guild_id, user_id):
        sql = 'SELECT t.expires_on, tl.reason, tl.author, tl.embed, tl.time FROM `timeouts` t ' \
              'RIGHT JOIN timeout_logs tl ON tl.guild=t.guild AND tl.user=t.user ' \
              f'WHERE tl.id=(SELECT MAX(id) FROM timeout_logs WHERE guild={guild_id} AND user={user_id})'

        try:
            row = (await self.execute(sql)).first()
        except SQLAlchemyError:
            logger.exception('Failed to get latest timeout log')
            return False

        return row

    async def get_latest_timeout_log_for(self, guild_id, user_id, author_id):
        sql = f'SELECT id, message, time FROM timeout_logs WHERE id=(SELECT MAX(id) FROM \
                timeout_logs WHERE guild={guild_id} AND user={user_id} AND author={author_id})'

        try:
            row = (await self.execute(sql)).first()
        except SQLAlchemyError:
            logger.exception('Failed to get latest timeout log')
            return False

        return row

    async def get_timeout_logs(self, guild_id, user_id):
        sql = 'SELECT author, reason, time, duration FROM timeout_logs WHERE ' \
              'guild=%s AND user=%s ORDER BY id DESC' % (guild_id, user_id)

        try:
            rows = await self.execute(sql)
        except SQLAlchemyError:
            return False

        return rows

    async def check_blacklist(self, command, user, ctx, fetch_raw: bool=False):
        """

        Args:
            command: Name of the command
            user: member/user object
            ctx: The context
            fetch_raw: if True the value of the active permission override is returned
                       if False will return a bool when the users permissions will be overridden
                       or None when no entries were found


        Returns: int, bool, None
            See fetch_raw to see possible return values
        """
        sql = 'SELECT * FROM `command_blacklist` WHERE type=%s AND %s ' \
              'AND (user=%s OR user IS NULL) LIMIT 1' % (BlacklistTypes.GLOBAL, command, user.id)
        rows = await self.execute(sql)

        if rows.first():
            return False

        if ctx.guild is None:
            return True

        channel = ctx.channel
        if isinstance(user, discord.Member) and user.roles:
            roles = '(role IS NULL OR role IN ({}))'.format(', '.join(map(lambda r: str(r.id), user.roles)))
        else:
            roles = 'role IS NULL'

        sql = f'SELECT `type`, `role`, `user`, `channel`  FROM `command_blacklist` WHERE guild={user.guild.id} AND {command} ' \
              f'AND (user IS NULL OR user={user.id}) AND {roles} AND (channel IS NULL OR channel={channel.id})'
        rows = (await self.execute(sql)).fetchall()
        if not rows:
            return None

        """
        Here are the returns
            1 user AND whitelist
            3 user AND blacklist
            4 whitelist AND role
            6 blacklist AND role
            8 channel AND whitelist
            10 channel AND blacklist
            16 whitelist AND server
            18 blacklist AND server
        """

        return check_perms(rows, return_raw=fetch_raw)

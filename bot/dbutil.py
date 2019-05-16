import logging
import time
import types

import discord
from asyncpg.exceptions import PostgresError
from discord.errors import InvalidArgument

from bot.globals import BlacklistTypes
from utils.utilities import check_perms

logger = logging.getLogger('debug')


def _args_to_string(args):
    """
    DO NOT USE WITH STRINGS
    ARGS ARE NOT ESCAPED

    Will turn args to a string. Should be only used on non string args only
    Args:
        args: List or generator of arguments

    Returns:
        String of args in format (1,2),(3,4),(5,6),...
    """
    if isinstance(args, types.GeneratorType) or isinstance(args[0], list) or isinstance(args[0], tuple):
        return ','.join([f"({','.join(map(str, arg))})" for arg in args])
    else:
        return ','.join([f"({arg})" for arg in args])


class DatabaseUtils:
    def __init__(self, bot):
        self._bot = bot

    @property
    def bot(self):
        return self._bot

    @staticmethod
    def create_bind_groups(group_amount, group_size):
        s = ''
        for i in range(1, group_amount*group_size, group_size):
            s += '('

            s += ','.join(map(lambda n: f'${n}', range(i, i+group_size))) + '),'

        return s.rstrip(',')

    async def fetchval(self, sql, args=None):
        args = args or ()

        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                return await conn.fetchval(sql, *args)

    async def fetch(self, sql, args=None, timeout=None, measure_time=False, fetchmany=True):
        args = args or ()

        async with self.bot.pool.acquire() as conn:
            t = time.perf_counter()

            if fetchmany:
                row = await conn.fetch(sql, *args, timeout=timeout)
            else:
                row = await conn.fetchrow(sql, *args, timeout=timeout)

            if measure_time:
                return row, time.perf_counter() - t

            return row

    async def insertmany(self, table, *, records=None, columns=None, measure_time=False, timeout=None):
        """
        Insert many records to a table. Will fail on conflicting unique keys for example because
        ON CONFLICT isn't supported

        Args:
            table: Name of the table
            records: List of record tuples
            columns: Optional list of columns to update. If not given will update all columns
            measure_time: If we should measure query time
            timeout: Optional timeout for the query

        Returns:
            Status from Connection.copy_records_to_table
        """
        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    t = time.perf_counter()
                    row = await conn.copy_records_to_table(table, records=records, columns=columns, timeout=timeout)

                    if measure_time:
                        return row, time.perf_counter() - t

                except PostgresError as e:
                    raise e

        return row

    async def execute_chunked(self, sql_statements, args=None, insertmany=False,
                              measure_time=False, timeout=None):
        """

        Args:
            sql_statements:
            args:
            insertmany:
            measure_time:
            timeout:

        Returns:

        """
        args = args or [() for _ in sql_statements]

        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    t = time.perf_counter()
                    rows = []

                    for idx, sql in enumerate(sql_statements):
                        if insertmany:
                            row = await conn.executemany(sql, args[idx], timeout=timeout)
                        else:
                            row = await conn.execute(sql, *args[idx], timeout=timeout)

                        rows.append(rows)

                    if measure_time:
                        return rows, time.perf_counter() - t

                except PostgresError as e:
                    raise e

        return row

    async def execute(self, sql, args=None, measure_time=False,
                      insertmany=False, timeout=None):
        """
        Args:
            sql: sql query
            *args: args passed to execute
            measure_time: Return time it took to run query as well as ResultProxy
            **params: params passed to execute

        Returns:
            ResultProxy or ResultProxy, int depending of the value of measure time
        """

        args = args or ()

        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    t = time.perf_counter()
                    if insertmany:
                        row = await conn.executemany(sql, args, timeout=timeout)
                    else:
                        row = await conn.execute(sql, *args, timeout=timeout)

                    if measure_time:
                        return row, time.perf_counter() - t

                except PostgresError as e:
                    raise e

        return row

    async def index_guild_member_roles(self, guild):
        import time
        t = time.time()
        default_role = guild.default_role.id

        async def execute(sql_, args=None, insertmany=False):
            try:
                await self.execute(sql_, args, insertmany=insertmany)
            except PostgresError:
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
        sql = 'DELETE FROM userroles ur USING roles r WHERE r.id=ur.role AND r.guild={} AND ur.uid IN ({})'.format(guild.id, ', '.join(all_members))

        # Deletes all server records
        # sql = 'DELETE userRoles FROM userRoles INNER JOIN roles WHERE roles.server=%s AND userRoles.role_id=roles.id'
        if not await execute(sql):
            return False
        logger.info('Deleted old records in %s' % (time.time() - t1))
        t1 = time.time()

        args = []
        for u in members:
            uid = u.id
            args.extend([(uid, r.id) for r in u.roles if r.id != default_role])

        sql_statements = []
        # 100k default chunk size
        chunk_size = 100000
        for i in range(0, len(args), chunk_size):
            # This piece of spaghetti code basically creates the
            # VALUES (1,2), (3,4), (5,6)...
            # part because asyncpg doesn't support any meaningful way to do it
            s = '(' + '),('.join([', '.join((str(u), str(r))) for u, r in args[i:i+chunk_size]]) + ')'
            sql_statements.append('INSERT INTO userroles (uid, role) VALUES %s ON CONFLICT DO NOTHING' % s)

        try:
            await self.execute_chunked(sql_statements)
        except PostgresError:
            return False

        logger.info('added user roles in %s' % (time.time() - t1))
        logger.info('indexed users in %s seconds' % (time.time() - t))
        return True

    async def index_guild_roles(self, guild):
        guild_id = guild.id

        def tuples():
            for r in guild.roles:
                yield r.id, guild_id

        roles = _args_to_string(tuples())
        role_ids = [str(r.id) for r in guild.roles]

        # We won't be using insertmany on this so we can use ON CONFLICT
        # Instead we prepare the args as a string beforehand. This works because
        # they're all just integers
        sql = 'INSERT INTO roles (id, guild) VALUES %s ON CONFLICT DO NOTHING' % roles

        try:
            await self.execute(sql)
            sql = 'DELETE FROM roles WHERE guild={} AND NOT id IN ({})'.format(guild.id, ', '.join(role_ids))
            await self.execute(sql)
        except PostgresError:
            logger.exception('Failed to index guild roles')
            return False
        return True

    async def add_guilds(self, *ids):
        if not ids:
            return

        ids = _args_to_string(ids)
        sql = 'INSERT INTO guilds (guild) VALUES %s ON CONFLICT DO NOTHING' % ids
        try:
            await self.execute(sql, ids)
            sql = 'INSERT INTO prefixes (guild) VALUES %s ON CONFLICT DO NOTHING' % ids
            await self.execute(sql, ids)
        except PostgresError:
            logger.exception('Failed to add new servers to db')
            return False
        return True

    async def add_roles(self, guild_id, *role_ids):
        def it():
            for r in role_ids:
                yield r, guild_id

        ids = _args_to_string(it())
        sql = 'INSERT INTO roles (id, guild) VALUES %s ON CONFLICT DO NOTHING' % ids

        try:
            await self.execute(sql)
        except PostgresError:
            logger.exception('Failed to add roles')
            return False

        return True

    async def add_user(self, user_id: int):
        sql = f'INSERT INTO users (id) VALUES ({user_id}) ON CONFLICT DO NOTHING'
        try:
            await self.execute(sql)
        except PostgresError:
            logger.exception('Failed to add user')
            return False

        return True

    async def add_users(self, *user_ids):
        ids = _args_to_string(user_ids)
        sql = 'INSERT INTO users (id) VALUES %s ON CONFLICT DO NOTHING' % ids

        try:
            await self.execute(sql)
        except PostgresError:
            logger.exception('Failed to add users')
            return False

        return True

    async def add_user_roles(self, role_ids, user_id, guild_id):
        if not await self.add_roles(guild_id, *role_ids):
            return

        def it():
            for r in role_ids:
                yield user_id, r

        ids = _args_to_string(it())
        sql = 'INSERT INTO userroles (uid, role) VALUES %s ON CONFLICT DO NOTHING' % ids

        try:
            await self.execute(sql)
        except PostgresError:
            logger.exception('Failed to add roles foreign keys')
            return False

        return True

    async def remove_user_roles(self, role_ids, user_id: int):
        sql = 'DELETE FROM userroles WHERE uid=%s and role IN (%s)' % (user_id, ', '.join(map(lambda i: str(i), role_ids)))
        try:
            await self.execute(sql)
            return True
        except PostgresError:
            logger.exception('Failed to delete roles')
            return False

    async def add_prefix(self, guild_id: int, prefix):
        sql = 'INSERT INTO prefixes (guild, prefix) VALUES ($1, $2)'

        try:
            await self.execute(sql, (guild_id, prefix))
            return True
        except PostgresError:
            logger.exception('Failed to add prefix')
            return False

    async def remove_prefix(self, guild_id: int, prefix):
        sql = 'DELETE FROM prefixes WHERE guild=$1 AND prefix=$2'

        try:
            await self.execute(sql, (guild_id, prefix))
            return True
        except PostgresError:
            logger.exception('Failed to remove prefix')
            return False

    async def delete_role(self, role_id: int, guild_id: int):
        sql = f'DELETE FROM roles WHERE id={role_id} AND guild={guild_id}'
        try:
            await self.execute(sql)
        except PostgresError:
            logger.exception(f'Could not delete role {role_id}')

    async def delete_user_roles(self, guild_id: int, user_id: int):
        try:
            sql = f'DELETE FROM userroles USING roles WHERE roles.id=userroles.role AND roles.guild={guild_id} AND userroles.uid={user_id}'
            await self.execute(sql)
        except PostgresError:
            logger.exception('Could not delete user roles')

    async def add_automute_blacklist(self, guild_id: int, *channel_ids):
        sql = 'INSERT INTO automute_blacklist (guild, channel) VALUES ($1, $2) ON CONFLICT DO NOTHING'
        ids = [(guild_id, c) for c in channel_ids]

        try:
            await self.execute(sql, ids, insertmany=True)
            success = True
        except PostgresError:
            success = False

        return success

    async def remove_automute_blacklist(self, guild_id: int, *channel_ids):
        if not channel_ids:
            return True

        channel_ids = ', '.join(map(str, channel_ids))
        sql = f'DELETE FROM automute_blacklist WHERE guild={guild_id} AND channel IN ({channel_ids}) '
        try:
            await self.execute(sql)
            success = True
        except PostgresError:
            success = False

        return success

    async def add_automute_whitelist(self, guild_id: int, *role_ids):
        if not role_ids:
            return True

        sql = 'INSERT INTO automute_whitelist (guild, role) VALUES ($1, $2) ON CONFLICT DO NOTHING'
        ids = [(guild_id, r) for r in role_ids]

        try:
            await self.execute(sql, ids, insertmany=True)
            success = True
        except PostgresError:
            success = False

        return success

    async def remove_automute_whitelist(self, guild_id: int, *role_ids):
        if not role_ids:
            return True

        role_ids = ', '.join(map(str, role_ids))
        sql = f'DELETE FROM automute_whitelist WHERE guild={guild_id} AND role IN ({role_ids})'
        try:
            await self.execute(sql)
            success = True
        except PostgresError:
            success = False

        return success

    async def multiple_last_seen(self, user_ids, usernames, guild_id, timestamps):

        sql_statements = []
        args = []
        step = 500

        for i in range(0, len(user_ids), step):
            data = []
            for uid, u, g, t in zip(user_ids[i:i+step], usernames[i:i+step], guild_id[i:i+step], timestamps[i:i+step]):
                data.extend((uid, u, g, t))

            sql = 'INSERT INTO last_seen_users (uid, username, guild, last_seen) VALUES %s ' \
                  'ON CONFLICT (uid, guild) DO UPDATE SET last_seen=EXCLUDED.last_seen, username=EXCLUDED.username' % self.create_bind_groups(len(data)//4, 4)

            sql_statements.append(sql)
            args.append(data)

        try:
            await self.execute_chunked(sql_statements, args)
        except PostgresError:
            logger.exception('Failed to set last seen')
            return False

        return True

    async def add_command(self, parent, name=""):
        sql = 'INSERT INTO command_stats (parent, cmd) VALUES ($1, $2) ON CONFLICT DO NOTHING'
        try:
            await self.execute(sql, (parent, name))
        except PostgresError:
            logger.exception('Failed to add command {} {}'.format(parent, name))
            return False

        return True

    async def add_commands(self, values):
        """
        Inserts multiple commands to the db
        Args:
            values: A list of tuples (parent, cmd)

        Returns:
            bool based on success
        """
        if not values:
            return
        sql = 'INSERT INTO command_stats (parent, cmd) VALUES %s ON CONFLICT DO NOTHING' % self.create_bind_groups(len(values), 2)
        try:
            # https://stackoverflow.com/a/952952/6046713 Flatten list
            await self.execute(sql, [item for sublist in values for item in sublist])
        except PostgresError:
            logger.exception('Failed to add commands {}'.format(values))
            return False

        return True

    async def command_used(self, parent, name=""):
        if name is None:
            name = ""
        sql = 'UPDATE command_stats SET uses=(uses+1) WHERE parent=$1 AND cmd=$2'
        try:
            await self.execute(sql, (parent, name))
        except PostgresError:
            logger.exception('Failed to update command {} {} usage'.format(parent, name))
            return False

        return True

    async def get_command_stats(self, parent=None, name=""):
        sql = 'SELECT * FROM command_stats'
        if parent:
            sql += ' WHERE parent=$1 AND cmd=$2'

        sql += ' ORDER BY uses DESC'

        try:
            await self.fetch(sql, (parent, name))
        except PostgresError:
            logger.exception('Failed to get command stats')
            return False

    async def increment_mute_roll(self, guild: int, user: int, win: bool):
        if win:
            sql = 'INSERT INTO mute_roll_stats  (guild, uid, wins, current_streak, biggest_streak) VALUES ($1, $2, 1, 1, 1)' \
                  ' ON CONFLICT (guild, uid) DO UPDATE SET wins=wins + 1, games=games + 1, current_streak=current_streak + 1, biggest_streak=GREATEST(current_streak, biggest_streak)'
        else:
            sql = 'INSERT INTO mute_roll_stats  (guild, uid) VALUES ($1, $2)' \
                  ' ON CONFLICT (guild, uid) DO UPDATE SET games=games+1, current_streak=0'

        try:
            await self.execute(sql, (guild, user))
        except PostgresError:
            logger.exception('Failed to update mute roll stats')
            return False

        return True

    async def get_mute_roll(self, guild: int, sort=None):
        if sort is None:
            # Algorithm based on https://stackoverflow.com/a/27710046
            # Gives priority to games played then wins and then winrate
            #      '1/SQRT(POW(wins/games-1, 2)*0.7 + POW(1/games, 2)*3 + POW(1/wins, 2)*2)'
            sort = '1/SQRT(POW(wins/games-1, 2)*0.7 + POW(1/games, 2)*3 + POW(1/GREATEST(wins, 1), 2) *2)'
        sql = 'SELECT uid as "user", * FROM mute_roll_stats WHERE guild=%s ORDER BY %s DESC' % (guild, sort)

        rows = await self.fetch(sql)
        return rows

    async def botban(self, user_id: int, reason):
        sql = 'INSERT INTO banned_users (uid, reason) VALUES ($1, $2)'
        await self.execute(sql, (user_id, reason))

    async def botunban(self, user_id: int):
        sql = 'DELETE FROM banned_users WHERE uid=%s' % user_id
        await self.execute(sql)

    async def blacklist_guild(self, guild_id: int, reason):
        sql = 'INSERT INTO guild_blacklist (guild, reason) VALUES ($1, $2)'
        await self.execute(sql, (guild_id, reason))

    async def unblacklist_guild(self, guild_id: int):
        sql = 'DELETE FROM guild_blacklist WHERE guild=%s' % guild_id
        await self.execute(sql)

    async def is_guild_blacklisted(self, guild_id: int):
        sql = 'SELECT 1 FROM guild_blacklist WHERE guild=%s' % guild_id
        r = await self.fetch(sql, fetchmany=False)
        return r is not None and r[0] == 1

    async def add_multiple_activities(self, data):
        """
        data is a list of dicts with each dict containing user, game and time
        """

        sql = 'INSERT INTO activity_log (uid, game, time) VALUES ($1, $2, $3) ON CONFLICT (uid) DO UPDATE SET time=EXCLUDED.time'

        try:
            await self.execute(sql, data)
        except PostgresError:
            logger.exception('Failed to log activities')
            return False

        return True

    async def get_activities(self, user):
        sql = 'SELECT uid as "user", * FROM activity_log WHERE uid=$1 ORDER BY time DESC LIMIT 5'
        try:
            rows = await self.fetch(sql, (user,))
        except PostgresError:
            logger.exception('Failed to log activities')
            return False

        return rows

    async def delete_activities(self, user):
        sql = 'DELETE FROM activity_log WHERE uid=$1'
        try:
            await self.execute(sql, (user,))
        except PostgresError:
            logger.exception('Failed to log activities')
            return False

        return True

    async def log_pokespawn(self, name, guild: int):
        sql = 'INSERT INTO pokespawns (name, guild) VALUES ($1, $2) ON CONFLICT (guild, name) DO UPDATE SET count=count+1'

        try:
            await self.execute(sql, (name, guild))
        except PostgresError:
            logger.exception('Failed to log pokespawn')
            return False

        return True

    async def add_timeout(self, guild: int, user, expires_on):
        sql = 'INSERT INTO timeouts (guild, uid, expires_on) VALUES ' \
              '($1, $2, $3) ON CONFLICT (guild, uid) DO UPDATE SET expires_on=$3'

        await self.execute(sql, (guild, user, expires_on))

    async def add_todo(self, todo, priority=0):
        sql = 'INSERT INTO todo (todo, priority) VALUES ($1, $2) RETURNING id'
        rowid = await self.fetchval(sql, (todo, priority))
        return rowid

    async def edit_todo(self, id: int, priority: int):
        sql = 'UPDATE todo SET priority=%s WHERE id=%s' % (priority, id)
        await self.execute(sql)

    async def get_todo(self, limit: int):
        sql = 'SELECT * FROM todo WHERE completed IS FALSE ORDER BY priority DESC LIMIT %s' % limit
        return await self.fetch(sql)

    async def add_temprole(self, user, role, guild, expires_at):
        sql = 'INSERT INTO temproles (uid, role, guild, expires_at) VALUES ' \
              '($1, $2, $3, $4) ON CONFLICT (role, uid) DO UPDATE SET expires_at=$4'

        try:
            await self.execute(sql, (user, role, guild, expires_at))
        except PostgresError:
            logger.exception('Failed to add temprole')

    async def remove_temprole(self, user: int, role: int):
        sql = 'DELETE FROM temproles WHERE uid=$1 AND role=$2'

        try:
            await self.execute(sql, (user, role))
        except PostgresError:
            logger.exception('Failed to remove temprole')

    async def add_changes(self, changes):
        sql = 'INSERT INTO changelog (changes) VALUES ($1) RETURNING id'
        rowid = await self.fetchval(sql, (changes, ))
        return rowid

    async def add_timeout_log(self, guild_id, user_id, author_id, reason, embed=None,
                              timestamp=None, modlog_message_id=None, duration=None,
                              show_in_logs=True):
        try:
            sql = 'INSERT INTO timeout_logs (guild, uid, author, reason, embed, message, time, duration, show_in_logs) VALUES ' \
                  '($1, $2, $3, $4, $5, $6, $7, $8, $9)'

            args = (
                guild_id,
                user_id,
                author_id,
                reason,
                embed,
                modlog_message_id,
                timestamp,
                duration,
                show_in_logs
            )

            await self.bot.dbutils.execute(sql, args)
        except PostgresError:
            logger.exception('Fail to log timeout')
            return False

        return True

    async def edit_timeout_log(self, guild_id: int, user_id: int, author_id: int, reason, embed=None):
        # https://stackoverflow.com/a/21683753/6046713
        sql = 'UPDATE timeout_logs SET reason=$1, embed=$2 ' \
              'WHERE id=(SELECT MAX(id) FROM timeout_logs WHERE guild=$3 AND uid=$4 AND author=$5)'

        try:
            args = (
                reason,
                embed,
                guild_id,
                user_id,
                author_id
            )

            await self.execute(sql, args)
        except PostgresError:
            logger.exception('Fail to edit timeout reason')
            return False

        return True

    async def get_latest_timeout_log(self, guild_id: int, user_id: int):
        sql = 'SELECT t.expires_on, tl.reason, tl.author, tl.embed, tl.time FROM timeouts t ' \
              'RIGHT JOIN timeout_logs tl ON tl.guild=t.guild AND tl.uid=t.uid ' \
              f'WHERE tl.id=(SELECT MAX(id) FROM timeout_logs WHERE guild={guild_id} AND uid={user_id})'

        try:
            row = await self.fetch(sql, fetchmany=False)
        except PostgresError:
            logger.exception('Failed to get latest timeout log')
            return False

        return row

    async def get_latest_timeout_log_for(self, guild_id: int, user_id: int, author_id: int):
        sql = f'SELECT id, message, time FROM timeout_logs WHERE id=(SELECT MAX(id) FROM \
                timeout_logs WHERE guild={guild_id} AND uid={user_id} AND author={author_id})'

        try:
            row = await self.fetch(sql, fetchmany=False)
        except PostgresError:
            logger.exception('Failed to get latest timeout log')
            return False

        return row

    async def get_timeout_logs(self, guild_id: int, user_id: int):
        sql = 'SELECT author, reason, time, duration, id FROM timeout_logs WHERE ' \
              'guild=%s AND uid=%s AND show_in_logs=TRUE ORDER BY id DESC' % (guild_id, user_id)

        try:
            rows = await self.fetch(sql)
        except PostgresError:
            logger.exception('Failed to get timeout logs')
            return False

        return rows

    async def remove_tlogs(self, where):
        sql = f'DELETE FROM timeout_logs WHERE {where}'

        try:
            row = await self.execute(sql)
        except PostgresError:
            return False

        return row

    async def get_timezone(self, user_id: int):
        sql = f'SELECT timezone FROM users WHERE id={user_id}'

        try:
            row = await self.fetch(sql, fetchmany=False)
            return row['timezone']
        except PostgresError:
            logger.exception('Failed to get user timezone')

    async def set_timezone(self, user_id: int, timezone):
        sql = 'INSERT INTO users (id, timezone) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET timezone=$2'

        try:
            await self.execute(sql, (user_id, timezone))
        except PostgresError:
            return False

        return True

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
        sql = 'SELECT uid as "user", * FROM command_blacklist WHERE type=%s AND %s ' \
              'AND (uid=%s OR uid IS NULL) LIMIT 1' % (BlacklistTypes.GLOBAL, command, user.id)
        rows = await self.fetch(sql, fetchmany=False)

        if rows:
            return False

        if ctx.guild is None:
            return True

        channel = ctx.channel
        if isinstance(user, discord.Member) and user.roles:
            roles = '(role IS NULL OR role IN ({}))'.format(', '.join(map(lambda r: str(r.id), user.roles)))
        else:
            roles = 'role IS NULL'

        sql = f'SELECT type, role, uid as user, channel  FROM command_blacklist WHERE guild={user.guild.id} AND {command} ' \
              f'AND (uid IS NULL OR uid={user.id}) AND {roles} AND (channel IS NULL OR channel={channel.id})'
        rows = await self.fetch(sql)
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

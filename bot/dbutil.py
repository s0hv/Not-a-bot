import logging
import re
import time
import types
import typing
from datetime import datetime

import discord
from asyncpg.exceptions import PostgresError
from discord.errors import InvalidArgument

from bot.globals import BlacklistTypes
from utils.utilities import check_perms

logger = logging.getLogger('terminal')

if typing.TYPE_CHECKING:
    from bot.botbase import BotBase


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
        return ','.join(f"({','.join(map(str, arg))})" for arg in args)
    else:
        return ','.join(f"({arg})" for arg in args)


class DatabaseUtils:
    def __init__(self, bot):
        self._bot = bot

    @property
    def bot(self) -> 'BotBase':
        return self._bot

    @staticmethod
    def create_bind_groups(group_amount, group_size):
        s = ''
        # If group size is 1 range will produce one too few groups
        if group_size == 1:
            group_amount += 1

        for i in range(1, group_amount*group_size, group_size):
            s += '('

            s += ','.join(map(lambda n: f'${n}', range(i, i+group_size))) + '),'

        return s.rstrip(',')

    @staticmethod
    def parse_affected_rows(s: str) -> int:
        m = re.match(r'\w+ (?:\d+ )?(\d+)', s)
        if not m:
            return 0

        return int(m.groups()[0])

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

    async def index_guild_member_roles(self, guild: discord.Guild):
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

        logger.info(f'added roles in {time.time() - t}')
        t1 = time.time()

        try:
            await guild.chunk()
            logger.info(f'added offline users in {time.time() - t1}')
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
        logger.info(f'Deleted old records in {time.time() - t1}')
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
            s = '(' + '),('.join(', '.join((str(u), str(r))) for u, r in args[i:i+chunk_size]) + ')'
            sql_statements.append('INSERT INTO userroles (uid, role) VALUES %s ON CONFLICT DO NOTHING' % s)

        try:
            await self.execute_chunked(sql_statements)
        except PostgresError:
            return False

        logger.info(f'added user roles in {time.time() - t1}')
        logger.info(f'indexed users in {time.time() - t} seconds')
        return True

    async def get_user_keeproles(self, guild: int, user: int):
        sql = 'SELECT role FROM userroles ur INNER JOIN roles r ON r.id = ur.role ' \
              'WHERE r.guild=$1 AND ur.uid=$2'

        rows = await self.fetch(sql, (guild, user))
        return [r['role'] for r in rows]

    async def delete_user_role(self, guild: int, user: int, role: int):
        sql = 'DELETE FROM userroles ur USING roles r ' \
              'WHERE r.guild=$1 AND ur.uid=$2 AND ur.role=$3'

        res = await self.execute(sql, (guild, user, role))
        return self.parse_affected_rows(res)

    async def add_user_role(self, guild: int, user: int, role: int):
        if not await self.add_roles(guild, role):
            return False

        sql = 'INSERT INTO userroles (uid, role) VALUES ($1, $2)'

        await self.execute(sql, (user, role))
        return True

    async def replace_user_keeproles(self, guild_id, user_id, roles):
        sql = 'DELETE FROM userroles ur using roles r ' \
              'WHERE r.guild=$1 AND ur.uid=$2'

        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                try:
                    await conn.execute(sql, guild_id, user_id)

                    groups = self.create_bind_groups(len(roles), 2)
                    data = []
                    for r in roles:
                        data.extend((user_id, r))

                    sql = f'INSERT INTO userroles (uid, role) VALUES {groups}'
                    await conn.execute(sql, *data)
                except PostgresError as e:
                    raise e

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
            await self.execute(sql)
            sql = 'INSERT INTO prefixes (guild) VALUES %s ON CONFLICT DO NOTHING' % ids
            await self.execute(sql)
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
        sql = 'DELETE FROM userroles WHERE uid=%s and role IN (%s)' % (user_id, ', '.join(map(str, role_ids)))
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

    async def add_command_uses(self, values):
        if not values:
            return

        await self.insertmany('command_usage',
                              records=values,
                              columns=('cmd', 'used_at', 'uid', 'guild'))

    async def command_used(self, parent, name, used_at, user_id=None, guild=None):
        if name is None:
            name = ""

        async with self.bot.pool.acquire() as conn:
            async with conn.transaction():
                sql = 'UPDATE command_stats SET uses=(uses+1) WHERE parent=$1 AND cmd=$2'
                try:
                    await conn.execute(sql, *(parent, name))
                except PostgresError:
                    logger.exception('Failed to update command {} {} usage'.format(parent, name))
                    return False

                sql = 'INSERT INTO command_usage (cmd, used_at, uid, guild) ' \
                      'VALUES ($1, $2, $3, $4)'
                cmd = parent
                if name:
                    cmd += ' ' + name
                try:
                    await conn.execute(sql, *(cmd, used_at, user_id, guild))
                except PostgresError:
                    logger.exception(f'Failed to update command use {cmd} {used_at}')
                    return False

        return True

    async def get_command_stats(self, parent=None, name=""):
        sql = 'SELECT * FROM command_stats'
        args = ()
        if parent:
            args = (parent, name)
            sql += ' WHERE parent=$1 AND cmd=$2'

        sql += ' ORDER BY uses DESC'

        try:
            return await self.fetch(sql, args)
        except PostgresError:
            logger.exception('Failed to get command stats')
            return False

    async def get_command_activity(self, names, after, user=None, guild=None, limit: int=None):

        where = []
        # Optimizations for single command cases
        if len(names) == 1:
            where.append('cmd=$1')
            select = 'COUNT(*), $1 as cmd'

        # Selection when no names specified
        elif not names:
            select = 'COUNT(cmd), cmd'

        else:
            where.append('cmd IN ' + self.create_bind_groups(1, len(names)))
            select = 'COUNT(cmd), cmd '

        sql = f'SELECT {select} FROM command_usage WHERE '

        if user:
            where.append(f'uid={int(user)}')

        if guild:
            where.append(f'guild={int(guild)}')

        idx = len(names) + 1
        where.append(f'used_at > ${idx}')

        sql += ' AND '.join(where)

        if len(names) != 1:
            sql += ' GROUP BY cmd ORDER BY COUNT(cmd) DESC'

        if limit:
            sql += f' LIMIT {int(limit)}'

        try:
            return await self.fetch(sql, (*names, after))
        except PostgresError:
            logger.exception('Failed to get command stats')
            return False

    async def increment_mute_roll(self, guild: int, user: int, win: bool):
        if win:
            sql = 'INSERT INTO mute_roll_stats AS m (guild, uid, wins, current_streak, biggest_streak) VALUES ($1, $2, 1, 1, 1) ' \
                  'ON CONFLICT (guild, uid) DO UPDATE SET wins=m.wins + 1, games=m.games + 1, current_lose_streak=0, ' \
                  'current_streak=m.current_streak + 1, biggest_streak=GREATEST(m.current_streak + 1, m.biggest_streak)'
        else:
            sql = 'INSERT INTO mute_roll_stats AS m (guild, uid, current_lose_streak, biggest_lose_streak) VALUES ($1, $2, 1, 1)' \
                  ' ON CONFLICT (guild, uid) DO UPDATE SET games=m.games+1, current_streak=0, ' \
                  'current_lose_streak=m.current_lose_streak + 1, biggest_lose_streak=GREATEST(m.current_lose_streak + 1, m.biggest_lose_streak)'

        try:
            await self.execute(sql, (guild, user))
        except PostgresError:
            logger.exception('Failed to update mute roll stats')
            return False

        return True

    async def get_mute_roll(self, guild: int, sort=None):
        """

        Args:
            guild:
            sort: set as "" to disable sorting

        Returns:

        """
        if sort is None:
            # Algorithm based on https://stackoverflow.com/a/27710046
            # Gives priority to wins and winrate.
            # This makes it so having more wins gets you easier to the top as long as your winrate is good
            sort = '1/SQRT( POWER( wins / games::decimal - 1 , 2) * 0.06 + ' \
                   'POWER(1 / games::decimal, 2) * 3 + ' \
                   'POWER(1 / GREATEST(wins::decimal, 1) , 2) )'

        if sort:
            sort = "ORDER BY %s DESC" % sort

        sql = 'SELECT * FROM mute_roll_stats WHERE guild=%s %s' % (guild, sort)

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

    async def get_blacklisted_guilds(self):
        sql = 'SELECT guild FROM guild_blacklist'
        return await self.fetch(sql)

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
        logger.debug(f'Adding timeout to {user} on guild {guild}')

        sql = 'INSERT INTO timeouts (guild, uid, expires_on) VALUES ' \
              '%s ON CONFLICT (guild, uid) DO UPDATE SET expires_on=$3'

        if isinstance(user, int):
            arg_string = '($1, $2, $3)'
            args = (guild, user, expires_on)

        else:
            arg_string = self.create_bind_groups(len(user), 3)
            args = []
            for uid in user:
                args.extend((guild, uid, expires_on))

        await self.execute(sql % arg_string, args)

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

    async def get_temproles(self, guild: int, user: int):
        sql = 'SELECT * FROM temproles WHERE guild=$1 AND uid=$2'

        return await self.fetch(sql, (guild, user))

    async def add_changes(self, changes):
        sql = 'INSERT INTO changelog (changes) VALUES ($1) RETURNING id'
        rowid = await self.fetchval(sql, (changes, ))
        return rowid

    async def index_join_dates(self, guild):
        sql = "INSERT INTO join_dates (uid, guild, first_join) VALUES %s ON CONFLICT DO NOTHING"
        chunk_size = 10000
        values = []
        sqls = []
        members = guild.members.copy()

        for i in range(0, len(members), chunk_size):
            data = []
            for m in members[i:i+chunk_size]:
                data.extend((m.id, guild.id, m.joined_at.replace(tzinfo=None)))

            values.append(data)
            sqls.append(sql % self.create_bind_groups(len(data)//3, 3))

        await self.execute_chunked(sqls, values)

    async def get_join_date(self, uid: int, guild_id: int):
        sql = f"SELECT first_join FROM join_dates WHERE uid={uid} AND guild={guild_id}"
        try:
            row = await self.fetch(sql, fetchmany=False)
        except PostgresError:
            return None

        if row:
            return row[0]

    async def add_timeout_log(self, guild_id, user_id, author_id, reason, embed=None,
                              timestamp=None, modlog_message_id=None, duration=None,
                              show_in_logs=True):

        args = [
            guild_id,
            user_id,
            author_id,
            reason,
            embed,
            modlog_message_id,
            timestamp,
            duration,
            show_in_logs
        ]

        if isinstance(user_id, int):
            arg_string = '($1, $2, $3, $4, $5, $6, $7, $8, $9)'

        else:
            arg_string = self.create_bind_groups(len(user_id), len(args))
            new_args = []
            for uid in user_id:
                args[1] = uid
                new_args.extend(args)

        try:
            sql = 'INSERT INTO timeout_logs (guild, uid, author, reason, embed, message, time, duration, show_in_logs) VALUES ' \
                  '%s' % arg_string

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

    async def get_last_role_time(self, user: int):
        sql = f'SELECT last_use FROM role_cooldown WHERE uid={user}'
        return await self.fetch(sql, fetchmany=False)

    async def update_last_role_time(self, user: int, last_use):
        sql = f'INSERT INTO role_cooldown (uid, last_use) VALUES ($1, $2) ON CONFLICT(uid) DO UPDATE SET last_use=$2'
        await self.execute(sql, (user, last_use))

    async def get_timeout_logs(self, guild_id: int, user_id: int, bot_id: int = None):
        bot_sql = '' if not bot_id else 'author!=$3 AND '
        sql = 'SELECT author, uid, reason, time, duration, id FROM timeout_logs WHERE ' \
              'guild=$1 AND uid=$2 AND %s show_in_logs=TRUE ORDER BY id DESC' % bot_sql

        args = [guild_id, user_id]
        if bot_id:
            args.append(bot_id)

        try:
            rows = await self.fetch(sql, args)
        except PostgresError:
            logger.exception('Failed to get timeout logs')
            return False

        return rows

    async def get_timeout_logs_by(self, guild_id: int, author_id: int):
        sql = 'SELECT uid, author, reason, time, duration, id FROM timeout_logs WHERE ' \
              'guild=%s AND author=%s AND show_in_logs=TRUE ORDER BY id DESC' % (guild_id, author_id)

        try:
            rows = await self.fetch(sql)
        except PostgresError:
            logger.exception('Failed to get timeout logss by user')
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
            if row:
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

    async def last_banner(self, guild_id: int):
        sql = f'SELECT last_banner FROM guilds WHERE guild={guild_id}'

        try:
            return await self.fetch(sql, fetchmany=False)
        except PostgresError:
            logger.exception('Failed to get last banner')
            return None

    async def set_last_banner(self, guild_id: int, banner):
        sql = f'UPDATE guilds SET last_banner=$1 WHERE guild={guild_id}'

        try:
            return await self.execute(sql, (banner, ))
        except PostgresError:
            logger.exception('Failed to set last banner')
            return None

    async def create_poll(self, emotes, title, strict, guild_id: int,
                          message_id: int, channel_id, expires_in,
                          no_duplicate_votes=False,
                          allow_multiple_entries=False,
                          max_winners=1,
                          giveaway=False,
                          allow_n_votes=None):
        async with self.bot.pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            sql = 'INSERT INTO polls (guild, title, strict, message, channel, expires_in, ignore_on_dupe, multiple_votes, max_winners, giveaway, allow_n_votes) ' \
                  'VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)'
            d = (
                guild_id,
                title,
                strict,
                message_id,
                channel_id,
                expires_in,
                no_duplicate_votes,
                allow_multiple_entries,
                max_winners,
                giveaway,
                allow_n_votes
            )
            try:
                await conn.execute(sql, *d)

                emotes_list = []
                if emotes:
                    sql = 'INSERT INTO emotes (name, emote, guild) VALUES ($1, $2, $3) '
                    values = []
                    # We add all successfully parsed emotes even if the bot failed to
                    # add them so strict mode will count them in too
                    for emote in emotes:
                        if not isinstance(emote, tuple):
                            name, id_ = emote, emote
                            emotes_list.append(id_)
                            guild = None
                        else:
                            # Prefix is the animated emoji prefix a: or empty str
                            prefix, name, id_ = emote
                            name = prefix + name
                            emotes_list.append(id_)
                            guild = guild_id
                        values.append((name, str(id_), guild))

                    # No need to run these if no user set emotes are used
                    if values:
                        # If emote is already in the table update its name
                        sql += ' ON CONFLICT (emote) DO UPDATE SET name=EXCLUDED.name'
                        await conn.executemany(sql, values)

                        sql = 'INSERT INTO pollemotes (poll_id, emote_id) VALUES ($1, $2) ON CONFLICT DO NOTHING '
                        values = []
                        for id_ in emotes_list:
                            values.append((message_id, str(id_)))

                        await conn.executemany(sql, values)

                await tr.commit()
            except PostgresError:
                await tr.rollback()
                logger.exception('Failed sql query')
                return False

        return True

    async def get_event_points(self, user_id: int) -> int:
        sql = 'SELECT points FROM event_users WHERE uid=$1'
        retval = await self.fetchval(sql, (user_id,))
        return retval or 0

    async def update_event_points(self, user_id: int, points: int):
        sql = 'UPDATE event_users SET points=points+$2 WHERE uid=$1'
        await self.execute(sql, [user_id, points])

    async def update_user_protect(self, uid: int, protected_until: datetime = None):
        sql = 'UPDATE event_users SET protected_until=$2 WHERE uid=$1'
        await self.execute(sql, (uid, protected_until))

    async def get_event_users(self):
        sql = 'SELECT uid, protected_until FROM event_users'
        return await self.fetch(sql)

    async def add_event_users(self, users):
        sql = 'INSERT INTO event_users (uid) VALUES %s ON CONFLICT DO NOTHING' % self.create_bind_groups(len(users), 1)
        await self.execute(sql, users)

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
        sql = 'SELECT * FROM command_blacklist WHERE type=%s AND %s ' \
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

        sql = f'SELECT type, role, uid, channel  FROM command_blacklist WHERE guild={user.guild.id} AND {command} ' \
              f'AND (uid IS NULL OR uid={user.id}) AND {roles} AND (channel IS NULL OR channel={channel.id})'
        rows = await self.fetch(sql)
        if not rows:
            return None

        return check_perms(rows, return_raw=fetch_raw)

    async def delete_user_data(self, uid: int):

        sqls = [
            'DELETE FROM command_usage WHERE uid=$1',
            'DELETE FROM join_dates WHERE uid=$1',
            'DELETE FROM last_seen_users WHERE uid=$1',
            'DELETE FROM messages WHERE user_id=$1',
            'DELETE FROM mute_roll_stats WHERE uid=$1'
        ]

        for sql in sqls:
            await self.execute(sql, [uid])

    async def do_not_track_is_on(self, uid: int) -> bool:
        sql = 'SELECT 1 FROM do_not_track WHERE uid=$1'

        row = await self.fetch(sql, [uid], fetchmany=False)

        return row is not None

    async def set_do_not_track(self, uid: int, set_on: bool) -> bool:
        if set_on:
            sql = 'INSERT INTO do_not_track (uid) VALUES ($1)'
        else:
            sql = 'DELETE FROM do_not_track WHERE uid=$1'

        try:
            await self.execute(sql, [uid])
        except:
            return False
        else:
            if set_on:
                self.bot.do_not_track.add(uid)
            else:
                self.bot.do_not_track.discard(uid)

            return True

    async def get_do_not_track(self):
        rows = await self.fetch('SELECT uid FROM do_not_track')
        return {row['uid'] for row in rows}

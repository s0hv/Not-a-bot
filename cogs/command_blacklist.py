import logging
import typing

import discord
from discord.ext import commands
from discord.ext.commands import BucketType, has_permissions
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command, group, cooldown
from bot.converters import CommandConverter
from bot.formatter import Paginator
from bot.globals import BlacklistTypes, PermValues
from cogs.cog import Cog
from utils.utilities import (split_string, get_role, send_paged_message)

logger = logging.getLogger('debug')
perms = discord.Permissions(8)


class CommandBlacklist(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @group(no_pm=True, invoke_without_command=True)
    @has_permissions(administrator=True)
    @cooldown(1, 5, type=BucketType.guild)
    async def blacklist(self, ctx, commands: commands.Greedy[CommandConverter]=None, *, mention: typing.Union[discord.TextChannel, discord.Role, discord.User]=None):
        """Blacklist a command for a user, role or channel
        To blacklist multiple commands at the same time wrap the command names in quotes
        like this {prefix}{name} \"command1 command2 command3\" #channel
        The hierarchy of `blacklist` and `whitelist` is as follows
        Whitelist always overrides blacklist of the same level

        Then levels of scope it can have are as follows
        `User` > `Role` > `Channel` > `Server` where each level overrides every scope perm after it
        e.g. Blacklisting command ping for role Member and whitelisting it for role Mod
        would make it so people with Member role wouldn't be able to use it unless they had Mod role

        Also if you further whitelisted ping from a single member
        that user would be able to use the command always
        since user whitelist overrides every other scope

        To blacklist a command server wide specify the commands and don't specify the mention param
        like this `{prefix}blacklist "cmd1 cmd2 etc"` which would blacklist those commands
        for everyone in the server unless they have it whitelisted
        Whitelisting server wide isn't possible

        For dangers of whitelisting see `{prefix}help whitelist`"""
        guild = ctx.guild

        if not commands and mention is None:
            return await ctx.send('No parameters given')

        async def _blacklist(name):
            if mention is None:
                whereclause = 'guild=%s AND type IN (%s, %s) AND command="%s" AND channel IS NULL AND role IS NULL AND user IS NULL' % (
                               guild.id, BlacklistTypes.BLACKLIST, BlacklistTypes.WHITELIST, name)
                success = await self._set_blacklist(ctx, whereclause, guild=guild.id, command=name)
                if success:
                    return 'Blacklisted command {} from this server'.format(name)
                elif success is None:
                    return 'Removed blacklist for command {} on this server'.format(name)

            elif isinstance(mention, discord.User):
                return await self._add_user_blacklist(ctx, name, mention, guild)

            elif isinstance(mention, discord.Role):
                return await self._add_role_blacklist(ctx, name, mention, guild)

            elif isinstance(mention, discord.TextChannel):
                return await self._add_channel_blacklist(ctx, name, mention, guild)

        s = ''
        if commands is None:
            val = await self._set_all_commands(ctx, mention)
            if isinstance(val, str):
                s += val
        else:
            for command in commands:
                if command.name == 'privacy':
                    await ctx.send("Cannot blacklist privacy command as it's required that anyone can see it")
                    continue

                val = await _blacklist(command.name)
                if isinstance(val, str):
                    s += val + '\n'

        if not s:
            return

        for msg in split_string(s, splitter='\n'):
            await ctx.send(msg)

    @blacklist.command(no_pm=True)
    @has_permissions(administrator=True)
    async def toggle(self, ctx):
        """
        Disable all commands on this server (owner will still be able to use them)
        Whitelisting commands also overrides this rule
        Won't override existing commands that have been blacklisted so when you toggle
        again the commands that have been specifically blacklisted are still blacklisted
        """

        guild = ctx.guild
        values = {'command': None, 'guild': guild.id, 'type': BlacklistTypes.BLACKLIST}
        where = 'guild=%s AND command IS NULL AND NOT type=%s AND user IS NULL AND role IS NULL AND channel IS NULL' % (guild.id, BlacklistTypes.GLOBAL)
        success = await self._set_blacklist(where, **values)
        if success:
            msg = 'All commands disabled on this server for non whitelisted users'
        elif success is None:
            msg = 'Commands are usable on this server again'
        else:
            return

        await ctx.send(msg)

    async def _set_all_commands(self, ctx, scope, type=BlacklistTypes.BLACKLIST):
        guild = ctx.guild
        values = {'command': None, 'guild': guild.id, 'type': type}
        where = 'guild=%s AND command IS NULL AND NOT type=%s AND ' % (guild.id, BlacklistTypes.GLOBAL)
        type_string = 'Blacklisted' if type == BlacklistTypes.BLACKLIST else 'Whitelisted'
        type_string2 = 'blacklist' if type == BlacklistTypes.BLACKLIST else 'whitelist'
        message = None
        if isinstance(scope, discord.User):
            userid = scope.id
            success = await self._set_blacklist(ctx, where + 'user=%s' % userid, user=userid, **values)
            if success:
                message = f'{type_string} all commands for user {scope} `{userid}`'
            elif success is None:
                message = f'removed {type_string2} from user {scope}, `{userid}`'

        elif isinstance(scope, discord.Role):
            success = await self._set_blacklist(ctx, where + 'role=%s' % scope.id, role=scope.id, **values)
            if success:
                message = '{0} all commands from role {1} `{1.id}`'.format(type_string, scope)
            elif success is None:
                message = 'Removed {0} from role {1} `{1.id}`'.format(type_string2, scope)

        elif isinstance(scope, discord.TextChannel):
            success = await self._set_blacklist(ctx, where + 'channel=%s' % scope.id,
                                                channel=scope.id, **values)
            if success:
                message = '{0} all commands from channel {1} `{1.id}`'.format(type_string, scope)
            elif success is None:
                message = 'Removed {0} from channel {1} `{1.id}`'.format(type_string2, scope)

        else:
            return 'No valid mentions'

        return message

    @command(no_pm=True)
    @has_permissions(administrator=True)
    @cooldown(1, 5, type=BucketType.guild)
    async def whitelist(self, ctx, commands: commands.Greedy[CommandConverter], *, mention: typing.Union[discord.TextChannel, discord.Role, discord.User]):
        """Whitelist a command for a user, role or channel
        To whitelist multiple commands at the same time wrap the command names in quotes
        like this {prefix}{name} \"command1 command2 command3\" #channel

        To see specifics on the hierarchy of whitelist/blacklist see `{prefix}help blacklist`

        **WHITELISTING COULD BE DANGEROUS IF YOU DON'T KNOW WHAT YOU ARE DOING!**
        Before whitelisting read the following

        Whitelisting WILL OVERRIDE ANY REQUIRED PERMS for the command being called
        If a command requires ban perms and you whitelist it for a role
        everyone with that role can use that command even when they don't have ban perms

        Due to safety reasons whitelisting commands from this module is not allowed.
        Give the users correct discord perms instead
        """
        msg = ctx.message
        guild = msg.guild

        async def _whitelist(_command):
            name = _command.name
            if _command.cog_name == self.__class__.__name__:
                return f"Due to safety reasons commands from {_command.cog_name} module can't be whitelisted"

            elif isinstance(mention, discord.User):
                return await self._add_user_whitelist(ctx, name, mention, guild)

            elif isinstance(mention, discord.Role):
                return await self._add_role_whitelist(ctx, name, mention, guild)

            elif isinstance(mention, discord.TextChannel):
                return await self._add_channel_whitelist(ctx, name, mention, guild)

        s = ''
        for command in commands:
            val = await _whitelist(command)
            if isinstance(val, str):
                s += val + '\n'

        if not s:
            return

        for msg in split_string(s, splitter='\n'):
            await ctx.send(msg)

    async def _set_blacklist(self, ctx, whereclause, type_=BlacklistTypes.BLACKLIST, **values):
        """
        :ctx: object that messages can be sent to
        :return: True when new permission is set
                 None when permission is toggled
                 False when operation failed
        """
        type_string = 'blacklist' if type_ == BlacklistTypes.BLACKLIST else 'whitelist'
        sql = 'SELECT `id`, `type` FROM `command_blacklist` WHERE %s' % whereclause
        try:
            row = (await self.bot.dbutil.execute(sql, values)).first()
        except SQLAlchemyError:
            logger.exception('Failed to remove blacklist')
            await ctx.send('Failed to remove %s' % type_string)
            return

        if row:
            if row['type'] == type_:
                sql = 'DELETE FROM `command_blacklist` WHERE id=:id'
                try:
                    await self.bot.dbutil.execute(sql, {'id': row['id']}, commit=True)
                except SQLAlchemyError:
                    logger.exception('Could not update %s with whereclause %s' % (type_string, whereclause))
                    await ctx.send('Failed to remove %s' % type_string)
                    return False
                else:
                    return
            else:
                sql = 'UPDATE `command_blacklist` SET type=:type WHERE id=:id'
                try:
                    await self.bot.dbutil.execute(sql, {'type': type_, 'id': row['id']}, commit=True)
                except SQLAlchemyError:
                    logger.exception('Could not update %s with whereclause %s' % (type_string, whereclause))
                    await ctx.send('Failed to remove %s' % type_string)
                    return False
                else:
                    return True
        else:
            sql = 'INSERT INTO `command_blacklist` ('
            values['type'] = type_
            keys = values.keys()
            val = '('
            l = len(keys)
            for idx, k in enumerate(keys):
                sql += '`%s`' % k
                val += ':%s' % k
                if idx != l - 1:
                    sql += ', '
                    val += ', '

            sql += ') VALUES ' + val + ')'
            try:
                await self.bot.dbutil.execute(sql, values, commit=True)
            except SQLAlchemyError:
                logger.exception('Could not set values %s' % values)
                await ctx.send('Failed to set %s' % type_string)
                return False

        return True

    async def _add_user_blacklist(self, ctx, command_name, user, guild):
        whereclause = 'guild=:guild AND command=:command AND user=:user AND NOT type=:type'
        success = await self._set_blacklist(ctx, whereclause, command=command_name,
                                            user=user.id,
                                            guild=guild.id,
                                            type=BlacklistTypes.GLOBAL)
        if success:
            return 'Blacklisted command {0} from user {1} `{1.id}`'.format(command_name, user)
        elif success is None:
            return 'Removed command {0} blacklist from user {1} `{1.id}`'.format(command_name, user)

    async def _add_role_blacklist(self, ctx, command_name, role, guild):
        whereclause = 'guild=:guild AND command=:command AND role=:role AND NOT type=:type'
        success = await self._set_blacklist(ctx, whereclause, command=command_name,
                                            role=role.id,
                                            guild=guild.id,
                                            type=BlacklistTypes.GLOBAL)
        if success:
            return 'Blacklisted command {0} from role {1} `{1.id}`'.format(command_name, role)
        elif success is None:
            return 'Removed command {0} blacklist from role {1} `{1.id}`'.format(command_name, role)

    async def _add_channel_blacklist(self, ctx, command_name, channel, guild):
        whereclause = 'guild=:guild AND command=:command AND channel=:channel AND NOT type=:type'
        success = await self._set_blacklist(ctx, whereclause,
                                            command=command_name,
                                            channel=channel.id,
                                            guild=guild.id,
                                            type=BlacklistTypes.GLOBAL)
        if success:
            return 'Blacklisted command {0} from channel {1} `{1.id}`'.format(command_name, channel)
        elif success is None:
            return 'Removed command {0} blacklist from channel {1} `{1.id}`'.format(command_name, channel)

    async def _add_user_whitelist(self, ctx, command_name, user, guild):
        whereclause = 'guild=:guild AND command=:command AND user=:user AND NOT type=:type'
        success = await self._set_blacklist(ctx, whereclause,
                                            type_=BlacklistTypes.WHITELIST,
                                            command=command_name,
                                            user=user.id,
                                            guild=guild.id,
                                            type=BlacklistTypes.GLOBAL)
        if success:
            return 'Whitelisted command {0} from user {1} `{1.id}`'.format(command_name, user)
        elif success is None:
            return 'Removed command {0} whitelist from user {1} `{1.id}`'.format(command_name, user)

    async def _add_role_whitelist(self, ctx, command_name, role, guild):
        whereclause = 'guild=:guild AND command=:command AND role=:role AND NOT type=:type'
        success = await self._set_blacklist(ctx, whereclause,
                                            type_=BlacklistTypes.WHITELIST,
                                            command=command_name,
                                            role=role.id,
                                            guild=guild.id,
                                            type=BlacklistTypes.GLOBAL)
        if success:
            return 'Whitelisted command {0} from role {1} `{1.id}`'.format(command_name, role)
        elif success is None:
            return 'Removed command {0} whitelist from role {1} `{1.id}`'.format(command_name, role)

    async def _add_channel_whitelist(self, ctx, command_name, channel, guild):
        whereclause = 'guild=:guild AND command=:command AND channel=:channel AND NOT type=:type'
        success = await self._set_blacklist(ctx, whereclause,
                                            type_=BlacklistTypes.WHITELIST,
                                            command=command_name,
                                            channel=channel.id,
                                            guild=guild.id,
                                            type=BlacklistTypes.GLOBAL)
        if success:
            return 'Whitelisted command {0} from channel {1} `{1.id}`'.format(command_name, channel)
        elif success is None:
            return 'Removed command {0} whitelist from channel {1} `{1.id}`'.format(command_name, channel)

    @command(owner_only=True)
    async def test_perms(self, ctx, user: discord.Member, command_):
        value = await self.bot.dbutil.check_blacklist(f'(command="{command_}" OR command IS NULL)', user, ctx, True)
        await ctx.send(value or 'No special perms')

    async def get_rows(self, whereclause, select='*'):
        sql = 'SELECT %s FROM `command_blacklist` WHERE %s' % (select, whereclause)
        rows = (await self.bot.dbutil.execute(sql)).fetchall()
        return rows

    @staticmethod
    def get_applying_perm(command_rows, return_type=False):
        smallest = 18
        smallest_row = None
        perm_type = 0x10  # guild
        for row in command_rows:
            if row['type'] == BlacklistTypes.GLOBAL:
                return False

            if row['type'] == BlacklistTypes.WHITELIST:
                v1 = PermValues.VALUES['whitelist']
            else:
                v1 = PermValues.VALUES['blacklist']

            if row['user'] is not None:
                v2 = PermValues.VALUES['user']
            elif row['role'] is not None:
                v2 = PermValues.VALUES['role']
            else:
                continue

            v = v1 | v2
            if v < smallest:
                smallest = v
                return_type = v2
                smallest_row = row

        if return_type:
            return smallest_row, perm_type

        return smallest_row

    @command(no_pm=True)
    @cooldown(1, 30, BucketType.user)
    async def role_perms(self, ctx, *role):
        """Show white- and blacklist for all or specified role"""
        guild = ctx.guild

        if role:
            role = ' '.join(role)
            role_ = get_role(role, guild.roles, name_matching=True)
            if not role_:
                return await ctx.send('No role found with {}'.format(role))
            where = 'guild={} AND user IS NULL AND channel IS NULL AND role={}'.format(guild.id, role_.id)
        else:
            where = 'guild={} AND user IS NULL AND channel IS NULL AND NOT role IS NULL ORDER BY role, type'.format(guild.id)

        rows = await self.get_rows(where)
        if not rows:
            return await ctx.send('No perms found')

        paginator = Paginator('Role perms')
        last = None
        last_type = None

        def get_command(row):
            return 'All commands' if row['command'] is None else row['command']

        for row in rows:
            if row['role'] != last:
                last = row['role']
                role = guild.get_role(row['role'])
                if role is None:
                    logger.warning('Role {} has been deleted and it has perms'.format(row['role']))
                    continue

                last_type = row['type']
                perm_type = 'Whitelisted:\n' if last_type == BlacklistTypes.WHITELIST else 'Blacklisted:\n'
                paginator.add_field('{0.name} {0.id}'.format(role), perm_type + get_command(row) + '\n')

            else:
                s = ''
                if row['type'] != last_type:
                    last_type = row['type']
                    s = '\nWhitelisted:\n' if last_type == BlacklistTypes.WHITELIST else '\nBlacklisted:\n'

                s += get_command(row) + '\n'
                paginator.add_to_field(s)

        paginator.finalize()
        pages = paginator.pages
        for idx, page in enumerate(pages):
            page.set_footer(text='Page {}/{}'.format(idx + 1, len(pages)))

        await send_paged_message(ctx, pages, embed=True)

    @command(no_pm=True, aliases=['sp'])
    @cooldown(1, 15, BucketType.guild)
    async def show_perms(self, ctx):
        """Shows all server perms in one paged embed"""
        sql = f'SELECT command, type, user, role, channel FROM command_blacklist WHERE guild={ctx.guild.id}'
        rows = await self.bot.dbutil.execute(sql)

        perms = {'guild': [], 'channel': [], 'role': [], 'user': []}

        for row in rows:
            if row['user']:
                perms['user'].append(row)
            elif row['channel']:
                perms['channel'].append(row)
            elif row['role']:
                perms['role'].append(row)
            else:
                perms['guild'].append(row)

        ITEMS_PER_PAGE = 10

        # Flatten dict to key value pairs
        newperms = []
        for k in perms:
            newperms.extend([(perm, k) for perm in sorted(perms[k], key=lambda r: r['type'])])

        paginator = Paginator(title=f"Permissions for guild {ctx.guild.name}", init_page=False)

        for i in range(0, len(newperms), ITEMS_PER_PAGE):
            s = ''
            for row, type_ in newperms[i:i+ITEMS_PER_PAGE]:
                t, e = ('whitelisted', '✅') if row['type'] == BlacklistTypes.WHITELIST else ('disabled', '❌')
                cmd = f'Command `{row["command"]}`' if row["command"] else 'All commands'

                if type_ == 'guild':
                    s += f'🖥{e} {cmd} {t} for this guild\n'

                elif type_ == 'channel':
                    s += f'📝{e} {cmd} {t} in channel <#{row["channel"]}>\n'

                elif type_ == 'role':
                    role = '<@&{0}> {0}'.format(row['role'])
                    s += f'⚙{e} {cmd} {t} for role {role}\n'

                elif type_ == 'user':
                    user = self.bot.get_user(row['user']) or ''
                    s += f'👤{e} {cmd} {t} for user <@{row["user"]}> {user}\n'

            paginator.add_page(description=s)

        paginator.finalize()
        await send_paged_message(ctx, paginator.pages, embed=True)

    @command(name='commands', no_pm=True)
    @cooldown(1, 30, type=BucketType.user)
    async def commands_(self, ctx, user: discord.Member=None):
        """Get your or the specified users white- and blacklisted commands on this server"""
        guild = ctx.guild
        if not user:
            user = ctx.author

        if user.roles:
            roles = '(role IS NULL OR role IN ({}))'.format(', '.join(map(lambda r: str(r.id), user.roles)))
        else:
            roles = 'role IS NULL'

        where = f'guild={guild.id} AND (user={user.id} or user IS NULL) AND channel IS NULL AND {roles}'

        rows = await self.get_rows(where)

        commands = {}
        for row in rows:
            name = row['command']

            if name in commands:
                commands[name].append(row)
            else:
                commands[name] = [row]

        whitelist = []
        blacklist = []
        global_blacklist = []
        for name, rows in commands.items():
            row = self.get_applying_perm(rows)
            name = f'`{name}`'
            if row is False:
                global_blacklist.append(name)
                continue

            # Don't want channel or server specific blacklists
            if row is None:
                continue

            if row['type'] == BlacklistTypes.WHITELIST:
                whitelist.append(name)

            elif row['type'] == BlacklistTypes.BLACKLIST:
                blacklist.append(name)

        s = ''
        if whitelist:
            s += f'{user}s whitelisted commands\n' + '\n'.join(whitelist) + '\n\n'

        if blacklist:
            s += f'Commands blacklisted fom {user}\n' + '\n'.join(blacklist) + '\n\n'

        if global_blacklist:
            s += f'Commands globally blacklisted for {user}\n' + '\n'.join(global_blacklist) + '\n\n'

        if not s:
            s = '{0} has no special perms set up on the server {1}'.format(user, guild.name)
        else:
            s += '{}s perms on server {}\nChannel specific perms are not checked'.format(user, guild.name)

        s = split_string(s, maxlen=2000, splitter='\n')
        for ss in s:
            await ctx.author.send(ss)


def setup(bot):
    bot.add_cog(CommandBlacklist(bot))

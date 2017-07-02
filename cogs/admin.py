from cogs.cog import Cog
import asyncio
from bot.bot import command, group
import time
from discord.ext.commands.core import GroupMixin


class Admin(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(name='eval', pass_context=True, owner_only=True)
    async def eval_(self, ctx, *, message):
        try:
            retval = eval(message)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            import traceback
            traceback.print_exc()
            retval = 'Exception\n%s' % e

        if not retval:
            retval = 'Done'

        await self.bot.say(retval)

    @group(name='t')
    async def t(self):
        print('t')
        return

    @t.group(name='tt')
    async def tt(self):
        print('tt')
        return

    @tt.command()
    async def tt1(self):
        print('tt1')
        return

    @t.command()
    async def t1(self):
        print('t1')
        return

    @command(name='exec', pass_context=True, owner_only=True)
    async def exec_(self, ctx, *, message):
        try:
            retval = exec(message)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            import traceback
            traceback.print_exc()
            retval = 'Exception\n%s' % e

        if not retval:
            retval = 'Done'

        await self.bot.say(retval)

    def _recursively_remove_all_commands(self, command, bot=None):
        commands = []
        for _command in command.commands.copy().values():
            if isinstance(_command, GroupMixin):
                l = self._recursively_remove_all_commands(_command)
                command.remove_command(_command.name)
                commands.append(l)
            else:
                commands.append(command.remove_command(_command.name))

        if bot:
            bot.remove_command(command.name)
        return command, commands

    def _recursively_add_all_commands(self, commands, bot):
        for command_ in commands:
            if isinstance(command_, tuple):
                command_, commands_ = command_
                bot.add_command(command_)
                self._recursively_add_all_commands(commands_, command_)
            else:
                bot.add_command(command_)

    @command(owner_only=True)
    async def reload(self, *, name):
        t = time.time()
        try:
            self.bot.unload_extension(name)
            self.bot.load_extension(name)
        except Exception as e:
            command = self.bot.get_command(name)
            if not command:
                return await self.bot.say('Could not reload %s because of an error\n%s' % (name, e))
            try:
                if isinstance(command, GroupMixin):
                    commands = self._recursively_remove_all_commands(command, self.bot)
                    self._recursively_add_all_commands([commands], self.bot)
                else:
                    self.bot.remove_command(command.name)
                    self.bot.add_command(command)
            except Exception as e:
                return await self.bot.say('Could not reload command(s) %s because of an error\n%s' % (name, e))

        await self.bot.say('Reloaded {} in {:.02f}'.format(name, time.time()-t))

    @command(pass_context=True, owner_only=True)
    async def shutdown(self, ctx):
        try:
            await self.bot.change_presence()
            try:
                sound = self.bot.get_cog('Audio')
                await sound.shutdown()
            except:
                pass

            for message in self.bot.timeout_messages.copy():
                await message.delete_now()
                message.cancel_tasks()

                self.bot.aiohttp_client.close()

        except Exception as e:
            print('[ERROR] Error while shutting down %s' % e)
        finally:
            await self.bot.close()

    @command(pass_context=True, owner_only=True)
    async def notice_me(self, ctx):
        server = ctx.message.server
        if server.id == '217677285442977792':
            await self.bot.request_offline_members(server)
            for member in list(server.members):
                print(member.name)
                await self.bot._wants_to_be_noticed(member, server)


    # TODO rework
    """
    async def check_commands(commands, level, channel):
        if commands is None:
            return

        _commands = set()
        for command in commands:
            if command.strip() == '':
                continue

            if command not in bot.commands:
                raise BotValueError('Command %s not found' % command)

            c = commands[command]
            if c.level > level:
                await bot.say_timeout('Cannot add command %s because commands requires level %s and yours is %s', channel, 120)
            _commands.add(c.name)

        return ', '.join(_commands)

    @bot.command(pass_context=True)
    async def permission_options(ctx):
        s = 'Permission group options and default values'
        for k, v in PERMISSION_OPTIONS.items():
            s += '\n{}={}'.format(k, v)

        await bot.send_message(ctx.message.channel, s)

    @bot.command(pass_context=True, level=5)
    async def create_permissions(ctx, *args):
        print(args, ctx)
        user_permissions = ctx.user_permissions
        args = ' '.join(args)
        args = re.findall(r'([\w\d]+=[\w\d\s]+)(?= [\w\d]+=[\w\d\s]+|$)', args)  # Could be improve but I don't know how

        kwargs = {}

        for arg in args:
            try:
                k, v = arg.split('=')
            except ValueError:
                raise BotValueError('Value %s could not be parsed' % arg)

            kwargs[k] = v.strip()

        channel = ctx.message.channel
        kwargs = parse_permissions(kwargs, user_permissions)
        kwargs['whitelist'] = await check_commands(kwargs['whitelist'], user_permissions.level, channel)
        kwargs['blacklist'] = await check_commands(kwargs['blacklist'], user_permissions.level, channel)

        msg = 'Confirm the creation if a permission group with{}\ny/n'.format(kwargs)
        await bot.say_timeout(msg, ctx.message.channel, 40)
        msg = await bot.wait_for_message(timeout=30, author=ctx.message.author, channel=channel, check=y_n_check)

        if msg is None or msg in ['n', 'no']:
            return await bot.say_timeout('Cancelling', ctx.message.channel, 40)

        bot.permissions.create_permissions_group(**kwargs)

    @bot.command(pass_context=True, level=5)
    async def set_permissions(ctx, group_name, *args):
        group = bot.permissions.get_permission_group(group_name)
        channel = ctx.message.channel
        perms = ctx.user_permissions
        if perms is None:
            return

        if group is None:
            return await bot.say_timeout('Permission group %s not found' % group_name, channel, 60)

        if group.level >= perms.level >= 0 and not perms.master_override:
            raise BotException('Your level must be higher than the groups level')

        if group.master_override and not perms.master_override:
            raise BotException("You cannot set roles with master override on if you don't have it yourself")

        u = ctx.message.mentions

        users = []
        if perms.master_override:
            users = [(None, i) for i in u]
        else:
            for user in u:
                users.append((bot.permissions.get_permissions(user.id), user))

        for role in ctx.message.role_mentions:
            usrs = bot.get_role_members(role, ctx.message.server)
            for user in usrs:
                if perms.master_override:
                    users.append((None, user))
                else:
                    users.append((bot.permissions.get_permissions(user.id), user))

        valid_users = []
        for user_perms, user in users:
            if perms.master_override:
                valid_users.append(user)
            elif 0 <= perms.level <= user_perms.level:
                await bot.say('Cannot change permission of %s because your level is too low' % user.name)
            else:
                valid_users.append(user)

        errors = bot.permissions.set_permissions(group, *valid_users)

        for user, e in errors.items():
            await bot.say('Could not change the permissions of %s because of an error. %s' % (user.name, e))

        await bot.say('Permissions set for %s users' % len(valid_users))
    """


def setup(bot):
    bot.add_cog(Admin(bot))
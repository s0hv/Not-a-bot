import asyncio
import logging
import time
from importlib import reload, import_module

from discord.ext.commands.core import GroupMixin
from discord.errors import HTTPException, InvalidArgument
from bot.bot import command
from cogs.cog import Cog

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


class BotAdmin(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(name='eval', owner_only=True)
    async def eval_(self, ctx, *, message):
        try:
            retval = eval(message)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            logger.exception('Failed to eval')
            retval = 'Exception\n%s' % e

        if not isinstance(retval, str):
            retval = str(retval)

        await ctx.send(retval)

    @command(name='exec', owner_only=True)
    async def exec_(self, ctx, *, message):
        try:
            retval = exec(message)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            logger.exception('Failed to eval')
            retval = 'Exception\n%s' % e

        if not isinstance(retval, str):
            retval = str(retval)

        await ctx.send(retval)

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
    async def reload(self, ctx, *, name):
        t = time.time()
        try:
            cog_name = 'cogs.%s' % name if not name.startswith('cogs.') else name
            self.bot.unload_extension(cog_name)
            self.bot.load_extension(cog_name)
        except Exception as e:
            command_ = self.bot.get_command(name)
            if not command_:
                return await ctx.send('Could not reload %s because of an error\n%s' % (name, e))
            try:
                if isinstance(command_, GroupMixin):
                    commands = self._recursively_remove_all_commands(command_, self.bot)
                    self._recursively_add_all_commands([commands], self.bot)
                else:
                    self.bot.remove_command(command_.name)
                    self.bot.add_command(command_)
            except Exception as e:
                return await ctx.send('Could not reload command(s) %s because of an error\n%s' % (name, e))

        await ctx.send('Reloaded {} in {:.0f}ms'.format(name, (time.time()-t)*1000))

    @command(owner_only=True)
    async def reload_all(self, ctx):
        t = time.time()
        errors = await self.bot.loop.run_in_executor(self.bot.threadpool, self.bot._load_cogs)
        t = (time.time() - t) * 1000
        for error in errors:
            await self.bot.say(error)
        await ctx.send('Reloaded all default cogs in {:.0f}ms'.format(t))

    @command(owner_only=True)
    async def shutdown(self, ctx):
        try:
            ctx.send('Beep boop')
        except HTTPException:
            pass

        try:
            audio = self.bot.get_cog('Audio')
            if audio:
                await audio.shutdown()

            pending = asyncio.Task.all_tasks(loop=self.bot.loop)
            gathered = asyncio.gather(*pending, loop=self.bot.loop)
            try:
                gathered.cancel()
                self.bot.loop.run_until_complete(gathered)

                # we want to retrieve any exceptions to make sure that
                # they don't nag us about it being un-retrieved.
                gathered.exception()
            except:
                pass

        except Exception:
            terminal.exception('Bot shutdown error')
        finally:
            await self.bot.logout()

    @command(owner_only=True)
    async def notice_me(self, ctx):
        guild = ctx.message.guild
        if guild.id == 217677285442977792:
            try:
                await self.bot.request_offline_members(guild)
            except InvalidArgument:
                pass
            for member in list(guild.members):
                await self.bot._wants_to_be_noticed(member, guild)

    @command(owner_only=True)
    async def cache_guilds(self):
        session = self.bot.get_session
        for guild in self.bot.guilds:
            sql = 'SELECT * FROM `guilds` WHERE guild=%s' % guild.id
            row = session.execute(sql).first()
            if not row:
                sql = 'INSERT INTO `guilds` (`guild`, `prefix`) ' \
                      'VALUES (%s, "%s")' % (guild.id, self.bot.command_prefix)
                try:
                    session.execute(sql)
                    session.commit()
                except:
                    session.rollback()
                    logger.exception('Failed to cache guild')

                d = {'prefix': self.bot.command_prefix}
            else:
                d = {**row}
                del d['guild']

            self.bot.guild_cache.update_guild(guild.id, **d)

    @command(owner_only=True)
    async def reload_module(self, ctx, module_name):
        try:
            reload(import_module(module_name))
        except Exception as e:
            return await ctx.send('Failed to reload module %s because of an error\n```%s```' % (module_name, e))
        await ctx.send('Reloaded module %s' % module_name)


def setup(bot):
    bot.add_cog(BotAdmin(bot))

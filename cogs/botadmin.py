import asyncio
import logging
import time
from importlib import reload, import_module

from discord.ext.commands.core import GroupMixin

from bot.bot import command
from cogs.cog import Cog

logger = logging.getLogger('debug')


class BotAdmin(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(name='eval', pass_context=True, owner_only=True)
    async def eval_(self, ctx, *, message):
        try:
            retval = eval(message)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            logger.exception('Failed to eval')
            retval = 'Exception\n%s' % e

        if not retval:
            retval = 'Done'

        await self.bot.say(retval)

    @command(name='exec', pass_context=True, owner_only=True)
    async def exec_(self, ctx, *, message):
        try:
            retval = exec(message)
            if asyncio.iscoroutine(retval):
                retval = await retval

        except Exception as e:
            logger.exception('Failed to eval')
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
            cog_name = 'cogs.%s' % name if not name.startswith('cogs.') else name
            self.bot.unload_extension(cog_name)
            self.bot.load_extension(cog_name)
        except Exception as e:
            command_ = self.bot.get_command(name)
            if not command_:
                return await self.bot.say('Could not reload %s because of an error\n%s' % (name, e))
            try:
                if isinstance(command_, GroupMixin):
                    commands = self._recursively_remove_all_commands(command_, self.bot)
                    self._recursively_add_all_commands([commands], self.bot)
                else:
                    self.bot.remove_command(command_.name)
                    self.bot.add_command(command_)
            except Exception as e:
                return await self.bot.say('Could not reload command(s) %s because of an error\n%s' % (name, e))

        await self.bot.say('Reloaded {} in {:.0f}ms'.format(name, (time.time()-t)*1000))

    @command(pass_context=True, owner_only=True)
    async def shutdown(self, ctx):
        try:
            await self.bot.change_presence()
            try:
                sound = self.bot.get_cog('Audio')
                await sound.shutdown()
            except:
                pass

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
                await self.bot._wants_to_be_noticed(member, server)

    @command(owner_only=True)
    async def test(self, msg_id):
        session = self.bot.get_session
        result = session.execute('SELECT `message` FROM `messages` WHERE `message_id` = %s' % msg_id)
        await self.bot.say(result.first()['message'])

    @command(owner_only=True)
    async def cache_servers(self):
        session = self.bot.get_session
        for server in self.bot.servers:
            sql = 'SELECT * FROM `servers` WHERE server=%s' % server.id
            row = session.execute(sql).first()
            if not row:
                sql = 'INSERT INTO `servers` (`server`, `prefix`) ' \
                      'VALUES (%s, "%s")' % (server.id, self.bot.command_prefix)
                try:
                    session.execute(sql)
                    session.commit()
                except:
                    session.rollback()
                    logger.exception('Failed to cache server')

                d = {'prefix': self.bot.command_prefix}
            else:
                d = {**row}
                del d['server']

            self.bot.server_cache.update_server(server.id, **d)

    @command(pass_context=True, owner_only=True)
    async def reconnect_vc(self, ctx):
        await self.bot.reconnect_voice_client(ctx.message.server)

    @command(pass_context=True, owner_only=True)
    async def force_skip(self, ctx):
        vc = self.bot.voice_clients_.get(ctx.message.server.id, None)
        if not vc:
            return

        vc.play_next_song.set()
        vc.audio_player.cancel()
        vc.activity_check.cancel()
        vc.create_audio_task()

    @command(owner_only=True)
    async def reload_module(self, module_name):
        try:
            reload(import_module(module_name))
        except Exception as e:
            return await self.bot.say('Failed to reload module %s because of an error\n```%s```' % (module_name, e))
        await self.bot.say('Reloaded module %s' % module_name)


def setup(bot):
    bot.add_cog(BotAdmin(bot))

import logging
from random import choice

import discord
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from bot.bot import Bot
from bot.cooldown import CooldownManager
from utils.utilities import (split_string, slots2dict, retry)

logger = logging.getLogger('debug')

initial_cogs = [
    'cogs.admin',
    'cogs.audio',
    'cogs.botmod',
    'cogs.emotes',
    'cogs.hearthstone',
    'cogs.jojo',
    'cogs.management',
    'cogs.misc',
    'cogs.search',
    'cogs.utils',
    'cogs.voting',
    'cogs.logging']


class Object:
    def __init__(self):
        pass


class NotABot(Bot):
    def __init__(self, prefix, conf, perms=None, aiohttp=None, **options):
        super().__init__(prefix, conf, perms, aiohttp, **options)
        cdm = CooldownManager()
        cdm.add_cooldown('oshit', 3, 8)
        cdm.add_cooldown('imnew', 3, 8)
        self.cdm = cdm

        if perms:
            perms.bot = self

        self.hi_new = {ord(c): '' for c in ", '"}
        self._setup()

    def _setup(self):
        db = 'test'
        engine = create_engine('mysql+pymysql://{0.db_user}:{0.db_password}@{0.db_host}:{0.db_port}/{1}?charset=utf8mb4'.format(self.config, db),
                               encoding='utf8')
        session_factory = sessionmaker(bind=engine)
        Session = scoped_session(session_factory)
        self._Session = Session
        self.mysql = Object()
        self.mysql.session = self.get_session
        self.mysql.engine = engine

    @property
    def get_session(self):
        return self._Session()

    async def on_ready(self):
        print('[INFO] Logged in as {0.user.name}'.format(self))
        await self.change_presence(game=discord.Game(name=self.config.game))

        for cog in initial_cogs:
            try:
                self.load_extension(cog)
            except Exception as e:
                print('Failed to load extension {}\n{}: {}'.format(cog, type(e).__name__, e))

    async def on_message(self, message):
        await self.wait_until_ready()
        if message.author.bot or message.author == self.user:
            return

        management = getattr(self, 'management', None)

        if message.server and message.server.id == '217677285442977792' and management:
            if len(message.mentions) + len(message.role_mentions) > 10:
                whitelist = self.management.get_mute_whitelist(message.server.id)
                invulnerable = discord.utils.find(lambda r: r.id in whitelist,
                                                  message.server.roles)
                if invulnerable is None or invulnerable not in message.author.roles:
                    role = discord.utils.find(lambda r: r.id == '322837972317896704',
                                              message.server.roles)
                    if role is not None:
                        await self.add_roles(message.author, role)
                        await self.send_message(message.channel,
                                                'Muted {0.mention}'.format(message.author))

        # If the message is a command do that instead
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        oshit = self.cdm.get_cooldown('oshit')
        imnew = self.cdm.get_cooldown('imnew')
        if oshit and oshit.trigger(False) and message.content.lower() == 'o shit':
            msg = 'waddup'
            await self.send_message(message.channel, msg)

            herecome = await self.wait_for_message(timeout=12, author=message.author, content='here come')
            if herecome is None:
                await self.send_message(message.channel, ':(')
            else:
                await self.send_message(message.channel, 'dat boi')
            return

        elif imnew and imnew.trigger(False) and message.content.lower().translate(self.hi_new) == 'hiimnew':
            await self.send_message(message.channel, 'Hi new, I\'m dad')

    async def on_member_join(self, member):
        server = member.server
        management = getattr(self, 'management', None)
        if not management:
            return

        server_config = management.get_config(server.id)
        if server_config is None:
            return

        conf = server_config.get('join', None)
        if conf is None:
            return

        channel = server.get_channel(conf['channel'])
        if channel is None:
            return

        message = management.format_join_leave(member, conf)

        await self.send_message(channel, message)

        if conf['add_color']:
            colors = server_config.get('colors', {})

            if colors and channel is not None:
                role = None
                for i in range(3):
                    color = choice(list(colors.values()))
                    roles = server.roles
                    role = list(filter(lambda r: r.id == color, roles))
                    if role:
                        break

                if role:
                    await self.add_roles(member, role[0])

        if server.id == '217677285442977792':
            await self._wants_to_be_noticed(member, server, remove=False)

    async def on_member_remove(self, member):
        management = getattr(self, 'management', None)
        if not management:
            return

        server = member.server
        conf = management.get_leave(server.id)
        if conf is None:
            return

        channel = server.get_channel(conf['channel'])
        if channel is None:
            return

        d = slots2dict(member)
        d.pop('user', None)
        message = conf['message'].format(user=str(member), **d)
        await self.send_message(channel, message)

    async def on_member_update(self, before, after):
        server = after.server
        if server.id == '217677285442977792':
            name = before.name if not before.nick else before.nick
            name2 = after.name if not after.nick else after.nick
            if name == name2:
                return

            await self._wants_to_be_noticed(after, server)

    async def _wants_to_be_noticed(self, member, server, remove=True):
        role = list(filter(lambda r: r.id == '318762162552045568', server.roles))
        if not role:
            return

        role = role[0]

        name = member.name if not member.nick else member.nick
        if ord(name[0]) <= 46:
            for i in range(0, 2):
                try:
                    await self.add_roles(member, role)
                except:
                    pass
                else:
                    break

        elif remove and role in member.roles:
                await retry(self.remove_roles, member, role)

    async def on_message_delete(self, msg):
        if msg.author.bot:
            return
        management = getattr(self, 'management', None)
        if not management:
            return

        conf = management.get_config(msg.server.id).get('on_delete', None)
        if conf is None:
            return

        channel = msg.server.get_channel(conf['channel'])
        if channel is None:
            return

        content = msg.content
        user = msg.author

        message = conf['message']
        d = slots2dict(user)
        for e in ['name', 'message']:
            d.pop(e, None)

        d['channel'] = msg.channel.mention
        message = message.format(name=str(user), message=content, **d)
        message = split_string(message)
        for m in message:
            await self.send_message(channel, m)

    async def on_message_edit(self, before, after):
        if before.author.bot:
            return

        management = getattr(self, 'management', None)
        if not management:
            return

        conf = management.get_config(before.server.id).get('on_edit', None)
        if not conf:
            return

        channel = before.server.get_channel(conf['channel'])
        if channel is None:
            return

        bef_content = before.content
        aft_content = after.content
        if bef_content == aft_content:
            return

        user = before.author

        message = conf['message']
        d = slots2dict(user)
        for e in ['name', 'before', 'after']:
            d.pop(e, None)

        d['channel'] = after.channel.mention
        message = message.format(name=str(user), **d,
                                 before=bef_content, after=aft_content)

        message = split_string(message, maxlen=1960)
        for m in message:
            await self.send_message(channel, m)

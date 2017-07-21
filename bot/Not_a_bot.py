import logging
from random import choice

import discord
from sqlalchemy import create_engine
from sqlalchemy.orm import scoped_session, sessionmaker

from bot.bot import Bot
from bot.cooldown import CooldownManager
from utils.utilities import (split_string, slots2dict, retry)
from cogs.voting import Poll
from bot.servercache import ServerCache

logger = logging.getLogger('debug')

initial_cogs = [
    'cogs.botadmin',
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
    'cogs.logging',
    'cogs.gachiGASM',
    'cogs.moderator',
    'cogs.settings']


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
        self._server_cache = ServerCache(self)

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

    def load_polls(self):
        session = self.get_session
        sql = 'SELECT polls.title, polls.message, polls.channel, polls.expires_in, polls.ignore_on_dupe, polls.multiple_votes, polls.strict, emotes.emote FROM polls LEFT OUTER JOIN pollEmotes ON polls.message = pollEmotes.poll_id LEFT OUTER JOIN emotes ON emotes.emote = pollEmotes.emote_id'
        poll_rows = session.execute(sql)
        polls = {}
        for row in poll_rows:
            poll = polls.get(row['message'], Poll(self, row['message'], row['channel'], row['title'],
                                                  expires_at=row['expires_in'],
                                                  strict=row['strict'],
                                                  no_duplicate_votes=row['ignore_on_dupe'],
                                                  multiple_votes=row['multiple_votes']))

            if poll.message not in polls:
                polls[poll.message] = poll

            poll.add_emote(row['emote'])

        for poll in polls.values():
            poll.start()

    @property
    def get_session(self):
        return self._Session()

    @property
    def server_cache(self):
        return self._server_cache

    async def on_ready(self):
        print('[INFO] Logged in as {0.user.name}'.format(self))
        await self.change_presence(game=discord.Game(name=self.config.game))

        for cog in initial_cogs:
            try:
                self.load_extension(cog)
            except Exception as e:
                print('Failed to load extension {}\n{}: {}'.format(cog, type(e).__name__, e))

        self.load_polls()

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

        if message.server and message.server.id == '217677285442977792' and message.author.id != '123050803752730624':
            if discord.utils.find(lambda r: r.id == '323098643030736919', message.role_mentions):
                await self.replace_role(message.author, message.author.roles, (*message.author.roles, '323098643030736919'))

        # If the message is a command do that instead
        if message.content.startswith(self.command_prefix):
            await self.process_commands(message)
            return

        oshit = self.cdm.get_cooldown('oshit')
        imnew = self.cdm.get_cooldown('imnew')
        if oshit and oshit.trigger(False) and message.content.lower().strip() == 'o shit':
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

    async def on_member_update(self, before, after):
        server = after.server
        if server.id == '217677285442977792':
            name = before.name if not before.nick else before.nick
            name2 = after.name if not after.nick else after.nick
            if name == name2:
                return

            await self._wants_to_be_noticed(after, server)

    async def on_server_join(self, server):
        session = self.get_session
        sql = 'INSERT INTO `servers` (`server`) ' \
              'VALUES (%s) ON DUPLICATE KEY IGNORE' % server.id
        session.execute(sql)
        session.commit()

        sql = 'SELECT * FROM `servers` WHERE server=%s' % server.id
        row = session.execute(sql).first()
        if not row:
            return

        self.server_cache.update_cached_server(server.id, **row)

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

    @staticmethod
    def _parse_on_delete(msg, conf):
        content = msg.content
        user = msg.author

        message = conf['message']
        d = slots2dict(msg)
        d = slots2dict(user, d)
        for e in ['name', 'message']:
            d.pop(e, None)

        d['channel'] = msg.channel.mention
        message = message.format(name=str(user), message=content, **d)
        return split_string(message)

    async def raw_message_delete(self, data):
        id = data.get('id')
        if not id:
            return

        session = self.get_session
        result = session.execute('SELECT `message` `user_id` `server` FROM `messages` WHERE `message_id` = %s' % id)
        msg = result.first()
        if not msg:
            return

        message, user_id, server_id = msg['message'], msg['user_id'], msg['server']
        server = self.get_server(server_id)
        if not server:
            return

        user = server.get_member(user_id)
        if not user:
            return

        channel_id = session.execute('SELECT `on_delete_channel` FROM `servers` WHERE `server` = %s' % server_id).first()
        if not channel_id:
            return

        channel = server.get_channel(channel_id['channel_id'])

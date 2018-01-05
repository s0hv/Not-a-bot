# Ignore this file

import json
import os
import re
from random import choice
from threading import Lock

import discord
from bot.bot import command
from utils.utilities import slots2dict, split_string
import logging

logger = logging.getLogger('debug')
manage_server = discord.Permissions(48)  # Manage server and channels
color_perms = discord.Permissions(268435504)  # Manage server, channels and roles


class ManagementHandler:
    def __init__(self, bot):
        self.bot = bot
        self.servers = {}
        self.path = os.path.join(os.getcwd(), 'data', 'servers.json')
        self._lock = Lock()
        self.reload_config()

    def reload_config(self):
        if os.path.exists(self.path):
            with open(self.path, 'r') as f:
                self.servers = json.load(f)

    @staticmethod
    def msg2dict(msg):
        d = {}
        attachments = [attachment['url'] for attachment in msg.attachments if 'url' in attachment]
        d['attachments'] = ', '.join(attachments)
        return d

    def format_on_edit(self, before, after, conf, check_equal=True):
        bef_content = before.content
        aft_content = after.content
        if check_equal:
            if bef_content == aft_content:
                return

        user = before.author

        message = conf['message']
        d = self.msg2dict(before)
        d = slots2dict(user, d)
        for e in ['name', 'before', 'after']:
            d.pop(e, None)

        d['channel'] = after.channel.mention
        message = message.format(name=str(user), **d,
                                 before=bef_content, after=aft_content)

        return message

    @staticmethod
    def format_join_leave(member, conf):
        d = slots2dict(member)
        d.pop('user', None)
        message = conf['message'].format(user=str(member), **d)
        return message

    def format_on_delete(self, msg, conf):
        content = msg.content
        user = msg.author

        message = conf['message']
        d = self.msg2dict(msg)
        d = slots2dict(user, d)
        for e in ['name', 'message']:
            d.pop(e, None)

        d['channel'] = msg.channel.mention
        message = message.format(name=str(user), message=content, **d)
        return message

    @staticmethod
    def get_channel(s, server):
        matches = re.findall(r'(?!<#)*\d+(?=>)*', s)
        if matches:
            id = matches[0]
            channel = server.get_channel(id)
            return channel

    def add_color_to_json(self, name, serverid, roleid):
        colors = self.get_colors(serverid)
        colors[name] = roleid

        self.save_json()

    def delete_color_from_json(self, name, serverid):
        colors = self.get_colors(serverid)
        try:
            del colors[name]
        except Exception as e:
            print(e)

        self.save_json()

    @staticmethod
    def get_roles_from_ids(server_roles, *ids):
        roles = []
        for r in ids:
            try:
                int(r)
            except:
                continue

            r = discord.utils.find(lambda role: role.id == str(r), server_roles)
            if r:
                roles.append(r)

        return roles

    @staticmethod
    def get_users_from_ids(server, *ids):
        users = []
        for i in ids:
            try:
                int(i)
            except:
                continue

            user = server.get_member(i)
            if user:
                users.append(user)

        return users

    async def join_leave(self, ctx, channel, message, add_color, join=True):
        key = 'join' if join else 'leave'
        user = ctx.message.author
        channel_ = ctx.message.channel
        server = ctx.message.server
        if not user.permissions_in(channel_).manage_channels:
            return await self.bot.send_message(channel_, "You don't have manage channel permissions")

        chn = self.get_channel(channel, server)
        if chn is None:
            return await self.bot.send_message(channel_, 'Could not get channel %s' % channel)

        config = self.servers.get(server.id, {})
        config[key] = {'message': message, 'channel': chn.id,
                       'add_color': add_color}
        self.servers[server.id] = config
        self.save_json()
        config_ = json.dumps(config[key], ensure_ascii=False)
        await self.bot.say('Current {} message config ```json\n{}```'.format(key, config_), delete_after=120)

        return config

    async def message_edited(self, ctx, channel, message, key='on_edit'):
        user = ctx.message.author
        channel_ = ctx.message.channel
        server = ctx.message.server
        if not user.permissions_in(channel_).manage_channels:
            return await self.bot.send_message(channel_, "You don't have manage channel permissions")

        config = self.get_config(server.id)
        chn = self.get_channel(channel, server)
        if chn is None:
            return await self.bot.send_message(channel_,
                                               'Could not get channel %s' % channel)

        config[key] = {'message': message, 'channel': chn.id}
        self.save_json()
        config_ = json.dumps(config[key], ensure_ascii=False)
        await self.bot.send_message(channel_,
                                    '{} config ```json\n{}```'.format(key, config_))

        return config

    def save_json(self):
        def save():
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.servers, f, ensure_ascii=False, indent=4)
                    return True
            except:
                return False

        with self._lock:
            for i in range(2):
                if save():
                    return

    def get_config(self, serverid):
        conf = self.servers.get(serverid, None)
        if conf is None:
            conf = {}
            self.servers[serverid] = conf

        return conf

    def get_join(self, serverid):
        config = self.get_config(serverid)
        return config.get('join', None)

    def get_leave(self, serverid):
        config = self.get_config(serverid)
        return config.get('leave', None)

    def get_colors(self, serverid):
        config = self.servers.get(serverid, {})
        if serverid not in self.servers:
            self.servers[serverid] = config

        colors = config.get('colors', {})
        if 'colors' not in config:
            config['colors'] = colors

        return colors

    def get_mute_whitelist(self, serverid):
        config = self.get_config(serverid)
        if 'unmutable' not in config:
            config['unmutable'] = []

        return config.get('unmutable', [])

    def set_muted_role(self, serverid, roleid):
        conf = self.get_config(serverid)
        conf['muted_role'] = roleid

        self.save_json()

    def remove_removed_colors(self, serverid):
        server = self.bot.get_server(serverid)
        roles = server.roles
        colors = self.get_colors(serverid)

        removed = []

        for key, color in list(colors.items()):
            role = discord.utils.find(lambda r: r.id == color, roles)
            if role is None:
                self.delete_color_from_json(key, serverid)
                removed.append(key)

        return removed


class Management:
    def __init__(self, bot):
        self.bot = bot
        self.utils = ManagementHandler(bot)
        self.bot.management = self.utils

    @command(pass_context=True, owner_only=True)
    async def test2(self, ctx, mention, role1, role2, replaced):
        mention = ctx.message.server.get_member(mention)
        await self.bot.replace_role(mention, (role1, role2), (replaced, ))

    @command(pass_context=True, owner_only=True)
    async def convert_colors(self, ctx):
        from colormath.color_conversions import convert_color
        from colormath.color_objects import LabColor, sRGBColor

        server = ctx.message.server
        colors = self.utils.get_colors(server.id)
        session = self.bot.get_session
        self.bot.dbutil.add_roles(server.id, *colors.values())
        for name, color_id in colors.items():
            role = self.bot.get_role(server, str(color_id))
            if not role:
                print('skipping %s %s' % (name, color_id))
                continue

            lab = convert_color(sRGBColor(*role.color.to_tuple(), is_upscaled=True), LabColor)
            sql = 'INSERT INTO `colors` (`id`, `name`, `value`, `lab_l`, `lab_a`, `lab_b`) VALUES ' \
                  '(:id, :name, :value, :lab_l, :lab_a, :lab_b)'
            session.execute(sql, params={'id': int(color_id),
                                         'name': name,
                                         'value': role.color.value,
                                         'lab_l': lab.lab_l,
                                         'lab_a': lab.lab_a,
                                         'lab_b': lab.lab_b})

        try:
            session.commit()
        except:
            session.rollback()

    @command(pass_context=True, owner_only=True)
    async def convert_color(self, ctx, color_id, name):
        from colormath.color_conversions import convert_color
        from colormath.color_objects import LabColor, sRGBColor

        server = ctx.message.server
        session = self.bot.get_session
        self.bot.dbutil.add_roles(server.id, color_id)
        role = self.bot.get_role(server, str(color_id))
        if not role:
            return

        lab = convert_color(
            sRGBColor(*role.color.to_tuple(), is_upscaled=True), LabColor)
        sql = 'INSERT INTO `colors` (`id`, `name`, `value`, `lab_l`, `lab_a`, `lab_b`) VALUES ' \
              '(:id, :name, :value, :lab_l, :lab_a, :lab_b)'
        try:
            session.execute(sql, params={'id': int(color_id),
                                         'name': name,
                                         'value': role.color.value,
                                         'lab_l': lab.lab_l,
                                         'lab_a': lab.lab_a,
                                         'lab_b': lab.lab_b})

            session.commit()
        except:
            session.rollback()
        await self.bot.say('k')

    @command(owner_only=True)
    async def reload_config(self):
        self.utils.reload_config()
        await self.bot.say('Reloaded config')


def setup(bot):
    bot.add_cog(Management(bot))
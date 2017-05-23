import json
import os
import re

from bot.bot import command
from colour import Color
import discord
from utils.utilities import y_n_check
from random import choice


class Management:
    def __init__(self, bot):
        self.bot = bot
        self.servers = {}
        self.path = os.path.join(os.getcwd(), 'data', 'servers.json')
        if os.path.exists(self.path):
            with open(self.path, 'r') as f:
                self.servers = json.load(f)

    @staticmethod
    def get_channel(s, server):
        matches = re.findall(r'(?!<#)*\d+(?=>)*', s)
        if matches:
            id = matches[0]
            channel = server.get_channel(id)
            return channel

    def add_color_to_json(self, name, serverid):
        colors = self.get_colors(serverid)
        colors.append(name)
        self.save_json()

    def delete_color_from_json(self, name, serverid):
        colors = self.get_colors(serverid)
        try:
            while name in colors:
                colors.remove(name)
        except Exception as e:
            print(e)

        self.save_json()

    async def _join_leave(self, ctx, channel, message, add_color, join=True):
        key = 'join' if join else 'leave'
        user = ctx.message.author
        channel_ = ctx.message.channel
        server = ctx.message.server
        if not user.permissions_in(channel_).manage_server:
            return await self.bot.send_message(channel_, "You don't have manage server permissions")

        chn = self.get_channel(channel, server)
        if chn is None:
            return await self.bot.send_message(channel_, 'Could not get channel %s' % channel)

        config = self.servers.get(server.id, {})
        config[key] = {'message': message, 'channel': chn.id,
                       'add_color': add_color}
        self.servers[server.id] = config
        self.save_json()
        config = json.dumps(config[key], ensure_ascii=False)
        await self.bot.say_timeout('Current {} message config ```json\n{}```'.format(key, config),
                                   channel_, 120)

    @command(pass_context=True)
    async def leave_message(self, ctx, channel, message):
        await self._join_leave(ctx, channel, message, False, join=False)

    @command(pass_context=True)
    async def join_message(self, ctx, channel, message, add_color=False):
        await self._join_leave(ctx, channel, message, add_color,  join=True)

    async def _message_edited(self, ctx, channel, message, key='on_edit'):
        server = ctx.message.server

        config = self.get_config(server.id)
        chn = self.get_channel(channel, server)
        if chn is None:
            return await self.bot.send_message(ctx.message.channel,
                                               'Could not get channel %s' % channel)

        config[key] = {'message': message, 'channel': chn.id}
        self.save_json()
        config = json.dumps(config[key], ensure_ascii=False)
        await self.bot.send_message(ctx.message.channel,
                                    '{} config ```json\n{}```'.format(key, config))

    @command(pass_context=True)
    async def on_edit_message(self, ctx, channel, message):
        await self._message_edited(ctx, channel, message)

    @command(pass_context=True)
    async def on_delete_message(self, ctx, channel, message):
        await self._message_edited(ctx, channel, message, key='on_delete')

    @command(pass_context=True, owner_only=True)
    async def delete_color(self, ctx, *, name):
        roles = list(filter(lambda r: str(r) == name, ctx.message.server.roles))
        server = ctx.message.server
        colors = self.get_colors(server.id)
        if name not in colors or not roles:
            return await self.bot.say('Color %s not found' % name)

        if len(roles) > 1:
            await self.bot.say('Multiple roles found. Delete them all y/n')
            msg = await self.bot.wait_for_message(timeout=10,
                                                  author=ctx.message.author,
                                                  channel=ctx.message.channel,
                                                  check=y_n_check)
            if msg is None or msg.content.lower().strip() in ['n', 'no']:
                return await self.bot.say('Cancelled')

        r_len = len(roles)
        failed = 0
        for role in roles:
            try:
                await self.bot.delete_role(server, role)
            except:
                failed += 1

        if failed == 0:
            await self.bot.say('Successfully deleted %s roles' % str(r_len))
        else:
            await self.bot.say('Successfully deleted {} roles and failed {}'.format(
                                r_len - failed, failed))

        self.delete_color_from_json(name, server.id)

    @command(pass_context=True, owner_only=True)
    async def add_color(self, ctx, color, *, name):
        try:
            color = Color(color)
        except (ValueError, AttributeError):
            return await self.bot.say('Color %s is invalid' % color)

        try:
            color = color.get_hex_l()
            if color.startswith('#'):
                color = color[1:]

            color = discord.Color(int(color, 16))
            everyone = ctx.message.server.default_role
            perms = discord.Permissions(everyone.permissions.value)
            await self.bot.create_role(ctx.message.server, name=name,
                                       colour=color,
                                       permissions=perms,
                                       mentionable=False, hoist=False)
        except Exception as e:
            print('[ERROR] Exception while creating role. %s' % e)
            return await self.bot.say('Could not create role')

        self.add_color_to_json(name, ctx.message.server.id)
        await self.bot.say('Color %s added' % name)

    @command(pass_context=True, aliases=['colour'])
    async def color(self, ctx, *, color):
        server = ctx.message.server
        roles = server.roles
        color = color.lower()
        colors = self.get_colors(server.id)
        role_ = list(filter(lambda r: str(r).lower() == color, roles))
        if not role_:
            return await self.bot.say('Color %s not found. Use !colors for all the available colors.' % color)

        _roles = []
        for role in ctx.message.author.roles:
            if str(role) in colors and role != role_[0]:
                _roles.append(role)

        try:
            await self.bot.remove_roles(ctx.message.author, *_roles)
            for r in _roles:
                if r in ctx.message.author.roles:
                    if str(r) in colors:
                        ctx.message.author.roles.remove(r)

            await self.bot.add_roles(ctx.message.author, *role_)
        except Exception as e:
            print(e)
            await self.bot.say('Failed to change color')
        else:
            await self.bot.say('Color set to %s' % color)

    @command(pass_context=True)
    async def colors(self, ctx):
        await self.bot.say('Available colors: {}'.format(', '.join(self.get_colors(ctx.message.server.id))))

    @command(pass_context=True, owner_only=True)
    async def color_uncolored(self, ctx):
        server = ctx.message.server
        colors = self.get_colors(server.id)
        if not colors:
            return

        roles = server.roles
        for member in server.members:
            if len(member.roles) == 1:
                color = choice(colors)
                role = list(filter(lambda r: str(r) == color, roles))
                try:
                    await self.bot.add_roles(member, *role)
                except Exception:
                    pass

    def save_json(self):
        def save():
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.servers, f, ensure_ascii=False, indent=4)
                    return True
            except:
                return False

        for i in range(3):
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

        colors = config.get('colors', [])
        if 'colors' not in config:
            config['colors'] = colors

        return colors

import json
import os
import re

from bot.bot import command
from colour import Color
import discord
from utils.utilities import y_n_check, slots2dict, normalize_text
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
    def format_on_edit(before, after, conf, check_equal=True):
        bef_content = before.content
        aft_content = after.content
        if check_equal:
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

        return message

    @staticmethod
    def format_join_leave(member, conf):
        d = slots2dict(member)
        d.pop('user', None)
        message = conf['message'].format(user=str(member), **d)
        return message

    @staticmethod
    def format_on_delete(msg, conf):
        content = msg.content
        user = msg.author

        message = conf['message']
        d = slots2dict(user)
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
        config_ = json.dumps(config[key], ensure_ascii=False)
        await self.bot.say_timeout('Current {} message config ```json\n{}```'.format(key, config_),
                                   channel_, 120)

        return config

    @command(pass_context=True)
    async def leave_message(self, ctx, channel, message=None):
        if channel.lower() == 'off':
            self.get_config(ctx.message.server.id).pop('leave', None)
            await self.bot.say('Removed on leave config')
            return

        if message is None:
            return await self.bot.say('You need to specify a message')

        old = self.get_config(ctx.message.server.id).get('leave', {})
        conf = await self._join_leave(ctx, channel, message, False, join=False)
        if not isinstance(conf, dict):
            return

        try:
            self.format_on_delete(ctx.message, conf['leave'])
        except Exception as e:
            conf['leave'] = old
            self.save_json()
            await self.bot.say('New format failed with error "{}"\n'
                               'reverting back'.format(e))

    @command(pass_context=True)
    async def join_message(self, ctx, channel, message=None, add_color=False):
        if channel.lower() == 'off':
            self.get_config(ctx.message.server.id).pop('join', None)
            await self.bot.say('Removed on join config')
            return

        if not message:
            return await self.bot.say('You need to specify a message')

        old = self.get_config(ctx.message.server.id).get('join', {})
        conf = await self._join_leave(ctx, channel, message, add_color,  join=True)
        if not isinstance(conf, dict):
            return

        try:
            self.format_on_delete(ctx.message, conf['join'])
        except Exception as e:
            conf['join'] = old
            self.save_json()
            await self.bot.say('New format failed with error "{}"\n'
                               'reverting back'.format(e))

    async def _message_edited(self, ctx, channel, message, key='on_edit'):
        user = ctx.message.author
        channel_ = ctx.message.channel
        server = ctx.message.server
        if not user.permissions_in(channel_).manage_server:
            return await self.bot.send_message(channel_, "You don't have manage server permissions")

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

    @command(pass_context=True)
    async def on_edit_message(self, ctx, channel, *, message):
        user = ctx.message.author
        channel_ = ctx.message.channel
        if not user.permissions_in(channel_).manage_server:
            return await self.bot.send_message(channel_, "You don't have manage server permissions")

        if channel.lower() == 'off':
            self.get_config(ctx.message.server.id).pop('on_edit', None)
            await self.bot.say('Removed on message edit config')
            return

        old = self.get_config(ctx.message.server.id).get('on_edit', {})
        conf = await self._message_edited(ctx, channel, message)
        if not isinstance(conf, dict):
            return

        try:
            self.format_on_edit(ctx.message, ctx.message, conf['on_edit'], False)
        except Exception as e:
            conf['on_edit'] = old
            self.save_json()
            await self.bot.say('New format failed with error "{}"\n'
                               'reverting back'.format(e))

    @command(pass_context=True)
    async def on_delete_message(self, ctx, channel, message):
        user = ctx.message.author
        channel_ = ctx.message.channel
        if not user.permissions_in(channel_).manage_server:
            return await self.bot.send_message(channel_, "You don't have manage server permissions")

        if channel.lower() == 'off':
            self.get_config(ctx.message.server.id).pop('on_delete', None)
            await self.bot.say('Removed on message delete config')
            return

        old = self.get_config(ctx.message.server.id).get('on_delete', {})
        conf = await self._message_edited(ctx, channel, message, key='on_delete')

        if not isinstance(conf, dict):
            return

        try:
            self.format_on_delete(ctx.message, conf['on_delete'])
        except Exception as e:
            conf['on_delete'] = old
            self.save_json()
            await self.bot.say('New format failed with error "{}"\n'
                               'reverting back'.format(e))

    @command(pass_context=True, owner_only=True)
    async def delete_color(self, ctx, *, name):
        server = ctx.message.server
        colors = self.get_colors(server.id)
        v = colors.values()
        roles = list(filter(lambda r: r.id in v, ctx.message.server.roles))

        if not roles:
            return await self.bot.say('Color %s not found' % name)

        role = roles[0]
        try:
            await self.bot.delete_role(server, role)
        except Exception as e:
            await self.bot.say('Could not delete color %s\n%s' % (name, e))
            return

        self.delete_color_from_json(name, server.id)
        await self.bot.say('Deleted color %s' % name)

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
            role = await self.bot.create_role(ctx.message.server, name=name,
                                              colour=color,
                                              permissions=perms,
                                              mentionable=False, hoist=False)
        except Exception as e:
            print('[ERROR] Exception while creating role. %s' % e)
            return await self.bot.say('Could not create role')

        self.add_color_to_json(name, ctx.message.server.id, role.id)
        await self.bot.say('Color %s added' % name)

    @command(pass_context=True, aliases=['colour'])
    async def color(self, ctx, *, color):
        server = ctx.message.server
        roles = server.roles
        color = color.lower()
        colors = self.get_colors(server.id)
        color_id = colors.get(color, None)
        role_ = list(filter(lambda r: r.id == color_id, roles))
        if not role_:
            return await self.bot.say('Color %s not found. Use !colors for all the available colors.' % color)

        role_ = role_[0]
        _roles = []
        for role in ctx.message.author.roles:
            v = colors.values()
            if role.id in v and role != role_:
                _roles.append(role)

        try:
            await self.bot.remove_roles(ctx.message.author, *_roles)
            v = colors.values()
            for r in _roles:
                if r in ctx.message.author.roles:
                    if r.id in v:
                        ctx.message.author.roles.remove(r)

            await self.bot.add_roles(ctx.message.author, role_)
        except Exception as e:
            print(e)
            await self.bot.say('Failed to change color')
        else:
            await self.bot.say('Color set to %s' % color)

    @command(pass_context=True)
    async def colors(self, ctx):
        await self.bot.say('Available colors: {}'.format(', '.join(self.get_colors(ctx.message.server.id).keys())))

    @command(pass_context=True, owner_only=True)
    async def color_uncolored(self, ctx):
        server = ctx.message.server
        colors = self.get_colors(server.id)
        if not colors:
            return

        roles = server.roles
        for member in server.members:
            if len(member.roles) == 1:
                color = choice(list(colors.values()))
                role = list(filter(lambda r: r.id == color, roles))
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

        colors = config.get('colors', {})
        if 'colors' not in config:
            config['colors'] = colors

        return colors

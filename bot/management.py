import json
import os
import re

from bot.bot import command
from colour import Color
import discord
from utils.utilities import y_n_check, slots2dict, normalize_text
from random import choice
from threading import Lock


class Management:
    def __init__(self, bot):
        self.bot = bot
        self.servers = {}
        self.path = os.path.join(os.getcwd(), 'data', 'servers.json')
        self._lock = Lock()
        self._load_config()

    def _load_config(self):
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
        color = colors.get(name, None)
        if not color:
            return await self.bot.say('Color %s not found' % name)

        v = colors.values()
        role = discord.utils.find(lambda r: r.id == color, server.roles)
        list(filter(lambda r: r.id in v, ctx.message.server.roles))

        if not role:
            return await self.bot.say('Color %s not found' % name)

        try:
            await self.bot.delete_role(server, role)
        except Exception as e:
            await self.bot.say('Could not delete color %s\n%s' % (name, e))
            return

        self.delete_color_from_json(name.lower(), server.id)
        await self.bot.say('Deleted color %s' % name)

    @command(pass_context=True, owner_only=True)
    async def mute_whitelist(self, ctx, *roles):
        role_mentions = ctx.message.role_mentions.copy()

        server_roles = ctx.message.server.roles
        role_mentions.extend(self.get_roles_from_ids(server_roles, *roles))

        if not role_mentions:
            return await self.bot.say(
                'Use the role ids or mention roles to add them to the whitelist')

        conf = self.get_mute_whitelist(ctx.message.server.id)
        for role in role_mentions:
            if role.id not in conf:
                conf.append(role.id)

        self.save_json()
        role_mentions = list(map(lambda r: r.name, role_mentions))
        await self.bot.say('Roles {} added to the whitelist'.format(', '.join(role_mentions)))

    @command(pass_context=True, owner_only=True)
    async def muted_role(self, ctx, *roles):
        server = ctx.message.server
        role_mentions = ctx.message.role_mentions
        role_mentions.extend(self.get_roles_from_ids(server.roles, *roles))
        if not role_mentions:
            return await self.bot.say('No role/role id specified')

        whitelist = self.get_mute_whitelist(server.id)
        role = role_mentions[0]
        if role.id in whitelist:
            return await self.bot.say('Role is already in the mute whitelist. '
                                      'Remove it from there first using !remove_mute_whitelist')

        self.set_muted_role(server.id, role.id)
        await self.bot.say('Muted role set to {0.name}: {0.id}'.format(role))

    @command(pass_context=True, owner_only=True)
    async def mute(self, ctx, *user):
        server = ctx.message.server
        mute_role = self.get_config(server.id).get('muted_role', None)
        if mute_role is None:
            return await self.bot.say('No mute role set')

        users = ctx.message.mentions.copy()
        users.extend(self.get_users_from_ids(server, *user))

        if not users:
            return await self.bot.say('No user ids or mentions')

        mute_role = discord.utils.find(lambda r: r.id == str(mute_role), server.roles)
        if mute_role is None:
            return await self.bot.say('Could not find the muted role')

        try:
            await self.bot.add_roles(users[0], mute_role)
            await self.bot.say('Muted user {}'.format(users[0].name))
        except:
            await self.bot.say('Could not mute user {}'.format(users[0].name))

    @command(pass_context=True, owner_only=True)
    async def unmute(self, ctx, *user):
        server = ctx.message.server
        mute_role = self.get_config(server.id).get('muted_role', None)
        if mute_role is None:
            return await self.bot.say('No mute role set')

        users = ctx.message.mentions.copy()
        users.extend(self.get_users_from_ids(server, *user))

        if not users:
            return await self.bot.say('No user ids or mentions')

        mute_role = discord.utils.find(lambda r: r.id == str(mute_role), server.roles)
        if mute_role is None:
            return await self.bot.say('Could not find the muted role')

        try:
            await self.bot.remove_roles(users[0], mute_role, remove_manually=False)
            await self.bot.say('Unmuted user {}'.format(users[0].name))
        except:
            await self.bot.say('Could not unmute user {}'.format(users[0].name))

    @command(pass_context=True, owner_only=True)
    async def remove_mute_whitelist(self, ctx, *roles):
        role_mentions = ctx.message.role_mentions.copy()

        server_roles = ctx.message.server.roles
        role_mentions.extend(self.get_roles_from_ids(server_roles, *roles))

        if not role_mentions:
            return await self.bot.say(
                'Use the role ids or mention roles to remove them from the whitelist')

        conf = self.get_mute_whitelist(ctx.message.server.id)
        removed = []
        for role in role_mentions:
            try:
                conf.remove(role.id)
            except ValueError:
                pass
            else:
                removed.append('```{0.name}```'.format(role))

        self.save_json()
        await self.bot.say('Roles {} removed from the whitelist'.format(', '.join(removed)))

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

        self.add_color_to_json(name.lower(), ctx.message.server.id, role.id)
        await self.bot.say('Color %s added' % name)

    @command(pass_context=True, owner_only=True)
    async def test2(self, ctx, mention, role1, role2, replaced):
        mention = ctx.message.server.get_member(mention)
        await self.bot.replace_role(mention, (role1, role2), (replaced, ))

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
            await self.bot.replace_role(ctx.message.author, _roles, (role_,))
        except Exception as e:
            print(e)
            await self.bot.say('Failed to change color')
        else:
            await self.bot.say('Color set to %s' % color)

    @command(pass_context=True)
    async def colors(self, ctx):
        await self.bot.say('Available colors: {}'.format(', '.join(self.get_colors(ctx.message.server.id).keys())))

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

    @command(pass_context=True, owner_only=True)
    async def check_colors(self, ctx):
        server = ctx.message.server
        removed = self.remove_removed_colors(server.id)
        if removed:
            await self.bot.say('removed colors {}'.format(', '.join(removed)))
        else:
            await  self.bot.say('No colors to remove')

    @command(pass_context=True, owner_only=True)
    async def color_uncolored(self, ctx):
        server = ctx.message.server
        removed = self.remove_removed_colors(server.id)
        if removed:
            await self.bot.say('Removed colors without role. {}'.format(', '.join(removed)))

        colors = self.get_colors(server.id)
        color_ids = list(colors.values())
        if not colors:
            return

        roles = server.roles
        colored = 0
        for member in server.members:
            m_roles = member.roles
            found = list(filter(lambda r: r.id in color_ids, m_roles))
            if not found:
                color = choice(color_ids)
                role = list(filter(lambda r: r.id == color, roles))
                try:
                    await self.bot.add_roles(member, *role)
                    colored += 1
                except Exception:
                    pass
            elif len(found) > 1:
                try:
                    await self.bot.replace_role(member, color_ids, (found[0],))
                    colored += 1
                except Exception:
                    pass

        await self.bot.say('Colored %s users without color role' % colored)

    @command(owner_only=True)
    async def reload_config(self):
        self._load_config()
        await self.bot.say('Reloaded config')

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

"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import configparser
import os

from utils import utilities
from functools import wraps
from discord.ext.commands.bot import _get_variable
from bot import exceptions


def owner_only(func):
    @wraps(func)
    async def _func_wrapper(ctx, *args, **kwargs):
        user = _get_variable('message')
        owner = ctx.bot.owner
        if not user or user.author.id == owner:
            return await func(ctx, *args, **kwargs)
        else:
            raise exceptions.PermissionError('Only the owner can use this command')

    return _func_wrapper


def check_permission(ctx):
    if ctx is None:
        raise exceptions.BotValueError('Error while processing command. Extra info in cmd',
                                       'No context class found. pass_context needs to be True')

    user_permissions = ctx.user_permissions
    if user_permissions.master_override:
        return True

    name = ctx.invoked_with

    if not user_permissions.command_usable(name):
        raise exceptions.PermissionError("You don't have the permission to use the command %s" % name)

    return True


class Permissions:
    def __init__(self, owner):
        self.config = configparser.ConfigParser()
        self.config.read(os.path.join(os.getcwd(), 'config', 'permissions.ini'), encoding='utf-8')
        self.values = self.config.keys()
        self.owner = owner
        self.groups = {s: PermissionGroup(s, **dict(self.config.items(s))) for s in self.config.sections()}
        self.groups['Owner'].master_override = True  # Owner has master override

    def get_permissions(self, id=None, role=None):
        if self.owner == id:
            return self.groups['Owner']

        if id is None and role is None:
            return self.groups['Default']

        for group in self.groups:
            if self.groups[group].id_in_group(id):
                return self.groups[group]

        for group in self.groups:
            if self.groups[group].role_in_group(role):
                return self.groups[group]

        return self.groups['Default']


class PermissionGroup:
    __slots__ = ['name', 'config', 'master_override', 'playlists', 'max_pl_len',
                 'playnow', 'edit_autoplaylist', 'whitelist', 'blacklist', 'users',
                 'roles']

    def __init__(self, name: str, master_override=False, **kwargs):
        self.name = name
        self.config = configparser.ConfigParser()
        self.config.read_dict({name: kwargs})
        self.master_override = master_override
        self.playlists = self.get_value('Playlists', bool, False)
        self.max_pl_len = self.get_value('MaxPlaylistSize', int, 10)
        self.playnow = self.get_value('PlayNow', bool, False)
        self.edit_autoplaylist = self.get_value('EditAutoplaylist', bool, False)
        self.blacklist = self._split(self.get_value('Blacklist', fallback=[]))
        self.whitelist = self._split(self.get_value('Whitelist', fallback=[]))
        self.users = self._split(self.get_value('UserList', fallback=[]))
        self.roles = self._split(self.get_value('RoleList', fallback=[]))

    def get_value(self, opt, opt_type=None, fallback=None):
        return utilities.get_config_value(self.config, self.name, opt, opt_type, fallback)

    # If s is string this splits it. Otherwise it does nothing
    def _split(self, s):
        if isinstance(s, str):
            return s.split(' ')

        else:
            return s

    def id_in_group(self, id):
        return id in self.users

    def role_in_group(self, role):
        return role in self.roles

    def command_usable(self, command):
        if self.whitelist:
            if command in self.whitelist:
                return True
            else:
                return False

        elif self.blacklist:
            if command in self.blacklist:
                return False

        return True



class Group:
    __slots__ = ['name', 'permissions', 'role_list', 'user_list']

    def __init__(self, name: str, master_override=False, **kwargs):
        self.name = name
        self.user_list = kwargs.pop('UserList', '').split(' ')
        self.role_list = kwargs.pop('RoleList', '').split(' ')
        self.permissions = PermissionGroup(name, master_override, **kwargs)

    def check_role(self, id_or_role):
        if id_or_role in self.user_list:
            return True
        elif id_or_role in self.role_list:
            return True

        return False

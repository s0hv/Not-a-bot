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

import collections
from functools import wraps

from peewee import *
from playhouse.pool import SqliteExtDatabase

from bot.exceptions import *
from bot.globals import PERMISSIONS, PERMISSION_OPTIONS


database = SqliteExtDatabase(PERMISSIONS, threadlocals=True)


def command_usable(permissions, command):
    if permissions.ban_commands:
        return PermissionError("You don't have the permission to use the command "
                               "%s because you have all commands blacklisted" % command.name)
    try:
        if permissions.whitelist is not None and len(permissions.whitelist) > 1:
            if command.name in permissions.whitelist.split(', '):
                return True
            else:
                raise PermissionError("You don't have the permission to use the command "
                                      "%s because it's not on your whitelist" % command.name)

        elif permissions.blacklist is not None and len(permissions.whitelist.strip()) > 1:
            if command.name in permissions.blacklist.split(', '):
                raise PermissionError("You don't have the permission to use the command "
                                      "%s because it's blacklisted for you" % command.name)

    except AttributeError:
        pass

    if 0 <= permissions.level < command.level:
        raise LevelPermissionException(command.level, permissions.level, "You don't have permission to use this command")

    return True


def check_permission(ctx, command):
    if ctx is None:
        raise BotValueError('Error while processing command. Extra info in cmd',
                            'No context class found. pass_context needs to be True')

    user_permissions = ctx.user_permissions
    if user_permissions.master_override:
        return True

    command_usable(user_permissions, command)

    return True


def database_transaction(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        database.connect()
        try:
            return func(*args, **kwargs)
        except Exception as e:
            print('[ERROR] Database transaction error\n%s' % e)
        finally:
            database.close()

    return wrapper


def parse_permissions(d, perms):
    keys = PERMISSION_OPTIONS.copy()
    true = ['on', 'true', 'yes']
    false = ['off', 'false', 'no']

    def valid_int_string(s, non_int, negative):
        try:
            s = int(s)
        except ValueError:
            raise InvalidValueException(s, non_int)

        if s < 0:
            raise InvalidValueException(s, negative)

        return s

    def valid_bool_str(s, name):
        if s in true:
            return True

        if s in false:
            return False

        raise InvalidValueException(s, '{} value must be {} or {}'.format(name, ', '.join(true), ', '.join(false)))

    for k, v in d.items():
        if k not in keys:
            raise InvalidArgumentException('Argument %s is invalid. To see valid arguments see !arguments' % k)

        if k == 'master_override':
            if v.lower() in true and not perms.master_override:
                raise InvalidPermissionsException('You can only set master_override on if your role has it set on')

        if k == 'level':
            v = valid_int_string(v, 'Level takes an integer as the parameter',
                                    'Level must be a positive integer')

            if v > perms.level >= 0:
                raise InvalidPermissionsException('You can only create permission with access level equal or lower than your level')

        if k == 'playlists':
            v = valid_bool_str(v, 'Playlist value')

        if k == 'max_playlist_length':
            v = valid_int_string(v, 'Playlist length takes an integer as the parameter',
                                    'Playlist length must be a positive integer')

        if k == 'edit_autoplaylist':
            v = valid_bool_str(v, 'edit_autoplaylist')
            if 10 > perms.level >= 0 and v:
                raise InvalidLevelException(10, 'To set edit_autoplaylist to true level must be at least 10')

        if k == 'edit_permissions':
            v = valid_bool_str(v, 'edit_permissions')
            if 7 > perms.level >= 0 and v:
                raise InvalidLevelException(7, 'To set edit_permissions to true level must be at least 7')

        if k == 'ban_commands':
            v = valid_bool_str(v, 'ban_commands')
            if 7 > perms.level >= 0 and v:
                raise InvalidLevelException(7, 'To set ban_commands to true level must be at least 7')

        if k == 'blacklist' or k == 'whitelist':
            v = v.split(' ')

        keys[k] = v

    return keys


class UserCache(collections.MutableMapping):
    def __init__(self, *args, maxlen=100, **kwargs):
        self.maxlen = maxlen
        self.d = dict(*args, **kwargs)

    def __iter__(self):
        return iter(self.d)

    def __len__(self):
        return len(self.d)

    def __getitem__(self, k):
        return self.d[k]

    def __delitem__(self, k):
        del self.d[k]

    def __setitem__(self, k, v):
        if k not in self and len(self) >= self.maxlen:
            self.popitem()

        self.d[k] = v


class Permissions:
    @database_transaction
    def __init__(self, owner, bot=None, sfx_bot=None):
        self.owner = owner
        self.bot = bot
        self.sfx_bot = sfx_bot
        self.database = database
        self.groups = {}
        self.user_cache = UserCache(maxlen=30)
        self.default_group = None
        self.owner_group = None

        for group in PermissionGroupTable.select():
            self.groups[group.id] = group
            if group.name == 'Owner':
                self.owner_group = group.id

            elif group.name == 'Default':
                    self.default_group = group.id

    @database_transaction
    def get_permissions(self, id=None):
        if id is None:
            return self.groups[self.default_group]

        if self.owner == id or self.bot.user.id == id or (self.sfx_bot is not None and self.sfx_bot.user.id == id):
            return self.groups[self.owner_group]

        if id in self.user_cache:
            return self.user_cache[id]

        permissions = self.groups[self.default_group]

        try:
            user = User.get(User.user_id == id)
            permissions = PermissionGroupTable.get(PermissionGroupTable.id == user.group)
            self.user_cache[id] = permissions
        except DoesNotExist:
            pass

        return permissions

    @database_transaction
    def set_permissions(self, permissions, *users):
        errors = {}
        for user in users:
            id = user.id
            with database.atomic() as txn:
                try:
                    u, c = User.get_or_create(user_id=id)
                    u.group = permissions.id
                    u.save()
                except Exception as e:
                    errors[user] = e
                    txn.rollback()

        return errors

    @database_transaction
    def get_permission_group(self, name):
        with database.atomic() as txn:
            try:
                group = PermissionGroupTable.get(name=name)
            except Exception as e:
                print('[ERROR] Database error. %s' % e)
                txn.rollback()
                return

            return group

    @database_transaction
    def create_permissions_group(self, **kwargs):
        with database.atomic() as txn:
            try:
                group = PermissionGroupTable.create(**kwargs)
            except Exception as e:
                txn.rollback()
                raise BotValueError('Error creating permission group.\n%s' % e)

            return group


class BaseModel(Model):
    class Meta:
        database = database


class PermissionGroupTable(BaseModel):
    name = CharField(unique=True)                    # Name of the group
    ban_commands = BooleanField(default=False)       # Ban the use of all commands
    master_override = BooleanField(default=False)    # Grants access to all everything
    playlists = BooleanField(default=True)           # Can queue playlists
    max_playlist_length = IntegerField(default=10)   # How many songs will be taken from the queued playlist max
    edit_autoplaylist = BooleanField(default=False)  # Can commit autoplaylist changes
    edit_permissions = BooleanField(default=False)   # Can edit and modify permission groups
    level = IntegerField(default=0)                  # The level this group grants
    whitelist = TextField(default=None, null=True)   # Whitelist of commands. Has priority over blacklist.
    blacklist = TextField(default=None, null=True)   # Blacklist of commands

    class Meta:
        db_table = 'permissiongroup'


class User(BaseModel):
    user_id = CharField(unique=True)
    group = ForeignKeyField(PermissionGroupTable, related_name='to_permission', null=True)


def create_default_permissions():
    try:
        database.connect()
        database.create_tables([PermissionGroupTable, User])

        with database.transaction():
            PermissionGroupTable.create(name='Owner', master_override=True, max_playlist_length=-1,
                                        level=-1, edit_autoplaylist=True, edit_permissions=True)

            PermissionGroupTable.create(name='Default')

    except OperationalError:
        pass
    finally:
        database.close()

create_default_permissions()

from sqlalchemy import text
from bot.exceptions import (NotEnoughPrefixes, PrefixExists,
                            PrefixDoesntExist)
from sqlalchemy.exc import SQLAlchemyError

class ServerCache:
    def __init__(self, bot):
        self._bot = bot
        self._servers = {}
        # Keys for integer values that need to be converted to string
        self._int2str = ['on_edit_channel', 'on_delete_channel', 'modlog', 'mute_role',
                         'on_join_channel', 'on_leave_channel']

    @property
    def bot(self):
        return self._bot

    def update_cached_server(self, server_id, **values):
        """
        Updates a servers cached values. None values are ignored
        """
        settings = self.get_settings(server_id)
        for k, v in values.items():
            if v is None:
                continue

            if k in self._int2str:
                v = str(v)

            settings[k] = v

        self._set_internal_value(server_id, 'prefixes', list(self.prefixes(server_id, use_set=True)))

    def set_value(self, server_id, name, value):
        sql = 'INSERT INTO `servers` (`server`, `{0}`) VALUES ({1}, :{0}) ON DUPLICATE KEY UPDATE {0}=:{0}'.format(name, server_id)
        session = self.bot.get_session
        try:
            session.execute(text(sql), params={name: value})
            session.commit()
            success = True
        except SQLAlchemyError:
            session.rollback()
            success = False
        settings = self.get_settings(server_id)
        settings[name] = value
        return success

    # Used for setting cached values not present in the database or in a different form e.g. cache a set as a list
    def _set_internal_value(self, server_id, name, value):
        settings = self.get_settings(server_id)
        internals = settings.get('_internals')
        if internals is None:
            internals = {}
            settings['_internals'] = internals

        internals[name] = value

    def _get_internals(self, server_id):
        settings = self.get_settings(server_id)
        internals = settings.get('_internals')
        if internals is None:
            internals = {}
            settings['_internals'] = internals

        return internals

    # utils
    def prefixes(self, server_id, use_set=False):
        if use_set:
            return self.get_settings(server_id).get('prefixes', {self.bot.default_prefix})

        prefixes = self._get_internals(server_id).get('prefixes')
        if prefixes is None:
            return tuple(self.bot.default_prefix, )

        return prefixes

    def add_prefix(self, server_id, prefix):
        settings = self.get_settings(server_id)
        if 'prefixes' not in settings:
            prefixes = {self.bot.default_prefix}
            settings['prefixes'] = prefixes
        else:
            prefixes = self.prefixes(server_id, use_set=True)

        if prefix in prefixes:
            raise PrefixExists('Prefix is already in use')

        success = self.bot.dbutil.add_prefix(server_id, prefix)
        if success:
            prefixes_list = self.prefixes(server_id)
            prefixes_list.append(prefix)
            prefixes.add(prefix)

        return success

    def remove_prefix(self, server_id, prefix):
        prefixes = self.prefixes(server_id, use_set=True)
        if prefix not in prefixes:
            raise PrefixDoesntExist("Prefix doesn't exist")

        if len(prefixes) == 1:
            raise NotEnoughPrefixes('Must have at least one prefix')

        success = self.bot.dbutil.remove_prefix(server_id, prefix)
        if success:
            prefixes.discard(prefix)
            try:
                self.prefixes(server_id).remove(prefix)
            except ValueError:
                pass

        return success

    # moderation
    def modlog(self, server_id):
        return self.get_settings(server_id).get('modlog', None)

    def set_modlog(self, server_id, channel_id):
        return self.set_value(server_id, 'modlog', channel_id)

    def mute_role(self, server_id):
        return self.get_settings(server_id).get('mute_role', None)

    def set_mute_role(self, server_id, role_id):
        return self.set_value(server_id, 'mute_role', role_id)

    def keeproles(self, server_id):
        if self.get_settings(server_id).get('keeproles', 0):
            return True
        else:
            return False

    def set_keeproles(self, server_id, value):
        return self.set_value(server_id, 'keeproles', value)

    # automod
    def automute(self, server_id):
        return self.get_settings(server_id).get('automute', False)

    def set_automute(self, server_id, on: bool):
        return self.set_value(server_id, 'automute', on)

    def automute_limit(self, server_id):
        return self.get_settings(server_id).get('automute_limit', 10)

    def set_automute_limit(self, server_id, limit: int):
        return self.set_value(server_id, 'automute_limit', limit)

    # join config
    def join_message(self, server_id, default_message=False):
        message = self.get_settings(server_id).get('on_join_message')
        if message is None and default_message:
            message = self.bot.config.join_message

        return message

    def set_join_message(self, server_id, message):
        return self.set_value(server_id, 'on_join_message', message)

    def join_channel(self, server_id):
        return self.get_settings(server_id).get('on_join_channel')

    def set_join_channel(self, server_id, channel):
        return self.set_value(server_id, 'on_join_channel', channel)

    # random color on join
    def random_color(self, server_id):
        return self.get_settings(server_id).get('color_on_join', False)

    def set_random_color(self, server_id, value):
        return self.set_value(server_id, 'color_on_join', value)

    # leave config
    def leave_message(self, server_id, default_message=False):
        message = self.get_settings(server_id).get('on_leave_message')
        if message is None and default_message:
            message = self.bot.config.leave_message

        return message

    def set_leave_message(self, server_id, message):
        return self.set_value(server_id, 'on_leave_message', message)

    def leave_channel(self, server_id):
        return self.get_settings(server_id).get('on_leave_channel')

    def set_leave_channel(self, server_id, channel):
        return self.set_value(server_id, 'on_leave_channel', channel)

    # On message edit
    def on_edit_message(self, server_id, default_message=False):
        message = self.get_settings(server_id).get('on_edit_message')
        if message is None and default_message:
            message = self.bot.config.edit_message

        return message

    def set_on_edit_message(self, server_id, message):
        return self.set_value(server_id, 'on_edit_message', message)

    def on_edit_channel(self, server_id):
        return self.get_settings(server_id).get('on_edit_channel')

    def set_on_edit_channel(self, server_id, channel):
        return self.set_value(server_id, 'on_edit_channel', channel)

    # On message delete
    def on_delete_message(self, server_id, default_message=False):
        message = self.get_settings(server_id).get('on_delete_message')
        if message is None and default_message:
            message = self.bot.config.delete_message

        return message

    def set_on_delete_message(self, server_id, message):
        return self.set_value(server_id, 'on_delete_message', message)

    def on_delete_channel(self, server_id):
        return self.get_settings(server_id).get('on_delete_channel')

    def set_on_delete_channel(self, server_id, channel):
        return self.set_value(server_id, 'on_delete_channel', channel)

    def get_settings(self, server_id):
        settings = self[server_id]
        if not settings:
            settings = {}
            self[server_id] = settings

        return settings

    def __getitem__(self, item):
        return self._servers.get(item, None)

    def __setitem__(self, key, value):
        self._servers[key] = value

    def __delitem__(self, key):
        try:
            del self._servers[key]
        except:
            pass
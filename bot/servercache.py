from sqlalchemy import text


class ServerCache:
    def __init__(self, bot):
        self._bot = bot
        self._servers = {}
        self._int2str = ['on_edit_channel', 'on_delete_channel', 'modlog', 'mute_role']

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

    def get_modlog(self, server_id):
        return self.get_settings(server_id).get('modlog', None)

    def set_value(self, server_id, name, value):
        sql = 'INSERT INTO `servers` (`server`, `{0}`) VALUES ({1}, :{0}) ON DUPLICATE KEY UPDATE {0}=:{0}'.format(name, server_id)
        session = self.bot.get_session
        session.execute(text(sql), params={name: value})
        session.commit()
        settings = self.get_settings(server_id)
        settings[name] = value

    def set_modlog(self, server_id, channel_id):
        self.set_value(server_id, 'modlog', channel_id)

    def set_mute_role(self, server_id, role_id):
        self.set_value(server_id, 'mute_role', role_id)

    def get_mute_role(self, server_id):
        return self.get_settings(server_id).get('mute_role', None)

    def set_keeproles(self, server_id, value):
        self.set_value(server_id, 'keeproles', value)

    def keeproles(self, server_id):
        if self.get_settings(server_id).get('keeproles', 0):
            return True
        else:
            return False

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
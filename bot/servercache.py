class ServerCache:
    def __init__(self, bot):
        self._bot = bot
        self._servers = {}

    @property
    def bot(self):
        return self._bot

    def update_cached_server(self, server_id, **values):
        settings = self.get_settings(server_id)
        for k, v in values.items():
            settings[k] = v

    def get_modlog(self, server_id):
        return self.get_settings(server_id).get('modlog', None)

    def set_modlog(self, server_id, channel):
        settings = self.get_settings(server_id)

        sql = 'INSERT INTO `servers` (`server`, `modlog`) VALUES ({0}, {1}) ON DUPLICATE KEY UPDATE modlog={1}'.format(server_id, channel)
        session = self.bot.get_session
        session.execute(sql)
        session.commit()
        settings['modlog'] = channel

    def get_settings(self, server_id):
        settings = self[server_id]
        print(server_id, settings)
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
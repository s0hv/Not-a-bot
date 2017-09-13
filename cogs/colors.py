from cogs.cog import Cog
import colormath


class Color:
    def __init__(self, role_id, name, value, lab_l, lab_a, lab_b, server_id):
        self.role_id = role_id
        self.name = name
        self.value = value
        self.lab = (lab_l, lab_a, lab_b)
        self.server_id = server_id

    def __str__(self):
        return self.name


class Colors(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._colors = {}

    def _cache_colors(self):
        session = self.bot.get_session
        sql = 'SELECT roles.server, colors.id, colors.value, colors.lab_l, colors.lab_a, colors.lab_b, colors.name FROM ' \
              'colors LEFT OUTER JOIN roles on roles.id=colors.id'

        rows = session.execute(sql).fetchall()
        for row in rows:
            if not self.bot.get_server(str(row['server'])):
                continue

            self.add_color(**row)

    def add_color(self, server, id, name, value, lab_l, lab_a, lab_b):
        try:
            server_id = str(int(server))
        except:
            server_id = server.id

        color = Color(id, value, name, lab_l, lab_a, lab_b, server_id)

        if server_id in self._colors:
            self._colors[server_id][id] = color
        else:
            self._colors[server_id] = {id: color}

        return color

    def get_color(self, name, server_id):
        return self._colors.get(server_id, {}).get(name)

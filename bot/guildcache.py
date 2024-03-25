from asyncpg.exceptions import PostgresError

from bot.exceptions import (NotEnoughPrefixes, PrefixExists,
                            PrefixDoesntExist)


class GuildCache:
    def __init__(self, bot):
        self._bot = bot
        self.guilds = {}

    @property
    def bot(self):
        return self._bot

    def update_cached_guild(self, guild_id, **values):
        """
        Updates a servers cached values. None values are ignored
        """
        settings = self.get_settings(guild_id)
        for k, v in values.items():
            if v is None:
                continue

            settings[k] = v

        # Reverse sort prefixes so some prefixes don't get overlooked
        # e.q. if you add a prefix a and then a prefix aa if the a prefix is
        # first in the list it will always get invoked when aa is used
        self._set_internal_value(guild_id, 'prefixes', sorted(list(self.prefixes(guild_id, use_set=True)), reverse=True))

    async def set_value(self, guild_id, name, value):
        # WARNING sql injection could happen if user input is allowed to the name var
        sql = 'INSERT INTO guilds (guild, {0}) VALUES ($1, $2) ON CONFLICT (guild) DO UPDATE SET {0}=$2'.format(name)
        try:
            await self.bot.dbutil.execute(sql, (guild_id, value))
            success = True
        except PostgresError:
            success = False
        settings = self.get_settings(guild_id)
        settings[name] = value
        return success

    # Used for setting cached values not present in the database or in a different form
    # e.g. cache a set as a list. Used only for prefixes as we need them stored in a
    # sorted list when checking for usable prefixes and a set when adding more
    # to the list
    def _set_internal_value(self, guild_id, name, value):
        settings = self.get_settings(guild_id)
        internals = settings.get('_internals')
        if internals is None:
            internals = {}
            settings['_internals'] = internals

        internals[name] = value

    def _get_internals(self, guild_id):
        settings = self.get_settings(guild_id)
        internals = settings.get('_internals')
        if internals is None:
            internals = {}
            settings['_internals'] = internals

        return internals

    # utils
    def prefixes(self, guild_id, use_set=False):
        if use_set:
            return self.get_settings(guild_id).get('prefixes', {*([self.bot.default_prefix] if isinstance(str, self.bot.default_prefix) else self.bot.default_prefix)})

        prefixes = self._get_internals(guild_id).get('prefixes')
        if prefixes is None:
            prefixes = list(self.get_settings(guild_id).get('prefixes', [self.bot.default_prefix] if isinstance(str, self.bot.default_prefix) else self.bot.default_prefix))
            self._set_internal_value(guild_id, 'prefixes', prefixes)

        return prefixes

    async def add_prefix(self, guild_id, prefix):
        settings = self.get_settings(guild_id)
        if 'prefixes' not in settings:
            prefixes = {self.bot.default_prefix}
            settings['prefixes'] = prefixes
        else:
            prefixes = self.prefixes(guild_id, use_set=True)

        if prefix in prefixes:
            raise PrefixExists('Prefix is already in use')

        success = await self.bot.dbutil.add_prefix(guild_id, prefix)
        if success:
            prefixes_list = self.prefixes(guild_id)
            prefixes_list.append(prefix)
            prefixes_list.sort(reverse=True)
            prefixes.add(prefix)

        return success

    async def remove_prefix(self, guild_id, prefix):
        prefixes = self.prefixes(guild_id, use_set=True)
        if prefix not in prefixes:
            raise PrefixDoesntExist("Prefix doesn't exist")

        if len(prefixes) == 1:
            raise NotEnoughPrefixes('Must have at least one prefix')

        success = await self.bot.dbutil.remove_prefix(guild_id, prefix)
        if success:
            prefixes.discard(prefix)
            try:
                self.prefixes(guild_id).remove(prefix)
            except ValueError:
                pass

        return success

    # moderation
    def modlog(self, guild_id):
        return self.get_settings(guild_id).get('modlog', None)

    async def set_modlog(self, guild_id, channel_id):
        return await self.set_value(guild_id, 'modlog', channel_id)

    def mute_role(self, guild_id):
        return self.get_settings(guild_id).get('mute_role', None)

    async def set_mute_role(self, guild_id, role_id):
        return await self.set_value(guild_id, 'mute_role', role_id)

    def log_unmutes(self, guild_id):
        return self.get_settings(guild_id).get('log_unmutes', False)

    async def set_log_unmutes(self, guild_id, boolean):
        return await self.set_value(guild_id, 'log_unmutes', boolean)

    def keeproles(self, guild_id):
        if self.get_settings(guild_id).get('keeproles', 0):
            return True
        else:
            return False

    async def set_keeproles(self, guild_id, value):
        return await self.set_value(guild_id, 'keeproles', value)

    # automod
    def automute(self, guild_id):
        return self.get_settings(guild_id).get('automute', False)

    async def set_automute(self, guild_id, on: bool):
        return await self.set_value(guild_id, 'automute', on)

    def automute_limit(self, guild_id):
        return self.get_settings(guild_id).get('automute_limit', 10)

    async def set_automute_limit(self, guild_id, limit: int):
        return await self.set_value(guild_id, 'automute_limit', limit)

    def automute_time(self, guild_id):
        return self.get_settings(guild_id).get('automute_time')

    async def set_automute_time(self, guild_id, time):
        return await self.set_value(guild_id, 'automute_time', time)

    # join config
    def join_message(self, guild_id, default_message=False):
        message = self.get_settings(guild_id).get('on_join_message')
        if message is None and default_message:
            message = self.bot.config.join_message

        return message

    async def set_join_message(self, guild_id, message):
        return await self.set_value(guild_id, 'on_join_message', message)

    def join_channel(self, guild_id):
        return self.get_settings(guild_id).get('on_join_channel')

    async def set_join_channel(self, guild_id, channel):
        return await self.set_value(guild_id, 'on_join_channel', channel)

    # random color on join
    def random_color(self, guild_id):
        return self.get_settings(guild_id).get('color_on_join', False)

    async def set_random_color(self, guild_id, value):
        return await self.set_value(guild_id, 'color_on_join', value)

    # leave config
    def leave_message(self, guild_id, default_message=False):
        message = self.get_settings(guild_id).get('on_leave_message')
        if message is None and default_message:
            message = self.bot.config.leave_message

        return message

    async def set_leave_message(self, guild_id, message):
        return await self.set_value(guild_id, 'on_leave_message', message)

    def leave_channel(self, guild_id):
        return self.get_settings(guild_id).get('on_leave_channel')

    async def set_leave_channel(self, guild_id, channel):
        return await self.set_value(guild_id, 'on_leave_channel', channel)

    # On message edit
    def on_edit_message(self, guild_id, default_message=False):
        message = self.get_settings(guild_id).get('on_edit_message')
        if message is None and default_message:
            message = self.bot.config.edit_message

        return message

    async def set_on_edit_message(self, guild_id, message):
        return await self.set_value(guild_id, 'on_edit_message', message)

    def on_edit_channel(self, guild_id):
        return self.get_settings(guild_id).get('on_edit_channel')

    async def set_on_edit_channel(self, guild_id, channel):
        return await self.set_value(guild_id, 'on_edit_channel', channel)

    def on_edit_embed(self, guild_id):
        return self.get_settings(guild_id).get('on_edit_embed')

    async def set_on_edit_embed(self, guild_id, boolean):
        return await self.set_value(guild_id, 'on_edit_embed', boolean)

    # On message delete
    def on_delete_message(self, guild_id, default_message=False):
        message = self.get_settings(guild_id).get('on_delete_message')
        if message is None and default_message:
            message = self.bot.config.delete_message

        return message

    async def set_on_delete_message(self, guild_id, message):
        return await self.set_value(guild_id, 'on_delete_message', message)

    def on_delete_channel(self, guild_id):
        return self.get_settings(guild_id).get('on_delete_channel')

    async def set_on_delete_channel(self, guild_id, channel):
        return await self.set_value(guild_id, 'on_delete_channel', channel)

    def on_delete_embed(self, guild_id):
        return self.get_settings(guild_id).get('on_delete_embed')

    async def set_on_delete_embed(self, guild_id, boolean):
        return await self.set_value(guild_id, 'on_delete_embed', boolean)

    def dailygachi(self, guild_id):
        return self.get_settings(guild_id).get('dailygachi')

    async def set_dailygachi(self, guild_id, channel):
        return await self.set_value(guild_id, 'dailygachi', channel)

    def get_settings(self, guild_id):
        settings = self[guild_id]
        if not settings:
            settings = {}
            self[guild_id] = settings

        return settings

    def __getitem__(self, item):
        return self.guilds.get(item, None)

    def __setitem__(self, key, value):
        self.guilds[key] = value

    def __delitem__(self, key):
        try:
            del self.guilds[key]
        except KeyError:
            pass

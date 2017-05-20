import json
import os
import re

from bot.bot import command


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

    @command(pass_context=True)
    async def leave_message(self, ctx, channel, message, mention=False):
        user = ctx.message.author
        channel_ = ctx.message.channel
        server = ctx.message.server
        if not user.permissions_in(channel_).manage_server:
            return await self.bot.say("You don't have manage server permissions")

        chn = self.get_channel(channel, server)
        if chn is None:
            return await self.bot.say('Could not get channel %s' % channel)

        if not isinstance(mention, bool):
            mention = False

        config = self.servers.get(server.id, {})
        config['leave'] = {'message': message, 'channel': chn.id, 'mention': mention}
        self.servers[server.id] = config
        self.save_json()
        await self.bot.say_timeout('Current leave message config {}'.format(self.servers[server.id]),
                                   chn, 120)

    @command(pass_context=True)
    async def join_message(self, ctx, channel, message, mention=False):
        return

    def save_json(self):
        def save():
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.servers, f, ensure_ascii=False)
                    return True
            except:
                return False

        for i in range(3):
            if save():
                return

    def get_config(self, server):
        return self.servers.get(server.id, None)

    def get_join(self, server):
        config = self.get_config(server)
        if config is None:
            return

        return config.get('join', None)
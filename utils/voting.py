from bot.bot import command
from utils.utilities import normalize_text
import os, json
import time


class VoteManager:
    def __init__(self, bot):
        self.bot = bot
        self.path = os.path.join(os.getcwd(), 'data', 'voteMessages.json')
        self.votes = {}
        if os.path.exists(self.path):
            with open(self.path) as f:
                self.votes = json.load(f)

    @command(pass_context=True, owner_only=True)
    async def vote(self, ctx, message, *, votes):
        # TODO Add permission check
        server = ctx.message.server
        msg = await self.bot.say(message)
        votes = normalize_text(votes).split(' ')
        success = 0
        for emote in votes:
            try:
                await self.bot.add_reaction(message, emote)
                success += 1
            except Exception as e:
                await self.bot.say('Error adding reaction\n%s' % e, timeout=20)

        if success == 0:
            try:
                self.bot.delete_message(msg)
            except:
                pass

            await self.bot.say('No reactions could be added to vote. Cancelling', timeout=60)
            return

    def on_vote(self, message, reaction, user):
        return

    def add_message(self, message):
        votes = self.get_vote_messages(message.server.id)
        votes[message.id] = time.time()

    def get_vote_messages(self, serverid):
        if serverid not in self.votes:
            self.votes[serverid] = {}

        return self.votes[serverid]

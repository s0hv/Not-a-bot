import json
import os
import time

from discord import User
import asyncio

from bot.bot import command


class Uservote:
    def __init__(self, user):
        self.user = user
        self._vote = None
        self.valid = True

    @property
    def vote(self):
        return self._vote

    @vote.setter
    def vote(self, emote):
        if self._vote is not None:
            self.valid = False

        self._vote = emote


class Vote:
    def __init__(self, message, duration=None):
        self.message = message
        self.duration = duration or 0
        self._created_at = time.time()

        if not isinstance(self.duration, int) or not isinstance(self.duration, float):
            raise ValueError('Duration must be int or float')

    @property
    def created_at(self):
        return self._created_at


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
        success = 0
        for emote in votes.split(' '):
            try:
                await self.bot.add_reaction(msg, emote.strip('<>'))
                success += 1
            except Exception as e:
                await self.bot.say('Error adding reaction%s\n%s' % (emote, e), delete_after=20)

        if success == 0:
            try:
                await self.bot.delete_message(msg)
            except:
                pass

            await self.bot.say('No reactions could be added to vote. Cancelling', delete_after=20)
            return

    async def get_most_voted(self, msg):
        users_voted = []
        votes = {}
        reactions = msg.reactions
        if not reactions:
            return

        for emote, users in reactions:
            votes_ = 0
            for user in list(users):
                if user not in users_voted:
                    users_voted.append(user)
                    votes_ += 1

            votes[emote] = votes_

        print(votes)
        emote = max(votes.keys(), key=lambda key: votes[key])
        return emote, votes[emote]

    def add_message(self, message):
        votes = self.get_vote_messages(message.server.id)
        votes[message.id] = time.time()

    def get_vote_messages(self, serverid):
        if serverid not in self.votes:
            self.votes[serverid] = {}

        return self.votes[serverid]


def setup(bot):
    bot.add_cog(VoteManager(bot))
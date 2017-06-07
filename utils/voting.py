import json
import os
import time

from discord import User

from bot.bot import command


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
        reactions = await self.get_reactions(msg)
        for emote, users in reactions.items():
            votes_ = 0
            for user in list(users):
                if user not in users_voted:
                    users_voted.append(user)
                    votes_ += 1

            votes[emote] = votes_

        print(votes)
        emote = max(votes.keys(), key=lambda key: votes[key])
        return emote, votes[emote]

    async def get_reactions(self, msg):
        token = self.bot.config.token
        client = self.bot.aiohttp_client
        url = 'https://discordapp.com/api/v6/channels/{0.channel.id}/messages/{0.id}'.format(msg) + '/reactions/{}?token=' + token
        reactions = msg.reactions

        reaction_users = {}
        for reaction in reactions:
            users = []
            emote = reaction.emoji
            if isinstance(emote, str):
                u = url.format(emote)
            else:
                u = url.format(':{0.name}:{0.id}'.format(emote))
            r = await client.get(u)
            j = await r.json()
            for user in j:
                users.append(User(**user))

            reaction_users[emote] = users

        return reaction_users

    def add_message(self, message):
        votes = self.get_vote_messages(message.server.id)
        votes[message.id] = time.time()

    def get_vote_messages(self, serverid):
        if serverid not in self.votes:
            self.votes[serverid] = {}

        return self.votes[serverid]

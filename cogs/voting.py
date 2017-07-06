import json
import os
import time
import argparse
from discord import User
import asyncio
import discord
from bot.bot import command
import sqlalchemy
from utils.utilities import get_emote_name_id


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
        self.session = self.bot.get_session
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('-title', nargs='+')
        self.parser.add_argument('-time', default=None)
        self.parser.add_argument('-emotes', default=None, nargs='+')
        self.parser.add_argument('-description', default=None, nargs='+')
        self.parser.add_argument('-strict', action='store_true')
        self.parser.add_argument('-no_duplicate_votes', action='store_true')

    @command(pass_context=True, owner_only=True)
    async def vote(self, ctx, *, message):
        # TODO Add permission check
        message = '-title '+ message if not message.startswith('-t') else message
        try:
            parsed = self.parser.parse_args(message.split(' '))
        except:
            return await self.bot.say('Failed to parse arguments')

        if parsed.strict and not parsed.emotes:
            return await self.bot.say('Cannot set strict mode without specifying any emotes')

        emotes = []
        failed = []
        if parsed.emotes:
            for emote in parsed.emotes:
                name = get_emote_name_id(emote)
                if name is None:
                    failed.append(emote)
                    continue

                emotes.append(name)

        if parsed.description:
            description = ' '.join(parsed.description)
        else:
            description = discord.Embed.Empty

        embed = discord.Embed(title=' '.join(parsed.title), description=description)
        if parsed.time:
            embed.add_field(name='Expires at', value=parsed.time)
        msg = await self.bot.send_message(ctx.message.channel, embed=embed)

        for emote in emotes:
            try:
                await self.bot.add_reaction(msg, '{}:{}'.format(*emote))
            except:
                failed.append(emote[0])
        if failed:
            await self.bot.say('Failed to get emotes `{}`'.format('` `'.join(failed)))

        sql = 'INSERT INTO `votes` (`server`, `strict`, `message`, `expires_in`, `ignore_dupes`) ' \
              'VALUES (:server, :strict, :message, :expires_in, :ignore_dupes)'
        d = {'server': ctx.message.server.id, 'strict': parsed.strict, 'message': msg.id, 'expires_in': parsed.time, 'ignore_dupes': parsed.no_duplicate_votes}
        self.session.execute(sql, params=d)

        if emotes:
            # TODO db name as variable
            sql = 'INSERT INTO `emotes` (`name`, `emote`, `server`, `vote_id`) VALUES '
            values = []
            for emote in emotes:
                name, id = emote
                values.append('("%s", %s, %s, %s)' % (name, id, ctx.message.server.id, msg.id))

            sql += ', '.join(values) + ' ON DUPLICATE KEY UPDATE name=name'
            result = self.session.execute(sql)

        self.session.commit()

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
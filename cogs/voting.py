import json
import os
import time
import argparse
from discord import User
import asyncio
import discord
from bot.bot import command
from datetime import datetime, timedelta
import re
import operator
from utils.utilities import get_emote_name_id, parse_time, datetime2sql, Object
import logging
from sqlalchemy import text


logger = logging.getLogger('debug')


class Poll:
    def __init__(self, bot, message, channel, title, expires_at=None, strict=False,
                 emotes=None, no_duplicate_votes=False, multiple_votes=False):
        """

        Args:
            bot:
            message: either `class`: discord.Message or int
            channel:
            title:
            expires_at:
            strict:
            emotes:
            no_duplicate_votes:
        """
        self._bot = bot
        self.message = message
        self.channel = str(channel)
        self.title = title
        self.expires_at = expires_at
        self.strict = strict
        self._emotes = emotes or []
        self.ignore_on_dupe = no_duplicate_votes
        self.multiple_votes = multiple_votes
        self._task = None

    @property
    def bot(self):
        return self._bot

    def add_emote(self, emote_id):
        # Used when recreating the poll
        self._emotes.append(emote_id)

    def start(self):
        self._task = self.bot.loop.create_task(self._wait())

    def stop(self):
        if self._task:
            try:
                self._task.cancel()
            except:
                pass

    async def _wait(self):
        time_ = self.expires_at - datetime.utcnow()
        time_ = time_.total_seconds()
        if time_ > 0:
            await asyncio.sleep(time_)

        await self.count_votes()

    async def count_votes(self):
        if isinstance(self.message, discord.Message):
            self.message = self.message.id

        self.message = str(self.message)
        try:
            chn = self.bot.get_channel(self.channel)
            msg = await self.bot.get_message(chn, self.message)
        except:
            logger.exception('Failed to end poll')
            channel = self.bot.get_channel(self.channel)
            return await self.bot.send_message(channel, 'Failed to end poll.\nReason: Could not get the poll message')

        votes = {}
        for reaction in msg.reactions:
            if self.strict:
                # Optimization LUL
                if isinstance(reaction.emoji, str):
                    if len(reaction.emoji) > 1:
                        continue

                id = ord(reaction.emoji) if isinstance(reaction.emoji, str) else reaction.emoji.id
                if id not in self._emotes:
                    continue

            users = await self.bot.get_reaction_users(reaction, limit=reaction.count)

            for user in users:
                if user.bot:
                    continue

                if self.ignore_on_dupe and user.id in votes:
                    votes[user.id] = None
                elif not self.multiple_votes:
                    votes[user.id] = [str(reaction.emoji)]
                else:
                    if user.id in votes:
                        votes[user.id] += (str(reaction.emoji), )
                    else:
                        votes[user.id] = [str(reaction.emoji)]

        scores = {}
        for u, reacts in votes.items():
            if reacts is None:
                continue

            for r in reacts:
                score = scores.get(r, 0)
                scores[r] = score + 1

        scores = sorted(scores.items(), key=operator.itemgetter(1))
        biggest = 0

        winners = []
        for emote, score in scores:
            if score > biggest:
                biggest = score
                winners = [emote]
            elif score == biggest:
                winners.append(emote)
            else:
                break

        if winners:
            end = '\nWinner(s) are {} with the score of {}'.format(' '.join(winners), biggest)
        else:
            end = ' with no winners'

        s = 'Poll ``{}`` ended{}'.format(self.title, end)
        await self.bot.send_message(chn, s)

        session = self.bot.get_session

        sql = 'DELETE FROM `polls` WHERE `message`= %s' % self.message
        try:
            session.execute(sql)
            session.commit()
        except:
            logger.exception('Could not delete poll')
            await self.bot.send_message(chn, 'Could not delete poll from database. The result might be recalculated')


class VoteManager:
    def __init__(self, bot):
        self.bot = bot
        self.session = self.bot.get_session
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('-header', nargs='+')
        self.parser.add_argument('-time', default='60s', nargs='+')
        self.parser.add_argument('-emotes', default=None, nargs='+')
        self.parser.add_argument('-description', default=None, nargs='+')
        self.parser.add_argument('-strict', action='store_true')
        self.parser.add_argument('-no_duplicate_votes', action='store_true')
        self.parser.add_argument('-allow_multiple_entries', action='store_true')

    @command(pass_context=True, owner_only=True, aliases=['vote'])
    async def poll(self, ctx, *, message):
        """
        Create a poll. See help poll for arguments
        Creates a poll that expires by default in 60 seconds
        Examples of use: -poll title -d description -e <:gappyGoodShit:326946656023085056> 👌 -a
        available arguments
        `-d` `-description` Description for the poll
        `-t` `-time` Time after which the poll is expired. Maximum time is 1 week
        `-e` `-emotes` Optional emotes that are automatically added to the poll

        These options require no arguments. Default values that are used when they aren't specified are marked in square brackets []
        `-s` `-strict` [false] Only count emotes specified in the -emotes argument
        `-n` `-no_duplicate_votes` [false] Ignores users who react to more than one emote
        `-a` `-allow_multiple_entries` [false] Count all reactions from the user. Even if that user reacted with multiple emotes.
        """
        # TODO Add permission check

        # Add -header if it's not present so argparser can recognise the argument
        message = '-header ' + message if not message.startswith('-t') else message
        try:
            parsed = self.parser.parse_args(message.split(' '))
        except:
            return await self.bot.say('Failed to parse arguments')

        if parsed.strict and not parsed.emotes:
            return await self.bot.say('Cannot set strict mode without specifying any emotes')

        if parsed.no_duplicate_votes and parsed.allow_multiple_entries:
            return await self.bot.say('Cannot have -n and -a specified at the same time. That would be dumb')

        expired_date = None
        title = ' '.join(parsed.header)
        if parsed.time:
            expires_in = parse_time(' '.join(parsed.time))
            if expires_in.total_seconds() == 0:
                await self.bot.say('No time specified or time given is 0 seconds. Using default value of 60s')
                expires_in = timedelta(seconds=60)
            if expires_in.days > 7:
                return await self.bot.say('Maximum time is 7 days')

            now = datetime.utcnow()
            expired_date = now + expires_in
            sql_date = datetime2sql(expired_date)
            parsed.time = sql_date

        emotes = []
        failed = []
        if parsed.emotes:
            for emote in parsed.emotes:
                if not emote.strip():
                    continue

                name = get_emote_name_id(emote)
                if name is None:
                    emotes.append(emote)
                else:
                    # TODO Better check for flag emotes
                    if len(name) > 1:
                        continue
                    emotes.append(name)

        if parsed.description:
            description = ' '.join(parsed.description)
        else:
            description = discord.Embed.Empty

        embed = discord.Embed(title=title, description=description)
        if parsed.time:
            embed.add_field(name='Expires at',
                            value='{}\nor in {}\nCurrent time {}'.format(parsed.time, str(expires_in), datetime.utcnow().ctime()))
        msg = await self.bot.send_message(ctx.message.channel, embed=embed)

        # add reactions to message
        for emote in emotes:
            try:
                emote = '{}:{}'.format(*emote) if isinstance(emote, tuple) else emote
                await self.bot.add_reaction(msg, emote)
            except:
                failed.append(emote)
        if failed:
            await self.bot.say('Failed to get emotes `{}`'.format('` `'.join(failed)),
                               delete_after=60)

        sql = 'INSERT INTO `polls` (`server`, `title`, `strict`, `message`, `channel`, `expires_in`, `ignore_on_dupe`, `multiple_votes`) ' \
              'VALUES (:server, :title, :strict, :message, :channel, :expires_in, :ignore_on_dupe, :multiple_votes)'
        d = {'server': ctx.message.server.id, 'title': title,
             'strict': parsed.strict, 'message': msg.id, 'channel': ctx.message.channel.id,
             'expires_in': parsed.time, 'ignore_on_dupe': parsed.no_duplicate_votes,
             'multiple_votes':parsed.allow_multiple_entries}
        try:
            self.session.execute(text(sql), params=d)

            emotes_list = []
            if emotes:
                sql = 'INSERT INTO `emotes` (`name`, `emote`, `server`) VALUES '
                values = []
                # We add all successfully parsed emotes even if the bot failed to
                # add them so strict mode will count them in too
                for emote in emotes:
                    if not isinstance(emote, tuple):
                        name, id = emote, ord(emote)
                        emotes_list.append(id)
                        server = 'NULL'
                    else:
                        name, id = emote
                        emotes_list.append(id)
                        server = ctx.message.server.id

                    values.append('("%s", %s, %s)' % (name, id, server))

                # If emote is already in the table update its name
                sql += ', '.join(values) + ' ON DUPLICATE KEY UPDATE name=name'
                self.session.execute(text(sql))

                sql = 'INSERT IGNORE INTO `pollEmotes` (`poll_id`, `emote_id`) VALUES '
                values = []
                for id in emotes_list:
                    values.append('(%s, %s)' % (msg.id, id))

                sql += ', '.join(values)
                self.session.execute(text(sql))

            self.session.commit()
        except:
            logger.exception('Failed sql query')
            return await self.bot.say('Failed to save poll. Exception has been logged')

        poll = Poll(self.bot, msg.id, msg.channel.id, title, expires_at=expired_date, strict=parsed.strict,
                    emotes=emotes_list, no_duplicate_votes=parsed.no_duplicate_votes,
                    multiple_votes=parsed.allow_multiple_entries)
        poll.start()

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
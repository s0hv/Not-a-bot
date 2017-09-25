import argparse
import asyncio
import logging
import operator
from datetime import datetime, timedelta

import discord
from sqlalchemy import text

from bot.bot import command
from utils.utilities import (get_emote_name_id, parse_time, datetime2sql,
                             get_avatar)

logger = logging.getLogger('debug')


class Poll:
    def __init__(self, bot, message, channel, title, expires_at=None,
                 strict=False, emotes=None, no_duplicate_votes=False,
                 multiple_votes=False, max_winners=1, after=None):
        """
        Args:
            message: either `class`: discord.Message or int
            others explained in VoteManager
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
        self.max_winners = max_winners
        self._task = None
        self._stopper = asyncio.Event()
        self._after = after

    @property
    def bot(self):
        return self._bot

    def add_emote(self, emote_id):
        # Used when recreating the poll
        self._emotes.append(emote_id)

    def start(self):
        self._stopper.clear()
        self._task = self.bot.loop.create_task(self._wait())
        if callable(self._after):
            self._task.add_done_callback(self._after)

    def stop(self):
        if self._task:
            try:
                self._task.cancel()
            except:
                pass

    def count_now(self):
        self._stopper.set()

    async def _wait(self):
        try:
            time_ = self.expires_at - datetime.utcnow()
            time_ = time_.total_seconds()
            if time_ > 0:
                await asyncio.wait_for(self._stopper.wait(), timeout=time_, loop=self.bot.loop)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            return

        await self.count_votes()

    async def count_votes(self):
        if isinstance(self.message, discord.Message):
            self.message = self.message.id

        session = self.bot.get_session
        self.message = str(self.message)
        try:
            chn = self.bot.get_channel(self.channel)
            msg = await self.bot.get_message(chn, self.message)
            chn = self.bot.get_channel('252872751319089153')
        except:
            logger.exception('Failed to end poll')
            channel = self.bot.get_channel(self.channel)
            sql = 'DELETE FROM `polls` WHERE `message`= %s' % self.message
            try:
                session.execute(sql)
                session.commit()
            except:
                logger.exception('Could not delete poll')
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

        scores = sorted(scores.items(), key=operator.itemgetter(1),  reverse=True)
        if scores:
            current_winners = []
            winners = 0
            current_score = -1
            end = '\nWinner(s) are '
            for emote, score in scores:
                if score > current_score:
                    current_score = score
                    current_winners.append(emote)
                elif score == current_score:
                    current_winners.append(emote)
                elif self.max_winners > winners and current_score >= score:
                    if current_score > score:
                        end += '{} with the score of {} '.format(' '.join(current_winners), current_score)
                        current_winners = []
                        current_score = score

                    current_winners.append(emote)
                else:
                    break

                winners += 1

            end += '{} with the score of {}'.format(' '.join(current_winners), current_score)
        else:
            end = ' with no winners'

        s = 'Poll ``{}`` ended{}'.format(self.title, end)
        await self.bot.send_message(chn, s)

        sql = 'DELETE FROM `polls` WHERE `message`= %s' % self.message
        try:
            session.execute(sql)
            session.commit()
        except:
            logger.exception('Could not delete poll')
            await self.bot.send_message(chn, 'Could not delete poll from database. The poll result might be recalculated')


class VoteManager:
    def __init__(self, bot):
        self.bot = bot
        self.session = self.bot.get_session
        self.polls = self.bot.polls
        self.load_polls()
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('-header', nargs='+')
        self.parser.add_argument('-time', default='60s', nargs='+')
        self.parser.add_argument('-emotes', default=None, nargs='+')
        self.parser.add_argument('-description', default=None, nargs='+')
        self.parser.add_argument('-max_winners', default=1, type=int)
        self.parser.add_argument('-strict', action='store_true')
        self.parser.add_argument('-no_duplicate_votes', action='store_true')
        self.parser.add_argument('-allow_multiple_entries', action='store_true')

    def load_polls(self):
        session = self.session
        sql = 'SELECT polls.title, polls.message, polls.channel, polls.expires_in, polls.ignore_on_dupe, polls.multiple_votes, polls.strict, emotes.emote FROM polls LEFT OUTER JOIN pollEmotes ON polls.message = pollEmotes.poll_id LEFT OUTER JOIN emotes ON emotes.emote = pollEmotes.emote_id'
        poll_rows = session.execute(sql)
        polls = {}
        for row in poll_rows:
            poll = polls.get(row['message'], Poll(self.bot, row['message'], row['channel'], row['title'],
                                                  expires_at=row['expires_in'],
                                                  strict=row['strict'],
                                                  no_duplicate_votes=row['ignore_on_dupe'],
                                                  multiple_votes=row['multiple_votes'],
                                                  after=lambda f: self.polls.pop(row['message'], None)))

            r = self.polls.get(row['message'])
            if r:
                r.stop()

            polls[row['message']] = poll
            poll.add_emote(row['emote'])

        for poll in polls.values():
            self.polls[int(poll.message)] = poll
            poll.start()

    @command(owner_only=True, pass_context=True)
    async def recalculate(self, ctx, msg_id, channel_id, *, message):
        # Add -header if it's not present so argparser can recognise the argument
        message = '-header ' + message if not message.startswith('-h') else message
        try:
            parsed = self.parser.parse_args(message.split(' '))
        except:
            return await self.bot.say('Failed to parse arguments')

        if parsed.strict and not parsed.emotes:
            return await self.bot.say('Cannot set strict mode without specifying any emotes')

        if parsed.no_duplicate_votes and parsed.allow_multiple_entries:
            return await self.bot.say('Cannot have -n and -a specified at the same time. That would be dumb')

        if parsed.max_winners < 1:
            return await self.bot.say('Max winners needs to be an integer bigger than 0')

        parsed.max_winners = min(parsed.max_winners, 20)

        title = ' '.join(parsed.header)
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
                    # TODO Better check for flag emotes
                    if len(emote) > 1:
                        continue
                    emotes.append(emote)
                else:
                    emotes.append(name)

        if parsed.description:
            description = ' '.join(parsed.description)
        else:
            description = discord.Embed.Empty

        embed = discord.Embed(title=title, description=description, timestamp=expired_date)
        if parsed.time:
            embed.add_field(name='Valid for',
                            value='%s' % str(expires_in))
        embed.set_footer(text='Expires at', icon_url=get_avatar(ctx.message.author))

        options = ''
        if parsed.strict:
            options += 'Strict mode on. Only specified emotes are counted\n'

        if parsed.no_duplicate_votes:
            options += 'Voting for more than one valid option will invalidate your vote\n'
        elif not parsed.allow_multiple_entries:
            options += 'If user votes multiple times only 1 reaction is counted'

        if parsed.allow_multiple_entries:
            options += 'All all valid votes are counted from a user\n'

        if parsed.max_winners > 1:
            options += 'Max amount of winners %s (might be more in case of a tie)' % parsed.max_winners

        if options:
            embed.add_field(name='Modifiers', value=options)

        emotes_list = []
        for emote in emotes:
            if not isinstance(emote, tuple):
                id = ord(emote)
                emotes_list.append(id)
            else:
                name, id = emote
                emotes_list.append(id)

        poll = Poll(self.bot, msg_id, channel_id, title, expires_at=expired_date, strict=parsed.strict,
                    emotes=emotes_list, no_duplicate_votes=parsed.no_duplicate_votes,
                    multiple_votes=parsed.allow_multiple_entries, max_winners=parsed.max_winners)

        await poll.count_votes()

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
        `-m` `-max_winners` [1] Maximum amount of winners. It might be more in case of a draw
        `-s` `-strict` [false] Only count emotes specified in the -emotes argument
        `-n` `-no_duplicate_votes` [false] Ignores users who react to more than one emote
        `-a` `-allow_multiple_entries` [false] Count all reactions from the user. Even if that user reacted with multiple emotes.
        """
        # TODO Add permission check

        # Add -header if it's not present so argparser can recognise the argument
        message = '-header ' + message if not message.startswith('-h') else message
        try:
            parsed = self.parser.parse_args(message.split(' '))
        except:
            return await self.bot.say('Failed to parse arguments')

        if parsed.strict and not parsed.emotes:
            return await self.bot.say('Cannot set strict mode without specifying any emotes')

        if parsed.no_duplicate_votes and parsed.allow_multiple_entries:
            return await self.bot.say('Cannot have -n and -a specified at the same time. That would be dumb')

        if parsed.max_winners < 1:
            return await self.bot.say('Max winners needs to be an integer bigger than 0')

        parsed.max_winners = min(parsed.max_winners, 20)

        title = ' '.join(parsed.header)
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
                    # TODO Better check for flag emotes
                    if len(emote) > 1:
                        continue
                    emotes.append(emote)
                else:
                    emotes.append(name)

        if parsed.description:
            description = ' '.join(parsed.description)
        else:
            description = discord.Embed.Empty

        embed = discord.Embed(title=title, description=description, timestamp=expired_date)
        if parsed.time:
            embed.add_field(name='Valid for',
                            value='%s' % str(expires_in))
        embed.set_footer(text='Expires at', icon_url=get_avatar(ctx.message.author))

        options = ''
        if parsed.strict:
            options += 'Strict mode on. Only specified emotes are counted\n'

        if parsed.no_duplicate_votes:
            options += 'Voting for more than one valid option will invalidate your vote\n'
        elif not parsed.allow_multiple_entries:
            options += 'If user votes multiple times only 1 reaction is counted'

        if parsed.allow_multiple_entries:
            options += 'All all valid votes are counted from a user\n'

        if parsed.max_winners > 1:
            options += 'Max amount of winners %s (might be more in case of a tie)' % parsed.max_winners

        if options:
            embed.add_field(name='Modifiers', value=options)

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

        sql = 'INSERT INTO `polls` (`server`, `title`, `strict`, `message`, `channel`, `expires_in`, `ignore_on_dupe`, `multiple_votes`, `max_winners`) ' \
              'VALUES (:server, :title, :strict, :message, :channel, :expires_in, :ignore_on_dupe, :multiple_votes, :max_winners)'
        d = {'server': ctx.message.server.id, 'title': title,
             'strict': parsed.strict, 'message': msg.id, 'channel': ctx.message.channel.id,
             'expires_in': parsed.time, 'ignore_on_dupe': parsed.no_duplicate_votes,
             'multiple_votes': parsed.allow_multiple_entries, 'max_winners': parsed.max_winners}
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
                    multiple_votes=parsed.allow_multiple_entries, max_winners=parsed.max_winners,
                    after=lambda f: self.polls.pop(msg.id, None))
        poll.start()
        self.polls[int(msg.id)] = poll


def setup(bot):
    bot.add_cog(VoteManager(bot))

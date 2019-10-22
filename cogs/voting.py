import argparse
import asyncio
import logging
import operator
import re
from datetime import datetime

import discord
import numpy
from asyncpg.exceptions import PostgresError
from discord.ext.commands import BucketType

from bot.bot import command, has_permissions, cooldown, bot_has_permissions
from bot.formatter import EmbedLimits
from cogs.cog import Cog
from utils.utilities import (get_emote_name_id, parse_time, get_avatar)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


def parse_emote(emote, only_id=False):
    if not emote.strip():
        return

    animated, name, emote_id = get_emote_name_id(emote)
    if name is None:
        if len(emote) > 2:
            # If length is more than 2 it's most likely not an unicode char
            return

        return emote

    if only_id:
        return int(emote_id)

    elif animated:
        return 'a:', name, emote_id
    else:
        return '', name, emote_id


class ProxyArgs:
    def __init__(self, strict=False, emotes=None, no_duplicate_votes=False,
                 multiple_votes=False, max_winners=1, giveaway: bool=False):

        self.strict = strict
        self.emotes = emotes or []
        self.ignore_on_dupe = no_duplicate_votes
        self.multiple_votes = multiple_votes
        self.max_winners = max_winners
        self.giveaway = giveaway

    def parse_giveaway(self, s):
        if not s.startswith('-g'):
            return

        self.giveaway = True
        match = re.findall('React with (.+?) to participate', s)
        if not match:
            self.emotes = ['🎉']
            return

        emote = parse_emote(match[0], True)
        self.emotes = [emote or '🎉']

    def parse_strict(self, s):
        if not s.startswith('-s'):
            return

        self.strict = True
        if self.emotes:
            return

        for emote in s[54:].split(' '):
            emote = parse_emote(emote, True)
            if emote:
                self.emotes.append(emote)

    def parse_winners(self, s):
        match = re.findall(r'of winners (\d+) \(might be', s)
        if match:
            self.max_winners = int(match[0])

    def sanity_check(self):
        if not self.giveaway:
            if self.strict and not self.emotes:
                raise ValueError('Strict mode without emotes')

            if self.ignore_on_dupe and self.multiple_votes:
                raise ValueError('No multiple votes and allow multiple votes on at the same time')

        if self.max_winners < 1:
            raise ValueError('Max winners less than 1')

        if self.max_winners > 30:
            raise ValueError('Maximum amount of winners is 30')

    def __dict__(self):
        return {'strict': self.strict, 'emotes': self.emotes,
                'no_duplicate_votes': self.ignore_on_dupe,
                'multiple_votes': self.multiple_votes,
                'max_winners': self.max_winners,
                'giveaway': self.giveaway}


class Poll:
    def __init__(self, bot, message, channel, title, expires_at=None,
                 strict=False, emotes=None, no_duplicate_votes=False,
                 multiple_votes=False, max_winners=1, after=None,
                 giveaway: bool=False):
        """
        Args:
            message: either `class`: discord.Message or int
            others explained in VoteManager
        """
        self._bot = bot
        self.message = message
        self.channel = channel
        self.title = title
        self.expires_at = expires_at
        self.strict = strict
        self._emotes = emotes or []
        self.ignore_on_dupe = no_duplicate_votes
        self.multiple_votes = multiple_votes
        self.max_winners = max_winners
        self.giveaway = giveaway
        self._task = None
        self._stopper = asyncio.Event(loop=self.bot.loop)
        self._after = after

    @property
    def bot(self):
        return self._bot

    def add_emote(self, emote_id):
        # Used when recreating the poll
        self._emotes.append(emote_id)

    def start(self):
        self._stopper.clear()
        self._task = asyncio.run_coroutine_threadsafe(self._wait(), loop=self.bot.loop)
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
            if self.expires_at is not None:
                time_ = self.expires_at - datetime.utcnow()
                time_ = time_.total_seconds()
                if time_ > 0:
                    await asyncio.wait_for(self._stopper.wait(), timeout=time_, loop=self.bot.loop)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            return

        try:
            await self.count_votes()
        except:
            logger.exception('Failed to count votes')

    async def count_votes(self):
        if isinstance(self.message, discord.Message):
            self.message = self.message.id

        try:
            chn = self.bot.get_channel(self.channel)
            if chn is None:
                return

            msg = await chn.fetch_message(self.message)
        except discord.DiscordException:
            logger.exception('Failed to end poll')
            channel = self.bot.get_channel(self.channel)
            sql = 'DELETE FROM polls WHERE message=%s' % self.message
            try:
                await self.bot.dbutil.execute(sql)
            except PostgresError:
                logger.exception('Could not delete poll')
            return await channel.send('Failed to end poll.\nReason: Could not get the poll message')

        votes = {}
        for reaction in msg.reactions:
            if self.strict:
                id = reaction.emoji if isinstance(reaction.emoji, str) else str(reaction.emoji.id)
                if id not in self._emotes:
                    continue

            async for user in reaction.users(limit=reaction.count):
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

        if self.giveaway:
            users = list(votes.keys())
            if not users:
                s = f'No winners for {self.title} `{self.message}`'
                winners = 'None'
            else:
                self.max_winners = min(len(users), self.max_winners)
                winners = numpy.random.choice(users, self.max_winners, False)
                winners = ', '.join(map(lambda u: f'<@{u}>', winners))
                s = f'Winners of {self.title} `{self.message}` are\n{winners}'

            if msg.author.id == self.bot.user.id:
                try:
                    embed = msg.embeds[0]
                    field = None
                    for idx, f in enumerate(embed.fields):
                        if f.name == 'Winners':
                            field = True
                            embed.set_field_at(idx, name='Winners', value=winners)
                            break

                    if not field:
                        embed.add_field(name='Winners', value=winners)

                    await msg.edit(embed=embed)
                except discord.HTTPException:
                    pass

        else:

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

        try:
            await chn.send(s)
        except discord.HTTPException:
            pass

        sql = 'DELETE FROM polls WHERE message= %s' % self.message
        try:
            await self.bot.dbutil.execute(sql)
        except PostgresError:
            logger.exception('Could not delete poll')
            await chn.send('Could not delete poll from database. The poll result might be recalculated')


class VoteManager(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.polls = self.bot.polls
        asyncio.run_coroutine_threadsafe(self.load_polls(), self.bot.loop)
        self.parser = argparse.ArgumentParser()
        self.parser.add_argument('-header', nargs='+')
        self.parser.add_argument('-time', default='60s', nargs='+')
        self.parser.add_argument('-emotes', default=None, nargs='+')
        self.parser.add_argument('-description', default=None, nargs='+')
        self.parser.add_argument('-max_winners', default=1, type=int)
        self.parser.add_argument('-strict', action='store_true')
        self.parser.add_argument('-no_duplicate_votes', action='store_true')
        self.parser.add_argument('-allow_multiple_entries', action='store_true')
        self.parser.add_argument('-giveaway', action='store_true')

    def __unload(self):
        for poll in list(self.polls.values()):
            poll.stop()

    async def load_polls(self):
        sql = 'SELECT polls.title, polls.message, polls.channel, polls.expires_in, polls.ignore_on_dupe, polls.multiple_votes, polls.strict, polls.max_winners, polls.giveaway, emotes.emote ' \
              'FROM polls LEFT OUTER JOIN pollemotes pe ON polls.message = pe.poll_id LEFT OUTER JOIN emotes ON emotes.emote = pe.emote_id'
        poll_rows = await self.bot.dbutil.fetch(sql)
        polls = {}
        for row in poll_rows:
            poll = polls.get(row['message'], Poll(self.bot, row['message'], row['channel'], row['title'],
                                                  expires_at=row['expires_in'],
                                                  strict=row['strict'],
                                                  no_duplicate_votes=row['ignore_on_dupe'],
                                                  multiple_votes=row['multiple_votes'],
                                                  max_winners=row['max_winners'] or 1,
                                                  after=lambda f: self.polls.pop(row['message'], None),
                                                  giveaway=row['giveaway']))

            r = self.polls.get(row['message'])
            if r:
                r.stop()

            polls[row['message']] = poll
            poll.add_emote(row['emote'])

        for poll in polls.values():
            self.polls[poll.message] = poll
            poll.start()

    @command(owner_only=True)
    async def recalculate(self, ctx, msg_id: int, channel_id: int, *, message):
        """Recalculate a poll result"""
        # Add -header if it's not present so argparser can recognise the argument
        message = '-header ' + message if not message.startswith('-h') else message
        try:
            parsed = self.parser.parse_args(message.split(' '))
        except:
            return await ctx.send('Failed to parse arguments')

        if parsed.strict and not parsed.emotes:
            return await ctx.send('Cannot set strict mode without specifying any emotes')

        if parsed.no_duplicate_votes and parsed.allow_multiple_entries:
            return await ctx.send('Cannot have -n and -a specified at the same time. That would be dumb')

        if parsed.max_winners < 1:
            return await ctx.send('Max winners needs to be an integer bigger than 0')

        parsed.max_winners = min(parsed.max_winners, 20)

        title = ' '.join(parsed.header)

        emotes = []
        if parsed.emotes:
            for emote in parsed.emotes:
                if not emote.strip():
                    continue

                animated, name, emote_id = get_emote_name_id(emote)
                if name is None:
                    if len(emote) > 2:
                        # If length is more than 2 it's most likely not an unicode char
                        continue

                    emotes.append(emote)
                else:
                    emotes.append((name, emote_id))

        emotes_list = []
        for emote in emotes:
            if not isinstance(emote, tuple):
                emotes_list.append(emote)
            else:
                name, id = emote
                emotes_list.append(id)

        poll = Poll(self.bot, msg_id, channel_id, title, strict=parsed.strict,
                    emotes=emotes_list, no_duplicate_votes=parsed.no_duplicate_votes,
                    multiple_votes=parsed.allow_multiple_entries, max_winners=parsed.max_winners)

        await poll.count_votes()

    @command(no_pm=True)
    @has_permissions(manage_messages=True, manage_guild=True)
    @cooldown(1, 5, BucketType.guild)
    async def reroll(self, ctx, message_id: int):
        """
        Reroll a poll or giveaway based on the message_id. Message doesn't have
        to be from this bot as long as the format is the same
        """

        try:
            msg = await ctx.channel.fetch_message(message_id)
        except discord.HTTPException:
            return await ctx.send('Message not found')

        if not msg.embeds:
            return await ctx.send('Embed not found')

        embed = None
        for e in msg.embeds:
            if isinstance(e, discord.Embed):
                embed = e
                break

        if not embed:
            return await ctx.send('Embed not found')

        title = embed.title if isinstance(embed.title, str) else 'No title'
        modifiers = None

        for field in embed.fields:
            if field.name == 'Modifiers':
                modifiers = field.value
                break

        if not modifiers:
            await ctx.send('Modifiers field not found')

        modifiers = modifiers.split('\n')
        args = ProxyArgs()

        for mod in modifiers:
            if mod.startswith('-s '):
                args.parse_strict(mod)

            elif mod.startswith('-n '):
                args.ignore_on_dupe = True

            elif mod.startswith('-a '):
                args.multiple_votes = True

            elif mod.startswith('-m '):
                args.parse_winners(mod)

            elif mod.startswith('-g '):
                args.parse_giveaway(mod)

        try:
            args.sanity_check()
        except ValueError as e:
            return await ctx.send(f'Sanity check failed\n{e}')

        poll = Poll(self.bot, msg.id, ctx.channel.id, title, **args.__dict__())
        poll.start()

    @command(no_pm=True)
    @bot_has_permissions(embed_links=True)
    @has_permissions(manage_messages=True, manage_guild=True)
    @cooldown(1, 20, BucketType.guild)
    async def poll(self, ctx, *, message):
        """
        Creates a poll that expires by default in 60 seconds
        Examples of use: {prefix}{name} title -d description -e <:GWjojoGappyGoodShit:364223863888019468> 👌 -a
        available arguments
        `-d` `-description` Description for the poll
        `-t` `-time` Time after which the poll is expired. Maximum time is 1 week
        `-e` `-emotes` Optional emotes that are automatically added to the poll

        These options require no arguments. Default values that are used when they aren't specified are marked in square brackets []
        `-g` `-giveaway` Activates giveaway mode. In this mode max one emote can be specified
        and winners are randomly selected when the poll ends. Available arguments with this are -d, -t, -e and -m
        `-m` `-max_winners` [1] Maximum amount of winners. It might be more in case of a draw
        `-s` `-strict` [false] Only count emotes specified in the -emotes argument
        `-n` `-no_duplicate_votes` [false] Ignores users who react to more than one emote
        `-a` `-allow_multiple_entries` [false] Count all reactions from the user. Even if that user reacted with multiple emotes.
        """

        # Add -header if it's not present so argparser can recognise the argument
        message = '-header ' + message if not message.startswith('-h') else message
        try:
            parsed = self.parser.parse_args(message.split(' '))
        except:
            return await ctx.send('Failed to parse arguments')

        if not parsed.giveaway:
            if parsed.strict and not parsed.emotes:
                return await ctx.send('Cannot set strict mode without specifying any emotes')

            if parsed.no_duplicate_votes and parsed.allow_multiple_entries:
                return await ctx.send('Cannot have -n and -a specified at the same time. That would be dumb')

        if parsed.max_winners < 1:
            return await ctx.send(
                'Max winners needs to be an integer bigger than 0')

        if parsed.max_winners > 30:
            return await ctx.send('Max winners cannot be bigger than 20')

        title = ' '.join(parsed.header)
        if len(title) > EmbedLimits.Title:
            await ctx.send(f'Max characters allowed for title is {EmbedLimits.Title}')
            return

        expires_in = parse_time(' '.join(parsed.time))
        if expires_in.total_seconds() == 0:
            await ctx.send('No time specified or time given is 0 seconds')
            return
        if expires_in.days > 14:
            return await ctx.send('Maximum time is 14 days')

        now = datetime.utcnow()
        expired_date = now + expires_in
        sql_date = expired_date
        parsed.time = sql_date

        emotes = []
        emote = ''  # Used with giveaways
        failed = []
        if parsed.emotes:
            for emote in parsed.emotes:
                emote = parse_emote(emote)
                if emote:
                    emotes.append(emote)

        if parsed.giveaway:
            if not emotes:
                emote = '🎉'
                emotes = [emote]
            else:
                emote = emotes[0]
                emotes = [emote]
                emote = '<{}{}:{}>'.format(*emote) if isinstance(emote, tuple) else emote

        if parsed.description:
            description = ' '.join(parsed.description)
        else:
            description = discord.Embed.Empty

        embed = discord.Embed(title=title, description=description, timestamp=expired_date)
        if parsed.time:
            embed.add_field(name='Valid for',
                            value='%s' % str(expires_in))
        embed.set_footer(text='Expires at', icon_url=get_avatar(ctx.author))

        options = ''
        if parsed.giveaway:
            options += f'-g Giveaway mode. React with {emote} to participate\n'
        else:
            if parsed.strict:
                fmt_emotes = ['<{}:{}:{}>'.format(*emote) if isinstance(emote, tuple) else emote for emote in emotes]
                options += f'-s Strict mode on. Only specified emotes are counted. {" ".join(fmt_emotes)}\n'

            if parsed.no_duplicate_votes:
                options += '-n Voting for more than one valid option will invalidate your vote\n'
            elif not parsed.allow_multiple_entries:
                options += 'If user votes multiple times only 1 reaction is counted'

            if parsed.allow_multiple_entries:
                options += '-a All all valid votes are counted from a user\n'

        if parsed.max_winners > 1:
            options += '-m Max amount of winners %s (might be more in case of a tie)' % parsed.max_winners

        if options:
            embed.add_field(name='Modifiers', value=options)

        msg = await ctx.send(embed=embed)

        # add reactions to message
        for emote in emotes:
            try:
                emote = '{}{}:{}'.format(*emote) if isinstance(emote, tuple) else emote
                await msg.add_reaction(emote)
            except discord.DiscordException:
                failed.append(emote)
        if failed:
            await ctx.send('Failed to get emotes `{}`'.format('` `'.join(failed)),
                           delete_after=60)

        async with self.bot.pool.acquire() as conn:
            tr = conn.transaction()
            await tr.start()
            sql = 'INSERT INTO polls (guild, title, strict, message, channel, expires_in, ignore_on_dupe, multiple_votes, max_winners, giveaway) ' \
                  'VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)'
            d = (
                ctx.guild.id,
                title,
                parsed.strict,
                msg.id,
                ctx.channel.id,
                parsed.time,
                parsed.no_duplicate_votes,
                parsed.allow_multiple_entries,
                parsed.max_winners,
                parsed.giveaway
            )

            try:
                await conn.execute(sql, *d)

                emotes_list = []
                if emotes:
                    sql = 'INSERT INTO emotes (name, emote, guild) VALUES ($1, $2, $3) '
                    values = []
                    # We add all successfully parsed emotes even if the bot failed to
                    # add them so strict mode will count them in too
                    for emote in emotes:
                        if not isinstance(emote, tuple):
                            name, id = emote, emote
                            emotes_list.append(id)
                            guild = None
                        else:
                            # Prefix is the animated emoji prefix a: or empty str
                            prefix, name, id = emote
                            name = prefix + name
                            emotes_list.append(id)
                            guild = ctx.guild.id
                        values.append((name, str(id), guild))

                    # No need to run these if no user set emotes are used
                    if values:
                        # If emote is already in the table update its name
                        sql += ' ON CONFLICT (emote) DO UPDATE SET name=EXCLUDED.name'
                        await conn.executemany(sql, values)

                        sql = 'INSERT INTO pollemotes (poll_id, emote_id) VALUES ($1, $2) ON CONFLICT DO NOTHING '
                        values = []
                        for id in emotes_list:
                            values.append((msg.id, str(id)))

                        await conn.executemany(sql, values)

                await tr.commit()
            except PostgresError:
                await tr.rollback()
                logger.exception('Failed sql query')
                await ctx.send('Failed to save poll. Exception has been logged')
                return

        if isinstance(emotes_list, str):
            # Error happened when this is a string. Otherwise it's a list
            return await ctx.send(emotes_list)

        poll = Poll(self.bot, msg.id, msg.channel.id, title, expires_at=expired_date, strict=parsed.strict,
                    emotes=emotes_list, no_duplicate_votes=parsed.no_duplicate_votes,
                    multiple_votes=parsed.allow_multiple_entries, max_winners=parsed.max_winners,
                    after=lambda f: self.polls.pop(msg.id, None), giveaway=parsed.giveaway)
        poll.start()
        self.polls[msg.id] = poll


def setup(bot):
    bot.add_cog(VoteManager(bot))

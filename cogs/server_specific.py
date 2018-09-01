import asyncio
import logging
import shlex
import subprocess
from datetime import datetime
import random

import aioredis
import discord
from discord.errors import HTTPException
from discord.ext.commands import (BucketType, check, bot_has_permissions)
from numpy.random import choice
from numpy import sqrt
from sqlalchemy.exc import SQLAlchemyError

from bot.bot import command, has_permissions, cooldown
from bot.formatter import Paginator
from cogs.cog import Cog
from utils.utilities import (split_string, parse_time, datetime2sql, call_later,
                             get_avatar, retry, send_paged_message)

logger = logging.getLogger('debug')


def create_check(guild_ids):
    def guild_check(ctx):
        return ctx.guild.id in guild_ids

    return guild_check


whitelist = [217677285442977792, 353927534439825429]
main_check = create_check(whitelist)


class ServerSpecific(Cog):
    def __init__(self, bot):
        super().__init__(bot)

        asyncio.run_coroutine_threadsafe(self.load_giveaways(), loop=self.bot.loop)
        self.main_whitelist = whitelist
        task = asyncio.run_coroutine_threadsafe(aioredis.create_redis((self.bot.config.db_host, self.bot.config.redis_port),
                                                                      password=self.bot.config.redis_auth,
                                                                      loop=bot.loop, encoding='utf-8'), loop=bot.loop)

        self.redis = task.result()

    def __unload(self):
        for g in list(self.bot.every_giveaways.values()):
            g.cancel()

    async def load_giveaways(self):
        sql = 'SELECT * FROM `giveaways`'
        try:
            rows = (await self.bot.dbutil.execute(sql)).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to load giveaways')
            return

        for row in rows:
            guild = row['guild']
            channel = row['channel']
            message = row['message']
            title = row['title']
            winners = row['winners']
            timeout = max((row['expires_in'] - datetime.utcnow()).total_seconds(), 0)
            if message in self.bot.every_giveaways:
                self.bot.every_giveaways[message].cancel()

            fut = call_later(self.remove_every, self.bot.loop, timeout, guild, channel, message, title, winners,
                             after=lambda f: self.bot.every_giveaways.pop(message))
            self.bot.every_giveaways[message] = fut

    @property
    def dbutil(self):
        return self.bot.dbutil

    async def _check_role_grant(self, ctx, user, role_id, guild_id):
        length = len(user.roles)
        if length == 1:
            user_role = 'user_role=%s' % role_id
        else:
            user_role = 'user_role IN (%s)' % ', '.join((str(r.id) for r in user.roles))

        sql = 'SELECT `role` FROM `role_granting` WHERE guild=%s AND role=%s AND %s LIMIT 1' % (guild_id, role_id, user_role)
        try:
            row = (await self.bot.dbutil.execute(sql)).first()
            if not row:
                return False
        except SQLAlchemyError:
            await ctx.send('Something went wrong. Try again in a bit')
            return None

        return True

    @command(no_pm=True)
    @cooldown(1, 4, type=BucketType.user)
    @check(main_check)
    @bot_has_permissions(manage_roles=True)
    async def grant(self, ctx, user: discord.Member, *, role: discord.Role):
        """Give a role to the specified user if you have the perms to do it"""
        guild = ctx.guild
        author = ctx.author
        length = len(author.roles)
        if length == 0:
            return

        no = (117256618617339905, 189458911886049281)
        if author.id in no and user.id in no and user.id != author.id:
            return await ctx.send('no')

        can_grant = await self._check_role_grant(ctx, author, role.id, guild.id)
        if can_grant is None:
            return
        elif can_grant is False:
            return await ctx.send("You don't have the permission to grant this role", delete_after=30)

        try:
            await user.add_roles(role, reason=f'{ctx.author} granted role')
        except HTTPException as e:
            return await ctx.send('Failed to add role\n%s' % e)

        await ctx.send('👌')

    @command(no_pm=True)
    @cooldown(2, 4, type=BucketType.user)
    @check(main_check)
    @bot_has_permissions(manage_roles=True)
    async def ungrant(self, ctx, user: discord.Member, *, role: discord.Role):
        """Remove a role from a user if you have the perms"""
        guild = ctx.guild
        author = ctx.message.author
        length = len(author.roles)
        if length == 0:
            return

        no = (117256618617339905, 189458911886049281)
        if author.id in no and user.id in no and user.id != author.id:
            return await ctx.send('no')

        can_grant = await self._check_role_grant(ctx, author, role.id, guild.id)
        if can_grant is None:
            return
        elif can_grant is False:
            return await ctx.send("You don't have the permission to remove this role", delete_after=30)

        try:
            await user.remove_roles(role, reason=f'{ctx.author} ungranted role')
        except HTTPException as e:
            return await ctx.send('Failed to remove role\n%s' % e)

        await ctx.send('👌')

    @command(no_pm=True, ignore_extra=True)
    @cooldown(2, 4, type=BucketType.guild)
    @check(main_check)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def add_grant(self, ctx, role: discord.Role, target_role: discord.Role):
        """Make the given role able to grant the target role"""
        guild = ctx.guild

        if not await self.dbutil.add_roles(guild.id, target_role.id, role.id):
            return await ctx.send('Could not add roles to database')

        sql = 'INSERT IGNORE INTO `role_granting` (`user_role`, `role`, `guild`) VALUES ' \
              '(%s, %s, %s)' % (role.id, target_role.id, guild.id)
        session = self.bot.get_session
        try:
            session.execute(sql)
            session.commit()
        except SQLAlchemyError:
            session.rollback()
            logger.exception('Failed to add grant role')
            return await ctx.send('Failed to add perms. Exception logged')

        await ctx.send(f'{role} 👌 {target_role}')

    @command(no_pm=True, ignore_extra=True)
    @cooldown(1, 4, type=BucketType.user)
    @check(main_check)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def remove_grant(self, ctx, role: discord.Role, target_role: discord.Role):
        """Remove a grantable role from the target role"""
        guild = ctx.guild

        sql = 'DELETE FROM `role_granting` WHERE user_role=%s AND role=%s AND guild=%s' % (role.id, target_role.id, guild.id)
        try:
            await self.dbutil.execute(sql, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to remove grant role')
            return await ctx.send('Failed to remove perms. Exception logged')

        await ctx.send(f'{role} 👌 {target_role}')

    @command(no_pm=True)
    @cooldown(2, 5)
    async def all_grants(self, ctx, role: discord.Role=None):
        sql = f'SELECT `role`, `user_role` FROM `role_granting` WHERE guild={ctx.guild.id}'
        if role:
            sql += f' AND user_role={role.id}'

        try:
            rows = await self.bot.dbutil.execute(sql)
        except SQLAlchemyError:
            logger.exception(f'Failed to get grants for role {role}')
            return await ctx.send('Failed to get grants')

        role_grants = {}
        for row in rows:
            role_id = row['user_role']
            target_role = row['role']
            if role_id not in role_grants:
                role_grants[role_id] = [target_role]
            else:
                role_grants[role_id].append(target_role)

        if not role_grants:
            return await ctx.send('No role grants found')

        paginator = Paginator('Role grants')
        for role_id, roles in role_grants.items():
            role = self.bot.get_role(role_id, ctx.guild)
            role_name = role.name if role else '*Deleted role*'
            paginator.add_field(f'{role_name} `{role_id}`')
            for role in roles:
                paginator.add_to_field(f'<@&{role}> `{role}`\n')

        paginator.finalize()
        await send_paged_message(self.bot, ctx, paginator.pages, embed=True)

    @command(no_pm=True, aliases=['get_grants', 'grants'])
    @cooldown(1, 4)
    @check(main_check)
    async def show_grants(self, ctx, user: discord.Member=None):
        """Shows the roles you or the specified user can grant"""
        guild = ctx.guild
        if not user:
            user = ctx.author

        sql = 'SELECT `role` FROM `role_granting` WHERE guild=%s AND user_role IN (%s)' % (guild.id, ', '.join((str(r.id) for r in user.roles)))
        try:
            rows = (await self.dbutil.execute(sql)).fetchall()
        except SQLAlchemyError:
            logger.exception('Failed to get role grants')
            return await ctx.send('Failed execute sql')

        if not rows:
            return await ctx.send("{} can't grant any roles".format(user))

        msg = 'Roles {} can grant:\n'.format(user)
        roles = set()
        for row in rows:
            role = self.bot.get_role(row['role'], guild)
            if not role:
                continue

            if role.id in roles:
                continue

            roles.add(role.id)
            msg += '{0.name} `{0.id}`\n'.format(role)

        if not roles:
            return await ctx.send("{} can't grant any roles".format(user))

        for s in split_string(msg, maxlen=2000, splitter='\n'):
            await ctx.send(s)

    @command()
    @cooldown(1, 3, type=BucketType.guild)
    @check(main_check)
    async def text(self, ctx):
        """Generate text"""
        if self.bot.test_mode:
            return

        p = '/home/pi/neural_networks/torch-rnn/cv/checkpoint_pi.t7'
        script = '/home/pi/neural_networks/torch-rnn/sample.lua'
        cmd = '/home/pi/torch/install/bin/th %s -checkpoint %s -length 200 -gpu -1' % (script, p)
        try:
            p = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd='/home/pi/neural_networks/torch-rnn/')
        except:
            await ctx.send('Not supported')
            return

        await ctx.trigger_typing()
        while p.poll() is None:
            await asyncio.sleep(0.2)

        out, err = p.communicate()
        await ctx.send(out.decode('utf-8'))

    @command(owner_only=True, aliases=['flip'])
    @check(main_check)
    async def flip_the_switch(self, ctx, value: bool=None):
        if value is None:
            self.bot.anti_abuse_switch = not self.bot.anti_abuse_switch
        else:
            self.bot.anti_abuse_switch = value

        await ctx.send(f'Switch set to {self.bot.anti_abuse_switch}')

    @command(no_pm=True)
    @cooldown(1, 3, type=BucketType.user)
    @check(create_check((217677285442977792, )))
    async def default_role(self, ctx):
        """Temporary fix to easily get default role"""
        if self.bot.test_mode:
            return

        guild = ctx.guild
        role = self.bot.get_role(352099343953559563, guild)
        if not role:
            return await ctx.send('Default role not found')

        member = ctx.author
        if role in member.roles:
            return await ctx.send('You already have the default role. Reload discord (ctrl + r) to get your global emotes')

        try:
            await member.add_roles(role)
        except HTTPException as e:
            return await ctx.send('Failed to add default role because of an error.\n{}'.format(e))

        await ctx.send('You now have the default role. Reload discord (ctrl + r) to get your global emotes')

    @command(no_pm=True)
    @cooldown(1, 600)
    @bot_has_permissions(manage_guild=True)
    @check(main_check)
    async def rotate(self, ctx, emoji=None):
        emoji_faces = ['😀', '😁', '😂', '🤣', '😃', '😄', '😅', '😆', '😉', '😊',
                       '😋', '😎', '😍', '😘', '😗', '😙', '😚', '☺', '🙂', '🤗',
                       '\U0001f929', '🤔', '\U0001f928', '😐', '😑', '😶', '🙄',
                       '😏', '😣', '😥', '😮', '🤐', '😯', '😪', '😫', '😴', '😌',
                       '😛', '😜', '😝', '🤤', '😒', '😓', '😔', '😕', '🙃', '🤑',
                       '😲', '☹', '🙁', '😖', '😞', '😟', '😤', '😢', '😭', '😦',
                       '😧', '😨', '😩', '\U0001f92f', '😬', '😰', '😱', '😳',
                       '\U0001f92a', '😵', '😡', '😠', '\U0001f92c', '😷', '🤒',
                       '🤕', '🤢', '\U0001f92e', '🤧', '😇', '🤠', '🤡', '🤥',
                       '\U0001f92b', '\U0001f92d', '\U0001f9d0', '🤓', '😈', '👿',
                       '👶',
                       '🐶', '🐱', '🐻', '🐸', '🐵', '🐧', '🐔', '🐣', '🐥', '🐝',
                       '🐍', '🐢']

        if emoji is not None and emoji not in emoji_faces:
            return await ctx.send('Invalid emoji')

        elif emoji is None:
            emoji = random.choice(emoji_faces)

        try:
            await ctx.guild.edit(name=emoji*50)
        except discord.HTTPException as e:
            await ctx.send(f'Failed to change name because of an error\n{e}')
        else:
            await ctx.send('♻')

    async def _toggle_every(self, channel, winners: int, expires_in):
        guild = channel.guild
        perms = channel.permissions_for(guild.get_member(self.bot.user.id))
        if not perms.manage_roles and not perms.administrator:
            return await channel.send('Invalid server perms')

        role = self.bot.get_role(323098643030736919 if not self.bot.test_mode else 440964128178307082, guild)
        if role is None:
            return await channel.send('Every role not found')

        sql = 'INSERT INTO `giveaways` (`guild`, `title`, `message`, `channel`, `winners`, `expires_in`) VALUES (:guild, :title, :message, :channel, :winners, :expires_in)'

        now = datetime.utcnow()
        expired_date = now + expires_in
        sql_date = datetime2sql(expired_date)

        title = 'Toggle the every role on the winner.'
        embed = discord.Embed(title='Giveaway: {}'.format(title),
                              description='React with <:GWjojoGachiGASM:363025405562585088> to enter',
                              timestamp=expired_date)
        text = 'Expires at'
        if winners > 1:
            text = '{} winners | '.format(winners) + text
        embed.set_footer(text=text, icon_url=get_avatar(self.bot.user))

        message = await channel.send(embed=embed)
        try:
            await message.add_reaction('GWjojoGachiGASM:363025405562585088')
        except:
            pass

        try:
            await self.bot.dbutil.execute(sql, params={'guild': guild.id,
                                                       'title': 'Toggle every',
                                                       'message': message.id,
                                                       'channel': channel.id,
                                                       'winners': winners,
                                                       'expires_in': sql_date},
                                          commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to create every toggle')
            return await channel.send('SQL error')

        task = call_later(self.remove_every, self.bot.loop, expires_in.total_seconds(),
                          guild.id, channel.id, message.id, title, winners)

        self.bot.every_giveaways[message.id] = task

    @command(no_pm=True)
    @cooldown(1, 3, type=BucketType.guild)
    @check(main_check)
    @has_permissions(manage_roles=True, manage_guild=True)
    @bot_has_permissions(manage_roles=True)
    async def toggle_every(self, ctx, winners: int, *, expires_in):
        """Host a giveaway to toggle the every role"""
        expires_in = parse_time(expires_in)
        if not expires_in:
            return await ctx.send('Invalid time string')

        if expires_in.days > 29:
            return await ctx.send('Maximum time is 29 days 23 hours 59 minutes and 59 seconds')

        if not self.bot.test_mode and expires_in.total_seconds() < 300:
            return await ctx.send('Minimum time is 5 minutes')

        if winners < 1:
            return await ctx.send('There must be more than 1 winner')

        if winners > 30:
            return await ctx.send('Maximum amount of winners is 30')

        await self._toggle_every(ctx.channel, winners, expires_in)

    async def delete_giveaway_from_db(self, message_id):
        sql = 'DELETE FROM `giveaways` WHERE message=:message'
        try:
            await self.bot.dbutil.execute(sql, {'message': message_id}, commit=True)
        except SQLAlchemyError:
            logger.exception('Failed to delete giveaway {}'.format(message_id))

    async def remove_every(self, guild, channel, message, title, winners):
        guild = self.bot.get_guild(guild)
        if not guild:
            await self.delete_giveaway_from_db(message)
            return

        role = self.bot.get_role(323098643030736919 if not self.bot.test_mode else 440964128178307082, guild)
        if role is None:
            await self.delete_giveaway_from_db(message)
            return

        channel = self.bot.get_channel(channel)
        if not channel:
            await self.delete_giveaway_from_db(message)
            return

        try:
            message = await channel.get_message(message)
        except discord.NotFound:
            logger.exception('Could not find message for every toggle')
            await self.delete_giveaway_from_db(message)
            return
        except Exception:
            logger.exception('Failed to get toggle every message')

        react = None
        for reaction in message.reactions:
            emoji = reaction.emoji
            if isinstance(emoji, str):
                continue
            if emoji.id == 363025405562585088 and emoji.name == 'GWjojoGachiGASM':
                react = reaction
                break

        if react is None:
            logger.debug('react not found')
            return

        title = 'Giveaway: {}'.format(title)
        description = 'No winners'
        users = await react.users(limit=react.count).flatten()
        candidates = [guild.get_member(user.id) for user in users if user.id != self.bot.user.id and guild.get_member(user.id)]
        winners = choice(candidates, min(winners, len(candidates)), replace=False)
        if len(winners) > 0:
            winners = sorted(winners, key=lambda u: u.name)
            description = 'Winners: {}'.format('\n'.join([user.mention for user in winners]))

        added = 0
        removed = 0
        for winner in winners:
            winner = guild.get_member(winner.id)
            if not winner:
                continue
            if role in winner.roles:
                retval = await retry(winner.remove_roles, role, reason='Won every toggle giveaway')
                removed += 1

            else:
                retval = await retry(winner.add_roles, role, reason='Won every toggle giveaway')
                added += 1

            if isinstance(retval, Exception):
                logger.debug('Failed to toggle every role on {0} {0.id}\n{1}'.format(winner, retval))

        embed = discord.Embed(title=title, description=description, timestamp=datetime.utcnow())
        embed.set_footer(text='Expired at', icon_url=get_avatar(self.bot.user))
        await message.edit(embed=embed)
        description += '\nAdded every to {} user(s) and removed it from {} user(s)'.format(added, removed)
        await message.channel.send(description)
        await self.delete_giveaway_from_db(message.id)

    async def on_member_join(self, member):
        if self.bot.test_mode:
            return

        guild = member.guild
        if guild.id != 366940074635558912:
            return

        if random.random() < 0.09:
            name = str(member.discriminator)
        else:
            name = str(random.randint(1000, 9999))
        await member.edit(nick=name, reason='Auto nick')

    async def on_message(self, message):
        if not message.guild or message.guild.id not in self.main_whitelist:
            return

        if message.webhook_id:
            return

        if message.author.bot:
            return

        blacklist = self.bot.get_cog('Moderator')
        if not blacklist:
            return

        blacklist = blacklist.automute_blacklist.get(message.guild.id, ())

        if message.channel.id in blacklist or message.channel.id in (384422173462364163, 484450452243742720):
            return

        user = message.author
        key = f'{message.guild.id}:{user.id}'
        value = await self.redis.get(key)
        if value:
            score, last_msg = value.split(':', 1)
            score = float(score)
        else:
            score, last_msg = 0, None

        ttl = await self.redis.ttl(key)
        created_td = (datetime.utcnow() - user.created_at)
        joined_td = (datetime.utcnow() - user.joined_at)
        if joined_td.days > 14:
            joined = 0.2  # 2/sqrt(1)*2
        else:
            # seconds to days
            # value is max up to 1 day after join
            joined = max(joined_td.total_seconds()/86400, 1)
            joined = 2/sqrt(joined)*2

        if created_td.days > 14:
            created = 0.2  # 2/(7**(1/4))*4
        else:
            # Calculated the same as join
            created = max(created_td.total_seconds()/86400, 1)
            created = 2/(created**(1/5))*4

        points = created+joined

        if ttl > 0:
            ttl = max(10-ttl, 0.5)
            points += 6*1/sqrt(ttl)

        if user.avatar is None:
            points += 5*max(created/2, 1)

        msg = message.content
        if msg:
            msg = msg.lower()
            if msg == last_msg:
                points += 5*((created+joined)/5)
        else:
            msg = ''

        score += points

        needed_for_mute = 50

        needed_for_mute += min(joined_td.days, 14)*2.14
        needed_for_mute += min(created_td.days, 21)*1.42

        if score > needed_for_mute:
            channel = self.bot.get_channel(252872751319089153)
            if channel:
                await channel.send(f'{user.mention} got muted for spam with score of {score} at {message.created_at}')

            score = 0
            msg = ''

        await self.redis.set(key, f'{score}:{msg}', expire=10)


def setup(bot):
    bot.add_cog(ServerSpecific(bot))

import asyncio
import logging
import random
import textwrap
import unicodedata
from datetime import datetime
from datetime import timedelta
from typing import Union

import discord
import emoji
from aioredis.errors import ConnectionClosedError
from asyncpg.exceptions import PostgresError
from discord.errors import HTTPException
from discord.ext.commands import (BucketType, check)
from numpy import sqrt
from numpy.random import choice

from bot.bot import command, has_permissions, cooldown, bot_has_permissions
from bot.formatter import Paginator
from cogs.cog import Cog
from utils.utilities import (split_string, parse_time, call_later,
                             get_avatar, retry, send_paged_message,
                             check_botperm)

logger = logging.getLogger('debug')
terminal = logging.getLogger('terminal')


def create_check(guild_ids):
    def guild_check(ctx):
        if not ctx.guild:
            return False

        return ctx.guild.id in guild_ids

    return guild_check


whitelist = [217677285442977792, 353927534439825429]
main_check = create_check(whitelist)
grant_whitelist = {486834412651151361, 279016719916204032, 468227890413174806}  # chef server and artx server
grant_whitelist.update(whitelist)
grant_check = create_check(grant_whitelist)

# waifus to add
"""
ram
emilia
chiaki nanami
nagito komaeda
ochako uraraka 
tsuyu asui
kyouka jirou
momo yaoyorozu
rias gremory
himiko toga
akeno himejima
xenovia quarta 
ushikai musume
Koneko toujou
asuna yuuki
kanna kamui
ann takamaki
yousei yunde
yorha 2-gou b-gata"""

# Name, chance of spawning, character id, japanese name, spawn images in a list
waifus = [('Billy Herrington', 3, 1000006, 'ビリー・ヘリントン', ['https://i.imgur.com/ny8IwLI.png', 'https://i.imgur.com/V9X7Rbm.png', 'https://i.imgur.com/RxxYp62.png']),
          ('Sans', 3, 1000007, 'オイラ', ['https://imgur.com/VSet9rA.jpg', 'https://imgur.com/Dv5HNHH.jpg']),
          ("Aqua", 10, 117223, 'アクア', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=7B4dkxZXrniNxKaJFq0XFVO86alUbsoiQNXbaxFmhwqyCd2KfYqkUpW5YHaZhuAh&tea=FvLvedTFWlgNSavX', 'https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=stWZ5xmBZkDH8bHyhVpG9Y4iae8Cqf3ajoY0lD7r3Sdysa4IilA6aZSUHznVbQWG&tea=TPiTxOZcgmMieAnO']),
          ('Zero Two', 10, 155679, 'ゼロツー', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=5YJ%2FlstHJTPWWcZ0RfBsOuoHlK48mDUK5Dd596ED%2BonGAIJcACI9xwoVreZSM0WI&tea=iBvsVVWHNcdsvaOK', 'https://cdn.discordapp.com/attachments/477293401054642177/477319994259275796/055fb45a-e8d7-4084-b61d-eea31b0fd235.jpg']),
          ('Shalltear Bloodfallen', 10, 116319, 'シャルティア・ブラッドフォールン', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=QZXjFYY%2BKrSOKMP7FXg1vTkHZLtBgIczQJEJWP3THtgsEIz7VhhE2menxbFv1VS9&tea=qckYylIRjoKUbjzG', 'https://cdn.discordapp.com/attachments/477293401054642177/477317853389783042/2b513572-a239-4bb7-a58a-bb48a23e4379.jpg']),
          ('Esdeath', 10, 65239, 'エスデス', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=oxQ4Hy%2Bhh4EuSfBwMzxGP%2BJgVhga0OQ3d%2BFdV4mxMcTABwPfyjO7Ai86D5mijMxq&tea=zCbXylfXYsArnJuq', 'https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=P%2BS2ZekqqFZ8xzXqKgipdQLzckmAwRK%2FUkvsnMCxcHFDyyRet4lgcGRqvbF1Y4Vq&tea=ulrKjZyNCLDhktvW']),
          ('Megumin', 10, 117225, 'めぐみん', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=3TvoZWcwlI3WlJXUyNLeloFBNV6oF2qq8NYfukqNk0ht0zqKhP7%2FrEGz0frs6Wq5&tea=wfDsVgPNOOTkwMhz', ]),
          ('Albedo', 10, 116275, 'アルベド', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=6mFvoz3jJ%2BwhW9lOWR49KTbLIiKjuYFhittUwcQhMc%2B0JstX%2FkkXyXVPZxWiiEkr&tea=VyKIujqwVbHiWTUz']),
          ('Rem', 10, 118763, 'レム', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=bUUxHLQv6IzKqWZnxrO8nUw723nFGHALSm9ZM8Ly3VU1%2B0DyE8qL1yRaNtnQe7wj&tea=AFfSbWSfwXFONvvV']),
          ('Diego Brando', 10, 20148, 'ディエゴ・ブランド', ['https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=Nbs7aqPzWrDwa840C1176Twp0%2BUyHLLCOdT%2BeWCwgifCwqahUPMkL%2BaxiRwRBRKQ&tea=pFRfsLjEOQsslUUH', 'https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=Lg2jU0NTaywjMfTknBSPDbB12eO4ntiYKtp1sELGRlmKmkifZCQ%2FvFUA0DnKYXfN&tea=NSegbKFrxcrMGodh', 'https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=xvdUezdjgRSgF%2FWtG56r9oIeIBpgzGEAqjpe8Ep%2Bymul%2FP%2Bmaw5I%2B8LQahC9IrHV&tea=yCbcZxVMIMMjOmNB', 'https://remilia.cirno.pw/teahouse/teapot.jpg?biscuit=aHoAgV%2ByDmwuZyEA4VOrFDMkzdINa9VAKU%2FQTYmz2KrV5YyC3pnkEjlmnNhOLYBE&tea=YxnsMKNWTiriokwC']),
          ]

chances = [t[1] for t in waifus]
_s = sum(chances)
chances = [p/_s for p in chances]
del _s


class ServerSpecific(Cog):
    def __init__(self, bot):
        super().__init__(bot)

        asyncio.run_coroutine_threadsafe(self.load_giveaways(), loop=self.bot.loop)
        self.main_whitelist = whitelist
        self.grant_whitelist = grant_whitelist
        self.redis = self.bot.redis
        self._zetas = {}
        self._redis_fails = 0

    def __unload(self):
        for g in list(self.bot.every_giveaways.values()):
            g.cancel()

    async def load_giveaways(self):
        sql = 'SELECT * FROM giveaways'
        try:
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
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
        where = 'uid=%s OR user_role IN (%s)' % (user.id, ', '.join((str(r.id) for r in user.roles)))

        sql = 'SELECT role FROM role_granting WHERE guild=%s AND role=%s AND (%s) LIMIT 1' % (guild_id, role_id, where)
        try:
            row = await self.bot.dbutil.fetch(sql, fetchmany=False)
            if not row:
                return False
        except PostgresError:
            await ctx.send('Something went wrong. Try again in a bit')
            return None

        return True

    @Cog.listener()
    async def on_member_update(self, before, after):
        if before.guild.id != 217677285442977792:
            return

        if after.id == 123050803752730624:
            return

        if before.roles != after.roles:
            r = after.guild.get_role(316288608287981569)
            if r in after.roles:
                await after.remove_roles(r, reason='No')

    @command(no_pm=True)
    @cooldown(1, 4, type=BucketType.user)
    @check(grant_check)
    @bot_has_permissions(manage_roles=True)
    async def grant(self, ctx, user: discord.Member, *, role: discord.Role):
        """Give a role to the specified user if you have the perms to do it"""
        guild = ctx.guild
        author = ctx.author

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
    @check(grant_check)
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

    @command(no_pm=True)
    @cooldown(2, 4, type=BucketType.guild)
    @check(grant_check)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def add_grant(self, ctx, role_user: Union[discord.Role, discord.Member], *, target_role: discord.Role):
        """Make the given role able to grant the target role"""
        guild = ctx.guild

        if isinstance(role_user, discord.Role):
            values = (role_user.id, target_role.id, guild.id, 0)
            roles = (role_user.id, target_role.id)
        else:
            values = (0, target_role.id, guild.id, role_user.id)
            roles = (target_role.id, 0)

        if not await self.dbutil.add_roles(guild.id, *roles):
            return await ctx.send('Could not add roles to database')

        sql = 'INSERT INTO role_granting (user_role, role, guild, uid) VALUES ' \
              '(%s, %s, %s, %s) ON CONFLICT DO NOTHING ' % values
        try:
            await self.dbutil.execute(sql)
        except PostgresError:
            logger.exception('Failed to add grant role')
            return await ctx.send('Failed to add perms. Exception logged')

        await ctx.send(f'{role_user} 👌 {target_role}')

    @command(no_pm=True)
    @cooldown(1, 4, type=BucketType.user)
    @check(grant_check)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def remove_grant(self, ctx, role_user: Union[discord.Role, discord.Member], *, target_role: discord.Role):
        """Remove a grantable role from the target role"""
        guild = ctx.guild

        if isinstance(role_user, discord.Role):
            where = 'user_role=%s' % role_user.id
        else:
            where = 'user=%s' % role_user.id

        sql = 'DELETE FROM role_granting WHERE role=%s AND guild=%s AND %s' % (target_role.id, guild.id, where)
        try:
            await self.dbutil.execute(sql)
        except PostgresError:
            logger.exception('Failed to remove role grant')
            return await ctx.send('Failed to remove perms. Exception logged')

        await ctx.send(f'{role_user} 👌 {target_role}')

    @command(no_pm=True)
    @cooldown(2, 5)
    async def all_grants(self, ctx, role_user: Union[discord.Role, discord.User]=None):
        """Shows all grants on the server.
        If user or role provided will get all grants specific to that."""
        sql = f'SELECT role, user_role, uid FROM role_granting WHERE guild={ctx.guild.id}'
        if isinstance(role_user, discord.Role):
            sql += f' AND user_role={role_user.id}'
        elif isinstance(role_user, discord.User):
            sql += f' AND uid={role_user.id}'

        try:
            rows = await self.bot.dbutil.fetch(sql)
        except PostgresError:
            logger.exception(f'Failed to get grants for {role_user}')
            return await ctx.send('Failed to get grants')

        role_grants = {}
        user_grants = {}
        # Add user grants and role grants to their respective dicts
        for row in rows:
            role_id = row['user_role']
            target_role = row['role']

            # Add user grants
            if not role_id:
                user = row['uid']
                if user in user_grants:
                    user_grants[user].append(target_role)
                else:
                    user_grants[user] = [target_role]

            # Add role grants
            else:
                if role_id not in role_grants:
                    role_grants[role_id] = [target_role]
                else:
                    role_grants[role_id].append(target_role)

        if not role_grants and not user_grants:
            return await ctx.send('No role grants found')

        # Paginate role grants first then user grants
        paginator = Paginator('Role grants')
        for role_id, roles in role_grants.items():
            role = ctx.guild.get_role(role_id)
            role_name = role.name if role else '*Deleted role*'
            paginator.add_field(f'{role_name} `{role_id}`')
            for role in roles:
                paginator.add_to_field(f'<@&{role}> `{role}`\n')

        for user_id, roles in user_grants.items():
            user = self.bot.get_user(user_id)
            if not user:
                user = f'<@{user}>'

            paginator.add_field(f'{user} `{user_id}`')
            for role in roles:
                paginator.add_to_field(f'<@&{role}> `{role}`\n')

        paginator.finalize()
        await send_paged_message(ctx, paginator.pages, embed=True)

    @command(no_pm=True, aliases=['get_grants', 'grants'])
    @cooldown(1, 4)
    @check(grant_check)
    async def show_grants(self, ctx, user: discord.Member=None):
        """Shows the roles you or the specified user can grant"""
        guild = ctx.guild
        if not user:
            user = ctx.author

        sql = 'SELECT role FROM role_granting WHERE guild=%s AND (uid=%s OR user_role IN (%s))' % (guild.id, user.id, ', '.join((str(r.id) for r in user.roles)))
        try:
            rows = await self.dbutil.fetch(sql)
        except PostgresError:
            logger.exception('Failed to get role grants')
            return await ctx.send('Failed execute sql')

        if not rows:
            return await ctx.send("{} can't grant any roles".format(user))

        msg = 'Roles {} can grant:\n'.format(user)
        roles = set()
        for row in rows:
            role = guild.get_role(row['role'])
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

    @command(disabled=True)
    @cooldown(1, 3, type=BucketType.guild)
    @check(main_check)
    async def text(self, ctx, prime='', n: int=100, sample: int=1):
        """Generate text"""
        if not 10 <= n <= 200:
            return await ctx.send('n has to be between 10 and 200')

        if not 0 <= sample <= 2:
            return await ctx.send('sample hs to be 0, 1 or 2')

        if not self.bot.tf_model:
            return await ctx.send('Not supported')

        async with ctx.typing():
            s = await self.bot.loop.run_in_executor(self.bot.threadpool, self.bot.tf_model.sample, prime, n, sample)

        await ctx.send(s)

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
        role = guild.get_role(352099343953559563)
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

    # https://stackoverflow.com/questions/48340622/extract-all-emojis-from-string-and-ignore-fitzpatrick-modifiers-skin-tones-etc
    @staticmethod
    def check_type(emoji_str):
        if unicodedata.name(emoji_str).startswith("EMOJI MODIFIER"):
            return False
        else:
            return True

    def extract_emojis(self, emojis):
        return [c for c in emojis if c in emoji.UNICODE_EMOJI and self.check_type(c)]

    @command(no_pm=True)
    @cooldown(1, 600)
    @bot_has_permissions(manage_guild=True)
    @check(main_check)
    async def rotate(self, ctx, emoji=None):
        emoji_faces = {'😀', '😁', '😂', '🤣', '😃', '😄', '😅', '😆', '😉',
                       '😊', '😋', '😎', '😍', '😘', '😗', '😙', '😚', '☺',
                       '🙂', '🤗', '\U0001f929', '🤔', '\U0001f928', '😐', '😑',
                       '😶', '🙄', '😏', '😣', '😥', '😮', '🤐', '😯', '😪',
                       '😫', '😴', '😌', '😛', '😜', '😝', '🤤', '😒', '😓',
                       '😔', '😕', '🙃', '🤑', '😲', '☹', '🙁', '😖', '😞',
                       '😟', '😤', '😢', '😭', '😦', '😧', '😨', '😩',
                       '\U0001f92f', '😬', '😰', '😱', '😳', '👱', '\U0001f92a',
                       '😡', '😠', '\U0001f92c', '😷', '🤒', '🤕', '🤢', '😵',
                       '\U0001f92e', '🤧', '😇', '🤠', '🤡', '🤥', '\U0001f92b',
                       '\U0001f92d', '\U0001f9d0', '🤓', '😈', '👿', '👶', '🐶',
                       '🐱', '🐻', '🐸', '🐵', '🐧', '🐔', '🐣', '🐥', '🐝',
                       '🐍', '🐢', '🐹', '💩', '👦', '👧', '👨', '👩', '🎅',
                       '🍆', '🥚', '👌', '👏', '🌚', '🌝', '🌞', '⭐', '🦆', '👖',
                       '🍑', '🌈', '♿', '💯', '🐛', '💣', '🔞', '🆗', '🚼', '🇫',
                       '🇭', '🅱'}

        if emoji is not None:
            invalid = True
            emoji_check = emoji
            if len(emoji) > 1:
                try:
                    emojis = self.extract_emojis(emoji)
                except ValueError:
                    return await ctx.send('Invalid emoji')

                if len(emojis) == 1:
                    emoji_check = emojis[0]

            if emoji_check in emoji_faces:
                invalid = False

            if invalid:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send('Invalid emoji')

        elif emoji is None:
            emoji = random.choice(list(emoji_faces))

        try:
            await ctx.guild.edit(name=emoji*(100//(len(emoji))))
        except discord.HTTPException as e:
            await ctx.send(f'Failed to change name because of an error\n{e}')
        else:
            await ctx.send('♻')

    async def _toggle_every(self, channel, winners: int, expires_in):
        """
        Creates a toggle every giveaway in my server. This is triggered either
        by the toggle_every command or every n amount of votes in dbl
        Args:
            channel (discord.TextChannel): channel where the giveaway will be held
            winners (int): amount of winners
            expires_in (timedelta): Timedelta denoting how long the giveaway will last

        Returns:
            nothing useful
        """
        guild = channel.guild
        perms = channel.permissions_for(guild.get_member(self.bot.user.id))
        if not perms.manage_roles and not perms.administrator:
            return await channel.send('Invalid server perms')

        role = guild.get_role(323098643030736919 if not self.bot.test_mode else 440964128178307082)
        if role is None:
            return await channel.send('Every role not found')

        sql = 'INSERT INTO giveaways (guild, title, message, channel, winners, expires_in) VALUES ($1, $2, $3, $4, $5, $6)'

        now = datetime.utcnow()
        expired_date = now + expires_in
        sql_date = expired_date

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
            await self.bot.dbutil.execute(sql, (guild.id, 'Toggle every',
                                                message.id, channel.id,
                                                winners, sql_date))
        except PostgresError:
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

        if winners > 100:
            return await ctx.send('Maximum amount of winners is 100')

        await self._toggle_every(ctx.channel, winners, expires_in)

    async def delete_giveaway_from_db(self, message_id: int):
        sql = 'DELETE FROM giveaways WHERE message=$1'
        try:
            await self.bot.dbutil.execute(sql, (message_id,))
        except PostgresError:
            logger.exception('Failed to delete giveaway {}'.format(message_id))

    async def remove_every(self, guild, channel, message, title, winners):
        guild = self.bot.get_guild(guild)
        if not guild:
            await self.delete_giveaway_from_db(message)
            return

        role = guild.get_role(323098643030736919 if not self.bot.test_mode else 440964128178307082)
        if role is None:
            await self.delete_giveaway_from_db(message)
            return

        channel = self.bot.get_channel(channel)
        if not channel:
            await self.delete_giveaway_from_db(message)
            return

        try:
            message = await channel.fetch_message(message)
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

        embed = discord.Embed(title=title, description=description[:2048], timestamp=datetime.utcnow())
        embed.set_footer(text='Expired at', icon_url=get_avatar(self.bot.user))
        await message.edit(embed=embed)
        description += '\nAdded every to {} user(s) and removed it from {} user(s)'.format(added, removed)
        for msg in split_string(description, splitter='\n', maxlen=2000):
            await message.channel.send(msg)

        await self.delete_giveaway_from_db(message.id)

    @Cog.listener()
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

    @Cog.listener()
    async def on_message(self, message):
        if not self.bot.antispam or not self.redis:
            return

        guild = message.guild
        if not guild or guild.id not in self.main_whitelist:
            return

        if message.webhook_id:
            return

        if message.author.bot:
            return

        if message.type != discord.MessageType.default:
            return

        moderator = self.bot.get_cog('Moderator')
        if not moderator:
            return

        blacklist = moderator.automute_blacklist.get(guild.id, ())

        if message.channel.id in blacklist or message.channel.id in (384422173462364163, 484450452243742720):
            return

        user = message.author
        whitelist = moderator.automute_whitelist.get(guild.id, ())
        invulnerable = discord.utils.find(lambda r: r.id in whitelist,
                                          user.roles)

        if invulnerable is not None:
            return

        mute_role = self.bot.guild_cache.mute_role(message.guild.id)
        mute_role = discord.utils.find(lambda r: r.id == mute_role,
                                       message.guild.roles)
        if not mute_role:
            return

        if mute_role in user.roles:
            return

        if not check_botperm('manage_roles', guild=message.guild, channel=message.channel):
            return

        key = f'{message.guild.id}:{user.id}'
        try:
            value = await self.redis.get(key)
        except ConnectionClosedError:
            self._redis_fails += 1
            if self._redis_fails > 1:
                    self.bot.redis = None
                    self.redis = None
                    await self.bot.get_channel(252872751319089153).send('Manual redis restart required')
                    return

            import aioredis
            terminal.exception('Connection closed. Reconnecting')
            redis = await aioredis.create_redis((self.bot.config.db_host, self.bot.config.redis_port),
                                        password=self.bot.config.redis_auth,
                                        loop=self.bot.loop, encoding='utf-8')

            old = self.bot.redis
            self.bot.redis = redis
            del old
            return

        self._redis_fails = 0

        if value:
            score, repeats, last_msg = value.split(':', 2)
            score = float(score)
            repeats = int(repeats)
        else:
            score, repeats, last_msg = 0, 0, None

        ttl = await self.redis.ttl(key)
        certainty = 0
        created_td = (datetime.utcnow() - user.created_at)
        joined_td = (datetime.utcnow() - user.joined_at)
        if joined_td.days > 14:
            joined = 0.2  # 2/sqrt(1)*2
        else:
            # seconds to days
            # value is max up to 1 day after join
            joined = max(joined_td.total_seconds()/86400, 1)
            joined = 2/sqrt(joined)*2
            certainty += joined * 4

        if created_td.days > 14:
            created = 0.2  # 2/(7**(1/4))*4
        else:
            # Calculated the same as join
            created = max(created_td.total_seconds()/86400, 1)
            created = 2/(created**(1/5))*4
            certainty += created * 4

        points = created+joined

        old_ttl = 10
        if ttl > 0:
            old_ttl = min(ttl+2, 10)

        if ttl > 4:
            ttl = max(10-ttl, 0.5)
            points += 6*1/sqrt(ttl)

        if user.avatar is None:
            points += 5*max(created/2, 1)
            certainty += 20

        msg = message.content

        if msg:
            msg = msg.lower()
            len_multi = max(sqrt(len(msg))/18, 0.5)
            if msg == last_msg:
                repeats += 1
                points += 5*((created+joined)/5) * len_multi
                points += repeats*3*len_multi
                certainty += repeats * 4

        else:
            msg = ''

        score += points

        needed_for_mute = 50

        needed_for_mute += min(joined_td.days, 14)*2.14
        needed_for_mute += min(created_td.days, 21)*1.42

        certainty *= 100 / needed_for_mute
        certainty = min(round(certainty, 1), 100)

        if score > needed_for_mute and certainty > 55:
            certainty = str(certainty) + '%'
            time = timedelta(hours=2)
            if self.bot.timeouts.get(guild.id, {}).get(user.id):
                return

            d = 'Automuted user {0} `{0.id}` for {1}'.format(message.author, time)

            await message.author.add_roles(mute_role, reason='[Automute] Spam')
            url = f'[Jump to](https://discordapp.com/channels/{guild.id}/{message.channel.id}/{message.id})'
            embed = discord.Embed(title='Moderation action [AUTOMUTE]',
                                  description=d, timestamp=datetime.utcnow())
            embed.add_field(name='Reason', value='Spam')
            embed.add_field(name='Certainty', value=certainty)
            embed.add_field(name='link', value=url)
            embed.set_thumbnail(url=user.avatar_url or user.default_avatar_url)
            embed.set_footer(text=str(self.bot.user), icon_url=self.bot.user.avatar_url or self.bot.user.default_avatar_url)
            msg = await moderator.send_to_modlog(guild, embed=embed)

            await moderator.add_timeout(await self.bot.get_context(message), guild.id, user.id,
                                        datetime.utcnow() + time,
                                        time.total_seconds(),
                                        reason='Automuted for spam. Certainty %s' % certainty,
                                        author=guild.me,
                                        modlog_msg=msg.id if msg else None)

            score = 0
            msg = ''

        await self.redis.set(key, f'{score}:{repeats}:{msg}', expire=old_ttl)

    @command()
    @check(lambda ctx: ctx.author.id==302276390403702785)  # Check if chad
    async def rt2_lock(self, ctx):
        if ctx.channel.id != 341610158755020820:
            return await ctx.send("This isn't rt2")

        mod = self.bot.get_cog('Moderator')
        if not mod:
            return await ctx.send("This bot doesn't support locking")

        await mod._set_channel_lock(ctx, True)

    @command(hidden=True)
    @cooldown(1, 60, BucketType.channel)
    async def zeta(self, ctx, channel: discord.TextChannel=None):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if not channel:
            channel = ctx.channel

        try:
            wh = await channel.webhooks()
            if not wh:
                return

            wh = wh[0]
        except discord.HTTPException:
            return

        waifu = choice(len(waifus), p=chances)
        waifu = waifus[waifu]

        def get_inits(s):
            inits = ''

            for c in s.split(' '):
                inits += f'{c[0].upper()}. '

            return inits

        initials = get_inits(waifu[0])
        link = choice(waifu[4])

        desc = """
        A waifu/husbando appeared!
        Try guessing their name with `.claim <name>` to claim them!

        Hints:
        This character's initials are '{}'
        Use `.lookup <name>` if you can't remember the full name.

        (If the image is missing, click [here]({}).)"""

        desc = textwrap.dedent(desc).format(initials, link).strip()
        e = discord.Embed(title='Character', color=16745712, description=desc)
        e.set_image(url=link)
        wb = self.bot.get_user(472141928578940958)

        await wh.send(embed=e, username=wb.name, avatar_url=wb.avatar_url)

        guessed = False

        def check_(msg):
            if msg.channel != channel:
                return False

            content = msg.content.lower()
            if content.startswith('.claim '):
                return True

            return False

        name = waifu[0]
        claimer = None
        self._zetas[ctx.guild.id] = ctx.message.id

        while guessed is False:
            try:
                msg = await self.bot.wait_for('message', check=check_, timeout=360)
            except asyncio.TimeoutError:
                guessed = None
                continue

            if ctx.guild.id in self._zetas and ctx.message.id != self._zetas[ctx.guild.id]:
                return

            guess = ' '.join(msg.content.split(' ')[1:]).replace('-', ' ').lower()
            if guess != name.lower():
                await wh.send("That isn't the right name.", username=wb.name, avatar_url=wb.avatar_url)
                continue

            await wh.send(f'Nice {msg.author.mention}, you claimed [ζ] {name}!', username=wb.name, avatar_url=wb.avatar_url)
            claimer = msg.author
            guessed = True

        try:
            self._zetas.pop(ctx.guild.id)
        except KeyError:
            pass

        if not guessed:
            return

        def get_stat():
            if name == 'Billy Herrington':
                return 999

            return random.randint(0, 100)

        stats = [get_stat() for _ in range(4)]
        character_id = waifu[2]

        desc = f"""
        Claimed by {claimer.mention}
        Local ID: {random.randint(500, 3000)}
        Global ID: {random.randint(2247321, 2847321)}
        Character ID: {character_id}
        Type: Zeta (ζ)
        
        Strength: {stats[0]}
        Agility: {stats[1]}
        Defense: {stats[2]}
        Endurance: {stats[3]}
        
        Cumulative Stats Index (CSI): {sum(stats)//len(stats)}
        
        Affection: 0
        Affection Cooldown: None
        """

        desc = textwrap.dedent(desc).strip()

        def check_(msg):
            if msg.channel != channel:
                return False

            content = msg.content.lower()
            if content.startswith('.latest') and msg.author == claimer:
                return True

            return False

        async def delete_wb_msg():
            def wb_check(msg):
                if msg.author != wb:
                    return False

                if msg.embeds:
                    embed = msg.embeds[0]
                    if f'{claimer.id}>' in embed.description:
                        return True

                return False

            try:
                msg = await self.bot.wait_for('message', check=wb_check, timeout=10)
            except asyncio.TimeoutError:
                return

            try:
                await msg.delete()
            except discord.HTTPException:
                return

        try:
            await self.bot.wait_for('message', check=check_, timeout=120)
        except asyncio.TimeoutError:
            return

        self.bot.loop.create_task(delete_wb_msg())

        e = discord.Embed(title=f'{name} ({waifu[3]})', color=16745712, description=desc)

        link = f'https://remilia.cirno.pw/portrait/{character_id}.jpg?v=1' if character_id < 1000006 else waifu[4][0]
        e.set_image(url=link)

        await wh.send(embed=e, username=wb.name, avatar_url=wb.avatar_url)


def setup(bot):
    bot.add_cog(ServerSpecific(bot))

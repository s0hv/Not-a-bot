import logging
import re

import disnake
from disnake import utils, Embed
from disnake.ext.commands import BucketType, guild_only, cooldown
from disnake.ext.commands.errors import BotMissingPermissions

from bot.bot import command, has_permissions
from cogs.cog import Cog
from utils.utilities import random_color, wait_for_yes, \
    check_botperm

logger = logging.getLogger('terminal')

pokestats = re.compile(r'''Level (?P<level>\d+) "?(?P<name>.+?)"?
.+?
(Holding: .+?\n)?Nature: (?P<nature>\w+)
HP: (?P<hp>\d+)( - IV: (?P<hp_iv>\d+)/\d+)?
Attack: (?P<attack>\d+)( - IV: (?P<attack_iv>\d+)/\d+)?
Defense: (?P<defense>\d+)( - IV: (?P<defense_iv>\d+)/\d+)?
Sp. Atk: (?P<spattack>\d+)( - IV: (?P<spattack_iv>\d+)/\d+)?
Sp. Def: (?P<spdefense>\d+)( - IV: (?P<spdefense_iv>\d+)/\d+)?
Speed: (?P<speed>\d+)( - IV: (?P<speed_iv>\d+)/\d+)?''')

pokemon = {}
stat_names = ('hp', 'attack', 'defense', 'spattack', 'spdefense', 'speed')
MAX_IV = (31, 31, 31, 31, 31, 31)
MIN_IV = (0, 0, 0, 0, 0, 0)

legendary_detector = re.compile(r'Congratulations (<@!?\d+>|.+?)! You caught a level \d+ (Shiny )?(.+?)!\s*(These colors seem unusual)?.*', re.MULTILINE | re.I)
legendaries = ['arceus', 'articuno', 'azelf', 'blacephalon', 'buzzwole',
               'celebi', 'celesteela', 'cobalion', 'cosmoem', 'cosmog',
               'cresselia', 'darkrai', 'deoxys', 'dialga', 'diancie',
               'entei', 'genesect', 'giratina', 'groudon', 'guzzlord',
               'heatran', 'ho-oh', 'hoopa', 'jirachi', 'kartana', 'keldeo',
               'kyogre', 'kyurem', 'landorus', 'latias', 'latios', 'lugia',
               'lunala', 'magearna', 'manaphy', 'marshadow', 'meloetta',
               'mesprit', 'mew', 'mewtwo', 'moltres', 'naganadel', 'necrozma',
               'nihilego', 'palkia', 'pheromosa', 'phione', 'poipole', 'raikou',
               'rayquaza', 'regice', 'regigigas', 'regirock', 'registeel',
               'reshiram', 'shaymin', 'silvally', 'solgaleo', 'stakataka',
               'suicune', 'tapu bulu', 'tapu fini', 'tapu koko', 'tapu lele',
               'terrakion', 'thundurus', 'tornadus', 'type: null', 'uxie',
               'victini', 'virizion', 'volcanion', 'xerneas', 'xurkitree',
               'yveltal', 'zapdos', 'zekrom', 'zeraora', 'zygarde',
               'meltan', 'melmetal', 'zacian', 'zamazenta', 'eternatus',
               'kubfu', 'urshifu', 'calyrex']


class Pokemon(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.poke_spawns = {}

    @staticmethod
    async def create_pokelog(ctx):
        guild = ctx.guild
        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(send_messages=False),
            guild.me: disnake.PermissionOverwrite(send_messages=True,
                                                  embed_links=True)
        }

        try:
            channel = await guild.create_text_channel('pokelog', overwrites=overwrites,
                                                      reason=f'{ctx.author} created pokelog')
        except disnake.HTTPException as e:
            return await ctx.send(f'Failed to create pokelog because of an error\n{e}')

        await ctx.send(f'Pokelog created in {channel.mention}')

    @command()
    @cooldown(1, 5, BucketType.guild)
    @guild_only()
    async def pokelog(self, ctx):
        """
        To log caught pokecord legendaries and shinies you need a channel name pokelog
        You can use this command to set one up with correct perms

        To include more pokemon or exclude pokemon you need to edit the
        channel description. The format is as follows
        ```
        ---
        Phione
        Shaymin

        +++
        Beldum
        Metang
        Metagross
        ```

        where pokemon under the --- are excluded and pokemon under +++ are included
        in pokelog. The name of the pokemon must be the same what p!info gives
        of that pokemon. Excluding also overrides including so if you put a pokemon
        to be excluded and included it will be excluded. Shinies are logged no matter the settings
        """
        channel = utils.find(lambda c: c.name == 'pokelog' and isinstance(c, disnake.TextChannel), ctx.guild.channels)
        if not channel:
            if not check_botperm('manage_channels', ctx=ctx, me=ctx.author):
                return await ctx.send('Pokelog channel not present')

            check_botperm('manage_channels', ctx=ctx, raise_error=BotMissingPermissions)

            await ctx.send('Pokelog channel not present. Do you want to create one (Y/N)')
            msg = await wait_for_yes(ctx, 30)
            if not msg:
                return

            await self.create_pokelog(ctx)
            return

        await ctx.send(f'Current pokelog channel is {channel.mention}\n'
                       'Make sure this bot has send messages and embed links perms set to ✅')

    @command()
    @guild_only()
    @has_permissions(manage_channels=True)
    @cooldown(1, 1, BucketType.guild)
    async def log_pokemon(self, ctx, message: disnake.Message):
        """
        This command can be used to force log any pokemon to the pokelog.
        This is done by linking the message where the pokemon is caught
        (usually in the format of "Congratulations @user! You caught a level 10 Magikarp!")

        Usage:
            {prefix}{name} https://discord.com/channels/353927534439825429/354712220761980939/826470021713625169
        """
        link = message.jump_url

        if not self._is_pokebot(message.author.id):
            await ctx.send(f'Message not from a supported bot. {link}')
            return

        success = await self._post2pokelog(message)
        if not success:
            await ctx.send(f'No pokelog found or failed to scan pokemon from message {link}')
        else:
            await ctx.send('Sent pokelog message')

    async def _post2pokelog(self, message):
        if not message.guild:
            return

        channel = utils.find(lambda c: c.name == 'pokelog' and isinstance(c, disnake.TextChannel), message.guild.channels)
        if not channel:
            return

        perms = channel.permissions_for(message.guild.get_member(self.bot.user.id))
        if not (perms.send_messages and perms.read_messages and perms.embed_links):
            return

        match = legendary_detector.match(message.content)
        if not match:
            return

        mention, shiny, poke, shiny2 = match.groups()
        shiny = shiny or shiny2

        include = []
        exclude = []
        if channel.topic:
            container = None
            for line in channel.topic.split('\n'):
                line = line.strip()
                if not line:
                    continue

                if line == '---':
                    container = exclude
                    continue

                if line == '+++':
                    container = include
                    continue

                if container is not None:
                    container.append(line.lower())

        if poke.lower() not in legendaries and not shiny and poke.lower() not in include:
            return

        if poke.lower() in exclude and not shiny:
            return

        if shiny:
            shiny = '-shiny'
        else:
            shiny = ''

        poke_fmt = poke.lower().replace('♂', 'm').replace('♀', 'f')
        poke_fmt = re.sub('[-. :]', '', poke_fmt)

        # Hardcode unown to always return the link to unown f since
        # that's the only unown in pokecord
        if 'unown' in poke_fmt:
            poke_fmt = 'unown-f'
            poke = 'Unown-f'

        if 'alolan' in poke_fmt:
            poke_fmt = poke_fmt.replace('alolan', '').strip() + '-alola'
            icon_fmt = ' '.join(poke.split(' ')[1:]) + '-alola'
        else:
            icon_fmt = poke

        # Temp fix until pokemon showdown adds sprites
        if 'meltan' in poke_fmt:
            icon = 'https://cdn.bulbagarden.net/upload/3/34/808MS.png'
            if shiny:
                url = 'https://i.imgur.com/m2YsdDT.png'
            else:
                url = 'https://i.imgur.com/fdrf77L.png'

        elif 'melmetal' in poke_fmt:
            icon = 'https://cdn.bulbagarden.net/upload/f/f1/809MS.png'
            if shiny:
                url = 'https://i.imgur.com/F1N9TQm.png'
            else:
                url = 'https://i.imgur.com/1M3QklX.png'

        elif 'detectivepikachu' in poke_fmt:
            icon = ''
            if shiny:
                url = 'https://i.imgur.com/5YWs0rA.png'
            else:
                url = 'https://i.imgur.com/9Sfddti.png'

        else:
            url = 'http://play.pokemonshowdown.com/sprites/xyani{}/{}.gif'.format(shiny, poke_fmt)
            icon_fmt = re.sub(' |: ', '-', icon_fmt).lower().replace('♂', '-m').replace('♀', '-f').replace('.', '')
            icon = f'https://raw.githubusercontent.com/msikma/pokesprite/master/icons/pokemon/{shiny[1:] or "regular"}/{icon_fmt}.png'

        desc = f'{mention} caught a **{"Shiny " if shiny else ""}{poke}**\n' \
               f'[Jump to message]({message.jump_url})'
        embed = Embed(description=desc, colour=random_color())
        embed.set_image(url=url)
        embed.set_thumbnail(url=icon)

        await channel.send(embed=embed)
        return True

    @staticmethod
    def _is_spawn(msg):
        if msg.embeds:
            embed = msg.embeds[0]
            return isinstance(embed.title, str) and 'wild' in embed.title.lower()

        return False

    def _is_pokebot(self, uid) -> bool:
        # Ignore others than pokecord
        # old pokecord id: 365975655608745985
        # new pokecord and poketwo
        return self.bot.test_mode or uid in (665301904791699476, 716390085896962058)

    @Cog.listener()
    async def on_message(self, message):
        if not self._is_pokebot(message.author.id):
            return

        if message.content:
            return await self._post2pokelog(message)

        #if self._is_spawn(message):
         #   self.poke_spawns[message.guild.id] = message.embeds[0].image.url

    """
    Unused code. Removed for same reason as guess_pokemon
    def get_match(self, img):
        raise NotImplementedError('Now uses a cnn instead of phash')
        binarydiff = self.only_hash != imagehash.phash(img,
                                                       hash_size=16,
                                                       highfreq_factor=6).hash.reshape(1, -1)
        hammingdiff = binarydiff.sum(axis=1)
        closest_match = numpy.argmin(hammingdiff)

        return self.poke_names[closest_match]

    async def match_pokemon(self, url):
        async with await self.bot.aiohttp_client.get(url) as r:
            data = BytesIO(await r.content.read())

        return await self.bot.loop.run_in_executor(self.bot.threadpool, self.get_match, Image.open(data))
        
    """


def setup(bot):
    bot.add_cog(Pokemon(bot))

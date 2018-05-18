import re
import math
import csv
import json
from bot.globals import POKESTATS
import os
from cogs.cog import Cog
from bot.bot import command
from discord.ext.commands import cooldown
from bot.exceptions import BotException
from discord.ext.commands.errors import BadArgument
from utils.utilities import basic_check
from discord.embeds import Embed, EmptyEmbed
from discord.errors import HTTPException
from discord.ext.commands.errors import UserInputError
from discord.ext.commands.converter import UserConverter


pokestats = re.compile(r'Level (?P<level>\d+) "?(?P<name>.+?)"?\n.+?\n(Holding: .+?\n)?Nature: (?P<nature>\w+)\nHP: (?P<hp>\d+)\nAttack: (?P<attack>\d+)\nDefense: (?P<defense>\d+)\nSp. Atk: (?P<spattack>\d+)\nSp. Def: (?P<spdefense>\d+)\nSpeed: (?P<speed>\d+)')
pokemon = {}
stat_names = ('hp', 'attack', 'defense', 'spattack', 'spdefense', 'speed')
MAX_IV = (31, 31, 31, 31, 31, 31)
MIN_IV = (0, 0, 0, 0, 0, 0)

# Stats taken from https://www.kaggle.com/mylesoneill/pokemon-sun-and-moon-gen-7-stats
with open(os.path.join(POKESTATS, 'pokemon.csv'), 'r', encoding='utf-8') as f:
    reader = csv.DictReader(f)
    keys = ('ndex', 'hp', 'attack', 'defense', 'spattack', 'spdefense', 'speed')
    for row in reader:
        name = None

        if '(Mega ' in row['forme']:
            name = row['forme']
            name = 'mega' + name.split('(Mega')[1].split(')')[0].lower()

        elif '(Primal Reversion)' in row['forme']:
            name = 'primal ' + row['species'].lower()

        else:
            name = row['species'].lower()

        if name in pokemon:
            continue

        pokemon[name] = {k: int(row[k]) for k in keys}

with open(os.path.join(POKESTATS, 'natures.json'), 'r') as f:
    natures = json.load(f)

# Good work from https://github.com/xKynn/PokecordCatcher
with open(os.path.join(POKESTATS, 'pokemonrefs.json'), 'r') as f:
    pokemonrefs = json.load(f)


# Below functions ported from https://github.com/dalphyx/pokemon-stat-calculator
# Formulas from https://bulbapedia.bulbagarden.net/wiki/Statistic
def calc_stat(iv, base, ev=0, level=1, nature=1):
    result = math.floor(((2 * base + iv + ev / 4) * level) / 100 + 5) * nature
    return math.floor(result)


def calc_hp_stats(iv, base, ev, level):
    # No.292 Shedinja's HP always be 1.
    if base == 1:
        return 1

    result = ((2 * base + iv + ev / 4) * level) / 100 + level + 10
    return math.floor(result)


def get_base_stats(name: str):
    poke = pokemon.get(name.lower())
    if not poke:
        raise BotException(f"Could not find pokemon `{name}`"
                           "Make sure you replace the nickname to the pokemons real name or this won't work")

    return tuple(poke[stat] for stat in stat_names)


def calc_all_stats(name, level, nature, evs=(100, 100, 100, 100, 100, 100), ivs=MAX_IV, with_max_level=False):
    if isinstance(nature, str):
        nature_ = natures.get(nature.lower())
        if not nature_:
            raise BotException(f'Could not find nature `{nature}`')

        nature = nature_

    base_stats = get_base_stats(name)

    def calc_stats(lvl):
        st = [calc_hp_stats(ivs[0], base_stats[0], evs[0], lvl)]

        for i in range(1, 6):
            st.append(calc_stat(ivs[i], base_stats[i], evs[i], lvl, nature[i - 1]))

        return st

    stats = calc_stats(level)
    if with_max_level and level != 100:
        max_stats = calc_stats(100)
    elif with_max_level:
        max_stats = stats

    if with_max_level:
        return stats, max_stats

    return stats


def from_max_stat(min: int, max: int, value: int) -> tuple:
    """
    Gets where the stats stands between the max and min
    Args:
        min: min value
        max: max value
        value: the current value of the stat

    Returns: tuple
        Percentage on how close the value is to the max and the actual diff to max
    """
    d = value - min
    from_max = max - value
    diff = max - min
    if diff == 0:
        delta = 'N/A'
    else:
        delta = d/diff

    return delta, from_max


class Pokemon(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(aliases=['pstats', 'pstat'])
    @cooldown(1, 3)
    async def poke_stats(self, ctx, *, stats=None):
        """
        Calculate how good your pokemons stats are.
        To be used in combination with pokecord

        How to use:
        Use p!info (use whatever prefix pokecord has on the server instead of p!)
        Copy the fields from Level to Speed. Then use the command as follows
        {prefix}pstats

        or manually

        {prefix}pstats Level 100 Pikachu
        2305/2610XP
        Nature: Hasty
        HP: 300
        Attack: 300
        Defense: 300
        Sp. Atk: 300
        Sp. Def: 300
        Speed: 300
        """
        async def process_embed(embed):
            stats = embed.title + '\n' + embed.description.replace('*', '')

            match = pokestats.match(stats)
            if not match:
                await ctx.send("Failed to parse stats. Make sure it's the correct format")
                return

            pokemon_name = pokemonrefs.get(embed.image.url.split('/')[-1].split('.')[0])
            if not pokemon_name:
                await ctx.send('Could not get pokemon name from message. Please give the name of the pokemon')
                msg = await self.bot.wait_for('message', check=basic_check(author=ctx.author, channel=ctx.channel),
                                              timeout=30)
                pokemon_name = msg.content

            stats = match.groupdict()
            stats['name'] = pokemon_name

            return stats

        def check_msg(msg):
            embed = msg.embeds[0]
            if embed.title != EmptyEmbed and embed.title.startswith('Level '):
                return embed

        author = None
        try:
            if stats:
                author = await (UserConverter().convert(ctx, stats))
        except (UserInputError):
            pass

        if not author:
            try:
                stats = int(stats)
            except (ValueError, TypeError):
                author = ctx.author
                not_found = 'Could not find p!info message'
                accept_any = True
                stats = None

        else:
            stats = None
            not_found = f'No p!info message found for user {author}'
            accept_any = False

        if not stats:
            _embed = None
            async for msg in ctx.channel.history():
                if msg.author.id != 365975655608745985:
                    continue
                if not msg.embeds:
                    continue
                embed = msg.embeds[0]
                if embed.title != EmptyEmbed and embed.title.startswith('Level '):
                    if author.avatar_url.startswith(embed.thumbnail.url):
                        _embed = embed
                        break
                    if accept_any and _embed is None:
                        _embed = embed

            if _embed is None:
                await ctx.send(not_found)
                return

            stats = await process_embed(_embed)

        elif isinstance(stats, int):
            try:
                msg = await ctx.channel.get_message(stats)
            except HTTPException as e:
                return await ctx.send(f'Could not get message with id `{stats}` because of an error\n{e}')

            embed = check_msg(msg)
            stats = await process_embed(embed)
        else:
            match = pokestats.match(stats)

            if not match:
                await ctx.send("Failed to parse stats. Make sure it's the correct format")
                return

            stats = match.groupdict()
        try:
            level = int(stats['level'])
        except ValueError:
            raise BadArgument('Could not convert level to integer')

        try:
            for name in stat_names:
                stats[name] = int(stats[name])
        except ValueError:
            raise BadArgument(f'Failed to convert {name} to integer')

        try:
            max_stats, lvl_max = calc_all_stats(stats['name'], level, stats['nature'], with_max_level=True)
            min_stats, lvl_min = calc_all_stats(stats['name'], level, stats['nature'], ivs=MIN_IV, evs=MIN_IV, with_max_level=True)
        except KeyError as e:
            return await ctx.send(f"{e}\nMake sure you replace the nickname to the pokemons real name in the message or this won't work")

        s = f'```py\nLevel {stats["level"]} {stats["name"]}\nStat: Max value | Delta | Percentage'
        if level != 100:
            s += ' | lv 100 stats WIP'
        s += '\n'
        for min_val, max_val, name, max_stat, min_stat in zip(min_stats, max_stats, stat_names, lvl_max, lvl_min):
            diff, from_max = from_max_stat(min_val, max_val, stats[name])
            fill = ' ' * (11 - len(name))
            fill2 = ' ' * (4 - len(str(max_val)))
            fill3 = ' ' * (6 - len(str(from_max)))

            if isinstance(diff, float):
                diff_n = diff
                diff = f'{diff*100:.0f}%'

            s += f'{name}:{fill}{max_stat}{fill2}| {from_max}{fill3}| {diff}'

            if level != 100:
                fill4 = ' ' * (11 - len(diff))
                if diff == 'N/A':
                    s += f'{fill4}| N/A'
                else:
                    delta = max_stat - min_stat
                    diff_max, _ = from_max_stat(min_val, max_val, stats[name] + 1)

                    s += f'{fill4}| {int(min_stat+delta*diff_n)}-{int(min(max_stat, min_stat+delta*diff_max))}'

            s += '\n'
        s += '```'
        await ctx.send(s)

    @command(aliases=['pstats_format'], ignore_extra=True)
    async def pstat_format(self, ctx):
        await ctx.send("""Level 100 Pikachu
        2305/2610XP
        Nature: Hasty
        HP: 300
        Attack: 300
        Defense: 300
        Sp. Atk: 300
        Sp. Def: 300
        Speed: 300""")


def setup(bot):
    bot.add_cog(Pokemon(bot))

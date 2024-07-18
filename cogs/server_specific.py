import asyncio
import logging
import random
import re
import shlex
import textwrap
from collections import Counter
from datetime import datetime
from datetime import timedelta
from difflib import ndiff
from math import ceil
from operator import attrgetter
from typing import Union, Optional

import disnake
import emoji
import numpy as np
import unicodedata
from aioredis import Redis
from aioredis.exceptions import ConnectionError as RedisConnectionError
from asyncpg.exceptions import PostgresError, UniqueViolationError
from colour import Color
from disnake import AllowedMentions
from disnake.errors import HTTPException
from disnake.ext.commands import (BucketType, check, dm_only, is_owner,
                                  BadArgument, cooldown)
from numpy import sqrt
from numpy.random import choice
from tatsu.data_structures import RankingObject
from tatsu.wrapper import ApiWrapper

from bot.bot import (command, has_permissions, bot_has_permissions,
                     Context)
from bot.formatter import EmbedPaginator
from bot.paginator import Paginator
from cogs.cog import Cog
from cogs.colors import Colors
from cogs.voting import Poll
from enums.data_enums import RedisKeyNamespaces
from utils.utilities import (split_string, parse_time, call_later,
                             get_avatar, retry,
                             check_botperm, format_timedelta, DateAccuracy,
                             wait_for_yes, utcnow)

logger = logging.getLogger('terminal')


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


tatsu_user_regex = re.compile(r'.+?Viewing server rankings .+? \[.+? (?P<user>.+?#\d{4}) +[*]{0,2}].+?', re.UNICODE)
tatsu_score_regex = re.compile(r'.+?with a total of `?(?P<score>\d+)`? .+ [*]{0,2}server score[*]{0,2}', re.I | re.U | re.M | re.DOTALL)

# Name, chance of spawning, character id, japanese name, spawn images in a list
waifus = [('Billy Herrington', 3, 1000006, 'ビリー・ヘリントン', ['https://i.imgur.com/ny8IwLI.png', 'https://i.imgur.com/V9X7Rbm.png', 'https://i.imgur.com/RxxYp62.png']),
          ('Sans', 3, 1000007, 'オイラ', ['https://imgur.com/VSet9rA.jpg', 'https://imgur.com/Dv5HNHH.jpg']),
          ]

waifus_tsuma = [
    ('Billy Herrington', 3, 900263, ['https://i.imgur.com/ny8IwLI.png', 'https://i.imgur.com/V9X7Rbm.png', 'https://i.imgur.com/RxxYp62.png']),
    ('Sans', 3, 900264, ['https://imgur.com/VSet9rA.jpg', 'https://imgur.com/Dv5HNHH.jpg']),
    ('Artoria Pendragon', 10, 497, ['https://i.imgur.com/pey3ckb.png',
                                    'https://i.imgur.com/JXPtxvH.png',
                                    'https://i.imgur.com/PTyq3vw.png',
                                    'https://i.imgur.com/UJcZZIl.png',
                                    'https://i.imgur.com/chjdbKl.png',
                                    'https://tsumabot.com/Images/497/5.jpg',
                                    'https://i.imgur.com/clNCrV7.png',
                                    'https://i.imgur.com/evMc389.jpg',
                                    'https://i.imgur.com/YKBjDrJ.png',
                                    'https://imgur.com/z5wWfmR.png',
                                    'https://i.imgur.com/YNdHyPT.jpg',
                                    'https://i.imgur.com/ryV5Xwt.png',
                                    'https://i.imgur.com/4GsSxA1.png',
                                    'https://i.imgur.com/oio5Yqe.png']),
    ('Astolfo', 8, 79995, ['https://i.imgur.com/mT4jo1u.png',
                           'https://i.imgur.com/O2MCa31.jpg',
                           'https://i.imgur.com/DArhRll.jpg',
                           'https://i.imgur.com/IXEYVOV.jpg',
                           'https://i.imgur.com/845UiKU.png',
                           'https://i.imgur.com/yZwOIi7.png',
                           'https://i.imgur.com/81uWiI7.jpg',
                           'https://i.imgur.com/3wxnd1R.png',
                           'https://i.imgur.com/0VMIewR.png',
                           'https://i.imgur.com/3SPQ8Jt.png',
                           'https://i.imgur.com/1cHJCCs.png']),
    ('Inui Toko', 10, 191000, ['https://i.imgur.com/n8vLZBP.jpg',
                               'https://i.imgur.com/bmbURRg.jpg',
                               'https://i.imgur.com/VSuuieD.jpg',
                               'https://i.imgur.com/1mMpHbW.png',
                               'https://i.imgur.com/1mvQYYI.png',
                               'https://i.imgur.com/D2Yl9Z9.png',
                               'https://i.imgur.com/hAO68qG.png',
                               'https://i.imgur.com/nGvfnOa.png',
                               'https://i.imgur.com/mx7jl39.png',
                               'https://i.imgur.com/JBgYoVB.png',
                               'https://i.imgur.com/rYHAXpt.png',
                               'https://i.imgur.com/f5K3ASG.png',
                               'https://i.imgur.com/Qt5Zd9q.png',
                               'https://i.imgur.com/NnBcBCf.png']),
    ('YoRHa 2gou Bgata', 10, 153798, ['https://cdn.myanimelist.net/images/characters/7/337223.jpg',
                                      'https://cdn.myanimelist.net/images/characters/3/392119.jpg',
                                      'https://i.imgur.com/iHIx0QC.jpg',
                                      'https://i.imgur.com/9zUAwjI.jpg',
                                      'https://i.imgur.com/ZFv9NSu.jpg',
                                      'https://i.imgur.com/cXJRcic.jpg',
                                      'https://i.imgur.com/rEWtZot.jpg',
                                      'https://i.imgur.com/zKfPb6w.jpg',
                                      'https://i.imgur.com/uQMAmwM.jpg',
                                      'https://i.imgur.com/WJo7OZl.jpg']),
    ('Gawr Gura', 9, 188696, ['https://i.imgur.com/uXAxNeH.png',
                              'https://i.imgur.com/CBPXwdz.png',
                              'https://i.imgur.com/v1pY2VZ.png',
                              'https://i.imgur.com/5uLHK18.png',
                              'https://i.imgur.com/Z4VqDWK.png',
                              'https://i.imgur.com/ZdCvtPs.png',
                              'https://i.imgur.com/l7PZf3X.png',
                              'https://i.imgur.com/sdZqBg8.png']),
    ('Miku Nakano', 10, 160603, ['https://tsumabot.com/Images/Tsumas/2a9cebd7-57a4-42cf-ac19-20512b73a243.jpg',
                                 'https://tsumabot.com/Images/Tsumas/b7b4cb23-749e-481a-ab95-c789de9258b0.jpg',
                                 'https://i.imgur.com/Q40o0vE.png',
                                 'https://imgur.com/k2jzyab.png',
                                 'https://imgur.com/ZiAoCol.png',
                                 'https://i.imgur.com/lx0lklZ.jpg',
                                 'https://imgur.com/NLVsmUa.png',
                                 'https://i.imgur.com/uiEUw5M.png',
                                 'https://i.imgur.com/9os97EF.png',
                                 'https://imgur.com/zMlusRJ.png',
                                 'https://imgur.com/wUyla41.png',
                                 'https://i.imgur.com/WTM6o4c.png',
                                 'https://i.imgur.com/AY28CoF.png',
                                 'https://i.imgur.com/IFHew18.png']),
    ('Nino Nakano', 10, 161472, ['https://cdn.myanimelist.net/images/characters/5/360121.jpg',
                                 'https://imgur.com/Nr3jJ5g.png',
                                 'https://i.imgur.com/yVLA4Fe.png',
                                 'https://cdn.myanimelist.net/images/characters/3/385946.jpg',
                                 'https://cdn.myanimelist.net/images/characters/12/385951.jpg',
                                 'https://i.imgur.com/0zA2Civ.jpg',
                                 'https://i.imgur.com/2cKoBdR.png',
                                 'https://i.imgur.com/TdcOD29.png',
                                 'https://i.imgur.com/BscfoNX.png',
                                 'https://i.imgur.com/nH5g15G.png',
                                 'https://i.imgur.com/YLP9y05.png',
                                 'https://i.imgur.com/Bgxs3fA.png',
                                 'https://i.imgur.com/mEkIDgE.png',
                                 'https://i.imgur.com/IPkIPH6.png']),
    ('Musashi Miyamoto', 8, 6194, ['https://i.imgur.com/mWlNxJS.jpg',
                                   'https://i.imgur.com/74icPLS.png',
                                   'https://i.imgur.com/1kixdJf.jpg',
                                   'https://i.imgur.com/nZATrTe.jpg',
                                   'https://i.imgur.com/fTF9UFD.jpg']),
    ('Ouzen', 7, 140106, ['https://cdn.myanimelist.net/images/characters/2/337540.jpg',
                          'https://cdn.myanimelist.net/images/characters/2/337577.jpg',
                          'https://cdn.myanimelist.net/images/characters/8/337579.jpg',
                          'https://cdn.myanimelist.net/images/characters/3/337582.jpg',
                          'https://cdn.myanimelist.net/images/characters/12/338457.jpg',
                          'https://cdn.myanimelist.net/images/characters/7/342925.jpg',
                          'https://cdn.myanimelist.net/images/characters/4/355419.jpg',
                          'https://cdn.myanimelist.net/images/characters/14/358235.jpg',
                          'https://i.imgur.com/ulrTIDE.png',
                          'https://cdn.myanimelist.net/images/characters/4/368293.jpg']),
    ('Diego Brando', 9, 20148, ['https://cdn.myanimelist.net/images/characters/7/241077.jpg',
                                'https://cdn.myanimelist.net/images/characters/5/318241.jpg',
                                'https://cdn.myanimelist.net/images/characters/11/326273.jpg',
                                'https://cdn.myanimelist.net/images/characters/8/328089.jpg',
                                'https://cdn.myanimelist.net/images/characters/9/362645.jpg',
                                'https://cdn.myanimelist.net/images/characters/12/372773.jpg',
                                'https://i.imgur.com/EQzXED3.jpg'])
]

waifu_chances = [t[1] for t in waifus]
_s = sum(waifu_chances)
waifu_chances = [p / _s for p in waifu_chances]
del _s

waifu_chances_tsuma = [t[1] for t in waifus_tsuma]
_s = sum(waifu_chances_tsuma)
waifu_chances_tsuma = [p / _s for p in waifu_chances_tsuma]
del _s

TSUMABOT_ID = 722390040977735712

FILTERED_ROLES = {321374867557580801, 331811458012807169, 361889118210359297,
                  380814558769578003, 337290275749756928, 422432520643018773,
                  322837972317896704, 323492471755636736, 329293030957776896,
                  317560511929647118, 363239074716188672, 365175139043901442,
                  585534893593722880}
FILTERED_ROLES = {disnake.Role(guild=None, state=None,  data={"id": id_, "name": ""})
                  for id_ in FILTERED_ROLES}

AVAILABLE_ROLES = {10: {
    disnake.Role(guild=None, state=None,  data={"id": 320674825423159296, "name": "No dignity"}),
    disnake.Role(guild=None, state=None,  data={"id": 322063025903239178, "name": "meem"}),
    disnake.Role(guild=None, state=None,  data={"id": 320667990116794369, "name": "HELL 2 U"}),
    disnake.Role(guild=None, state=None,  data={"id": 320673902047264768, "name": "I refuse"}),
    disnake.Role(guild=None, state=None,  data={"id": 322737580778979328, "name": "SHIIIIIIIIIIIIZZZZZAAAAAAA"}),
    disnake.Role(guild=None, state=None,  data={"id": 322438861537935360, "name": "CHEW"}),
    disnake.Role(guild=None, state=None,  data={"id": 322425271791910922, "name": "deleted-role"}),
    disnake.Role(guild=None, state=None,  data={"id": 322760382542381056, "name": "Couldn't beat me 1 2 3"}),
    disnake.Role(guild=None, state=None,  data={"id": 322761051303051264, "name": "ok"}),
    disnake.Role(guild=None, state=None,  data={"id": 322416531520749568, "name": "degenerate"}),
    disnake.Role(guild=None, state=None,  data={"id": 325627566406893570, "name": "he"}),
    disnake.Role(guild=None, state=None,  data={"id": 325415104894074881, "name": "ew no"}),
    disnake.Role(guild=None, state=None,  data={"id": 325629356309479424, "name": "she"}),
    disnake.Role(guild=None, state=None,  data={"id": 326096831777996800, "name": "new tole"}),
    disnake.Role(guild=None, state=None,  data={"id": 329331992778768397, "name": "to role or not to role"}),
    disnake.Role(guild=None, state=None,  data={"id": 329333048917229579, "name": "DORARARARARARARARARARARARARARARARA"}),
    disnake.Role(guild=None, state=None,  data={"id": 330058759986479105, "name": "The entire horse"}),
    disnake.Role(guild=None, state=None,  data={"id": 330079869599744000, "name": "baguette"}),
    disnake.Role(guild=None, state=None,  data={"id": 330080088597200896, "name": "4 U"}),
    disnake.Role(guild=None, state=None,  data={"id": 330080062441259019, "name": "big guy"}),
    disnake.Role(guild=None, state=None,  data={"id": 336219409251172352, "name": "The whole horse"}),
    disnake.Role(guild=None, state=None,  data={"id": 338238407845216266, "name": "ok masta let's kill da ho"}),
    disnake.Role(guild=None, state=None,  data={"id": 338238532101472256, "name": "BEEEEEEEEEEEEEETCH"}),
    disnake.Role(guild=None, state=None,  data={"id": 340950870483271681, "name": "FEEL THE HATRED OF TEN THOUSAND YEARS!"}),
    disnake.Role(guild=None, state=None,  data={"id": 349982610161926144, "name": "Fruit mafia"}),
    disnake.Role(guild=None, state=None,  data={"id": 380074801076633600, "name": "Attack helicopter"}),
    disnake.Role(guild=None, state=None,  data={"id": 381762837199978496, "name": "Gappy makes me happy"}),
    disnake.Role(guild=None, state=None,  data={"id": 389133241216663563, "name": "Comfortably numb"}),
    disnake.Role(guild=None, state=None,  data={"id": 398957784185438218, "name": "Bruce U"}),
    disnake.Role(guild=None, state=None,  data={"id": 523192033544896512, "name": "Today I will +t random ham"}),
    disnake.Role(guild=None, state=None, data={"id": 884495493160402955, "name": "Fuck you leatherman"}),
    disnake.Role(guild=None, state=None, data={"id": 884495647854710794, "name": "ok i pull up"}),
    },

    365: {
        disnake.Role(guild=None, state=None,  data={"id": 321863210884005906, "name": "What did you say about my hair"}),
        disnake.Role(guild=None, state=None,  data={"id": 320885539408707584, "name": "Your next line's gonna be"}),
        disnake.Role(guild=None, state=None,  data={"id": 321285882860535808, "name": "JJBA stands for Johnny Joestar's Big Ass"}),
        disnake.Role(guild=None, state=None,  data={"id": 330317213133438976, "name": "Dik brothas"}),
        disnake.Role(guild=None, state=None,  data={"id": 322667100340748289, "name": "Wannabe staff"}),
        disnake.Role(guild=None, state=None,  data={"id": 324084336083075072, "name": "rng fucks me in the ASS!"}),
        disnake.Role(guild=None, state=None, data={"id": 884495079518138408, "name": "Jej"}),
        disnake.Role(guild=None, state=None, data={"id": 884496543590285373, "name": "Floppa enthusiast"}),
    },

    548: {
        disnake.Role(guild=None, state=None,  data={"id": 323486994179031042, "name": "I got 2 steel balls and I ain't afraid to use them"}),
        disnake.Role(guild=None, state=None,  data={"id": 321697480351940608, "name": "ORA ORA ORA ORA ORA ORA ORA ORA ORA ORA MUDA MUDA MUDA MUDA MUDA MUDA MUDA MUDA"}),
        disnake.Role(guild=None, state=None,  data={"id": 330440908187369472, "name": "CEO of Heterosexuality"}),
        disnake.Role(guild=None, state=None,  data={"id": 329350731918344193, "name": "4 balls"}),
        disnake.Role(guild=None, state=None,  data={"id": 358615843120218112, "name": "weirdo"}),
        disnake.Role(guild=None, state=None,  data={"id": 336437276156493825, "name": "Wannabe owner"}),
        disnake.Role(guild=None, state=None,  data={"id": 327519034545537024, "name": "food"})

    },

    730: {
        disnake.Role(guild=None, state=None,  data={"id": 326686698782195712, "name": "Made in heaven"}),
        disnake.Role(guild=None, state=None,  data={"id": 320916323821682689, "name": "Filthy acts at a reasonable price"}),
        disnake.Role(guild=None, state=None,  data={"id": 321361294555086858, "name": "Speedwagon best waifu"}),
        disnake.Role(guild=None, state=None,  data={"id": 320879943703855104, "name": "Passione boss"}),
        disnake.Role(guild=None, state=None,  data={"id": 320638312375386114, "name": "Dolphin l̶o̶v̶e̶r̶ fucker"}),
        disnake.Role(guild=None, state=None,  data={"id": 318683559462436864, "name": "Sex pistols ( ͡° ͜ʖ ͡°)"}),
        disnake.Role(guild=None, state=None,  data={"id": 318843712098533376, "name": "Taste of a liar"}),
        disnake.Role(guild=None, state=None,  data={"id": 323474940298788864, "name": "Wannabe bot"}),
        disnake.Role(guild=None, state=None,  data={"id": 325712897843920896, "name": "Can't spell s0hvaperuna"}),
        disnake.Role(guild=None, state=None,  data={"id": 1061291489960923227, "name": "Gary loves you"}),
        disnake.Role(guild=None, state=None,  data={"id": 1061706836723634196, "name": "Smelled the pine trees along the way"}),
    },

    900: {
        disnake.Role(guild=None, state=None,  data={"id": 321310583200677889, "name": "The fucking strong"}),
        disnake.Role(guild=None, state=None,  data={"id": 318432714984521728, "name": "Za Warudo"}),
        disnake.Role(guild=None, state=None,  data={"id": 376789104794533898, "name": "no u"}),
        disnake.Role(guild=None, state=None,  data={"id": 348900633979518977, "name": "Role to die"}),
        disnake.Role(guild=None, state=None,  data={"id": 349123036189818894, "name": "koichipose"}),
        disnake.Role(guild=None, state=None,  data={"id": 318383761953652741, "name": "The Ashura"}),
        disnake.Role(guild=None, state=None,  data={"id": 1260901563128352781, "name": "CURSE YOU BAYLE!"}),
    },

    1500: {
        disnake.Role(guild=None, state=None, data={"id": 968563116130578472, "name": "Radahn festival enjoyer"}),
        disnake.Role(guild=None, state=None, data={"id": 978028956395634779, "name": "Saucy jack"}),
        disnake.Role(guild=None, state=None, data={"id": 1128975230447140894, "name": "member of the En Family"}),
        disnake.Role(guild=None, state=None, data={"id": 1201860328573648936, "name": "Nah, I'd win"}),
        disnake.Role(guild=None, state=None, data={"id": 1201860468734709780, "name": "Perhaps, this is hell"}),
    }
}


class RoleResponse:
    def __init__(self, msg, image_url=None):
        self.msg = msg
        self.img = image_url

    async def send_message(self, ctx: Context, role: disnake.Role = None):
        author = ctx.author
        role_mention = role.mention if role else role

        # Pad longer role names less and shorter strings more
        role_padding = ' ' * random.randint(40, 70) if not role \
            else ' ' * (60 - int(len(role.name) * 1.25))

        description = self.msg.format(
            author=author,
            role=role_mention,
            bot=ctx.bot.user,
            role_padding=role_padding
        )

        if self.img:
            embed = disnake.Embed(description=description)
            embed.set_image(url=self.img)
            await ctx.send(embed=embed, allowed_mentions=AllowedMentions.none())

        else:
            await ctx.send(description, allowed_mentions=AllowedMentions.none())


role_response_success = [
    RoleResponse("You escape {bot.mention}'s hold and get your friend to beat him up. You successfully steal the role {role}", 'https://i.imgur.com/Z6qmUEV.gif'),
    RoleResponse("His smile radiates on your face and blesses you with {role}.", 'https://i.imgur.com/egiCht9.jpg'),
    RoleResponse("You scientifically prove that traps aren't gay and get a role as a reward. {role}"),
    RoleResponse("You have a moment of silence for Billy as he looks upon you and grants you a role. {role}", 'https://i.imgur.com/PRnTXpc.png'),
    RoleResponse("You recite some classical poetry and get a role as a reward for your performance. {role}", 'https://manly.gachimuchi.men/HzmKEk7k.png'),
    RoleResponse("You stare in awe as Pucci removes a disc from his White Snake. He places it in your hand, bestowing upon you the role {role}", 'https://cdn.discordapp.com/attachments/252872751319089153/664747484190343179/image0.png'),
    RoleResponse("You gain a role. That turns you on. {role}", 'https://i.imgur.com/TZIKltp.gif'),
    RoleResponse("You bribe the mods of this server for a new role. {role}"),
    RoleResponse("You weren't supposed to get a role now but you gave yourself one anyways. {role}", 'https://manly.gachimuchi.men/4r38X6qL.gif'),
    RoleResponse("||You gain a new role {role}{role_padding}||"),
    RoleResponse("Our daddy taught us not to be ashamed of our roles. Especially when they're {role}", 'https://manly.gachimuchi.men/POpNeZDE.gif'),
    RoleResponse("The {role}. The {role} is real.", 'https://manly.gachimuchi.men/38pa8425l1zr.gif'),
    RoleResponse("It's your birthday today. You get {role} as a gift."),
]

role_response_fail = [
    RoleResponse("Never lucky <a:tyler1Rage:592360154775945262>"),
    RoleResponse("Due to a technical error the role went to a gang of traps instead <:AstolfoPlushie:592595615188385802><a:AstolfoPlushie:474085216651051010><:AstolfoPlushie:592595615188385802>"),
    RoleResponse("404 Role not found."),
    RoleResponse("{bot.mention} flexes on you as you lay on the ground with no tole.", 'https://i.imgur.com/VFruiTR.gif'),
    RoleResponse("When you realize that you didn't get any roles this time.", 'https://i.imgur.com/YIP6W84.png'),
    RoleResponse("You get offered black market roles but you don't know how to respond. The chance to acquire a role passes by.", 'https://i.imgur.com/Xo7s9Vx.jpg'),
    RoleResponse("You get abused by moderators and gain nothing."),
    RoleResponse("You're just dead weight.", 'https://i.redd.it/m1866wrhfnl21.jpg'),
    RoleResponse("soap rigs the game! <:PeepoEvil:635509941309800478>"),
    RoleResponse("No role goddammit!", 'https://cdn.discordapp.com/attachments/341610158755020820/591706871237312561/1547775958351.gif'),
    RoleResponse("You get canceled on twitter and thus are not eligible to get a role now."),
    RoleResponse("You're finally awake. You hit your head pretty hard there. A new role? Discord? What are you talking about? Epic Games is just about to reveal Fortnite 2! Let's go watch the event."),
    RoleResponse("||No role this time. Maybe next time.{role_padding}||"),
    RoleResponse("I think you got the wrong door. The leatherclub's two blocks down."),
    RoleResponse('', 'https://manly.gachimuchi.men/ll2a095z8whe.jpg'),
    RoleResponse('You know nothing pendejo.'),
    RoleResponse('You get killed by demons while trying to get a role.', 'https://manly.gachimuchi.men/pacbscl1un9a.jpg'),
    RoleResponse('Now YOU give ME a role :index_pointing_at_the_viewer:', 'https://i.imgur.com/OG8Zj6s.png'),
    RoleResponse('Unfortunately for you, however, you are maidenless.', 'https://manly.gachimuchi.men/rz0Xcf91vJTq.png'),
    RoleResponse('CURSE YOU BAYLE!!!! I HEREBY VOW YOU WILL RUE THIS DAY! BEHOLD, A TRUE DRAKE WARRIOR! '
                 'AND I, IGON! YOUR FEARS MADE FLESH! SOLID OF SCALES YOU MAY BE, FOUL DRAGON! '
                 'BUT I WILL RIDDLE WITH HOLES YOUR ROTTEN HIDE! WITH A HAIL OF HARPOONS! WITH EVERY LAST DROP OF MY BEING!\n'
                 'YAAHHHHHHHAAAAAAAAAAAAAAHH!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!')
]

start_date = datetime(year=2020, month=8, day=1, hour=12)


class ServerSpecific(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self.bot.server.add_listener(self.reduce_role_cooldown)
        self.main_whitelist = whitelist
        self.grant_whitelist = grant_whitelist
        self.redis: Redis = self.bot.redis
        self._zetas = {}
        self._d = {}
        self._redis_fails = 0
        self._removing_every = False
        self.replace_tatsu_api = False
        self._using_toletole = {}
        self._tatsu_api = ApiWrapper(self.bot.config.tatsumaki_key)

    async def cog_load(self):
        await super().cog_load()
        await self.load_giveaways()

    def cog_unload(self):
        self._zetas.clear()
        self._d.clear()

        self.bot.server.remove_listener(self.reduce_role_cooldown)
        for g in list(self.bot.every_giveaways.values()):
            g.cancel()

    async def reduce_role_cooldown(self, data):
        user = data.get('user', None)
        if not user:
            return

        user = int(user)

        sql = "UPDATE role_cooldown SET last_use=(last_use - INTERVAL '150' MINUTE ) WHERE uid=$1"
        await self.bot.dbutil.execute(sql, (user,))

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
            timeout = max((row['expires_in'] - utcnow()).total_seconds(), 0)
            if message in self.bot.every_giveaways:
                self.bot.every_giveaways[message].cancel()

            fut = call_later(self._remove_every, self.bot.loop, timeout, guild, channel, message, title, winners,
                             after=lambda f: self.bot.every_giveaways.pop(message, None))
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

    @command()
    @cooldown(1, 4, type=BucketType.user)
    @check(grant_check)
    @bot_has_permissions(manage_roles=True)
    async def grant(self, ctx, user: disnake.Member, *, role: disnake.Role):
        """Give a role to the specified user if you have the perms to do it"""
        guild = ctx.guild
        author = ctx.author

        no = (117256618617339905, 189458911886049281)
        if author.id in no and user.id in no and user.id != author.id:
            return await ctx.send('no')

        noV2 = (189458911886049281, 326524736521633792)
        if author.id in noV2 and user.id in noV2 and user.id != author.id:
            return await ctx.send('👌')

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

    @command()
    @cooldown(2, 4, type=BucketType.user)
    @check(grant_check)
    @bot_has_permissions(manage_roles=True)
    async def ungrant(self, ctx, user: disnake.Member, *, role: disnake.Role):
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

    @command()
    @cooldown(2, 4, type=BucketType.guild)
    @check(grant_check)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def add_grant(self, ctx, role_user: Union[disnake.Role, disnake.Member], *, target_role: disnake.Role):
        """Make the given role able to grant the target role"""
        guild = ctx.guild

        if isinstance(role_user, disnake.Role):
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

    @command()
    @cooldown(1, 4, type=BucketType.user)
    @check(grant_check)
    @has_permissions(administrator=True)
    @bot_has_permissions(manage_roles=True)
    async def remove_grant(self, ctx, role_user: Union[disnake.Role, disnake.Member], *, target_role: disnake.Role):
        """Remove a grantable role from the target role"""
        guild = ctx.guild

        if isinstance(role_user, disnake.Role):
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

    @command()
    @cooldown(2, 5)
    @check(grant_check)
    async def all_grants(self, ctx, role_user: Union[disnake.Role, disnake.User]=None):
        """Shows all grants on the server.
        If user or role provided will get all grants specific to that."""
        sql = f'SELECT role, user_role, uid FROM role_granting WHERE guild={ctx.guild.id}'
        if isinstance(role_user, disnake.Role):
            sql += f' AND user_role={role_user.id}'
        elif isinstance(role_user, disnake.User):
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
        paginator = EmbedPaginator('Role grants')
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

        view = Paginator(paginator.pages, show_stop_button=True, hide_page_count=True, page_to_footer=True)
        await view.send(ctx)

    @command(aliases=['get_grants', 'grants'])
    @cooldown(1, 4)
    @check(grant_check)
    async def show_grants(self, ctx, user: disnake.Member=None):
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

    @command(aliases=['flip'])
    @is_owner()
    @check(main_check)
    async def flip_the_switch(self, ctx, value: bool=None):
        if value is None:
            self.bot.anti_abuse_switch = not self.bot.anti_abuse_switch
        else:
            self.bot.anti_abuse_switch = value

        await ctx.send(f'Switch set to {self.bot.anti_abuse_switch}')

    @command()
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

    @command()
    @cooldown(1, 600)
    @bot_has_permissions(manage_guild=True)
    @check(main_check)
    async def rotate(self, ctx, *, rotate_emojis: str=None):
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
                       '🇭', '🅱', '🎃', '💀', '👻', '🍞 ', '🍌'}
        emoji_blacklist = {'🇦', '🇧', '🇨', '🇩', '🇪', '🇫', '🇬', '🇭', '🇮', '🇯', '🇰', '🇱',
                           '🇲', '🇳', '🇴', '🇵', '🇶', '🇷', '🇹', '🇺', '🇻', '🇼', '🇽', '🇾',
                           '🇿', '🇸'}

        rotate = ''
        if rotate_emojis is not None:
            all_emojis = rotate_emojis.replace('  ', ' ').split(' ')
            if len(all_emojis) > 2:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send('Too many emojis given')

            for rotate_emoji in all_emojis:
                emoji_full = rotate_emoji
                rotate_emoji = ''.join(rotate_emoji[:2])
                invalid = True
                emoji_check = rotate_emoji

                if len(rotate_emoji) > 1:
                    try:
                        emojis = self.extract_emojis(rotate_emoji)
                    except ValueError:
                        ctx.command.reset_cooldown(ctx)
                        return await ctx.send(f'Invalid emoji {emoji_full}', allowed_mentions=AllowedMentions.none())

                    if len(emojis) != 1:
                        ctx.command.reset_cooldown(ctx)
                        return await ctx.send(f'Invalid emoji {emoji_full}', allowed_mentions=AllowedMentions.none())

                    emoji_check = emojis[0]

                if emoji_check in emoji_blacklist:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send(f'Invalid emoji {emoji_full}', allowed_mentions=AllowedMentions.none())

                if len(emoji.get_emoji_regexp().findall(emoji_check)) == len(rotate_emoji):
                    invalid = False

                if invalid:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send(f'Invalid emoji {emoji_full}', allowed_mentions=AllowedMentions.none())

                rotate += rotate_emoji

        elif rotate_emojis is None:
            rotate = random.choice(list(emoji_faces))

        try:
            await ctx.guild.edit(name=rotate * (100 // (len(rotate))))
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to change name because of an error\n{e}')
        else:
            await ctx.send('♻')

    async def _toggle_every(self, channel, winners: int, expires_in):
        """
        Creates a toggle every giveaway in my server. This is triggered either
        by the toggle_every command or every n amount of votes in dbl
        Args:
            channel (disnake.TextChannel): channel where the giveaway will be held
            winners (int): amount of winners
            expires_in (timedelta): Timedelta denoting how long the giveaway will last

        Returns:
            nothing useful
        """
        guild = channel.guild
        perms = channel.permissions_for(guild.get_member(self.bot.user.id))
        if not perms.manage_roles and not perms.administrator:
            return await channel.send('Invalid server perms')

        role = guild.get_role(884490396225388585 if not self.bot.test_mode else 440964128178307082)
        if role is None:
            return await channel.send('Every role not found')

        sql = 'INSERT INTO giveaways (guild, title, message, channel, winners, expires_in) VALUES ($1, $2, $3, $4, $5, $6)'

        now = utcnow()
        expired_date = now + expires_in
        sql_date = expired_date

        title = 'Toggle the every role on the winner.'
        embed = disnake.Embed(title='Giveaway: {}'.format(title),
                              description='React with <:GWjojoGachiGASM:363025405562585088> to enter',
                              timestamp=expired_date)
        text = 'Expires at'
        if winners > 1:
            text = '{} winners | '.format(winners) + text
        embed.set_footer(text=text, icon_url=get_avatar(self.bot.user))

        message = await channel.send(embed=embed)
        try:
            await message.add_reaction('GWjojoGachiGASM:363025405562585088')
        except (disnake.HTTPException, disnake.ClientException):
            pass

        try:
            await self.bot.dbutil.execute(sql, (guild.id, 'Toggle every',
                                                message.id, channel.id,
                                                winners, sql_date))
        except PostgresError:
            logger.exception('Failed to create every toggle')
            return await channel.send('SQL error')

        task = call_later(self._remove_every, self.bot.loop, expires_in.total_seconds(),
                          guild.id, channel.id, message.id, title, winners)

        self.bot.every_giveaways[message.id] = task

    @command()
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

    async def _remove_every(self, guild, channel, message, title, winners):
        guild = self.bot.get_guild(guild)
        if not guild:
            await self.delete_giveaway_from_db(message)
            return

        role = guild.get_role(884490396225388585 if not self.bot.test_mode else 440964128178307082)
        if role is None:
            await self.delete_giveaway_from_db(message)
            return

        channel = self.bot.get_channel(channel)
        if not channel:
            await self.delete_giveaway_from_db(message)
            return

        try:
            message = await channel.fetch_message(message)
        except disnake.NotFound:
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
            description = 'Winners: {}'.format('\n'.join(user.mention for user in winners))

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

        embed = disnake.Embed(title=title, description=description[:2048], timestamp=utcnow())
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

        if message.type != disnake.MessageType.default:
            return

        if isinstance(message.author, disnake.User):
            return

        moderator = self.bot.get_cog('Moderator')
        if not moderator:
            return

        blacklist = moderator.automute_blacklist.get(guild.id, ())

        if message.channel.id in blacklist or message.channel.id in (384422173462364163, 484450452243742720):
            return

        user = message.author
        whitelist = moderator.automute_whitelist.get(guild.id, ())
        invulnerable = disnake.utils.find(lambda r: r.id in whitelist,
                                          user.roles)

        if invulnerable is not None:
            return

        mute_role = self.bot.guild_cache.mute_role(message.guild.id)
        mute_role = disnake.utils.find(lambda r: r.id == mute_role,
                                       message.guild.roles)
        if not mute_role:
            return

        if mute_role in user.roles:
            return

        if not check_botperm('manage_roles', guild=message.guild, channel=message.channel):
            return

        key = f'{RedisKeyNamespaces.Automute.value}:{message.guild.id}:{user.id}'
        try:
            value = await self.redis.get(key)
        except RedisConnectionError:
            self._redis_fails += 1
            if self._redis_fails > 1:
                self.bot.redis = None
                self.redis = None
                await self.bot.get_channel(252872751319089153).send('Manual redis restart required')
                return

            from aioredis.client import Redis
            logger.exception('Connection closed. Reconnecting')
            redis = self.bot.create_redis()

            old = self.bot.redis
            # Connect
            await redis.ping()

            old: Redis = self.bot.redis
            await old.close()
            self.bot.redis = redis
            self.redis = redis
            del old
            return

        self._redis_fails = 0

        if value:
            score, repeats, last_msg = value.decode('utf-8').split(':', 2)
            score = float(score)
            repeats = int(repeats)
        else:
            score, repeats, last_msg = 0, 0, None

        ttl = await self.redis.ttl(key)
        certainty = 0
        created_td = (utcnow() - user.created_at)
        joined_td = (utcnow() - user.joined_at)
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
            embed = disnake.Embed(title='Moderation action [AUTOMUTE]',
                                  description=d, timestamp=utcnow())
            embed.add_field(name='Reason', value='Spam')
            embed.add_field(name='Certainty', value=certainty)
            embed.add_field(name='link', value=url)
            embed.set_thumbnail(url=user.display_avatar.url)
            embed.set_footer(text=str(self.bot.user), icon_url=self.bot.user.display_avatar.url)
            msg = await moderator.send_to_modlog(guild, embed=embed)

            await moderator.add_timeout(await self.bot.get_context(message), guild.id, user.id,
                                        utcnow() + time,
                                        time.total_seconds(),
                                        reason='Automuted for spam. Certainty %s' % certainty,
                                        author=guild.me,
                                        modlog_msg=msg.id if msg else None)

            score = 0
            msg = ''

        await self.redis.set(key, f'{score}:{repeats}:{msg}', ex=old_ttl)

    @command()
    @check(lambda ctx: ctx.author.id==302276390403702785)  # Check if chad
    async def rt2_lock(self, ctx):
        if ctx.channel.id != 341610158755020820:
            return await ctx.send("This isn't rt2")

        mod = self.bot.get_cog('Moderator')
        if not mod:
            return await ctx.send("This bot doesn't support locking")

        await mod._set_channel_lock(ctx, True)

    # noinspection PyUnreachableCode
    async def edit_user_points(self, uid, guild_id, score: int, action='remove'):
        raise NotImplementedError('Tatsu api broke')
        if not self.bot.config.tatsumaki_key:
            return

        limit = 50000
        m, left = divmod(score, limit)
        scores = [limit for _ in range(m)]
        if left:
            scores.append(left)

        if not scores:
            return

        url = f'https://api.tatsumaki.xyz/guilds/{guild_id}/members/{uid}/points'
        headers = {'Authorization': self.bot.config.tatsumaki_key,
                   'Content-Type': 'application/json'}
        body = {'action': action}

        for score in scores:
            body['amount'] = score
            async with aiohttp.ClientSession() as client:
                async with client.put(url, headers=headers, json=body) as r:
                    if r.status != 200:
                        return False

        return True

    async def get_user_stats(self, uid, guild_id) -> Optional[RankingObject]:
        if not self.bot.config.tatsumaki_key:
            return

        user = await self._tatsu_api.get_member_ranking(guild_id, uid)
        if isinstance(user, Exception):
            return

        return user

    async def get_role_chance(self, ctx, member, user_roles=None,
                              delta_days=None):
        if not user_roles:
            user_roles = set(ctx.author.roles)

        if not delta_days:
            first_join = await self.dbutil.get_join_date(member.id, ctx.guild.id) \
                         or ctx.author.joined_at
            delta_days = (utcnow() - first_join).days

        score = None

        # Replace tatsu api with a command parser
        if self.replace_tatsu_api:
            await ctx.send(f'{ctx.author} use the `gaytop` command so the bot can read your server score.\n'
                           'This is required because Tatsu API is broke and has outdated scores.')

            def check(msg):
                nonlocal score
                if msg.author.id != 172002275412279296 or not (msg.content or msg.embeds):
                    return False

                match = tatsu_user_regex.match(msg.content)
                if not match or match.groups()[0].strip() != str(ctx.author):
                    return False

                embed = msg.embeds[0]
                if not embed.description:
                    return False

                match = tatsu_score_regex.match(embed.description)
                if not match:
                    return False

                score = int(match.groups()[0])
                logger.debug(f'Tatsu score for {ctx.author.id} is {score}')
                return True

            msg = None
            try:
                msg = await self.bot.wait_for('message', check=check, timeout=20)
            except asyncio.TimeoutError:
                pass

            if not msg:
                await ctx.send('`gaytop` command result not found. Try again later')
                return

        else:
            user = await self.get_user_stats(member.id, ctx.guild.id)
            score = user and user.score

        if not score:
            await ctx.send('Failed to get server score. Try again later')
            return

        # Give points to people who've been in server for long time
        if score > 100000:
            score += 110 * delta_days

        is_booster = ctx.guild.get_role(585534893593722880) in member.roles

        # Return chances of role
        def role_get(s, r):
            if not is_booster and s < 8000:
                return 0

            return (s / 3000 + 70 / r) * (r**-3 + (r * 0.5)**-2 + (r * 100)**-1)

        role_count = len(user_roles - FILTERED_ROLES)
        return role_get(int(score), role_count)

    # Disabled until tatsu api supports it
    @command(aliases=['goodbye_every'], enabled=False, hidden=True)
    @check(create_check((217677285442977792,)))
    #@check(main_check)
    @cooldown(1, 20, BucketType.user)
    async def remove_every(self, ctx):
        """
        Remove every role. This costs 100k tatsu server points
        """
        member = ctx.author
        guild = ctx.guild
        if self._removing_every:
            await ctx.send('Try again later')
            return

        every = guild.get_role(884490396225388585)
        # every = guild.get_role(355372842088660992)
        if not every:
            return

        if every not in member.roles:
            await ctx.send("You don't have the every role")
            return

        points = await self.get_user_stats(member.id, guild.id) or {}
        points = points.get('points')
        if not points:
            await ctx.send('Failed to get server points. Try again later')
            return

        points = int(points)
        cost = 100000  # 100k

        if points < cost:
            await ctx.send(f"You don't have enough tatsu points. You have {points} points and you need {cost-points} more")
            return

        try:
            await member.remove_roles(every, reason='Every removal for 100k tatsu points')
        except disnake.HTTPException as e:
            await ctx.send(f'Failed to remove every because of an error.\n{e}')
            await self.edit_user_points(member.id, guild.id, cost, 'add')
            return

        c = guild.get_channel(252872751319089153)
        await c.send(f't#points remove {member.id} {cost}\n<@123050803752730624>')
        self._removing_every = True

        await ctx.send('Every removed successfully')

        def e_check(msg):
            if msg.channel.id != c.id:
                return False

            return msg.content and msg.content.startswith('t#points')

        def set_false(_):
            self._removing_every = False

        self.bot.loop.create_task(self.bot.wait_for('message', check=e_check, timeout=60*60*16)).\
            add_done_callback(set_false)

    @command(aliases=['tc', 'tolechance'])
    @check(create_check((217677285442977792,)))
    @cooldown(1, 10, BucketType.user)
    async def rolechance(self, ctx):
        """
        Chance of tole
        """
        chances = await self.get_role_chance(ctx, ctx.author)
        if chances is None:
            return

        chances = min(1, chances)
        await ctx.send(f'Your chances of getting a role is {chances*100:.1f}%')

    async def get_role_cooldown(self, ctx):
        # Get last use timestamp
        try:
            row = await self.dbutil.get_last_role_time(ctx.author.id)
        except PostgresError:
            await ctx.send('Failed to get timestamp of last use of this command. Try again later')
            return False

        # Check that cooldown has passed
        if row:
            role_cooldown = (utcnow() - row[0])

            return role_cooldown

        return None

    @staticmethod
    def get_cooldown_days(member):
        return 4 if member.premium_since else 7

    @command(aliases=['rcd', 'tcd'])
    @check(create_check((217677285442977792,)))
    @cooldown(1, 10, BucketType.user)
    async def rolecooldown(self, ctx):
        cd = await self.get_role_cooldown(ctx)
        if cd is False:
            return

        cooldown_days = self.get_cooldown_days(ctx.author)

        if cd is not None and cd.days < cooldown_days:
            t = format_timedelta(timedelta(days=cooldown_days) - cd,
                                 DateAccuracy.Day - DateAccuracy.Hour)
            await ctx.send(f'You can use toletole in {t}')
            return

        await ctx.send('You can use toletole now')

    @command(aliases=['tole_get', 'toletole', 'give_role', 'give_tole'])
    @check(create_check((217677285442977792,)))
    @cooldown(1, 10, BucketType.user)
    async def role_get(self, ctx, mentionable: bool=None):
        """
        Chance to get a role. By default, only gives mentionable roles if no other roles are available.
        This can be changed if you use set mentionable to true.
        e.g.
        `{prefix}{name} on` will also take mentionable roles into account

        Original idea by xerd
        """

        # Skip invocation if waiting for tatsu message
        temp = self._using_toletole.get(ctx.author.id)
        if temp and (utcnow() - temp).total_seconds() < 30:
            return

        # Get last use timestamp
        try:
            row = await self.dbutil.get_last_role_time(ctx.author.id)
        except PostgresError:
            await ctx.send('Failed to get timestamp of last use of this command. Try again later')
            return

        # Check that cooldown has passed
        if row and row[0] is not None:
            cooldown_days = self.get_cooldown_days(ctx.author)

            role_cooldown = (utcnow() - row[0])
            if role_cooldown.days < cooldown_days:
                t = format_timedelta(timedelta(days=cooldown_days) - role_cooldown,
                                     DateAccuracy.Day-DateAccuracy.Hour)
                await ctx.send(f"You're still ratelimited for this command. Cooldown ends in {t}")
                return

        guild = ctx.guild
        first_join = await self.dbutil.get_join_date(ctx.author.id, guild.id) or ctx.author.joined_at
        delta_days = (utcnow() - first_join).days

        # Set of all the roles a user can get
        roles = set()
        mentionable_roles = set()

        # Get available roles
        for days, toles in AVAILABLE_ROLES.items():
            if days < delta_days:
                for role in toles:
                    role = guild.get_role(role.id)
                    # Check that the role exists and the if it can be mentionable
                    if not role:
                        continue

                    if role.mentionable:
                        mentionable_roles.add(role)
                    else:
                        roles.add(role)

        # Check that roles are available
        user_roles = set(ctx.author.roles)
        roles = roles - user_roles
        mentionable_roles = mentionable_roles - user_roles

        if mentionable or (mentionable is None and not roles):
            roles.update(mentionable_roles)

        if not roles:
            if mentionable is False:
                await ctx.send('No unmentionable roles available. Use `!toletole on` to include mentionable roles.')
            else:
                await ctx.send('No roles available to you at the moment. Try again after being more active')
            return

        self._using_toletole[ctx.author.id] = utcnow()
        chances = await self.get_role_chance(ctx, ctx.author, user_roles, delta_days)
        if chances is None:
            return

        if chances < 0.000001:
            await ctx.send('0% chances of getting a role. Try again after being more active')
            return

        try:
            await self.dbutil.update_last_role_time(ctx.author.id, utcnow())
        except PostgresError:
            await ctx.send('Failed to update cooldown of the command. Try again in a bit')
            return

        self._using_toletole.pop(ctx.author.id, None)

        got_new_role = random.random() < chances
        if got_new_role:
            role = choice(list(roles))
            await ctx.author.add_roles(role)
            await choice(role_response_success).send_message(ctx, role)

        else:
            await choice(role_response_fail).send_message(ctx)

    @command()
    @is_owner()
    async def check_role_response(self, ctx: Context, response_idx: int, is_success: bool = True):
        role = ctx.author.roles[-1]
        if is_success:
            await role_response_success[response_idx].send_message(ctx, role)
        else:
            await role_response_fail[response_idx].send_message(ctx)

    @command(hidden=True)
    @cooldown(1, 60, BucketType.channel)
    async def zeta(self, ctx, channel: disnake.TextChannel=None):
        try:
            await ctx.message.delete()
        except disnake.HTTPException:
            pass

        if not channel:
            channel = ctx.channel

        # Check that we can retrieve a webhook
        try:
            wh = await channel.webhooks()
            if not wh:
                return

            wh = wh[0]
        except disnake.HTTPException:
            return

        # Get random waifu
        waifu = choice(len(waifus), p=waifu_chances)
        waifu = waifus[waifu]

        # Get initials for a character
        def get_inits(s):
            inits = ''

            for c in s.split(' '):
                inits += f'{c[0].upper()}. '

            return inits

        initials = get_inits(waifu[0])

        # Get image link
        link = choice(waifu[4])
        img_number = f'Character image #{waifu[4].index(link)}'

        # Description of the spawn message
        desc = """
        A waifu/husbando appeared!
        Try guessing their name with `.claim <name>` to claim them!

        Hints:
        This character's initials are '{}'
        Use `.lookup <name>` if you can't remember the full name.

        (If the image is missing, click [here]({}).)"""

        # Create spawn message
        desc = textwrap.dedent(desc).format(initials, link).strip()
        c = random.choice(list(Color('#e767e4').range_to('#b442c3', 100)))
        e = disnake.Embed(title='Character', color=int(c.get_hex_l().replace('#', ''), 16),
                          description=desc)
        e.set_image(url=link)
        wb = self.bot.get_user(472141928578940958)

        await wh.send(embed=e, username=wb.name, avatar_url=wb.display_avatar.url)

        # Checking for character claims below
        guessed = False

        # Check that the message is a valid waifubot command
        def check_(msg):
            if msg.channel != channel:
                return False

            content = msg.content.lower()
            if content.startswith('.claim '):
                return True

            if msg.author.id == 472141928578940958:
                return True

            return False

        name = waifu[0]
        claimer = None
        self._zetas[ctx.guild.id] = ctx.message.id

        name_formatted = name.replace('-', '').lower()

        # Claim check loop
        while guessed is False:
            try:
                msg = await self.bot.wait_for('message', check=check_, timeout=360)
            except asyncio.TimeoutError:
                guessed = None
                continue

            if ctx.guild.id in self._zetas and ctx.message.id != self._zetas[ctx.guild.id]:
                return

            if msg.author.id == 472141928578940958:
                if not msg.embeds:
                    continue

                # If waifubot spawns a new character remove this zeta spawn
                if msg.embeds[0].title == 'Character':
                    guessed = None

                continue

            # Check if correct character name given
            guess = ' '.join(msg.content.split(' ')[1:]).replace('-', '').lower()
            if guess != name_formatted:
                # Check if name was close
                diff = len([c for c in ndiff(name_formatted, guess) if c.startswith('+')])
                if diff == 0:
                    diff = len([c for c in ndiff(name_formatted, guess) if c.startswith('-')])

                if 0 < diff < 6:
                    await wh.send(f"You were close, but wrong. What you gave was {diff} letter(s) off.",
                                  username=wb.name, avatar_url=wb.display_avatar.url)
                else:
                    await wh.send("That isn't the right name.", username=wb.name, avatar_url=wb.display_avatar.url)

                continue

            await wh.send(f'Nice {msg.author.mention}, you claimed [ζ] {name}!', username=wb.name, avatar_url=wb.display_avatar.url)
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
        Local ID: {random.randint(2000, 5000)}
        Global ID: {random.randint(30661764, 45992646)}
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

        # Check if .latest called
        def check2_(msg):
            if msg.channel != channel:
                return False

            content = msg.content.lower()
            if content.startswith('.latest') and msg.author == claimer:
                return True

            return False

        # Delete waifubot's response to .latest
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
            except disnake.HTTPException:
                return

        try:
            await self.bot.wait_for('message', check=check2_, timeout=120)
        except asyncio.TimeoutError:
            return

        self.bot.loop.create_task(delete_wb_msg())

        e = disnake.Embed(title=f'{name} ({waifu[3]})', color=16745712, description=desc)
        e.set_footer(text=img_number)

        e.set_image(url=link)

        await wh.send(embed=e, username=wb.name, avatar_url=wb.display_avatar.url)

    @command(hidden=True)
    @cooldown(1, 60, BucketType.channel)
    async def tsuma_d(self, ctx: Context, channel: disnake.TextChannel = None):
        try:
            await ctx.message.delete()
        except disnake.HTTPException:
            pass

        if not channel:
            channel = ctx.channel

        # Check that we can retrieve a webhook
        try:
            wh = await channel.webhooks()
            if not wh:
                return

            wh = wh[0]
        except disnake.HTTPException:
            return

        # Get random waifu
        waifu: int = choice(len(waifus_tsuma), p=waifu_chances_tsuma)
        waifu_name, _, tsuma_id, pictures = waifus_tsuma[waifu]

        case_order_insensitive_name = Counter(waifu_name.lower().split(' '))

        name_unmasked = waifu_name.replace(' ', '')
        name_mask = np.zeros((len(name_unmasked),), dtype=bool)

        idx = 0
        space_indices = set()
        for word in waifu_name.split(' '):
            name_mask[idx] = True
            idx += len(word)
            space_indices.add(idx)

        def apply_mask():
            out = ''
            for idx_, char in enumerate(name_unmasked):
                unmasked = name_mask[idx_]
                if idx_ in space_indices:
                    out += ' '

                if unmasked:
                    out += char
                else:
                    out += r' \_ '

            return out

        # Get image link
        image_url = choice(pictures)
        image_number = pictures.index(image_url) + 1

        # Description of the spawn message
        desc = f"""
        Try claiming the tsuma with their name
        `.claim <name>`
        
        Hints
        Use the .hint command to get hints
        
        You can use [this]({image_url}) link to view the image"""

        # Create spawn message
        desc = textwrap.dedent(desc).strip()
        tsuma_embed = disnake.Embed(
            title=apply_mask(),
            color=61183,  # #00EEFF
            description=desc
        )
        tsuma_embed.set_image(url=image_url)
        tsuma_embed.set_footer(text='use .claim <name>')
        tsumabot = ctx.guild.get_member(TSUMABOT_ID) or self.bot.get_user(TSUMABOT_ID)
        if not tsumabot:
            return

        if isinstance(tsumabot, disnake.Member):
            wh_name = tsumabot.display_name
        else:
            wh_name = tsumabot.name

        webhook_kwargs = {
            'username': wh_name,
            'avatar_url': tsumabot.display_avatar.url
        }

        original_message = await wh.send(embed=tsuma_embed, wait=True, **webhook_kwargs)

        # Checking for character claims below
        guessed = False

        # Check that the message is a valid tsumabot command
        def check_(msg):
            if msg.channel != channel:
                return False

            if not msg.content.startswith('.'):
                return False

            content = strip_cmd(msg.content)
            if content.startswith('claim ') or content.startswith('hint'):
                return True

            # Used for despawning
            if msg.author.id == TSUMABOT_ID:
                return True

            return False

        claimer = None
        self._d[ctx.guild.id] = ctx.message.id

        def strip_cmd(s):
            return s.lstrip('. ').lower()

        async def wait_for_claim_msg():
            def tsumabot_check(msg: disnake.Message):
                if msg.channel != channel:
                    return False

                if msg.author.id == TSUMABOT_ID and (msg.content in ('No active spawn yet.', 'Incorrect Name, Try Again.') or msg.content.replace("'", '') == 'Couldnt find spawn. Try Again'):
                    return True

                return False

            while True:
                msg: disnake.Message = await self.bot.wait_for('message',
                                                               check=tsumabot_check)
                try:
                    await msg.delete()
                except disnake.HTTPException:
                    pass

        delete_msg_task = self.bot.loop.create_task(wait_for_claim_msg())

        try:
            # Claim check loop
            while guessed is False:
                try:
                    msg: disnake.Message = await self.bot.wait_for('message', check=check_, timeout=360)
                except asyncio.TimeoutError:
                    guessed = None
                    continue

                # Check if new tsuma spawned or cog unloaded
                if ctx.guild.id not in self._d or ctx.message.id != self._d[ctx.guild.id]:
                    return

                if msg.author.id == TSUMABOT_ID:
                    if not msg.embeds:
                        continue

                    # If tsumabot spawns a new character remove this zeta spawn
                    if '_ ' in msg.embeds[0].title:
                        guessed = None

                    continue

                msg_words = strip_cmd(msg.content).split(' ')
                cmd = msg_words[0].lower()

                if cmd not in ('claim', 'hint'):
                    # something weird happened
                    guessed = None
                    continue

                if cmd == 'hint':
                    if name_mask.sum() == len(name_unmasked) - 1:
                        await wh.send('Out of Hints.', **webhook_kwargs)
                        continue

                    available_indices = np.where(~name_mask)[0]
                    max_revealed = random.randint(int(len(available_indices) * 0.30), int(len(available_indices) * 0.40))
                    max_revealed = min(max(max_revealed, 3), len(available_indices) - 1)

                    name_mask[choice(available_indices, max_revealed, replace=False)] = True

                    tsuma_embed.title = apply_mask()
                    try:
                        await original_message.edit(embed=tsuma_embed)
                    except disnake.HTTPException:
                        return
                    continue

                # Check if correct character name given
                guess = Counter(msg_words[1:])
                if guess != case_order_insensitive_name:
                    await wh.send("Incorrect Name, Try Again.", **webhook_kwargs)
                    continue

                await wh.send(f'Congratulations {msg.author.mention}! You have claimed [Ⅾ] {waifu_name}',
                              wait=True, **webhook_kwargs)
                claimer = msg.author
                guessed = True

                # Description of the spawn message
                desc = f"""
                TsumaID: {tsuma_id}
                
                `.harem` to view your tsumas.
                `.latest` to view your most recent claim.
                
                Image #{image_number} - Click [here]({image_url}) to view"""
                tsuma_embed.description = textwrap.dedent(desc).strip()
                tsuma_embed.title = waifu_name
                tsuma_embed.set_footer(text=f'claimed by: {msg.author.name}', icon_url=msg.author.display_avatar)

                try:
                    await original_message.edit(embed=tsuma_embed)
                except disnake.HTTPException:
                    pass
        finally:
            await asyncio.sleep(0.4)
            delete_msg_task.cancel()

        try:
            self._d.pop(ctx.guild.id)
        except KeyError:
            pass

        async def delete_latest_msg():
            def tsumabot_check(msg: disnake.Message):
                if msg.channel != channel or msg.author.id != TSUMABOT_ID:
                    return False

                if not msg.embeds:
                    return False

                embed = msg.embeds[0]
                if embed.author and embed.author.name == str(claimer):
                    return True

                return False

            try:
                msg: disnake.Message = await self.bot.wait_for('message', check=tsumabot_check, timeout=60)
            except asyncio.TimeoutError:
                return

            try:
                await msg.delete()
            except disnake.HTTPException:
                pass

        latest_desc = f"""
        LocalID: {random.randint(5000, 25000)}
        Tag:
        ❤ Affection: 0"""
        latest_desc = textwrap.dedent(latest_desc).strip()
        latest_embed = disnake.Embed(title=f'{waifu_name} [Ⅾ]', description=latest_desc, color=61183)

        latest_embed.set_author(name=str(claimer), icon_url=claimer.display_avatar.url)
        latest_embed.set_footer(text=f'Image Variant : {image_number}')
        latest_embed.set_image(url=image_url)

        def check_latest(msg: disnake.Message):
            if msg.channel != channel or msg.author != claimer:
                return False

            cmd = strip_cmd(msg.content)
            if not cmd or cmd not in ('last', 'latest'):
                return False

            return True

        try:
            await self.bot.wait_for('message', check=check_latest, timeout=60)
        except asyncio.TimeoutError:
            return

        self.bot.loop.create_task(delete_latest_msg())

        await wh.send(embed=latest_embed, **webhook_kwargs)

    @command(enabled=False, hidden=True)
    @cooldown(1, 10, BucketType.user)
    @check(main_check)
    async def participate(self, ctx):
        """
        Become a valid candidate in the upcoming mod election
        """
        rs = [373810020518985728, 339841138393612288, 343356073186689035]
        guild = ctx.guild
        if [r for r in rs if guild.get_role(r) in ctx.author.roles]:
            await ctx.send("You're already a mod")
            return

        await ctx.send(f"Are you sure you want to participate in the election as a candidate? Once you're in you cannot back out.")
        if not await wait_for_yes(ctx, timeout=15):
            return

        sql = 'UPDATE candidates SET is_participating=TRUE WHERE uid=$1 RETURNING 1'
        try:
            row = await self.dbutil.fetch(sql, (ctx.author.id,), fetchmany=False)
        except:
            await ctx.send('Failed to update participation status.')
            return

        if not row:
            await ctx.send("You're not eligible to become a candidate in the election. Try again next time.")
        else:
            await ctx.send("You have successfully registered as a valid candidate in the elections.")

    @command(enabled=False, hidden=True)
    @cooldown(1, 10, BucketType.user)
    @check(main_check)
    async def set_description(self, ctx, *, description):
        """
        Set your description that can be viewed by others.
        """
        sql = 'UPDATE candidates SET description=$1 WHERE uid=$2 AND is_participating=TRUE RETURNING 1'
        try:
            row = await self.dbutil.fetch(sql, (description, ctx.author.id), fetchmany=False)
        except:
            await ctx.send('Failed to update your description.')
            return

        if not row:
            await ctx.send("You're not participating in the election. Use !participate to become a valid candidate.")
        else:
            await ctx.send("You have successfully updated your description.")

    @command(aliases=['evote'], enabled=False, hidden=True)
    @dm_only()
    @cooldown(1, 10, BucketType.user)
    async def electronic_vote(self, ctx, *, user: disnake.User):
        """
        Vote in the elections. Voting opens on August 1st 12:00 UTC
        """
        if utcnow() < start_date:
            await ctx.send("Voting hasn't started yet")
            return

        guild = self.bot.get_guild(353927534439825429 if self.bot.test_mode else 217677285442977792)
        if not guild:
            logger.warning(f'Guild not found when {ctx.author} tried to evote')
            return

        member = guild.get_member(ctx.author.id)
        if not member:
            try:
                member = await guild.fetch_member(ctx.author.id)
            except disnake.HTTPException:
                logger.exception('Failed to get author for evote')
                return
            if not member:
                logger.warning('Failed to get author for evote')
                return

        if member.id == user.id:
            await ctx.send('Cannot vote for yourself')
            return

        # Around 4 months
        days = 124
        if (utcnow() - member.joined_at).days < days:
            joined_at = await self.dbutil.get_join_date(member.id, guild.id)
            if not joined_at or (utcnow() - joined_at).days < days:
                return await ctx.send("You're not eligible to vote because you haven't been in the server for long enough")

        await ctx.send(f"You're trying to vote for {user} `{user.id}`.\n"
                       f"Type yes to confirm. "
                       f"You cannot change your vote after it has been successfully registered.")

        if not await wait_for_yes(ctx, timeout=15):
            return

        sql = 'INSERT INTO elections (voter_id, candidate_id) SELECT $1, uid FROM candidates WHERE uid=$2 AND is_participating=TRUE RETURNING 1'

        try:
            row = await self.dbutil.fetch(sql, (member.id, user.id), fetchmany=False)
        except UniqueViolationError:
            await ctx.send('Failed to vote because you have already voted')
            return
        except:
            logger.exception(f'Failed to register vote of {user}')
            await ctx.send('Failed to register vote. Try again later')
            return

        if not row:
            await ctx.send(f"Failed to vote for {user} because they aren't participating in the election as a candidate")
        else:
            await ctx.send(f'Successfully registered your vote for {user}')

    @command(enabled=False, hidden=True)
    @check(main_check)
    @cooldown(1, 10, BucketType.user)
    async def candidate(self, ctx, *, member: disnake.Member):
        """
        View the profile of a candidate
        """

        sql = 'SELECT description FROM candidates WHERE uid=$1 AND is_participating=TRUE'

        try:
            row = await self.dbutil.fetch(sql, (member.id,), fetchmany=False)
        except:
            logger.exception(f'Failed to fetch candidate profile for {member}')
            await ctx.send('Failed to fetch the candidate profile.')
            return

        if not row:
            await ctx.send(f'{member} is not participating in the election.')
            return

        description = row['description'] or 'No description'
        title = f'Candidate profile for {member}'
        embed = disnake.Embed(title=title, description=description)
        embed.set_thumbnail(url=get_avatar(member))

        await ctx.send(embed=embed)

    @command(enabled=False, hidden=True)
    @check(main_check)
    @cooldown(2, 10, BucketType.channel)
    async def candidates(self, ctx, show_description=False):
        """
        Get all candidates. Use `{prefix}candidates on` to view descriptions
        """

        sql = 'SELECT uid, description FROM candidates WHERE is_participating=TRUE'
        try:
            rows = await self.dbutil.fetch(sql)
        except:
            await ctx.send('Failed to get candidates. Try again later')
            return

        g = ctx.guild
        members = sorted(
            filter(bool, map(g.get_member, (r['uid'] for r in rows))),
            key=attrgetter('name')
        )
        descriptions = {}
        if show_description:
            descriptions = {r['uid']: r['description'] for r in rows}

        page_size = 10 if not show_description else 1
        page_count = ceil(len(members) / page_size)
        pages = [False for _ in range(page_count)]

        title = "List of all candidates"

        def cache_page(idx):
            if show_description:
                member = members[idx]
                description = descriptions[member.id] or 'No description'
                embed = disnake.Embed(title=f'Candidate profile for {member}', description=description)
                embed.set_thumbnail(url=get_avatar(member))

            else:
                i = idx * page_size
                member_slice = members[i:i + page_size]

                def fmt_user(member):
                    return f'{member} `{member.id}`'

                description = '\n'.join(map(fmt_user, member_slice))

                embed = disnake.Embed(title=title, description=description)

            embed.set_footer(text=f'Page {idx + 1}/{len(pages)}')
            pages[idx] = embed
            return embed

        def get_page(_, idx):
            return pages[idx] or cache_page(idx)

        # await send_paged_message(ctx, pages, True, page_method=get_page)

    # noinspection PyUnreachableCode
    @command(enabled=False, hidden=True)
    @is_owner()
    async def count_votes(self, ctx):
        return
        guild = ctx.guild
        c = guild.get_channel(339517543989379092) if not self.bot.test_mode else ctx
        if not c:
            await ctx.send('channel not found')
            return

        sql = 'SELECT candidate_id FROM elections ORDER BY random()'
        try:
            votes = [r[0] for r in await self.dbutil.fetch(sql)]
        except:
            logger.exception('Fail...')
            await ctx.send('Failed to get votes')
            return

        users = {}
        for uid in set(votes):
            user = guild.get_member(uid)
            if not user:
                try:
                    user = await guild.fetch_member(uid)
                except disnake.HTTPException:
                    continue
            users[uid] = user

        ganypepe = guild.get_member(222399701390065674)
        if ganypepe:
            counter = Counter({ganypepe: 45})
        else:
            counter = Counter()

        chunk_size = 4
        fmt = '{1} new vote(s) for {0} ({2} total)\n'

        for i in range(0, len(votes), chunk_size):
            v = votes[i:i+chunk_size]
            real_votes = [users.get(uid) for uid in v if uid in users]
            new_c = Counter(real_votes)
            counter.update(real_votes)

            m = ''.join(fmt.format(*pair, counter[pair[0]]) for pair in new_c.most_common())
            try:
                await c.send(m)
            except:
                logger.exception('Failed to send message')
                continue

            await asyncio.sleep(10)

        final_fmt = '{0.mention} got a total of {1} votes\n'
        top_5 = counter.most_common()

        final_m = ''.join(final_fmt.format(*pair) for pair in top_5)

        final_m = f'The final result of this election is\n\n{final_m}'
        for m in split_string(final_m, splitter='\n'):
            try:
                await c.send(m)
            except:
                logger.exception(f'Failed to send "{final_m}"')
                await ctx.send('Failed to post final result')
                continue

    @command()
    @is_owner()
    @check(main_check)
    async def color_vote(self, ctx, winners: int, max_votes: int, days: int, test: bool, *, colors: str):
        c: Colors = self.bot.get_cog('Colors')
        colors = shlex.split(colors)
        emotes = ['0️⃣', '1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
        emotes = emotes[:len(colors)]

        new_colors = []

        def do_image():
            from cogs.colors import Color as ServerColor

            for idx, color in enumerate(colors):
                try:
                    color_name = color.split(': ')
                    if len(color_name) == 2:
                        color_name, color = color_name
                    else:
                        color_name = color_name[0]
                        color = color_name

                    color = c.color_from_str(color)
                    if isinstance(color, tuple):
                        color = c.rgb2hex(*color)

                    color = ServerColor.from_hex(f'{idx}. {color_name}', color[:7], set_lab=True)
                    new_colors.append(color)
                except (TypeError, ValueError):
                    raise BadArgument(f'Failed to create image using color {color}')

            return c._sorted_color_image(new_colors)

        if test:
            data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_image)
            await ctx.send(file=disnake.File(data, 'colors.png'))
            return

        description = f'''
        Vote for the the color you want to to replace existing colors.
        Vote for a color by reacting with the number the color is labeled with.
        '''
        title = 'Color vote'
        expires_in = utcnow() + timedelta(days=days)
        embed = disnake.Embed(title=title, description=description,
                              timestamp=expires_in)

        options = 'Strict mode on. Only the number emotes are valid votes.\n'
        options += f'Voting for more than {max_votes} valid option(s) will make some votes ignored\n'
        if winners > 1:
            options += f'Max amount of winners {winners} (might be more in case of a tie)'

        if options:
            embed.add_field(name='Modifiers', value=options)

        embed.set_footer(text='Expires at', icon_url=get_avatar(ctx.author))

        await ctx.trigger_typing()
        data = await self.bot.loop.run_in_executor(self.bot.threadpool, do_image)

        file = disnake.File(data, 'colors.png')
        embed.set_image(url='attachment://colors.png')

        msg = await ctx.send(embed=embed, file=file)

        for emote in emotes:
            try:
                await msg.add_reaction(emote)
            except disnake.DiscordException:
                pass

        await self.dbutil.create_poll(emotes, title, True, ctx.guild.id, msg.id,
                                ctx.channel.id, expires_in, True,
                                max_winners=winners,
                                allow_n_votes=max_votes)
        poll = Poll(self.bot, msg.id, ctx.channel.id, title,
                    expires_at=expires_in,
                    strict=True,
                    emotes=emotes,
                    max_winners=winners,
                    allow_n_votes=max_votes,
                    multiple_votes=max_votes > 1)
        poll.start()
        self.bot.get_cog('VoteManager').polls[msg.id] = poll


def setup(bot):
    bot.add_cog(ServerSpecific(bot))

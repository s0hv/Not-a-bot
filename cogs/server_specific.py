import asyncio
import logging
import random
import textwrap
import unicodedata
from datetime import datetime
from datetime import timedelta
from difflib import ndiff
from typing import Union

import discord
import emoji
from aiohttp.client_exceptions import ClientError
from aiohttp.http_exceptions import HttpProcessingError
from aioredis.errors import ConnectionClosedError
from asyncpg.exceptions import PostgresError
from colour import Color
from discord.errors import HTTPException
from discord.ext.commands import (BucketType, check)
from numpy import sqrt
from numpy.random import choice

from bot.bot import command, has_permissions, cooldown, bot_has_permissions
from bot.formatter import Paginator
from cogs.cog import Cog
from utils.utilities import (split_string, parse_time, call_later,
                             get_avatar, retry, send_paged_message,
                             check_botperm, format_timedelta, DateAccuracy)

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
Mai Sakurajima
kanna kamui
ann takamaki
yousei yunde"""

# Name, chance of spawning, character id, japanese name, spawn images in a list
waifus = [('Billy Herrington', 3, 1000006, 'ビリー・ヘリントン', ['https://i.imgur.com/ny8IwLI.png', 'https://i.imgur.com/V9X7Rbm.png', 'https://i.imgur.com/RxxYp62.png']),

          ('Sans', 3, 1000007, 'オイラ', ['https://imgur.com/VSet9rA.jpg', 'https://imgur.com/Dv5HNHH.jpg']),

          ("Aqua", 10, 117223, 'アクア', ['https://remilia.cirno.pw/image/117223/8a5bf967-ea5c-4077-8693-3a72dfdeda15.jpg',
                                       'https://remilia.cirno.pw/image/117223/4491938b-9852-43a4-9e77-3c88fc2a83c1.jpg',
                                       'https://remilia.cirno.pw/image/117223/249ee590-d9cf-49db-9e82-dc81f3e976de.jpg',
                                       'https://remilia.cirno.pw/image/117223/a5aebd7c-a1d4-472f-94f0-f8cad133aac3.jpg',
                                       'https://remilia.cirno.pw/image/117223/a80a8a44-ea9a-4ec3-8634-3ec266af23ae.jpg'
                                       'https://remilia.cirno.pw/image/117223/d629b228-62de-465b-88b9-ee43e1d9a4d5.jpg',
                                       'https://remilia.cirno.pw/image/117223/30367c34-ac96-4f53-a2bf-86519188273a.jpg',
                                       'https://remilia.cirno.pw/image/117223/8f122ed8-236f-4b0a-8dd0-ad2351fe4ec6.jpg',
                                       'https://remilia.cirno.pw/image/117223/db90d082-bb3f-488d-9401-7db8234b7448.jpg',
                                       'https://remilia.cirno.pw/image/117223/afc94ad7-a5bc-4bbf-b9e1-17f945a81a88.jpg',
                                       'https://remilia.cirno.pw/image/117223/13d69193-a8ce-44af-88fc-d65f8c47baa7.jpg',
                                       'https://remilia.cirno.pw/image/117223/434274bd-9e85-4da8-aebf-6862a0ff3db9.jpg',
                                       'https://remilia.cirno.pw/image/117223/e9ebb3bf-5cad-44b1-b80e-6b5d29d4086e.jpg',
                                       'https://remilia.cirno.pw/image/117223/7d92c3b3-4c73-4bd4-a4b9-60e2b81e2572.jpg',
                                       'https://remilia.cirno.pw/image/117223/561f660b-fcbc-4d46-9738-c56b7c284974.jpg',
                                       'https://remilia.cirno.pw/image/117223/f32cd559-a5ae-44c1-9279-d1fa79fc0678.jpg',
                                       'https://remilia.cirno.pw/image/117223/3db706fc-728e-4d85-a0a1-be2a7c41e803.jpg']),

          ('Zero Two', 10, 155679, 'ゼロツー', ['https://remilia.cirno.pw/image/155679/3b985740-607e-43cf-9e70-2b99124995f4.jpg',
                                            'https://remilia.cirno.pw/image/155679/c28593d0-08c4-4616-ab7a-905d0e693923.jpg',
                                            'https://remilia.cirno.pw/image/155679/d526e174-881f-4539-b2df-251d7577c094.jpg',
                                            'https://remilia.cirno.pw/image/155679/07fd0fc6-193e-40fa-a93d-1969338c7293.jpg',
                                            'https://remilia.cirno.pw/image/155679/ae537ce5-95e5-46a6-9975-3efcba887758.jpg',
                                            'https://remilia.cirno.pw/image/155679/621a6ec6-a946-43bf-88d8-54f89e55558d.jpg',
                                            'https://remilia.cirno.pw/image/155679/f715e4b4-412e-40df-af10-0e6287603a2f.jpg',
                                            'https://remilia.cirno.pw/image/155679/27e9fc57-9e94-4abc-a53f-c5ae117b81be.jpg',
                                            'https://remilia.cirno.pw/image/155679/40a7a452-3b10-4502-9347-a9f8e9f3c96f.jpg']),

          ('Albedo', 10, 116275, 'アルベド', ['https://remilia.cirno.pw/image/116275/9f928af1-25c8-4c47-b64b-e6ade0b21852.jpg',
                                          'https://remilia.cirno.pw/image/116275/2a3e9176-f65c-4a80-9a71-5b27cfc0d718.jpg',
                                          'https://remilia.cirno.pw/image/116275/93f07543-7fd2-4144-8c4c-91e58e207624.jpg',
                                          'https://remilia.cirno.pw/image/116275/62f84a38-a8b3-49e6-985b-cd95256e5e21.jpg',
                                          'https://remilia.cirno.pw/image/116275/68cd7f9b-9113-41cc-829d-808b3a61d415.jpg',
                                          'https://remilia.cirno.pw/image/116275/1035ee75-c2d4-4ac9-8880-1d04da7b833f.jpg']),

          ('Rem', 10, 118763, 'レム', ['https://remilia.cirno.pw/image/118763/eb7f66a2-7c4e-4a60-8db2-2b71194b3f16.jpg',
                                     'https://remilia.cirno.pw/image/118763/0e18b232-c09f-427d-967a-ba13cfed68cc.jpg',
                                     'https://remilia.cirno.pw/image/118763/2a9edebc-16dc-4238-8527-3c29c8f7e88e.jpg',
                                     'https://remilia.cirno.pw/image/118763/30f70c08-1a9e-4280-a60d-22ffb27de0d2.jpg',
                                     'https://remilia.cirno.pw/image/118763/566b834c-4ff6-4467-9aaa-04b6e4928a7d.jpg',
                                     'https://remilia.cirno.pw/image/118763/f151eba2-4bbe-46fb-a42c-78a97ce4200e.jpg',
                                     'https://remilia.cirno.pw/image/118763/040d7267-4469-4526-81ec-990dd6caa24c.jpg',
                                     'https://remilia.cirno.pw/image/118763/bde14658-fd55-49b7-be21-2950824a5609.jpg',
                                     'https://remilia.cirno.pw/image/118763/3a430b82-918c-4565-bf21-6e4b57d9b502.jpg',
                                     'https://remilia.cirno.pw/image/118763/663cc9f9-bf65-4a70-b663-e64b3af98b3b.jpg',
                                     'https://remilia.cirno.pw/image/118763/35f22c51-0d3d-432c-b1ab-0ad3aa7bc3ba.jpg',
                                     'https://remilia.cirno.pw/image/118763/51666a5c-c2f0-4445-8918-910d2e4147e5.jpg',
                                     'https://remilia.cirno.pw/image/118763/85f3bc45-ff71-43e9-ae55-8c7af22eb900.jpg',
                                     'https://remilia.cirno.pw/image/118763/26b48261-d208-41d9-8c6a-9057e17b533d.jpg',
                                     'https://remilia.cirno.pw/image/118763/e3f0d401-7d33-4d80-bb1a-ef9590ce98f1.jpg',
                                     'https://remilia.cirno.pw/image/118763/358a4347-6c43-49a5-bd16-9490a6f7e7e5.jpg']),

          ('Diego Brando', 10, 20148, 'ディエゴ・ブランド', ['https://remilia.cirno.pw/image/20148/a784eb6a-9e51-4aac-8181-8f95ad4e4082.jpg',
                                                        'https://remilia.cirno.pw/image/20148/d17cb5f6-442b-4453-ba2a-2fb33ed98c39.jpg',
                                                        'https://remilia.cirno.pw/image/20148/7f361064-d410-4ec7-89e2-c47dd31f3340.jpg',
                                                        'https://remilia.cirno.pw/image/20148/8c7140e9-d9f8-4d40-81a8-601bd553cefe.jpg',
                                                        'https://remilia.cirno.pw/image/20148/b680c43d-2e2c-430d-9b0e-7e23db457333.jpg']),

          ('Caesar Anthonio Zeppeli', 10, 21959, 'シーザー・アントニオ・ツェペリ', ['https://remilia.cirno.pw/image/21959/2fd6b9f9-3657-40f6-a5c5-87b9a8e245a9.jpg',
                                                                                'https://remilia.cirno.pw/image/21959/c82c68fd-a172-466c-a4a7-10e395da6440.jpg']),

          ('Nezuko Kamado', 10, 146157, '竈門 禰豆子', ['https://remilia.cirno.pw/image/146157/b14931d7-9c59-46fc-b4d7-3375cf2510b1.jpg',
                                                        'https://remilia.cirno.pw/image/146157/42b6fbd8-4090-42e9-bbf8-d795751e42c4.jpg']),
          ('YoRHa 2-gou B-gata', 10, 153798, 'ヨルハ2号B型', ['https://remilia.cirno.pw/image/153798/3d422bbf-4a91-4ea2-b59a-d59a8f82f07b.jpg']),

          ('Rias Gremory', 10, 50389, 'リアス・グレモリー', ['https://remilia.cirno.pw/image/50389/64667c4b-452e-4545-9fd9-405eba3331bf.jpg',
                                                           'https://remilia.cirno.pw/image/50389/2baa6fcf-78f2-4c93-9590-32a3bd90b32c.jpg',
                                                           'https://remilia.cirno.pw/image/50389/24da6571-e509-4808-855c-4d1864d90d3c.jpg',
                                                           'https://remilia.cirno.pw/image/50389/d57f41fb-f0dd-4ecf-bc02-82197513473c.jpg'
                                                           'https://remilia.cirno.pw/image/50389/352880a3-7f9a-4cb3-9234-590ab3e946ca.jpg',
                                                           'https://remilia.cirno.pw/image/50389/3fc0938f-8712-4b6c-9ebf-3f742ef266e6.jpg',
                                                           'https://remilia.cirno.pw/image/50389/b1def5ff-a6bb-4939-8800-e9747efd2b74.jpg',
                                                           'https://remilia.cirno.pw/image/50389/81d290db-8845-4443-9853-eebe824f35f2.jpg']),

          ('Mai Sakurajima', 10, 118739, '桜島 麻衣', ['https://remilia.cirno.pw/image/118739/1616c1cc-e043-46a2-96a1-76daeb880b9b.jpg',
                                                   'https://remilia.cirno.pw/image/118739/6ca5f2a9-e6df-48cb-bb0c-0a2abf3360d2.jpg',
                                                   'https://remilia.cirno.pw/image/118739/048a5491-4b69-4936-b9f4-ec49d97c2e47.jpg',
                                                   'https://remilia.cirno.pw/image/118739/a8b92e98-7865-4cf9-99a3-976ef015d186.jpg']),
          ('Fumino Furuhashi', 10, 148394, '古橋 文乃', ['https://remilia.cirno.pw/image/148394/06fe5be2-90a7-48f6-a0ec-054d5f8c643d.jpg',
                                                     'https://remilia.cirno.pw/image/148394/5a1e0587-ad4e-477a-b84e-d2ae973f920f.jpg'])
          ]

chances = [t[1] for t in waifus]
_s = sum(chances)
chances = [p/_s for p in chances]
del _s

FILTERED_ROLES = {321374867557580801, 331811458012807169, 361889118210359297,
                  380814558769578003, 337290275749756928, 422432520643018773,
                  322837972317896704, 323492471755636736, 329293030957776896}
FILTERED_ROLES = {discord.Role(guild=None, state=None,  data={"id": id_, "name": ""})
                  for id_ in FILTERED_ROLES}

AVAILABLE_ROLES = {10: {
    discord.Role(guild=None, state=None,  data={"id": 320674825423159296, "name": "No dignity"}),
    discord.Role(guild=None, state=None,  data={"id": 322063025903239178, "name": "meem"}),
    discord.Role(guild=None, state=None,  data={"id": 320667990116794369, "name": "HELL 2 U"}),
    discord.Role(guild=None, state=None,  data={"id": 320673902047264768, "name": "I refuse"}),
    discord.Role(guild=None, state=None,  data={"id": 322737580778979328, "name": "SHIIIIIIIIIIIIZZZZZAAAAAAA"}),
    discord.Role(guild=None, state=None,  data={"id": 322438861537935360, "name": "CHEW"}),
    discord.Role(guild=None, state=None,  data={"id": 322425271791910922, "name": "deleted-role"}),
    discord.Role(guild=None, state=None,  data={"id": 322760382542381056, "name": "Couldn't beat me 1 2 3"}),
    discord.Role(guild=None, state=None,  data={"id": 322761051303051264, "name": "ok"}),
    discord.Role(guild=None, state=None,  data={"id": 322416531520749568, "name": "degenerate"}),
    discord.Role(guild=None, state=None,  data={"id": 322450803602358273, "name": "new role"}),
    discord.Role(guild=None, state=None,  data={"id": 322837341926457367, "name": "Pineapple on pizza"}),
    discord.Role(guild=None, state=None,  data={"id": 323497232211116042, "name": "What the fuck did you just fucking say about my hair, you little「STAND USER」? I’ll have you know I"}),
    discord.Role(guild=None, state=None,  data={"id": 323497233670602753, "name": "graduated top of my class in Budogaoka Middle & High School, and I’ve been involved in numerous"}),
    discord.Role(guild=None, state=None,  data={"id": 323497236551958540, "name": "I’m the top 「STAND USER」in the entire Morioh armed forces. You are nothing to me but just another"}),
    discord.Role(guild=None, state=None,  data={"id": 323497235302187008, "name": "secret raids on DIO, and I have over 300 confirmed DORARARARARAs. I am trained in Stand warfare and"}),
    discord.Role(guild=None, state=None,  data={"id": 323497240058527745, "name": "Duwang, mark my fucking words. You think you can get away with saying that shit to me over Echoes"}),
    discord.Role(guild=None, state=None,  data={"id": 323497244793896961, "name": "Diamond, maggot. The Stand that wipes out the pathetic little thing you call your life. You’re"}),
    discord.Role(guild=None, state=None,  data={"id": 323497238175285250, "name": "Kira. I will wipe you the fuck out with precision the likes of which has never been seen before in"}),
    discord.Role(guild=None, state=None,  data={"id": 323497241459294211, "name": "Act 1? Think again, fucker. As we speak I am contacting my secret network of the Speedwagon"}),
    discord.Role(guild=None, state=None,  data={"id": 323497246446452740, "name": "fucking dead,「STAND USER 」. I can be anywhere, anytime, and I can heal and then kill you in over"}),
    discord.Role(guild=None, state=None,  data={"id": 323497243212513281, "name": "Foundation across Japan and your Stand is being traced right now so you better prepare for Crazy"}),
    discord.Role(guild=None, state=None,  data={"id": 323497248136626199, "name": "seven hundred ways, and that’s just with my Stand. Not only am I extensively trained in Stand"}),
    discord.Role(guild=None, state=None,  data={"id": 323497250003353600, "name": "combat, but I have access to the entire arsenal of the Speedwagon Foundation and I will use it to"}),
    discord.Role(guild=None, state=None,  data={"id": 323497253123915776, "name": "could have known what unholy retribution your little “clever” Killer Queen was about to bring down"}),
    discord.Role(guild=None, state=None,  data={"id": 323497251408314369, "name": "its full extent to wipe your miserable ass off the face of Morioh, you little shit. If only you"}),
    discord.Role(guild=None, state=None,  data={"id": 323497254348521475, "name": "upon you, maybe you would have held your fucking tongue. But you couldn’t, you didn’t, and now"}),
    discord.Role(guild=None, state=None,  data={"id": 323497255992819713, "name": "you’re paying the price, you goddamn idiot. I will shit DORARARARARARAs all over you and you will"}),
    discord.Role(guild=None, state=None,  data={"id": 323497257749970955, "name": "drown in it. You’re fucking dead, Kira."}),
    discord.Role(guild=None, state=None,  data={"id": 325627566406893570, "name": "he"}),
    discord.Role(guild=None, state=None,  data={"id": 325415104894074881, "name": "ew no"}),
    discord.Role(guild=None, state=None,  data={"id": 325629356309479424, "name": "she"}),
    discord.Role(guild=None, state=None,  data={"id": 326096831777996800, "name": "new tole"}),
    discord.Role(guild=None, state=None,  data={"id": 329331992778768397, "name": "to role or not to role"}),
    discord.Role(guild=None, state=None,  data={"id": 329333048917229579, "name": "DORARARARARARARARARARARARARARARARA"}),
    discord.Role(guild=None, state=None,  data={"id": 330058759986479105, "name": "The entire horse"}),
    discord.Role(guild=None, state=None,  data={"id": 330079869599744000, "name": "baguette"}),
    discord.Role(guild=None, state=None,  data={"id": 330080088597200896, "name": "4 U"}),
    discord.Role(guild=None, state=None,  data={"id": 330080062441259019, "name": "big guy"}),
    discord.Role(guild=None, state=None,  data={"id": 336219409251172352, "name": "The whole horse"}),
    discord.Role(guild=None, state=None,  data={"id": 338238407845216266, "name": "ok masta let's kill da ho"}),
    discord.Role(guild=None, state=None,  data={"id": 338238532101472256, "name": "BEEEEEEEEEEEEEETCH"}),
    discord.Role(guild=None, state=None,  data={"id": 340950870483271681, "name": "FEEL THE HATRED OF TEN THOUSAND YEARS!"}),
    discord.Role(guild=None, state=None,  data={"id": 349982610161926144, "name": "Fruit mafia"}),
    discord.Role(guild=None, state=None,  data={"id": 380074801076633600, "name": "Attack helicopter"}),
    discord.Role(guild=None, state=None,  data={"id": 381762837199978496, "name": "Gappy makes me happy"}),
    discord.Role(guild=None, state=None,  data={"id": 389133241216663563, "name": "Comfortably numb"}),
    discord.Role(guild=None, state=None,  data={"id": 398957784185438218, "name": "Bruce U"}),
    discord.Role(guild=None, state=None,  data={"id": 523192033544896512, "name": "Today I will +t random ham"}),
    },

    365: {
        discord.Role(guild=None, state=None,  data={"id": 321863210884005906, "name": "What did you say about my hair"}),
        discord.Role(guild=None, state=None,  data={"id": 320885539408707584, "name": "Your next line's gonna be"}),
        discord.Role(guild=None, state=None,  data={"id": 321285882860535808, "name": "JJBA stands for Johnny Joestar's Big Ass"}),
        discord.Role(guild=None, state=None,  data={"id": 330317213133438976, "name": "Dik brothas"}),
        discord.Role(guild=None, state=None,  data={"id": 322667100340748289, "name": "Wannabe staff"}),
        discord.Role(guild=None, state=None,  data={"id": 324084336083075072, "name": "rng fucks me in the ASS!"})
    },

    548: {
        discord.Role(guild=None, state=None,  data={"id": 323486994179031042, "name": "I got 2 steel balls and I ain't afraid to use them"}),
        discord.Role(guild=None, state=None,  data={"id": 321697480351940608, "name": "ORA ORA ORA ORA ORA ORA ORA ORA ORA ORA MUDA MUDA MUDA MUDA MUDA MUDA MUDA MUDA"}),
        discord.Role(guild=None, state=None,  data={"id": 330440908187369472, "name": "CEO of Heterosexuality"}),
        discord.Role(guild=None, state=None,  data={"id": 329350731918344193, "name": "4 balls"}),
        discord.Role(guild=None, state=None,  data={"id": 358615843120218112, "name": "weirdo"}),
        discord.Role(guild=None, state=None,  data={"id": 336437276156493825, "name": "Wannabe owner"}),
        discord.Role(guild=None, state=None,  data={"id": 327519034545537024, "name": "food"})

    },

    730: {
        discord.Role(guild=None, state=None,  data={"id": 326686698782195712, "name": "Made in heaven"}),
        discord.Role(guild=None, state=None,  data={"id": 320916323821682689, "name": "Filthy acts at a reasonable price"}),
        discord.Role(guild=None, state=None,  data={"id": 321361294555086858, "name": "Speedwagon best waifu"}),
        discord.Role(guild=None, state=None,  data={"id": 320879943703855104, "name": "Passione boss"}),
        discord.Role(guild=None, state=None,  data={"id": 320638312375386114, "name": "Dolphin l̶o̶v̶e̶r̶ fucker"}),
        discord.Role(guild=None, state=None,  data={"id": 318683559462436864, "name": "Sex pistols ( ͡° ͜ʖ ͡°)"}),
        discord.Role(guild=None, state=None,  data={"id": 318843712098533376, "name": "Taste of a liar"}),
        discord.Role(guild=None, state=None,  data={"id": 323474940298788864, "name": "Wannabe bot"})
    },

    900: {
        discord.Role(guild=None, state=None,  data={"id": 321310583200677889, "name": "The fucking strong"}),
        discord.Role(guild=None, state=None,  data={"id": 318432714984521728, "name": "Za Warudo"}),
        discord.Role(guild=None, state=None,  data={"id": 376789104794533898, "name": "no u"}),
        discord.Role(guild=None, state=None,  data={"id": 348900633979518977, "name": "Role to die"}),
        discord.Role(guild=None, state=None,  data={"id": 349123036189818894, "name": "koichipose"})
    }
}


class RoleResponse:
    def __init__(self, msg, image_url=None):
        self.msg = msg
        self.img = image_url

    async def send_message(self, ctx, role=None):
        author = ctx.author
        description = self.msg.format(author=author, role=role, bot=ctx.bot.user)

        if self.img:
            embed = discord.Embed(description=description)
            embed.set_image(url=self.img)
            await ctx.send(embed=embed)

        else:
            await ctx.send(description)


role_response_success = [
    RoleResponse("You escape **{bot}**'s hold and get your friend to beat him up. You successfully steal the role \"{role}\"", 'https://i.imgur.com/Z6qmUEV.gif'),
    RoleResponse("His smile radiates on your face and blesses you with \"{role}\"", 'https://i.imgur.com/egiCht9.jpg'),
    RoleResponse("You scientifically prove that traps aren't gay and get a role as a reward. ({role})"),
    RoleResponse("You have a moment of silence for Billy as he looks upon you and grants you a role. ({role})", 'https://i.imgur.com/PRnTXpc.png'),
    RoleResponse("You recite some classical poetry and get a role as a reward for your performance. ({role})", 'https://manly.gachimuchi.men/HzmKEk7k.png'),
    RoleResponse("You stare in awe as Pucci removes a disc from his White Snake. He places it in your hand, bestowing upon you the role {role}", 'https://cdn.discordapp.com/attachments/252872751319089153/664747484190343179/image0.png'),
    RoleResponse("You gain a role. That turns you on. ({role})", 'https://i.imgur.com/TZIKltp.gif')
]

role_response_fail = [
    RoleResponse("Never lucky <a:tyler1Rage:592360154775945262>"),
    RoleResponse("Due to a technical error the role went to a gang of traps instead <:AstolfoPlushie:592595615188385802><a:AstolfoPlushie:474085216651051010><:AstolfoPlushie:592595615188385802>"),
    RoleResponse("404 Role not found"),
    RoleResponse("{bot} flexes on you as you lay on the ground with no tole", 'https://i.imgur.com/VFruiTR.gif'),
    RoleResponse("When you realize that you didn't get any roles this time", 'https://i.imgur.com/YIP6W84.png'),
    RoleResponse("You get offered black market roles but you don't know how to respond and the chance to acquire a role passes by", 'https://i.imgur.com/Xo7s9Vx.jpg'),
    RoleResponse("You get abused by moderators and gain nothing"),
    RoleResponse("You're just dead weight", 'https://i.redd.it/m1866wrhfnl21.jpg'),
    RoleResponse("soap rigs the game! <:PeepoEvil:635509941309800478>"),
    RoleResponse("No role goddammit", 'https://cdn.discordapp.com/attachments/341610158755020820/591706871237312561/1547775958351.gif')
]


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
    async def rotate(self, ctx, rotate_emoji=None):
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

        if rotate_emoji is not None:
            rotate_emoji = ''.join(rotate_emoji[:2])
            invalid = True
            emoji_check = rotate_emoji

            if len(rotate_emoji) > 1:
                try:
                    emojis = self.extract_emojis(rotate_emoji)
                except ValueError:
                    ctx.command.reset_cooldown(ctx)
                    return await ctx.send('Invalid emoji')

                if len(emojis) != 1:
                    ctx.command.reset_cooldown(ctx)
                    await ctx.send('Invalid emoji given')
                    return

                emoji_check = emojis[0]

            if emoji_check in emoji_blacklist:
                ctx.command.reset_cooldown(ctx)
                await ctx.send('Invalid emoji')
                return

            if len(emoji.get_emoji_regexp().findall(emoji_check)) == len(rotate_emoji):
                invalid = False

            if invalid:
                ctx.command.reset_cooldown(ctx)
                return await ctx.send('Invalid emoji')

        elif rotate_emoji is None:
            rotate_emoji = random.choice(list(emoji_faces))

        try:
            pass
            await ctx.guild.edit(name=rotate_emoji * (100 // (len(rotate_emoji))))
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

    async def get_user_score(self, uid, guild_id):
        if not self.bot.config.tatsumaki_key:
            return None

        url = f'https://api.tatsumaki.xyz/guilds/{guild_id}/members/{uid}/stats'
        headers = {'Authorization': self.bot.config.tatsumaki_key}

        try:
            async with self.bot.aiohttp_client.get(url, headers=headers) as r:
                if r.status != 200:
                    return

                data = await r.json()
                if data.get('user_id') == str(uid):
                    return data.get('score')
        except (HttpProcessingError, ClientError):
            return

    async def get_role_chance(self, ctx, member, user_roles=None,
                              delta_days=None):
        if not user_roles:
            user_roles = set(ctx.author.roles)

        if not delta_days:
            first_join = await self.dbutil.get_join_date(member.id, ctx.guild.id) \
                         or ctx.author.joined_at
            delta_days = (datetime.utcnow() - first_join).days

        score = await self.get_user_score(member.id, ctx.guild.id)
        if not score:
            await ctx.send('Failed to get server score. Try again later')
            return

        score = int(score)
        # Give points to people who've been in server for long time
        if score > 100000:
            score += 110 * delta_days

        # Return chances of role
        def role_get(s, r):
            if s < 8000:
                return 0

            return (s / 3000 + 70 / r) * (r**-3 + (r * 0.5)**-2 + (r * 100)**-1)

        role_count = len(user_roles - FILTERED_ROLES)
        return role_get(int(score), role_count)

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

    @command(aliases=['tole_get', 'toletole', 'give_role', 'give_tole'])
    @check(create_check((217677285442977792,)))
    @cooldown(1, 10, BucketType.user)
    async def role_get(self, ctx, mentionable: bool=False):
        """
        Chance to get a role. By default you don't get mentionable roles.
        This can be changed if you use set mentionable to true.
        e.g.
        `{prefix}{name} on` will also take mentionable roles into account

        Original idea by xerd
        """

        # Get last use timestamp
        try:
            row = await self.dbutil.get_last_role_time(ctx.author.id)
        except PostgresError:
            await ctx.send('Failed to get timestamp of last use of this command. Try again later')
            return

        # Check that cooldown has passed
        if row:
            cooldown_days = 7

            # Boosters have 1 day lower cooldown
            if ctx.author.premium_since:
                cooldown_days -= 1

            role_cooldown = (datetime.utcnow() - row[0])
            if role_cooldown.days < cooldown_days:
                t = format_timedelta(timedelta(days=cooldown_days) - role_cooldown,
                                     DateAccuracy.Day-DateAccuracy.Hour)
                await ctx.send(f"You're still ratelimited for this command. Cooldown ends in {t}")
                return

        guild = ctx.guild
        first_join = await self.dbutil.get_join_date(ctx.author.id, guild.id) or ctx.author.joined_at
        delta_days = (datetime.utcnow() - first_join).days

        # Set of all the roles a user can get
        roles = set()

        # Get available roles
        for days, toles in AVAILABLE_ROLES.items():
            if days < delta_days:
                for role in toles:
                    role = guild.get_role(role.id)
                    # Check that the role exists and the if it can be mentionable
                    if not role or (not mentionable and role.mentionable):
                        continue

                    roles.add(role)

        # Check that roles are available
        user_roles = set(ctx.author.roles)
        roles = roles - user_roles
        if not roles:
            await ctx.send('No roles available to you at the moment. Try again after being more active')
            return

        chances = await self.get_role_chance(ctx, ctx.author, user_roles, delta_days)
        if chances is None:
            return

        try:
            await self.dbutil.update_last_role_time(ctx.author.id, datetime.utcnow())
        except PostgresError:
            await ctx.send('Failed to update cooldown of the command. Try again in a bit')
            return

        got_new_role = random.random() < chances
        if got_new_role:
            role = choice(list(roles))
            await ctx.author.add_roles(role)
            await choice(role_response_success).send_message(ctx, role)

        else:
            await choice(role_response_fail).send_message(ctx)

    @command(hidden=True)
    @cooldown(1, 60, BucketType.channel)
    async def zeta(self, ctx, channel: discord.TextChannel=None):
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass

        if not channel:
            channel = ctx.channel

        # Check that we can retrieve a webhook
        try:
            wh = await channel.webhooks()
            if not wh:
                return

            wh = wh[0]
        except discord.HTTPException:
            return

        # Get random waifu
        waifu = choice(len(waifus), p=chances)
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
        e = discord.Embed(title='Character', color=int(c.get_hex_l().replace('#', ''), 16),
                          description=desc)
        e.set_image(url=link)
        wb = self.bot.get_user(472141928578940958)

        await wh.send(embed=e, username=wb.name, avatar_url=wb.avatar_url)

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
                                  username=wb.name, avatar_url=wb.avatar_url)
                else:
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
            except discord.HTTPException:
                return

        try:
            await self.bot.wait_for('message', check=check2_, timeout=120)
        except asyncio.TimeoutError:
            return

        self.bot.loop.create_task(delete_wb_msg())

        e = discord.Embed(title=f'{name} ({waifu[3]})', color=16745712, description=desc)
        e.set_footer(text=img_number)

        e.set_image(url=link)

        await wh.send(embed=e, username=wb.name, avatar_url=wb.avatar_url)


def setup(bot):
    bot.add_cog(ServerSpecific(bot))

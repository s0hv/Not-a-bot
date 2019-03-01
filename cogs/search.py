"""
MIT License

Copyright (c) 2017 s0hvaperuna

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

import logging
from collections import deque

from aiohttp import ClientSession
from discord.ext.commands import cooldown

from bot.bot import command
from cogs.cog import Cog
from utils.utilities import send_paged_message

logger = logging.getLogger('debug')


class SearchItem():
    def __init__(self, **kwargs):
        self.url = kwargs.pop('link', 'None')
        self.title = kwargs.pop('title', 'Untitled')

    def __str__(self):
        return '{0.url}'.format(self)


class Search(Cog):
    def __init__(self, bot, client: ClientSession):
        super().__init__(bot)
        self.client = client
        self.last_search = deque()
        self.key = bot.config.google_api_key
        self.cx = self.bot.config.custom_search

    @command(aliases=['im', 'img'])
    @cooldown(2, 5)
    async def image(self, ctx, *, query):
        """Google search an image"""
        #logger.debug('Image search query: {}'.format(query))
        return await self._search(ctx, query, True, safe='off' if ctx.channel.nsfw else 'high')

    @command()
    @cooldown(2, 5)
    async def google(self, ctx, *, query):
        #logger.debug('Web search query: {}'.format(query))
        return await self._search(ctx, query, safe='off' if ctx.channel.nsfw else 'medium')

    async def _search(self, ctx, query, image=False, safe='off'):
        params = {'key': self.key,
                  'cx': self.cx,
                  'q': query,
                  'safe': safe}

        if image:
            params['searchType'] = 'image'

        async with self.client.get('https://www.googleapis.com/customsearch/v1', params=params) as r:
            if r.status == 200:
                json = await r.json()
                if 'error' in json:
                    reason = json['error'].get('message', 'Unknown reason')
                    return await ctx.send('Failed to search because of an error\n```{}```'.format(reason))

                #logger.debug('Search result: {}'.format(json))

                total_results = json['searchInformation']['totalResults']
                if int(total_results) == 0:
                    return await ctx.send('No results with the keywords "{}"'.format(query))

                if 'items' in json:
                    items = []
                    for item in json['items']:
                        items.append(SearchItem(**item))

                    return await send_paged_message(ctx, items,
                                                    page_method=lambda p,
                                                                       i: str(
                                                        p))
            else:
                return await ctx.send('Http error {}'.format(r.status))


def setup(bot):
    bot.add_cog(Search(bot, bot.aiohttp_client))

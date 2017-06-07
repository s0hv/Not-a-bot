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

from bot.bot import command

logger = logging.getLogger('debug')


class SearchItem:
    def __init__(self, **kwargs):
        self.url = kwargs.pop('link', 'None')
        self.title = kwargs.pop('title', 'Untitled')

    def __str__(self):
        return '{0.url}'.format(self)


class Search:
    def __init__(self, bot, client: ClientSession):
        self.bot = bot
        self.client = client
        self.last_search = deque()
        self.key = bot.config.google_api_key
        self.cx = self.bot.config.custom_search

    @command(pass_context=True, level=1)
    async def image(self, ctx, *, query):
        logger.debug('Image search query: {}'.format(query))
        return await self.search(ctx, query, True)

    @command(pass_context=True, level=1)
    async def google(self, ctx, *, query):
        logger.debug('Web search query: {}'.format(query))
        return await self.search(ctx, query)

    async def search(self, ctx, query, image=False):
        params = {'key': self.key,
                  'cx': self.cx,
                  'q': query}

        if image:
            params['searchType'] = 'image'

        async with self.client.get('https://www.googleapis.com/customsearch/v1', params=params) as r:
            if r.status == 200:
                channel = ctx.message.channel
                json = await r.json()
                logger.debug('Search result: {}'.format(json))

                total_results = json['searchInformation']['totalResults']
                if int(total_results) == 0:
                    return await self.bot.say_timeout('No results with the keywords "{}"'.format(query),
                                                      channel, 30)

                if 'items' in json:
                    self.last_search.clear()
                    for item in json['items']:
                        self.last_search.append(SearchItem(**item))

                return await self.bot.say_timeout(self.last_search.popleft(), channel)

    @command(pass_context=True, ignore_extra=True)
    async def next_result(self, ctx):
        try:
            return await self.bot.say_timeout(self.last_search.popleft(), ctx.message.channel)
        except IndexError:
            return await self.bot.say_timeout('No more results', ctx.message.channel, 60)

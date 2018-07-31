import re
from bs4 import BeautifulSoup


id_regex = re.compile(r'.watch\?v=([a-zA-Z0-9_-]{11})')
urlbase = 'https://www.youtube.com/watch?v=%s'


def url2id(url):
    return url.split('/')[-1].split('=')[-1]


def id2url(id):
    return urlbase % id


async def get_related_vids(vid_id, client, filtered=None):
    url = id2url(vid_id)
    if not filtered:
        filtered = (vid_id, )
    else:
        filtered.append(vid_id)

    async with client.get(url) as r:
        if r.status != 200:
            return

        content = await r.text()
        soup = BeautifulSoup(content, 'lxml')
        up_next = soup.find('div', {'class': 'watch-sidebar'})
        if up_next:
            matches = id_regex.findall(str(up_next))
            for match in matches:
                if match not in filtered:
                    return match

        ids = id_regex.findall(content)
        if not ids:
            return

        for _id in ids:
            if _id != vid_id and _id not in filtered:
                return _id


import asyncio
from aiohttp.client import ClientSession

loop = asyncio.get_event_loop()
c = ClientSession(loop=loop)
id = loop.run_until_complete(get_related_vids('g9hwjQBQFIo', c))
print(id)
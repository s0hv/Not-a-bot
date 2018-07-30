import re
from bs4 import BeautifulSoup


id_regex = re.compile(r'.watch\?v=([a-zA-Z0-9_-]{11})')
urlbase = 'https://www.youtube.com/watch?v=%s'


def url2id(url):
    return url.split('/')[-1].split('=')[-1]


def id2url(id):
    return urlbase % id


async def get_related_vids(vid_id, client):
    url = id2url(vid_id)
    async with client.get(url) as r:
        if r.status != 200:
            return

        content = await r.text()
        soup = BeautifulSoup(content, 'lxml')
        up_next = soup.find('div', {'class': 'watch-sidebar'})
        if up_next:
            matches = id_regex.findall(str(up_next))
            if matches:
                return matches[0]

        ids = id_regex.findall(content)
        if not ids:
            return

        for _id in ids:
            if _id != vid_id:
                return _id

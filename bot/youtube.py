import re
from enum import Enum

import isodate
from bs4 import BeautifulSoup
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

id_regex = re.compile(r'.watch\?v=([a-zA-Z0-9_-]{11})')
video_id_regex = re.compile(r'https?://(?:www\.)?(?:youtu\.be/|youtube\.com\S*?[^\w\s-])([\w-]{11})(?=[^\w-]|$)[?=&+%\w.-]*')
playlist_id_regex = re.compile(r'https?://(?:www\.)?(?:youtu\.be/|youtube\.com/playlist[&?]list=([^&]+))(?=[^\w-]|$)[?=&+%\w.-]*')
urlbase = 'https://www.youtube.com/watch?v=%s'


def url2id(url):
    return url.split('/')[-1].split('=')[-1]


def id2url(id):
    return urlbase % id


def extract_playlist_id(url):
    playlist_id = playlist_id_regex.match(url)
    if playlist_id:
        return playlist_id.groups()[0]


def extract_video_id(url):
    video_id = video_id_regex.match(url)
    if video_id:
        return video_id.groups()[0]


def parse_youtube_duration(duration):
    return int(isodate.parse_duration(duration).total_seconds())


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


class Part(Enum):
    ContentDetails = 'contentDetails'
    ID = 'id'
    Snippet = 'snippet'
    Status = 'status'

    @staticmethod
    def combine(*parts):
        return ','.join([p.value for p in parts])


class YTApi:
    def __init__(self, api_key):
        self._api_key = api_key
        self.client = build('youtube', 'v3', developerKey=self.api_key)

    @property
    def api_key(self):
        return self._api_key

    def playlist_items(self, playlist_id, part, max_results: int=None, page_token=None):
        if isinstance(part, Part):
            part = part.value

        if max_results is None:
            max_results = 5000

        all_items = []
        _max_results = min(50, max_results)
        params = {'part': part, 'playlistId': playlist_id,
                  'maxResults': _max_results}
        js = None

        while max_results > 0:
            if page_token:
                params['pageToken'] = page_token

            try:
                js = self.client.playlistItems().list(**params).execute()
            except HttpError:
                return

            page_token = js.get('nextPageToken')
            all_items.extend(js.get('items', []))

            if page_token is None:
                return all_items

            max_results -= _max_results
            _max_results = min(50, max_results)

        if js and all_items:
            return all_items

    def video_info(self, ids, part):
        if isinstance(part, Part):
            part = part.value

        params = {'part': part}

        page_token = False
        all_items = []
        js = {}
        for idx in range(0, len(ids), 50):
            if page_token:
                params['pageToken'] = page_token
            params['id'] = ','.join(ids[idx:idx+50])
            try:
                js = self.client.videos().list(**params).execute()
            except HttpError:
                return

            page_token = js.get('nextPageToken')
            all_items.extend(js.get('items', []))

        return all_items

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

import json
import os

import youtube_dl
from discord import Message
from numpy import random

from bot.audio import Audio

params = {'extract_flat': True, 'skip_download': True}
yt = youtube_dl.YoutubeDL(params=params, auto_init=True)

urls = ['https://www.youtube.com/playlist?list=PLN4vRgceumM-p8YThpXP9XbEfbj-uJycn',
        'https://www.youtube.com/playlist?list=PLPVK3WmPTxwFAqHg6w35tAbJah7DgOBvJ',
        'https://www.youtube.com/playlist?list=PLk1DIHfcjT13GtsfSCQnSNf9fsV-yaley']

url_format = 'https://www.youtube.com/watch?v=%s'

async def update_gachi():
    videos = {}
    for url in urls:
        result = yt.extract_info(url)
        videos.update(result)
    return videos


async def random_gachi(sound: Audio, ctx, amount):
    with open(os.path.join(os.path.dirname(__file__), 'gachi.txt'), 'r') as f:
        js = json.load(f)

    purge_list = []

    if amount > 100:
        amount = 100

    videos = js['entries']
    for a in range(0, amount):

        for i in range(0, 3):
            video = random.choice(videos)
            response = await sound.play_song(ctx, url_format % video['url'])
            if isinstance(response, Message):
                purge_list += [response]
                break

    return purge_list

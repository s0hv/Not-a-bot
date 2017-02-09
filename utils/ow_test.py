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

from aiohttp import ClientSession
import json

client = ClientSession()

async def get_ow(bt):
    with open('battletags.json', 'r+') as f:
        data = json.load(f)
        bt = data['users'][bt]
    async with client.get('https://api.lootbox.eu/pc/eu/%s/profile' % bt) as r:
        if r.status == 200:
            js = await r.json()
            js = js['data']
            print(js)
            quick = js['games']['quick']
            cmp = js['games']['competitive']
            winrate_qp = int(quick['wins'])/int(quick['played'])
            winrate_cmp = int(cmp['wins'])/int(cmp['played'])
            print("Winrate for %s is"%bt.replace('-', '#'), str(round(winrate_qp*100, 2)) + '%',
                  "in quick play and", str(round(winrate_cmp*100, 2)) + '%', "in competitive")


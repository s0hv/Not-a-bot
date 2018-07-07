import json

import requests
from bs4 import BeautifulSoup

url = 'https://en.wikipedia.org/wiki/List_of_colors_(compact)'
r = requests.get(url)
soup = BeautifulSoup(r.content, 'lxml')

rows = soup.find_all('div', style='float:left;display:inline;font-size:90%;margin:1px 5px 1px 5px;width:11em; height:6em;text-align:center;padding:auto;')
colors = {}
for row in rows:
    name = row.find('a')
    if name:
        name = name.text
    else:
        continue
    color = row.find('p').get('title')

    d = {}
    hsv, rgb, hex_ = color.split('; ')
    hsv_ = []
    for s in hsv[4:-1].split(','):
        s = s[:-1]
        if s:
            hsv_.append(int(s))
        else:
            hsv_.append(None)

    d['hsv'] = hsv_
    d['rgb'] = [int(s) for s in rgb[4:-1].split(',')]
    d['hex'] = hex_
    colors[name.lower()] = d

with open('color_names.json', 'w') as f:
    json.dump(colors, f, indent=4)

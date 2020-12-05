import itertools
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
    hsv, rgb, hex_ = color.split('\n')

    d['rgb'] = [int(s) for s in rgb[5:-1].split(' ')]
    d['hex'] = hex_.split(' ')[-1]
    colors[name.lower()] = d

url2 = 'https://encycolorpedia.com/named'
r = requests.get(url2)
soup = BeautifulSoup(r.content, 'lxml')

rows = soup.select('section ol li')
for row in rows:
    name, hex_ = row.get_text('\n').split('\n')
    name = name.lower()
    rgb = [int(''.join(itertools.islice(s, 2)), 16) for s in [iter(hex_[1:])]*3]

    if name in colors and colors[name]['hex'].lower() != hex_.lower():
        print(name, hex_)
    else:
        d = {
            'hex': hex_,
            'rgb': rgb
        }
        colors[name] = d

print(len(colors.keys()))
with open('color_names.json', 'w') as f:
    json.dump(colors, f, indent=4)

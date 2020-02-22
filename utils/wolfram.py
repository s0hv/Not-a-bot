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
import urllib

from bs4 import BeautifulSoup

terminal = logging.getLogger('terminal')


async def math(calculation, client, key):
    if key is None:
        return "No api key specified"

    calculation = urllib.parse.quote_plus(calculation)
    terminal.debug(calculation)
    api = 'http://api.wolframalpha.com/v2/query?appid=%s&input=%s&format=plaintext' % (key, calculation)
    async with client.get(api) as r:
        if r.status == 200:
            content = await r.text()
            soup = BeautifulSoup(content, 'lxml')
            result = soup.find('queryresult').get('success')
            if result != 'true':
                return "I don't even math"

            pods = soup.find_all('pod', primary='true')
            answers = []
            for pod in pods:
                try:
                    txt = pod.find('plaintext').text
                except AttributeError:
                    continue

                title = pod.attrs.get('title', '')
                subpods = pod.find_all('subpod')
                if subpods:
                    for subpod in subpods:
                        try:
                            txt = subpod.find('plaintext').text
                        except AttributeError:
                            continue

                        answers.append(f'{title}: `{txt.strip()}`')

                else:
                    answers.append(f'{title}: `{txt.strip()}`')
                if len(answers) > 5:
                    break

            if not answers:
                for pod in soup.find_all('pod', error='false'):
                    if pod.attrs.get('id') == 'Input':
                        continue
                    try:
                        txt = pod.find('plaintext').text
                        if not txt:
                            continue
                    except AttributeError:
                        continue

                    title = pod.attrs.get('title', '')
                    answers.append(f'{title}: `{txt.strip()}`')
                    if len(answers) > 3:
                        break

            return '\n'.join(answers) or 'No answer...'

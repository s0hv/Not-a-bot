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

import asyncio
import functools
import logging
from concurrent.futures import ThreadPoolExecutor

import yt_dlp
from yt_dlp import YoutubeDL

terminal = logging.getLogger('terminal')


opts = {
    'format': 'bestaudio[abr<500]/bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
    'extract_flat': 'in_playlist'
}

yt_dlp.utils.bug_reports_message = lambda: ''


class Downloader:
    def __init__(self):
        self.thread_pool = ThreadPoolExecutor(max_workers=3)
        self.safe_ytdl = YoutubeDL(opts)
        self.safe_ytdl.params['ignore_errors'] = True

        self.unsafe_ytdl = YoutubeDL(opts)

        self.non_flat_ytdl = YoutubeDL(opts)
        self.non_flat_ytdl.params['extract_flat'] = False

    async def extract_info(self, loop, on_error=None, extract_flat=True, *args, **kwargs):
        if extract_flat:
            ytdl = self.unsafe_ytdl
        else:
            ytdl = self.non_flat_ytdl

        terminal.debug('dl called {} {}'.format(args, kwargs))
        if callable(on_error):
            try:
                return ytdl.sanitize_info(await loop.run_in_executor(self.thread_pool, functools.partial(ytdl.extract_info, *args, **kwargs)))

            except Exception as e:

                # when using functools.partial asyncio.iscoroutine doesn't know if
                # the function is async or not so we get the original method to test it
                if isinstance(on_error, functools.partial):
                    func = on_error.func
                else:
                    func = on_error

                if asyncio.iscoroutinefunction(func):
                    asyncio.ensure_future(on_error(e), loop=loop)

                elif asyncio.iscoroutine(func):
                    asyncio.ensure_future(on_error, loop=loop)

                else:
                    loop.call_soon_threadsafe(on_error, e)

        else:
            return ytdl.sanitize_info(await loop.run_in_executor(self.thread_pool, functools.partial(ytdl.extract_info, *args, **kwargs)))

    async def safe_extract_info(self, loop, *args, **kwargs):
        terminal.debug('dl called {} {}'.format(args, kwargs))
        ytdl = self.safe_ytdl
        return ytdl.sanitize_info(await loop.run_in_executor(self.thread_pool, functools.partial(ytdl.extract_info, *args, **kwargs)))

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

from discord.client import Client
import discord


class TimeoutMessage:
    def __init__(self, message, timeout=None, bot=None, deque=None):
        """
        A message class that can be used to have messages that will delete themselves
        after a certain amount of time has passed.

        Args:
            message: TimeoutMessage that await bot.send_message returns. Not a string.
            timeout: The amount of time to be waited before the message is deleted
                     as an int or float
            bot: The Bot or Client class that the message is being sent from
        """
        self.message = message
        self.timeout = timeout
        self.bot = bot
        self.deque = deque
        self.loop = bot.loop
        self._lock = asyncio.Event()  # A lock that causes the message to be deleted when set is called
        if not isinstance(bot, Client):
            print('[ERROR] Bot is not an instance of discord.Client. Message cannot be deleted')
            return

        if not isinstance(timeout, int) and not isinstance(timeout, float):
            print('[ERROR] Timeout is not a number. Message will not be deleted')
            return

        # If either of these is None the message will not be deleted
        if self.bot is not None and timeout is not None:
            self.lock_task = asyncio.ensure_future(self.set_lock(), loop=self.loop)
            self.deletion_task = asyncio.ensure_future(self._delete_message(), loop=self.loop)

    # Sleep for :timeout: amount and then set _lock
    async def set_lock(self):
        try:
            await asyncio.sleep(self.timeout)
            self.loop.call_soon_threadsafe(self._lock.set)
        except:
            pass

    # Set the lock value to true immediately. Useful when skipping songs
    # or shutting the bot down while wanting to delete useless messages
    async def delete_now(self):
        if self.timeout is None:
            return
        try:
            await self.bot.delete_message(self.message)
        except:
            pass

    # Waits for the lock to be set and then deletes the message
    async def _delete_message(self):
        try:
            await self._lock.wait()
            await self.bot.delete_message(self.message)
            self.deque.remove(self)
        except:
            pass

    def cancel_tasks(self):
        try:
            if not self.lock_task.done():
                self.lock_task.cancel()
        except:
            pass

        try:
            if not self.deletion_task.done():
                self.deletion_task.cancel()
        except:
            pass

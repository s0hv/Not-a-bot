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

from discord.ext.commands.errors import CommandError

terminal = logging.getLogger('terminal')


class BotException(CommandError):
    def __init__(self, message=None, *args, cmd_message: str=None, domain=None):
        super().__init__(message, *args)
        self._domain = domain
        if cmd_message is not None:
            terminal.info(cmd_message)

        self._message = message

    @property
    def message(self):
        return self._message

    @property
    def __cause__(self):
        return self


class SilentException(CommandError):
    def __init__(self):
        super().__init__()


class InvalidOwnerIDException(BotException):
    pass


class NotOwner(BotException):
    @property
    def message(self):
        return 'Only the owner can use this command'


class PermException(BotException):
    @property
    def message(self):
        return "You don't have the permission to use this command. \nRequired permissions are: " + self._message


class CommandBlacklisted(BotException):
    @property
    def message(self):
        return self._message


class ImageSizeException(BotException):
    def __init__(self, message, max_pixel, *args, **kwargs):
        super().__init__(message, *args, **kwargs)
        self.max_pixel = max_pixel

    @property
    def message(self):
        return f"Image has too many pixels {self._message} > {self.max_pixel}"


class NotEnoughPrefixes(BotException):
    pass


class PrefixExists(BotException):
    pass


class PrefixDoesntExist(BotException):
    pass


class NoPokeFoundException(BotException):
    @property
    def message(self):
        return 'No pokemon found with {}'.format(self._message)


class NoCachedFileException(Exception):
    pass

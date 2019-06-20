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

from discord.ext.commands.errors import CommandError, CheckFailure

terminal = logging.getLogger('terminal')


class BotException(CommandError):
    def __init__(self, message=None, *args, cmd_message: str=None, domain=None):
        super().__init__(message, *args)
        self._domain = domain
        if cmd_message is not None:
            terminal.info(cmd_message)

        self._message = message or ''

    @property
    def message(self):
        return self._message

    def __str__(self):
        return self.message

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
    def __init__(self, msg, full_msg=None):
        """
        full_msg is always a string and is always equal to msg if msg is not None
        It's used to get the error message when something is blacklisted for a guild or channel
        """
        super().__init__(msg)
        self._full_msg = full_msg or msg

    @property
    def message(self):
        return self._message

    @property
    def full_message(self):
        return self._full_msg


class ImageSizeException(BotException):
    def __init__(self, size, max_pixel, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_pixel = max_pixel
        self._message = size

    @property
    def message(self):
        return f"Image has too many pixels {self._message} > {self.max_pixel}"


class ImageResizeException(BotException):
    def __init__(self, size, max_pixel, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_pixel = max_pixel
        self._message = size

    @property
    def message(self):
        return f"Resized image would have too many pixels {self._message} > {self.max_pixel}\n" \
               "Usually this is because of extremely wide/tall pictures"


class ImageProcessingError(BotException):
    @property
    def message(self):
        return f'Failed to process because of an error\n{self._message}'


class ImageDownloadError(BotException):
    def __init__(self, message, url):
        super().__init__(message)
        self.url = url

    @property
    def message(self):
        return f"Failed to download image {self.url} because {self._message}"


class TooManyFrames(BotException):
    def __init__(self, max_frames, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_frames = max_frames

    @property
    def message(self):
        return f'Too many gif frames. Max is {self.max_frames}'


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


class MissingFeatures(CheckFailure):
    def __init__(self, missing_features, *args):
        self.missing_features = missing_features

        missing = [feature.replace('_', ' ').replace('guild', 'server').upper() for feature in missing_features]

        if len(missing) > 2:
            fmt = '{}, and {}'.format(", ".join(missing[:-1]), missing[-1])
        else:
            fmt = ' and '.join(missing)
        message = 'Guild is missing {} feature(s) to run this command.'.format(fmt)
        super().__init__(message, *args)

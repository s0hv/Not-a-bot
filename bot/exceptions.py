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


class BotException(Exception):
    def __init__(self, message, cmd_message: str=None):
        self._message = message
        if cmd_message is not None:
            print(cmd_message)

    @property
    def message(self):
        return self._message

    @property
    def __cause__(self):
        return self


class InvalidOwnerIDException(BotException):
    pass


class PermissionError(BotException):
    @property
    def message(self):
        return "You don't have the permission to use this command. \nReason: " + self._message


class InvalidLevelException(BotException):
    def __init__(self, required, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._required = required

    @property
    def message(self):
        return ("Required level is %s.\n" % self._required) + self._message


class LevelPermissionException(BotException):
    def __init__(self, required, current, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._required = required
        self._current = current

    @property
    def message(self):
        return "%s\nRequired level to use this command is %s and your level is %s" % (self._message, self._required, self._current)


class InvalidArgumentException(BotException):
    @property
    def message(self):
        return "Invalid argument.\n" + self._message


class InvalidPermissionsException(BotException):
    @property
    def message(self):
        return self._message


class InvalidValueException(BotException):
    def __init__(self, val, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._val = val

    @property
    def message(self):
        return ('The given value "%s" is invalid.\n' % self._val) + self._message


class BotValueError(BotException):
    pass


class NoCachedFileException(Exception):
    pass

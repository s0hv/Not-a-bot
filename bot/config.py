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

import configparser
import os

from bot.exceptions import InvalidOwnerIDException
from utils.utilities import get_config_value


class Config:
    def __init__(self, logger=None):
        self.logger = logger

        self.config = configparser.ConfigParser()
        path = os.path.join(os.getcwd(), 'config', 'config.ini')
        if not os.path.exists(path):
            path = os.path.join(os.getcwd(), 'config', 'example_config.ini')
            if not os.path.exists(path):
                raise ValueError('No config file found')

        self.config.read(path, encoding='utf-8')

        self.token = self.config.get('Credentials', 'Token', fallback=None)
        self.sfx_token = self.config.get('Credentials', 'SfxToken', fallback=None)

        self.mashape_key = get_config_value(self.config, 'Credentials', 'MashapeKey', str, None)
        self.google_api_key = get_config_value(self.config, 'Credentials', 'GoogleAPI', str, None)
        self.custom_search = get_config_value(self.config, 'Credentials', 'CustomSearch', str, None)
        self.wolfram_key = get_config_value(self.config, 'Credentials', 'WolframKey', str, None)

        self.random_sfx = get_config_value(self.config, 'SFXSettings', 'RandomSfx', bool, True)


        try:
            self.owner = str(self.config.get('Owner', 'OwnerID', fallback=None))
            int(self.owner)
        except ValueError as e:
            raise InvalidOwnerIDException('%s\nThe given OwnerID is not valid' % e)

        try:
            self.default_volume = self.config.getfloat('MusicSettings', 'DefaultVolume', fallback=0.15)
        except ValueError as e:
            print("Error %s. The value for DefaultVolume in config isn't a number. Default volume set to 0.15" % e)
            self.default_volume = 0.15

        try:
            self.autoplaylist = self.config.getboolean('MusicSettings', 'Autoplaylist', fallback=False)
        except ValueError as e:
            print("Error %s. Autoplaylist value is not correct. Autoplaylist set to off" % e)
            self.autoplaylist = False

        try:
            self.now_playing = self.config.getboolean('MusicSettings', 'NowPlaying', fallback=False)
        except ValueError as e:
            print("[ERROR] %s. NowPlaying value is not correct. NowPlaying set to off" % e)
            self.now_playing = False

        try:
            self.delete_after = self.config.getboolean('MusicSettings', 'DeleteAfter', fallback=False)
        except ValueError as e:
            print("[ERROR] %s. DeleteAfter value is not boolean. DeleteAfter set to off" % e)
            self.delete_after = False

        try:
            self.download = self.config.getboolean('MusicSettings', 'DownloadSongs', fallback=True)
        except ValueError as e:
            print("[ERROR] %s. DownloadSongs value is not boolean. DownloadSongs set to on" % e)
            self.download = True

        try:
            self.auto_volume = self.config.getboolean('MusicSettings', 'AutoVolume', fallback=False)
        except ValueError as e:
            print("[ERROR] %s. AutoVolume value is not boolean. AutoVolume set to off" % e)
            self.auto_volume = False

        try:
            self.volume_multiplier = self.config.getfloat('MusicSettings', 'VolumeMultiplier', fallback=0.01)
        except ValueError as e:
            print("[ERROR] %s. VolumeMultiplier value is not a number. VolumeMultiplier set to 0.01" % e)
            self.volume_multiplier = 0.01

        try:
            self.gachi = self.config.getboolean('MusicSettings', 'Gachi', fallback=False)
        except ValueError as e:
            print("[ERROR] %s. Gachi value is not boolean. Gachi set to off" % e)
            self.gachi = False

        self.game = self.config.get('BotOptions', 'Game', fallback=None)
        self.sfx_game = self.config.get('BotOptions', 'SfxGame', fallback=None)

        try:
            self.delete_messages = self.config.getboolean('BotOptions', 'DeleteMessages', fallback=False)
        except ValueError as e:
            print("[ERROR] %s. DeleteMessages value is not boolean. DeleteMessages set to off" % e)
            self.delete_messages = False

        try:
            self.max_combo = self.config.getint('SFXSettings', 'MaxCombo', fallback=8)
        except ValueError as e:
            print('[ERROR] %s. MaxCombo value is incorrect. Value set to default (8)' % e)
            self.max_combo = 8

        if self.game is None:
            print('[INFO] No game set for main bot')
            self.game = ''
        if self.sfx_game is None:
            print('[INFO] No game set for sfx bot')
            self.sfx_game = ''

        self.check_values()

    def check_values(self):
        assert self.token != 'bot_token', 'You need to specify your bots token in the config'
        assert self.token != self.sfx_token, "The bots can't have the same token"
        assert self.owner != 'id', 'Please put your discord user id to the config'

        if self.sfx_token is not None and self.sfx_token.lower() == 'bot_token':
            print('[INFO] No valid token given for sfx bot. Only main bot will be used')
            self.sfx_token = None

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
import json
import logging
import os

from bot.exceptions import InvalidOwnerIDException
from utils.utilities import get_config_value

terminal = logging.getLogger('terminal')


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
        self.audio_token = self.config.get('Credentials', 'AudioToken', fallback=None)
        self.test_token = self.config.get('Credentials', 'TestToken', fallback=None)

        self.mashape_key = get_config_value(self.config, 'Credentials', 'MashapeKey', str, None)
        self.google_api_key = get_config_value(self.config, 'Credentials', 'GoogleAPI', str, None)
        self.custom_search = get_config_value(self.config, 'Credentials', 'CustomSearch', str, None)
        self.wolfram_key = get_config_value(self.config, 'Credentials', 'WolframKey', str, None)
        self.feedback_webhook = get_config_value(self.config, 'Credentials', 'FeedbackWebhook', str, None)
        self.dbl_token = get_config_value(self.config, 'Credentials', 'DBApiKey', str, None)

        self.dbl_server = get_config_value(self.config, 'Webhook', 'Server', str, None)
        self.dbl_port = get_config_value(self.config, 'Webhook', 'Port', int, None)
        self.dbl_auth = get_config_value(self.config, 'Webhook', 'Auth', str, None)
        self.dbl_auth = get_config_value(self.config, 'Webhook', 'Webhook', str, None)

        self.random_sfx = get_config_value(self.config, 'SFXSettings', 'RandomSfx', bool, False)

        self.db_user = get_config_value(self.config, 'Database', 'Username', str)
        self.db_password = get_config_value(self.config, 'Database', 'Password', str)
        self.db_host = get_config_value(self.config, 'Database', 'Host', str)
        self.db_port = get_config_value(self.config, 'Database', 'Port', str)
        self.sfx_db_user = get_config_value(self.config, 'Database', 'SFXUsername', str)
        self.sfx_db_pass = get_config_value(self.config, 'Database', 'SFXPassword', str)
        self.redis_auth = get_config_value(self.config, 'Database', 'RedisAuth', str)
        self.redis_port = get_config_value(self.config, 'Database', 'RedisPort', int)


        try:
            self.owner = self.config.getint('Owner', 'OwnerID', fallback=None)
        except ValueError:
            raise InvalidOwnerIDException('%s\nThe given OwnerID is not valid')

        try:
            self.default_volume = self.config.getfloat('MusicSettings', 'DefaultVolume', fallback=0.15)
        except ValueError:
            terminal.exception("The value for DefaultVolume in config isn't a number. Default volume set to 0.15")
            self.default_volume = 0.15

        try:
            self.autoplaylist = self.config.getboolean('MusicSettings', 'Autoplaylist', fallback=False)
        except ValueError:
            terminal.exception("Autoplaylist value is not correct. Autoplaylist set to off")
            self.autoplaylist = False

        try:
            self.now_playing = self.config.getboolean('MusicSettings', 'NowPlaying', fallback=False)
        except ValueError:
            terminal.exception("NowPlaying value is not correct. NowPlaying set to off")
            self.now_playing = False

        try:
            self.delete_after = self.config.getboolean('MusicSettings', 'DeleteAfter', fallback=False)
        except ValueError:
            terminal.exception("DeleteAfter value is not boolean. DeleteAfter set to off")
            self.delete_after = False

        try:
            self.download = self.config.getboolean('MusicSettings', 'DownloadSongs', fallback=True)
        except ValueError:
            terminal.exception("DownloadSongs value is not boolean. DownloadSongs set to on")
            self.download = True

        try:
            self.auto_volume = self.config.getboolean('MusicSettings', 'AutoVolume', fallback=False)
        except ValueError:
            terminal.exception("AutoVolume value is not boolean. AutoVolume set to off")
            self.auto_volume = False

        try:
            self.volume_multiplier = self.config.getfloat('MusicSettings', 'VolumeMultiplier', fallback=0.01)
        except ValueError:
            terminal.exception("VolumeMultiplier value is not a number. VolumeMultiplier set to 0.01")
            self.volume_multiplier = 0.01

        try:
            self.gachi = self.config.getboolean('MusicSettings', 'Gachi', fallback=False)
        except ValueError:
            terminal.exception("Gachi value is not boolean. Gachi set to off")
            self.gachi = False

        p = os.path.join(os.getcwd(), 'config', 'activity.json')
        if not os.path.exists(p):
            terminal.warning('Activity config not found')
            self.default_activity = {}
        else:
            with open(p) as f:
                # Activity config put in json because it's easier to handle in code
                self.default_activity = json.load(f)

        self.game = self.config.get('BotOptions', 'Game', fallback=None)
        self.sfx_game = self.config.get('BotOptions', 'SfxGame', fallback=None)
        self.phantomjs = self.config.get('BotOptions', 'PhantomJS', fallback='phantomjs')
        self.chromedriver = self.config.get('BotOptions', 'Chromedriver', fallback='chromedriver')
        self.chrome = self.config.get('BotOptions', 'Chrome', fallback=None)

        try:
            self.delete_messages = self.config.getboolean('BotOptions', 'DeleteMessages', fallback=False)
        except ValueError:
            terminal.exception("DeleteMessages value is not boolean. DeleteMessages set to off")
            self.delete_messages = False

        try:
            self.max_combo = self.config.getint('SFXSettings', 'MaxCombo', fallback=8)
        except ValueError:
            terminal.exception('MaxCombo value is incorrect. Value set to default (8)')
            self.max_combo = 8

        if self.game is None:
            terminal.info('No game set for main bot')
            self.game = ''
        if self.sfx_game is None:
            terminal.info('No game set for sfx bot')
            self.sfx_game = ''

        self.leave_message = self.config.get('Defaults', 'LeaveMessage', fallback='None')
        self.join_message = self.config.get('Defaults', 'JoinMessage', fallback='None')
        self.edit_message = self.config.get('Defaults', 'EditMessage', fallback='None')
        self.delete_message = self.config.get('Defaults', 'DeleteMessage', fallback='None')

        self.check_values()

    def check_values(self):
        if self.token == 'bot_token':
            raise ValueError('You need to specify your bots token in the config')

        if self.token == self.sfx_token:
            raise ValueError("The bots can't have the same token")

        if self.owner == 'id':
            raise ValueError('Please put your discord user id to the config')

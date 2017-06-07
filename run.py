#!/usr/bin/env python
# -*-coding=utf-8 -*-

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
from multiprocessing import Process

import discord

from bot.config import Config
from bot.permissions import Permissions


def main():
    discord_logger = logging.getLogger('discord')
    discord_logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
    handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
    discord_logger.addHandler(handler)

    logger = logging.getLogger('debug')
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(filename='debug.log', encoding='utf-8', mode='a')
    handler.setFormatter(logging.Formatter('%(asctime)s:%(levelname)s:%(name)s: %(message)s'))
    logger.addHandler(handler)

    config = Config()
    permissions = Permissions(config.owner)
    try:
        from bot import main_bot
    except ImportError as e:
        print('[ERROR] Could not import bot\n%s' % e)
        exit(1)

    if not discord.opus.is_loaded():
        discord.opus.load_opus('opus')

    if config.sfx_token is not None:
        from bot import sfx_bot
    else:
        sfx_bot = None

    if sfx_bot is not None:
        sfx_bot = sfx_bot.SfxBot(config)
        print('[INFO] Sfx bot starting up')
        sfx_bot.start()

    print('[INFO] Main bot starting up')
    logger.info('Starting bots')
    main_bot.start(config, permissions)

if __name__ == '__main__':
    main()

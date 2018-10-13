from bot.globals import PLAYLISTS
import json
import os
from utils.utilities import write_playlist, read_lines


import sys

lines = ''.join(sys.stdin.readlines())
videos = json.loads(lines, encoding='utf-8')
gachilist = os.path.join(PLAYLISTS, 'gachi.txt')


def add_to_list(new_vids):
    write_playlist(gachilist, new_vids, mode='a')


def delete_from_list(deleted_vids):
    songs = set(read_lines(gachilist))
    changed = False
    for song in deleted_vids:
        try:
            songs.remove(song)
            changed = True

        except KeyError:
            pass

    if not changed:
        return

    write_playlist(gachilist, songs)


url_format = videos['url_format']

if videos['new']:
    add_to_list([url_format % vid['id'] for vid in videos['new']])

if videos['deleted']:
    delete_from_list([url_format % vid['id'] for vid in videos['deleted']])

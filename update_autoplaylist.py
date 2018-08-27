from bot.globals import AUTOPLAYLIST
import json
from utils.utilities import write_playlist, read_lines


import sys

lines = ''.join(sys.stdin.readlines())
videos = json.loads(lines, encoding='utf-8')


def add_to_ap(new_vids):
    write_playlist(AUTOPLAYLIST, new_vids, mode='a')


def delete_from_ap(deleted_vids):
    songs = set(read_lines(AUTOPLAYLIST))
    changed = False
    for song in deleted_vids:
        try:
            songs.remove(song)
            changed = True

        except KeyError:
            pass

    if not changed:
        return

    write_playlist(AUTOPLAYLIST, songs)


url_format = videos['url_format']

if videos['new']:
    add_to_ap([url_format % vid for vid in videos['new']])

if videos['deleted']:
    delete_from_ap([url_format % vid for vid in videos['deleted']])

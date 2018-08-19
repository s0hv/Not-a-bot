import logging

from bot.bot import command
from bot.globals import ADD_AUTOPLAYLIST, DELETE_AUTOPLAYLIST, AUTOPLAYLIST
from bot.globals import Auth
from cogs.cog import Cog
from utils.utilities import read_lines, empty_file, write_playlist, test_url

terminal = logging.getLogger('terminal')


class BotMod(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(ignore_extra=True, auth=Auth.BOT_MOD)
    async def add_all(self, ctx):
        """Add the pending songs to autoplaylist"""
        songs = set(read_lines(ADD_AUTOPLAYLIST))

        invalid = []
        for song in list(songs):
            if not test_url(song):
                songs.remove(song)
                invalid.append(song)

        if invalid:
            await ctx.send('Invalid url(s):\n%s' % ', '.join(invalid), delete_after=40)

        write_playlist(AUTOPLAYLIST, songs, mode='a')
        empty_file(ADD_AUTOPLAYLIST)

        amount = len(songs)
        await ctx.send('Added %s song(s) to autoplaylist' % amount)

    @command(ignore_extra=True, auth=Auth.BOT_MOD)
    async def delete_all(self, ctx):
        """Delete pending songs from autoplaylist"""
        delete_songs = set(read_lines(DELETE_AUTOPLAYLIST))

        _songs = read_lines(AUTOPLAYLIST)
        songs = set(_songs)
        duplicates = len(_songs) - len(songs)

        failed = 0
        succeeded = 0
        for song in delete_songs:
            try:
                songs.remove(song)
                succeeded += 1
            except KeyError as e:
                failed += 1
                terminal.exception('Failed to delete all from autoplaylist')

        write_playlist(AUTOPLAYLIST, songs)

        empty_file(DELETE_AUTOPLAYLIST)

        await ctx.send('Successfully deleted {0} songs, {1} duplicates and failed {2}'.format(succeeded, duplicates, failed))


def setup(bot):
    bot.add_cog(BotMod(bot))

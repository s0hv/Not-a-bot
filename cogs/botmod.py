from cogs.cog import Cog
from bot.globals import ADD_AUTOPLAYLIST, DELETE_AUTOPLAYLIST, AUTOPLAYLIST
from utils.utilities import read_lines, empty_file, write_playlist, test_url
from bot.bot import command
from bot.globals import Auth


class BotMod(Cog):
    def __init__(self, bot):
        super().__init__(bot)

    @command(pass_context=True, ignore_extra=True, auth=Auth.MOD)
    async def add_all(self, ctx):
        """Add the pending songs to autoplaylist"""
        songs = set(read_lines(ADD_AUTOPLAYLIST))

        invalid = []
        for song in list(songs):
            if not test_url(song):
                songs.remove(song)
                invalid.append(song)

        if invalid:
            await self.bot.say('Invalid url(s):\n%s' % ', '.join(invalid), delete_after=40)

        write_playlist(AUTOPLAYLIST, songs, 'a')
        empty_file(ADD_AUTOPLAYLIST)

        amount = len(songs)
        await self.bot.say('Added %s song(s) to autoplaylist' % amount)

    @command(pass_context=True, ignore_extra=True, auth=Auth.MOD)
    async def delete_all(self, ctx):
        """Delete pending songs from autoplaylist"""
        delete_songs = set(read_lines(DELETE_AUTOPLAYLIST))

        songs = set(read_lines(AUTOPLAYLIST))

        failed = 0
        succeeded = 0
        for song in delete_songs:
            try:
                songs.remove(song)
                succeeded += 1
            except KeyError as e:
                failed += 1
                print('[EXCEPTION] KeyError: %s' % e)

        write_playlist(AUTOPLAYLIST, songs)

        empty_file(DELETE_AUTOPLAYLIST)

        await self.bot.say('Successfully deleted {0} songs and failed {1}'.format(succeeded, failed))


def setup(bot):
    bot.add_cog(BotMod(bot))

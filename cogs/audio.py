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

import asyncio
import logging
import os
import re
import shutil
from datetime import timedelta
from math import floor
from random import choice
from typing import Optional, Union

import disnake
from disnake import AllowedMentions, ApplicationCommandInteraction
from disnake.ext import commands
from disnake.ext.commands import Param
from disnake.ext.commands import guild_only
from disnake.ext.commands import (slash_command, is_owner, cooldown)
from disnake.ext.commands.cooldowns import BucketType

from bot import player
from bot.bot import command, Context
from bot.converters import convert_timedelta
from bot.downloader import Downloader
from bot.globals import ADD_AUTOPLAYLIST, DELETE_AUTOPLAYLIST
from bot.globals import Auth
from bot.paginator import Paginator
from bot.player import get_track_pos, MusicPlayer, format_time
from bot.playlist import (Playlist, validate_playlist_name, load_playlist,
                          create_playlist, validate_playlist, write_playlist,
                          PLAYLISTS)
from bot.song import Song, PartialSong
from bot.youtube import (extract_playlist_id, extract_video_id, Part, id2url,
                         parse_youtube_duration)
from utils.utilities import (parse_seek, seek_from_timestamp,
                             basic_check, format_timedelta, test_url,
                             wait_for_words, DateAccuracy)

logger = logging.getLogger('audio')
terminal = logging.getLogger('terminal')

stereo_modes = ["sine", "triangle", "square", "sawup", "sawdown", 'off', 'left', 'right']

VolumeType = Param(name='volume', default=None, min_value=0, max_value=200)
PlaylistOwner = Param(description='Owner of the playlist', name='user', default=None)
PlaylistShuffle = Param(description='Whether to shuffle the playlist or not. Shuffles by default.', name='shuffle', default=True)
PlaylistName = Param(description='Name of the playlist', name='playlist_name')
LongerThan = Param(description='If false will find songs shorter than the given duration', name='longer_than', default=True)
Duration = Param(converter=convert_timedelta, description='Duration in the format 1h 1m 1s', name='duration')
Clear = Param(description='If set to True will clear the found items', name='clear', default=False)
OptionalBool = Param(None)


def check_who_queued(user):
    """
    Returns a function that checks if the song was requested by user
    """
    def pred(song):
        if song.requested_by and song.requested_by.id == user.id:
            return True

        return False

    return pred


def check_duration(sec, larger=True):
    """
    Creates a function you can use to check songs
    Args:
        sec:
            duration that we compare to in seconds
        larger:
            determines if we do a larger than operation

    Returns:
        Function that can be used to check songs
    """
    def pred(song):
        if larger:
            if song.duration > sec:
                return True
        else:
            if song.duration < sec:
                return True

        return False

    return pred


def select_by_predicate(songs, pred):
    selected = []
    for song in songs:
        if pred(song):
            selected.append(song)

    return selected


def playlist2partialsong(songs):
    return [PartialSong(**song) for song in songs]

def get_indices(items: Optional[str]) -> Optional[list[range | int]]:
    if not items:
        return None

    indexes = items.split(' ')
    index = []
    for idx in indexes:
        if '-' in idx:
            idx = idx.split('-')
            a = int(idx[0])
            b = int(idx[1])
            index += range(a - 1, b)
        else:
            index.append(int(idx) - 1)

    return index


class Audio(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.musicplayers = self.bot.playlists
        self.viewed_playlists = self.bot.viewed_playlists
        self.downloader = Downloader()

    def get_musicplayer(self, guild_id: int, is_on: bool=True) -> Optional[MusicPlayer]:
        """
        Gets the musicplayer for the guild if it exists
        Args:
            guild_id (int): id of the guild
            is_on (bool):
                If set on will only accept a musicplayer which has been initialized
                and is ready to play without work. If it finds unsuitable target
                it will destroy it and recursively call this function again

        Returns:
            MusicPlayer: If musicplayer was found
                         else None
        """
        musicplayer = self.musicplayers.get(guild_id)
        if musicplayer is None:
            musicplayer = self.find_musicplayer_from_garbage(guild_id)

            if is_on and musicplayer is not None and not musicplayer.is_alive():
                MusicPlayer.__instances__.discard(musicplayer)
                musicplayer.selfdestruct()
                del musicplayer
                return self.get_musicplayer(guild_id)

        return musicplayer

    def find_musicplayer_from_garbage(self, guild_id: int) -> Optional[MusicPlayer]:
        for obj in MusicPlayer.get_instances():
            if obj.channel.guild.id == guild_id:
                self.musicplayers[guild_id] = obj
                return obj

    async def check_player(self, ctx: ApplicationCommandInteraction | Context) -> Optional[MusicPlayer]:
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer is None:
            terminal.error('Playlist not found even when voice is playing')
            await ctx.send(f'No playlist found. Use force_stop to reset voice state')

        return musicplayer

    @staticmethod
    def _parse_filters(options: str, filter_name: str, value: str, remove=False):
        logger.debug('Parsing filters: {0}, {1}, {2}'.format(options, filter_name, value))
        if remove:
            matches = re.findall(r'("|^|, )({}=.+?)(, |"|$)'.format(filter_name), options)
        else:
            matches = re.findall(r'(?: |"|^|,)({}=.+?)(?:, |"|$)'.format(filter_name), options)
        logger.debug('Filter matches: {}'.format(matches))

        if remove:
            if not matches:
                return options
            matches = matches[0]
            if matches.count(' ,') == 2:
                options = options.replace(''.join(matches), ', ')

            elif matches[0] == '"':
                options = options.replace(''.join(matches[1]), '')
            elif matches[2] == '"':
                options = options.replace(''.join(matches[:2]), '')
            else:
                options = options.replace(''.join(matches), '')
            if '-filter:a ""' in options:
                options = options.replace('-filter:a ""', '')

            return options

        if matches:
            return options.replace(matches[0].strip(), '{0}={1}'.format(filter_name, value))

        else:
            filt = '{0}={1}'.format(filter_name, value)
            logger.debug('Filter value set to {}'.format(filt))
            if '-filter:a "' in options:
                bef_filt, aft_filt = options.split('-filter:a "', 2)
                logger.debug('before and after filter. "{0}", "{1}"'.format(bef_filt, aft_filt))
                options = '{0}-filter:a "{1}, {2}'.format(bef_filt, filt, aft_filt)

            else:
                options += ' -filter:a "{0}"'.format(filt)

            return options

    @staticmethod
    async def check_voice(ctx: ApplicationCommandInteraction | Context, user_connected: bool=True) -> bool:
        voice_client = ctx.guild.voice_client
        if voice_client is None:
            await ctx.send('Not connected to a voice channel')
            return False

        if user_connected and not ctx.author.voice:
            await ctx.send("You aren't connected to a voice channel")
            return False

        elif user_connected and ctx.author.voice.channel.id != voice_client.channel.id:
            await ctx.send("You aren't connected to this bots voice channel")
            return False

        return True

    async def get_player_and_check(self, ctx):
        if not await self.check_voice(ctx):
            return

        if not await self.check_player(ctx):
            return

        musicplayer = await self.check_player(ctx)

        return musicplayer

    @slash_command(aliases=['a'])
    @cooldown(1, 4, type=BucketType.guild)
    async def again(self, ctx):
        """Queue the currently playing song to the end of the queue"""
        await self._again(ctx)

    @slash_command()
    @cooldown(1, 3, type=BucketType.guild)
    async def again_play_now(self, ctx):
        """Queue the currently playing song to the start of the queue"""
        await self._again(ctx, True)

    async def _again(self, ctx: ApplicationCommandInteraction, priority: bool=False):
        """
        Args:
            ctx: class Context
            priority: If true song is added to the start of the playlist

        Returns:
            None
        """
        if not await self.check_voice(ctx):
            return

        voice_client = ctx.guild.voice_client
        if not voice_client.is_playing():
            return await ctx.send('Not playing anything')

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        song = Song.from_song(musicplayer.current, requested_by=ctx.author)
        await musicplayer.playlist.add_from_song(song, priority, channel=ctx)

    @commands.cooldown(2, 3, type=BucketType.guild)
    @slash_command(description='Seeks to the given position in the song')
    async def seek(self, ctx: ApplicationCommandInteraction, where: str = Param(description='Position to seek to using this format: 1h 1m 1s')):
        """
        Seek a song using this format 1h 1m 1s 1ms,
        where at least one of them is required. Milliseconds must be zero padded
        so to seek only one millisecond put 001ms. Otherwise, the song will just
        restart. e.g. 1h 4s and 2m1s3ms both should work.
        """
        await ctx.response.defer()
        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None or not ctx.guild.voice_client.is_playing():
            return await ctx.send('Not playing anything', ephemeral=True)

        seek = parse_seek(where)
        if seek is None:
            return await ctx.send('Invalid time string')

        await self._seek(musicplayer, current, seek)
        await ctx.send('✅')

    async def _seek(self, musicplayer, current, seek_dict, options=None,
                    speed=None):
        """
        Args:
            current: The song that we want to seek

            seek_dict: A command that is passed to before_options

            options: passed to create_ffmpeg_player options
        Returns:
            None
        """
        if options is None:
            options = current.options

        logger.debug('Seeking with dict {0} and these options: before_options="{1}", options="{2}"'.format(seek_dict, current.before_options, options))

        await current.validate_url()
        musicplayer.player.seek(current.filename, seek_dict, before_options=current.before_options, options=options, speed=speed)

    @staticmethod
    def _parse_play(string, ctx, metadata=None):
        options = {}
        filters = []
        if metadata and 'filter' in metadata:
            fltr = metadata['filter']
            if isinstance(fltr, str):
                filters.append(fltr)
            else:
                filters.extend(fltr)

        song_name = string

        if filters:
            options['options'] = '-filter:a "{}"'.format(', '.join(filters))

        if metadata is not None:
            for key in options:
                if key in metadata:
                    logger.debug('Setting metadata[{0}] to {1} from {2}'.format(key, options[key], metadata[key]))
                    metadata[key] = options[key]
                else:
                    logger.debug('Added {0} with value {1} to metadata'.format(key, options[key]))
                    metadata[key] = options[key]
        else:
            metadata = options

        if 'requested_by' not in metadata:
            metadata['requested_by'] = ctx.author

        if not test_url(song_name):
            song_name = 'ytsearch:' + song_name

        logger.debug('Parse play returned {0}, {1}'.format(song_name, metadata))
        return song_name, metadata

    @command(enabled=False, hidden=True)
    async def sfx(self, ctx):
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        musicplayer.player.source2 = player.FFmpegPCMAudio('file', reconnect=False)

    @slash_command(cooldown_after_parsing=True, name='play',
                   description='Play the given song. A link will play the link and keywords will do a YouTube search.')
    @commands.cooldown(1, 3, type=BucketType.user)
    @guild_only()
    async def play_slash(self, ctx: ApplicationCommandInteraction, *, song_name: str):
        """Put a song in the playlist. If you put a link it will play that link and
        if you put keywords it will search YouTube for them"""
        await ctx.response.defer()
        await self.play_song(ctx, song_name)

    @command(cooldown_after_parsing=True, name='play')
    @commands.cooldown(1, 3, type=BucketType.user)
    @guild_only()
    async def play_cmd(self, ctx: Context, *, song_name: str):
        """Put a song in the playlist. If you put a link it will play that link and
        if you put keywords it will search YouTube for them"""
        await self.play_song(ctx, song_name)

    @slash_command()
    @commands.cooldown(1, 3, type=BucketType.user)
    async def play_gapless(self, ctx: ApplicationCommandInteraction, song_name: str):
        """Works the same as /play but this also sets gapless playback mode on"""
        await ctx.response.defer()
        await self.play_song(ctx, song_name, gapless=True)

    async def summon_checks(self, ctx: ApplicationCommandInteraction | Context) -> tuple[Optional[MusicPlayer], Optional[bool]]:
        if not ctx.author.voice:
            await ctx.send('Not connected to a voice channel')
            return None, None

        voice_client = ctx.guild.voice_client
        if voice_client and voice_client.channel.id != ctx.author.voice.channel.id:
            await ctx.send('Not connected to the same channel as the bot')
            return None, None

        success = False
        if voice_client is None:
            success = await self._summon(ctx, create_task=False)
            if not success:
                terminal.debug('Failed to join vc')
                return None, None

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return None, None

        return musicplayer, success

    async def play_song(self, ctx: ApplicationCommandInteraction | Context, song_name, priority=False, gapless=False, **metadata):
        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        musicplayer.gapless = gapless
        song_name, metadata = self._parse_play(song_name, ctx, metadata)

        maxlen = -1 if ctx.author.id == self.bot.owner_id else 20
        await musicplayer.playlist.add_song(song_name, maxlen=maxlen,
                                            channel=ctx,
                                            priority=priority, **metadata)
        if priority:
            await musicplayer.reset_gapless()
        if success:
            musicplayer.start_playlist()

    @slash_command(name='playlist', description='Playlist related commands')
    async def playlist(self, _):
        pass

    @playlist.sub_command(aliases=['play_p', 'pp'], name='play')
    @cooldown(1, 10, BucketType.user)
    async def play_playlist(
            self, ctx: ApplicationCommandInteraction,
            playlist_name: str = PlaylistName,
            user: disnake.User = PlaylistOwner,
            shuffle: bool = PlaylistShuffle,
            max_songs: int = Param(None, min_value=0),
            items: Optional[str] = Param(None, description='Which playlist positions to queue. e.g. "4", "1-10", "1 5-9"')):
        """Queue a saved playlist in random order"""
        await ctx.response.defer()
        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        user = user if user else ctx.author
        if not await musicplayer.playlist.add_from_playlist(
                user, playlist_name, ctx, shuffle=shuffle, author=ctx.author, max_songs=max_songs, indices=get_indices(items)
        ):
            return await ctx.send(f"Couldn't find playlist {playlist_name} of user {user} or playlist was empty")

        if success:
            musicplayer.start_playlist()

    @playlist.sub_command(name='play_random')
    @cooldown(1, 5, BucketType.user)
    async def play_random_playlist(
            self, ctx: ApplicationCommandInteraction,
            playlist_name: str =PlaylistName,
            user: disnake.User = PlaylistOwner):
        """Queue a random song from given playlist"""
        await ctx.response.defer()
        songs = await self.get_playlist(ctx, user, playlist_name)
        if songs is False:
            return

        song = choice(songs)
        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        song = Song(musicplayer.playlist, config=self.bot.config, **song,
                    requested_by=ctx.author)

        await musicplayer.playlist.add_from_song(song, channel=ctx)
        if success:
            musicplayer.start_playlist()

    @playlist.sub_command(name='play_viewed', description='Enqueues all the songs from the last playlist you viewed filters included.')
    @cooldown(1, 5)
    async def play_viewed_playlist(self, ctx: ApplicationCommandInteraction):
        """
        Enqueues all the songs from the last playlist you viewed.
        You can use this to filter playlist and add songs based on that filter
        """
        await ctx.response.defer()
        songs = self.viewed_playlists.get(ctx.author.id, None)
        if not songs:
            await ctx.send("You haven't viewed any playlists. Use `view_playlist` "
                           "or any of it's subcommands then use this command to add those songs to the list")
            return

        musicplayer, success = await self.summon_checks(ctx)
        if not musicplayer:
            return

        self.viewed_playlists.pop(ctx.author.id, None)

        songs[1].cancel()
        name = songs[2]
        songs = songs[0]

        added = await musicplayer.playlist.add_from_partials(songs, ctx.author, ctx)

        await ctx.send(f'Enqueued {added} songs from {name}')

        if success:
            musicplayer.start_playlist()

    async def _process_links(self, ctx: ApplicationCommandInteraction, links: list[str], max_size=30, **metadata):
        is_owner = ctx.author.id == self.bot.owner_id
        songs = links
        failed = []
        new_songs = []
        youtube_vids = []
        youtube_playlists = []
        song = None

        def on_error(_):
            nonlocal song
            failed.append(song.replace('@', '@\u200b'))

        for song in songs:
            if len(new_songs) >= max_size:
                await ctx.send(f'Playlist filled (max size {max_size}) before all songs could be processed. Latest processed song was {new_songs[-1].webpage_url}')
                break

            if not test_url(song):
                failed.append(song.replace('@', '@\u200b'))
                continue

            video_id = extract_video_id(song)
            if video_id:
                youtube_vids.append(video_id)
                continue

            playlist_id = extract_playlist_id(song)
            if playlist_id:
                youtube_playlists.append(playlist_id)
                continue

            info = await self.downloader.extract_info(self.bot.loop,
                                                      url=song,
                                                      download=False,
                                                      on_error=on_error)
            if not info:
                await ctx.send('Nothing found or error')
                return

            if 'entries' in info:
                # Link was a playlist so we process it as one
                entries = await Playlist.process_playlist(info, channel=ctx)
                if not entries:
                    failed.append(song.replace('@', '@\u200b'))
                    continue

                def error(_):
                    nonlocal entry
                    # skipcq: PYL-W0631
                    # We want to get the error for the current entry in the loop so
                    # we access the loop variable here
                    failed.append(entry)

                infos = []
                for entry in entries:
                    info = await self.downloader.extract_info(self.bot.loop,
                                                              url=entry,
                                                              download=False,
                                                              on_error=error)
                    if info is None:
                        continue

                    infos.append(info)

                    # If total amount of songs after adding this is more
                    # than max we stop adding them. This is because you could
                    # bypass max_size by using playlists.
                    if len(new_songs) + len(infos) >= max_size:
                        break

            else:
                infos = [info]

            for info in infos:
                new_songs.append(Song(webpage_url=info['webpage_url'],
                                      title=info.get('title'),
                                      duration=info.get('duration'),
                                      **metadata))

        # Max results for youtube api
        max_results = 1000 if not is_owner else 5000
        for playlist_id in youtube_playlists:
            videos = await self.bot.run_async(self.bot.yt_api.playlist_items,
                                              playlist_id, Part.ContentDetails,
                                              max_results)
            if not videos:
                await ctx.send(f"Failed to download youtube playlist with the id {playlist_id}")
            else:
                youtube_vids.extend([vid['contentDetails']['videoId'] for vid in videos])

        if youtube_vids:
            if len(youtube_vids) > max_results:
                await ctx.send(f'Youtube vid limit reached. Skipping {len(youtube_vids) - max_results} entries')

            videos = await self.bot.run_async(self.bot.yt_api.video_info,
                                              youtube_vids[:max_results], Part.combine(Part.ContentDetails, Part.Snippet))

            for song in videos:
                snippet = song['snippet']
                new_songs.append(Song(webpage_url=id2url(song['id']),
                                      title=snippet['title'],
                                      duration=parse_youtube_duration(song['contentDetails']['duration']),
                                      **metadata))

        return new_songs, failed

    # TODO Add subcommands to add from queue but with a filter
    @playlist.sub_command(name='add', aliases=['atp'], cooldown_after_parsing=True, description='Adds songs to the given playlist.')
    @cooldown(1, 20, BucketType.user)
    async def add_to_playlist(
            self, ctx: ApplicationCommandInteraction,
            playlist_name: str = PlaylistName,
            song_links: str = Param()):
        """
        Adds songs to the given playlist.
        If the keyword queue is given as in `{prefix}{name} queue` it will
        add the current queue to the playlist. There is no limit to the max added
        songs with this method.

        Otherwise, you can give it links to songs or playlists, and it'll add
        those to the playlist. Max amount of songs added this way is 30 for
        non YouTube links and hundreds for YouTube links
        """
        await ctx.response.defer()
        songs = load_playlist(playlist_name, ctx.author.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name}")
            ctx.application_command.reset_cooldown(ctx)
            return

        path = os.path.join(PLAYLISTS, str(ctx.author.id), playlist_name)
        if os.path.islink(path):
            await ctx.send('Playlist cannot be edited because it\'s a shallow copy.\n'
                           'See help of copy_playlist for info on how to make a deep copy')
            return

        if song_links.lower().strip(' \n') == 'queue':
            musicplayer = self.get_musicplayer(ctx.guild.id)
            if not musicplayer or musicplayer.player is None or musicplayer.current is None:
                ctx.application_command.reset_cooldown(ctx)
                await ctx.send('No songs currently in queue')
                return

            new_songs = list(musicplayer.playlist.playlist)
            if musicplayer.current:
                new_songs.append(musicplayer.current)

            await ctx.send('Getting song infos for playlist')
            added = 0
            for song in new_songs:
                if not song.duration:
                    await song.download(return_if_downloading=False)

                if not song.success:
                    continue

                added += 1
                songs.append({'webpage_url': song.webpage_url, 'title': song.title,
                              'duration': song.duration})

        else:
            await ctx.send('Getting song infos for playlist')
            res = await self._process_links(ctx, song_links.replace('\n', ' ').split(' '))
            if not res:
                await ctx.send('Failed to process links')
                return

            new_songs, failed = res

            if failed:
                await ctx.send('Failed to add %s' % ', '.join(failed))

            if not new_songs:
                return

            added = len(new_songs)
            for song in new_songs:
                songs.append({'webpage_url': song.webpage_url, 'title': song.title,
                              'duration': song.duration})

        try:
            s = write_playlist(songs, playlist_name, ctx.author.id, overwrite=True)
        except (FileExistsError, PermissionError) as e:
            await ctx.send(str(e))
            return

        await ctx.send(f'{s}\nAdded {added} songs')

    @playlist.sub_command_group(name='delete', description='Delete playlists or songs from them')
    async def playlist_delete(self, _):
        pass

    @playlist_delete.sub_command(name='from', description='Delete the given links from the playlist. If no links given deletes current song.')
    @cooldown(1, 5, BucketType.user)
    async def delete_from_playlist(self, ctx: ApplicationCommandInteraction,
                                   playlist_name: str = PlaylistName,
                                   song_links: str = None):
        """Delete the given links from the playlist.
        If no links are given will delete the currently playing song.
        There is no limit to how many links can be deleted from a playlist at once
        other than discords maximum character limit"""
        await ctx.response.defer()
        songs = load_playlist(playlist_name, ctx.author.id)

        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name}")
            ctx.application_command.reset_cooldown(ctx)
            return

        if not song_links:
            musicplayer = self.get_musicplayer(ctx.guild.id)
            if not musicplayer or musicplayer.player is None or musicplayer.current is None:
                ctx.application_command.reset_cooldown(ctx)
                await ctx.send('No songs currently in queue')
                return

            song_links = [musicplayer.current.webpage_url]
        else:
            song_links = re.split(r'[\n\s]', song_links)

        song_links = set(song_links)
        old_len = len(songs)  # Used to check how many songs were deleted
        songs = list(filter(lambda song: song['webpage_url'] not in song_links, songs))

        deleted = old_len - len(songs)

        try:
            s = write_playlist(songs, playlist_name, ctx.author.id, overwrite=True)
        except (FileExistsError, PermissionError) as e:
            await ctx.send(str(e))
            return

        await ctx.send(f'{s}\nDeleted {deleted} song(s)')

    @playlist.sub_command(name='create', description='Create a playlist from the current queue or from links you pass after the prompt.')
    @cooldown(1, 20, BucketType.user)
    async def create_playlist(self, ctx: ApplicationCommandInteraction, playlist_name: str = PlaylistName):
        """
        Create a playlist from the current queue or from links you pass after the prompt.
        When creating a playlist from current queue there is no limit to song amount
        """
        await ctx.response.defer()
        if not validate_playlist_name(playlist_name):
            ctx.application_command.reset_cooldown(ctx)
            return await ctx.send(f"{playlist_name} doesn't follow naming rules. Allowed characters are a-Z and 0-9 and max length is 100", ephemeral=True)

        await ctx.send('What would you like the contents of the playlist to be\n'
                       'For current music queue say `yes` otherwise post all the links you want in your playlist.\n'
                       'Max amount of self posted links is 30 for non youtube links and hundreds for youtube links')

        try:
            msg = await self.bot.wait_for('message', check=basic_check(ctx.author, ctx.channel), timeout=60)
        except asyncio.TimeoutError:
            ctx.application_command.reset_cooldown(ctx)
            return await ctx.send('Took too long.')

        if msg.content.lower() == 'yes':
            musicplayer = self.get_musicplayer(ctx.guild.id)
            if not musicplayer or musicplayer.player is None or musicplayer.current is None:
                ctx.application_command.reset_cooldown(ctx)
                await ctx.send("No songs currently in queue. Playlist wasn't created")
                return

            songs = list(musicplayer.playlist.playlist)
            if musicplayer.current:
                songs.append(musicplayer.current)

            await ctx.send('Getting song infos for playlist')
            await create_playlist(songs, ctx.author, playlist_name, ctx)

        else:
            await ctx.send('Getting song infos for playlist')
            new_songs, failed = await self._process_links(ctx, msg.content.replace('\n', ' ').split(' '))

            if new_songs:
                await create_playlist(new_songs, ctx.author, playlist_name, ctx)

            if failed:
                await ctx.send('Failed to add %s' % ', '.join(failed))

    @staticmethod
    async def _copy_playlist(ctx: ApplicationCommandInteraction, user: disnake.User, name, deep=False):
        user = user if user else ctx.author
        src = validate_playlist(name, user.id)
        if src is False:
            ctx.application_command.reset_cooldown(ctx)
            await ctx.send(f"Couldn't find playlist {name} of user {user}")
            return

        dst = os.path.join(PLAYLISTS, str(ctx.author.id))
        if not os.path.exists(dst):
            os.mkdir(dst)
        dst = os.path.join(dst, name)

        if os.path.exists(dst):
            ctx.application_command.reset_cooldown(ctx)
            await ctx.send(f'Filename {name} is already in use')
            return

        try:
            if deep:
                shutil.copyfile(src, dst)
            else:
                os.symlink(src, dst)
        except OSError:
            logger.exception('failed to copy playlist')
            await ctx.send('Failed to copy playlist. Try again later')
            return

        await ctx.send(f'Successfully copied {user}\'s playlist {name} to {name}')

    @playlist.sub_command(name='copy', description='Copy a playlist to your own playlists with a name.')
    @cooldown(1, 20, BucketType.user)
    async def copy_playlist(
            self, ctx: ApplicationCommandInteraction,
            playlist_name: str = PlaylistName,
            user: disnake.User = PlaylistOwner,
            deep: bool = Param(description='If set to True you can edit the copied playlist.', default=False)):
        """
        Copy a playlist to your own playlists with a name.
        By default, you can't edit a playlist you've copied, but it mirrors all changes the original user will make to it.
        This means if the original owner deletes the playlist the copy will also become empty.

        If you want to make a deep copy that doesn't mirror changes but will work and be editable by you
        no matter what happens to the original use the subcommand deep as shown in the example
        """
        await ctx.response.defer()
        await self._copy_playlist(ctx, user, playlist_name, deep=deep)

    @staticmethod
    async def get_playlist(ctx, user, name):
        user = user if user else ctx.author
        songs = load_playlist(name, user.id)
        if songs is False:
            await ctx.respond(f"Couldn't find playlist {name} of user {user}")

        return songs

    def add_viewed_playlist(self, user, playlist, name):
        async def pop_list():
            await asyncio.sleep(60)
            self.viewed_playlists.pop(user.id, None)

        if user.id in self.viewed_playlists:
            self.viewed_playlists[user.id][1].cancel()

        task = asyncio.run_coroutine_threadsafe(pop_list(), loop=self.bot.loop)
        self.viewed_playlists[user.id] = (playlist, task, name)

    @playlist.sub_command(name='list', aliases=['lp'])
    @cooldown(1, 5, BucketType.user)
    async def list_playlists(self, ctx: ApplicationCommandInteraction, user: disnake.User = PlaylistOwner):
        """
        List all the names of the playlists a user own. If user is not provided defaults to you
        """
        user = user if user else ctx.author
        p = os.path.join(PLAYLISTS, str(user.id))

        if not os.path.exists(p):
            return await ctx.send(f"{user} doesn't have any playlists")

        try:
            playlists = os.listdir(p)
        except OSError:
            logger.exception(f'Failed to list playlists of {user.id}')
            await ctx.send('Failed to get playlists because of an error')
            return

        if not playlists:
            return await ctx.send(f"{user} doesn't have any playlists")

        await ctx.send(f'Playlists of {user}\n\n' + '\n'.join(playlists))

    @playlist_delete.sub_command(name='duplicates')
    @cooldown(1, 5, BucketType.user)
    async def clear_playlist_duplicates(self, ctx: ApplicationCommandInteraction, playlist_name: str = PlaylistName):
        """
        Clears all duplicate links from the given playlist
        """
        await ctx.response.defer()
        songs = await self.get_playlist(ctx, ctx.author, playlist_name)
        if not songs:
            return

        links = set()
        # Adds non duplicates to the list and skips duplicates
        new_songs = [song for song in songs if not song['webpage_url'] in links and not links.add(song['webpage_url'])]

        try:
            write_playlist(new_songs, playlist_name, ctx.author.id, overwrite=True)
        except (FileExistsError, PermissionError) as e:
            await ctx.send(str(e))
            return

        await ctx.send(f'Deleted {len(songs) - len(new_songs)} duplicate(s) from the playlist "{playlist_name}"')

    @playlist.sub_command_group(name='view', description='View a playlist with or without filters')
    async def playlist_view(self):
        pass

    @playlist_view.sub_command(name='playlist', description="Get the contents of one of your playlists or someone else's playlists")
    @cooldown(1, 5, BucketType.user)
    async def view_playlist(self, ctx: ApplicationCommandInteraction,
                            playlist_name: str = PlaylistName,
                            user: disnake.User = PlaylistOwner):
        """
        Get the contents of one of your playlists or someone else's playlists
        Usage
        `{prefix}{name} [user] name of playlist`
        where [user] is replaced with the user who owns the playlist.
        User is an optional parameter and when not given will default to your playlists
        """
        # This is needed for add_viewed_playlist to work when no user is provided
        await ctx.response.defer()
        user = user if user else ctx.author
        songs = await self.get_playlist(ctx, user, playlist_name)
        if songs is False:
            return

        songs = playlist2partialsong(songs)
        self.add_viewed_playlist(user, songs, playlist_name)
        await self.send_playlist(ctx, songs, None, partial=True, accurate_indices=False)

    @playlist_view.sub_command(name='by_duration', description='Filters playlist by song duration.')
    @cooldown(1, 5, BucketType.user)
    async def playlist_by_time(
            self, ctx: ApplicationCommandInteraction,
            playlist_name: str = PlaylistName,
            duration: timedelta = Duration,
            user: disnake.User = PlaylistOwner,
            longer_than: bool = LongerThan,
            clear: bool = Clear):
        """Filters playlist by song duration.
        `{prefix}{name} [User#1234] "playlist name" no 10m` will select all songs under 10min and
        `{prefix}{name} [User#1234] "playlist name" 10m` will select songs over 10min"""
        user = user if user else ctx.author
        songs = load_playlist(playlist_name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name} of user {user}")
            return

        selected = select_by_predicate(playlist2partialsong(songs), check_duration(duration.total_seconds(), longer_than))
        if not selected:
            await ctx.send(f'No songs {"longer" if longer_than else "shorter"} than {duration}')
            return

        if clear:
            length = len(songs)

            try:
                s = write_playlist([song.__dict__() for song in selected], playlist_name,
                                   user.id, overwrite=True)
            except (FileExistsError, PermissionError) as e:
                await ctx.send(str(e))
                return

            s += f'\n{length - len(selected)} songs deleted that were longer than {duration}'
            await ctx.send(s)
            return

        self.add_viewed_playlist(user, selected, playlist_name)
        await self.send_playlist(ctx, selected, None, partial=True, accurate_indices=False)

    @playlist_view.sub_command(name='by_name', description='Filter playlist by song name. Regex can be used for this.')
    @cooldown(1, 5, BucketType.user)
    async def playlist_by_name(
            self, ctx: ApplicationCommandInteraction,
            playlist_name: str = PlaylistName,
            song_name: str = Param(),
            user: disnake.User = PlaylistOwner,
            clear: bool = Clear):
        """Filter playlist by song name. Regex can be used for this.
        Trying to kill the bot with regex will get u botbanned tho"""
        user = user if user else ctx.author
        songs = load_playlist(playlist_name, user.id)
        if songs is False:
            await ctx.send(f"Couldn't find playlist {playlist_name} of user {user}")
            return

        songs = playlist2partialsong(songs)
        matches = await self.prepare_regex_search(ctx, songs, song_name)
        if matches is False:
            return

        if not matches:
            return await ctx.send(f'No songs found with `{song_name}`')

        def pred(song):
            return song.title in matches

        selected = select_by_predicate(songs, pred)
        if not selected:
            # We have this 2 times in case the playlist changes while we are checking
            await ctx.send(f'No songs found with `{song_name}`')
            return

        if clear:
            length = len(songs)

            try:
                s = write_playlist([song.__dict__() for song in selected], playlist_name,
                                   user.id, overwrite=True)
            except (FileExistsError, PermissionError) as e:
                await ctx.send(str(e))
                return

            s += f'\n{length - len(selected)} songs deleted that matched `{song_name}`'
            await ctx.send(s)
            return

        self.add_viewed_playlist(user, selected, playlist_name)
        await self.send_playlist(ctx, selected, None, partial=True, accurate_indices=False)

    @playlist_delete.sub_command(name='playlist', description='Deletes a whole playlist')
    @cooldown(1, 10, BucketType.user)
    async def delete_playlist(self, ctx: ApplicationCommandInteraction, playlist_name: str = PlaylistName):
        """Delete a playlist with the given name"""
        src = validate_playlist(playlist_name, ctx.author.id)
        if not src:
            ctx.application_command.reset_cooldown(ctx)
            await ctx.send(f"Couldn't find playlist with name {playlist_name}")
            return

        await ctx.send(f"You're about to delete your playlist \"{playlist_name}\". Type `confirm` for confirmation")
        if not await wait_for_words(ctx, ['confirm'], timeout=60):
            return

        try:
            os.remove(src)
        except OSError:
            logger.exception(f'Failed to remove playlist {src}')
            await ctx.send('Failed to delete playlist because of an error')
            return

        await ctx.send(f'Successfully deleted playlist {playlist_name}')

    async def _search(self, ctx: ApplicationCommandInteraction | Context, name):
        if isinstance(ctx, Context):
            await ctx.trigger_typing()

        vc = True if ctx.author.voice else False
        if name.startswith('-yt '):
            site = 'yt'
            name = name.split('-yt ', 1)[1]
        elif name.startswith('-sc '):
            site = 'sc'
            name = name.split('-sc ', 1)[1]
        else:
            site = 'yt'

        if vc:
            musicplayer = self.get_musicplayer(ctx.guild.id)
            success = False
            if not musicplayer:
                success = await self._summon(ctx, create_task=False)
                if not success:
                    terminal.debug('Failed to join vc')
                    return await ctx.send('Failed to join vc')

            musicplayer = await self.check_player(ctx)
            if not musicplayer:
                return

            await musicplayer.playlist.search(name, ctx, site)
            if success:
                musicplayer.start_playlist()
        else:
            await Playlist(self.bot, downloader=self.downloader).search(name, ctx, site, in_vc=False)

    @slash_command(name='search', description='Search for songs from YouTube or Soundcloud (using "-sc " prefix)')
    @commands.cooldown(1, 5, type=BucketType.user)
    async def search_slash(self, ctx: ApplicationCommandInteraction, *, name):
        """Search for songs. Default site is YouTube
        Supported sites: -yt YouTube, -sc Soundcloud
        To use a different site start the search with the site prefix
        e.g. {prefix}{name} -sc a cool song"""
        await ctx.response.defer()
        await self._search(ctx, name)

    @command(name='search')
    @commands.cooldown(1, 5, type=BucketType.user)
    async def search_cmd(self, ctx: Context, *, name):
        """Search for songs. Default site is YouTube
        Supported sites: -yt YouTube, -sc Soundcloud
        To use a different site start the search with the site prefix
        e.g. {prefix}{name} -sc a cool song"""
        await self._search(ctx, name)

    async def _summon(self, ctx: ApplicationCommandInteraction | Context, create_task=True, change_channel=False, channel=None):
        if not ctx.author.voice:
            await ctx.send("You aren't connected to a voice channel")
            return False

        if not channel:
            channel = ctx.author.voice.channel

        musicplayer = self.get_musicplayer(ctx.guild.id, is_on=False)
        if musicplayer is None:
            musicplayer = MusicPlayer(self.bot, self.disconnect_voice, channel=ctx.channel,
                                      downloader=self.downloader)
            self.musicplayers[ctx.guild.id] = musicplayer
        else:
            musicplayer.change_channel(ctx.channel)

        if musicplayer.voice is None:
            voice_client = ctx.guild.voice_client
            try:
                if voice_client and voice_client.channel:
                    await voice_client.disconnect(force=True)

                musicplayer.voice = await channel.connect()
            except (disnake.HTTPException, asyncio.TimeoutError) as e:
                await ctx.send(f'Failed to join vc because of an error\n{e}')
                return False
            except disnake.ClientException:
                await ctx.send(f'Bot is having some difficulties joining voice. You should probably use `/force_stop`')
                return False

            if create_task:
                musicplayer.start_playlist()
        else:
            try:
                if channel.id != musicplayer.voice.channel.id:
                    if change_channel:
                        await musicplayer.voice.move_to(channel)
                    else:
                        await ctx.send("You aren't allowed to change channels")
                elif not musicplayer.voice.is_connected():
                    await musicplayer.voice.channel.connect()
            except (disnake.HTTPException, asyncio.TimeoutError) as e:
                await ctx.send(f'Failed to join vc because of an error\n{e}')
                return False
            except disnake.ClientException:
                await ctx.send(f'Failed to join vc because of an error')
                return False

        return True

    @slash_command()
    @cooldown(1, 3, type=BucketType.guild)
    async def summon(self, ctx: ApplicationCommandInteraction):
        """Summons the bot to join your voice channel."""
        await ctx.response.defer()
        await self._summon(ctx)
        if not ctx.response.is_done():
            await ctx.send('✅')

    @slash_command()
    @cooldown(1, 3, type=BucketType.guild)
    async def move(self, ctx: ApplicationCommandInteraction, channel: disnake.VoiceChannel=None):
        """Moves the bot to your current voice channel or the specified voice channel"""
        await ctx.response.defer()
        await self._summon(ctx, change_channel=True, channel=channel)
        if not ctx.response.is_done():
            await ctx.send('✅')

    @cooldown(2, 5, BucketType.guild)
    @slash_command()
    async def repeat(self, ctx: ApplicationCommandInteraction, value: bool = OptionalBool):
        """If set on the current song will repeat until this is set off"""
        if not await self.check_voice(ctx):
            return
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        if value is None:
            musicplayer.repeat = not musicplayer.repeat

        if musicplayer.repeat:
            s = 'Repeat set on :recycle:'

        else:
            s = 'Repeat set off'

        await ctx.send(s)

    @cooldown(1, 5, BucketType.guild)
    @slash_command()
    async def speed(self, ctx: ApplicationCommandInteraction, value: float = Param(min_value=0.5, max_value=2)):
        """Change the speed of the currently playing song"""
        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)
        current.set_filter('atempo', value)
        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        musicplayer._speed_mod = value
        await self._seek(musicplayer, current, seek, options=current.options, speed=value)
        await ctx.send(f'Speed set to {value:.1f}')

    @commands.cooldown(2, 5, BucketType.guild)
    @slash_command(name='remove_silence')
    async def cutsilence(
            self, ctx: ApplicationCommandInteraction,
            is_enabled: bool = Param(None, description='Sets silence removing on or off')
    ):
        """
        Cut the silence at the end of audio
        """

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)

        if is_enabled is None:
            is_enabled = musicplayer.persistent_filters.get('silenceremove') is None

        if is_enabled:
            value = '1:0:-60dB:1:5:-50dB'
            if current:
                current.set_filter('silenceremove', value)

            musicplayer.persistent_filters['silenceremove'] = value
            s = 'Silence will be now cut at the end of the song.\n' \
                'Duration shows uncut length of the song so it might cut out before reaching the specified end'
        else:
            if current:
                current.remove_filter('silenceremove')

            musicplayer.persistent_filters.pop('silenceremove', None)
            s = 'No more cutting silence at the end of the song'

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)

        await ctx.send(s)

    @command(name='filter')
    @is_owner()
    async def custom_filter(self, ctx: Context, name: str, value: str=None):
        """Set custom filter and value. owner only"""
        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)

        if value:
            current.set_filter(name, value)
        else:
            current.remove_filter(name)

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)
        await ctx.send('✅')

    @commands.cooldown(1, 5, BucketType.guild)
    @slash_command()
    @guild_only()
    async def bass(self, ctx: ApplicationCommandInteraction, bass: int = Param(max_value=60, min_value=-60)):
        """Add or decrease the amount of bass boost. Value will persist for every song until set back to 0."""
        value = bass
        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)

        if value:
            value = 'g=%s' % value
            current.set_filter('bass', value)
            musicplayer.persistent_filters['bass'] = value
        else:
            current.remove_filter('bass')
            musicplayer.persistent_filters.pop('bass', None)

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)
        await ctx.send(f'Bass set to {bass}')

    @cooldown(1, 5, BucketType.guild)
    @slash_command(description='Set a stereo effect on the song')
    async def stereo(
            self, ctx: ApplicationCommandInteraction,
            mode: str = Param('sine', description="Type of stereo effect", choices=stereo_modes),
            speed: int = Param(500, description='Speed of the effect in ms', min_value=10, max_value=2000)
    ):
        """Works almost the same way {prefix}play does
        Default stereo type is sine.
        All available modes are `sine`, `triangle`, `square`, `sawup`, `sawdown`, `left`, `right`, `off`, `none`
        left and right work independently of the other modes so you can have both
        on at the same time. e.g. calling `{prefix}{name} left` and `{prefix}{name} sine` after that
        would make the sinewave effect only on the left channel.
        """

        if not await self.check_voice(ctx):
            return

        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            return

        current = musicplayer.current
        if current is None:
            return await ctx.send('Not playing anything right now', delete_after=20)

        mode = mode.lower()
        modes = stereo_modes
        if mode not in modes:
            ctx.application_command.reset_cooldown(ctx)
            return await ctx.send('Incorrect mode specified')

        sec = musicplayer.duration
        logger.debug('seeking with timestamp {}'.format(sec))
        seek = seek_from_timestamp(sec)
        if mode in ('left', 'right'):
            # https://trac.ffmpeg.org/wiki/AudioChannelManipulation
            # For more info on channel manipulation with ffmpeg
            mode = 'FR=FR' if mode == 'right' else 'FL=FL'
            current.set_filter('pan', f'stereo|{mode}')

        elif mode in ('off', 'none'):
            current.remove_filter('pan')
            current.remove_filter('apulsator')
        else:
            current.set_filter('apulsator', f'mode={mode}:timing=ms:ms={speed}')

        logger.debug('Filters parsed. Returned: {}'.format(current.options))
        await self._seek(musicplayer, current, seek, options=current.options)
        await ctx.send('✅')

    @slash_command(name='clear', description='Clears the playlist or removes some songs from it.')
    async def clear(self, _):
        pass

    @clear.sub_command(name='some', description='Clear the selected indexes from the playlist.')
    @cooldown(1, 4, type=BucketType.guild)
    async def clear_(
            self, ctx: ApplicationCommandInteraction,
            items: str = Param(description='Which playlist positions to remove. e.g. "4", "1-10", "1 5-9"')
    ):
        """
        Clear the selected indexes from the playlist.
        "!clear all" empties the whole playlist
        usage:
            {prefix}{name} 1-4 7-9 5
            would delete songs at positions 1 to 4, 5 and 7 to 9
        """
        if not items:
            await ctx.send('No arguments given. To clear playlist completely give `all` '
                           'as an argument. Otherwise the indexes of the songs')
            return

        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            await ctx.send('Not playing music')
            return

        await musicplayer.playlist.clear(get_indices(items), ctx)

    @clear.sub_command(name='all')
    @cooldown(1, 4, type=BucketType.guild)
    async def clear_all(self, ctx: ApplicationCommandInteraction):
        """
        Clears the whole playlist
        """
        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            await ctx.send('Not playing music')
            return

        await musicplayer.playlist.clear(None, ctx)

    @clear.sub_command(name='from')
    @cooldown(2, 5)
    async def from_(self, ctx: ApplicationCommandInteraction, user: disnake.User):
        """Clears all songs from the specified user"""
        musicplayer = await self.get_player_and_check(ctx)
        if not musicplayer:
            return

        cleared = musicplayer.playlist.clear_by_predicate(check_who_queued(user))
        await ctx.send(f'Cleared {cleared} songs from user {user}')

    @clear.sub_command(name='longer_than', description='Delete all songs from queue longer than specified duration.')
    @cooldown(2, 5)
    async def longer_than(self, ctx: ApplicationCommandInteraction,
                          duration: timedelta = Duration):
        """Delete all songs from queue longer than specified duration.
        Duration is a time string in the format of 1d 1h 1m 1s"""
        musicplayer = await self.get_player_and_check(ctx)
        if not musicplayer:
            return

        sec = duration.total_seconds()
        cleared = musicplayer.playlist.clear_by_predicate(check_duration(sec))
        await ctx.send(f'Cleared {cleared} songs longer than {duration}')

    async def prepare_regex_search(self, ctx: ApplicationCommandInteraction, songs, song_name):
        """
        Prepare regex for use in playlist filtering
        """
        matches = set()

        try:
            r = re.compile(song_name, re.IGNORECASE)
        except re.error as e:
            await ctx.send('Failed to compile regex\n' + str(e))
            return False

        # This needs to be run in executor in case someone decides to use
        # an evil regex
        def get_matches():
            for song in list(songs):
                if not song.title:
                    continue

                if r.search(song.title):
                    matches.add(song.title)

        try:
            await asyncio.wait_for(self.bot.loop.run_in_executor(self.bot.threadpool, get_matches),
                             timeout=1.5)
        except asyncio.TimeoutError:
            logger.warning(f'{ctx.author} {ctx.author.id} timeouted regex. Used regex was {song_name}')
            await ctx.send('Search timed out')
            return False

        return matches

    @clear.sub_command(name='name', description='Clear queue by song name. Regex can be used for this.')
    @cooldown(2, 4)
    async def by_name(self, ctx: ApplicationCommandInteraction, song_name: str):
        """Clear queue by song name. Regex can be used for this.
        Trying to kill the bot with regex will get u botbanned tho"""
        musicplayer = await self.get_player_and_check(ctx)
        if not musicplayer:
            return

        matches = await self.prepare_regex_search(ctx, musicplayer.playlist.playlist, song_name)
        if matches is False:
            return

        def pred(song):
            return song.title in matches

        cleared = musicplayer.playlist.clear_by_predicate(pred)
        await ctx.send(f'Cleared {cleared} songs matching {song_name}')

    @cooldown(2, 3, type=BucketType.guild)
    @slash_command(aliases=['vol'], name='volume', description='Sets the volume of the currently playing song. Displays the current volume if no value given')
    @guild_only()
    async def volume_slash(self, inter: ApplicationCommandInteraction, volume: int = VolumeType):
        await self.volume(inter, volume)

    @cooldown(2, 3, type=BucketType.guild)
    @command(aliases=['vol'], name='volume')
    @guild_only()
    async def volume_cmd(self, ctx: Context, volume: int = None):
        """
        Sets the volume of the currently playing song.
        If no parameters are given it shows the current volume instead
        Effective values are between 0 and 200
        """
        await self.volume(ctx, volume)

    async def volume(self, ctx: ApplicationCommandInteraction | Context, volume: int = None):
        value = volume
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not await self.check_voice(ctx):
            return

        # If value is smaller than zero, or it hasn't been given this shows the current volume
        if value is None or value < 0:
            await ctx.send('Volume is currently at {:.0%}'.format(musicplayer.current_volume))
            return

        musicplayer.current_volume = value / 100
        await ctx.send('Set the volume to {:.0%}'.format(musicplayer.current_volume))

    @commands.cooldown(2, 3, type=BucketType.guild)
    @slash_command(description="Sets the default volume of the player that will be used when song specific volume isn't set.")
    async def default_volume(self, ctx: ApplicationCommandInteraction, volume: int = VolumeType):
        """
        Sets the default volume of the player that will be used when song specific volume isn't set.
        If no parameters are given it shows the current default volume instead
        """
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not await self.check_voice(ctx):
            return

        # If value is smaller than zero or it hasn't been given this shows the current volume
        if volume is None:
            await ctx.send('Default volume is currently at {:.0%}'.format(musicplayer.volume))
            return

        musicplayer.volume = min(volume / 100, 2)
        await ctx.send('Set the default volume to {:.0%}'.format(musicplayer.volume))

    @commands.cooldown(1, 4, type=BucketType.guild)
    @slash_command(name='playing', aliases=['np'])
    @guild_only()
    async def playing_slash(self, inter: ApplicationCommandInteraction):
        """Gets the currently playing song"""
        await self.playing(inter)

    @commands.cooldown(1, 4, type=BucketType.guild)
    @command(name='playing', aliases=['np'])
    @guild_only()
    async def playing_cmd(self, ctx: Context):
        """Gets the currently playing song"""
        await self.playing(ctx)

    async def playing(self, ctx: ApplicationCommandInteraction | Context):
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer or musicplayer.player is None or musicplayer.current is None:
            await ctx.send('No songs currently in queue')
        else:
            duration = musicplayer.current.duration
            tr_pos = get_track_pos(duration, musicplayer.duration)
            s = musicplayer.current.long_str + f' {tr_pos}'
            s += ' 🔁\n' if musicplayer.repeat else '\n'
            if duration:
                pos = round(20 * min(1, musicplayer.duration/duration))
                slider = f'00:00 {"─"*pos}●{"─"*(20-pos-1)}  {format_time(duration)}'
            else:
                slider = f'00:00 {"─"*19}●  {format_time(musicplayer.duration)}'

            s += slider
            await ctx.send(s, allowed_mentions=AllowedMentions.none())

    @cooldown(1, 3, type=BucketType.user)
    @slash_command(name='playnow')
    async def play_now(self, ctx: ApplicationCommandInteraction, song_name: str):
        """
        Adds a song to the top of the queue.
        """
        await ctx.response.defer()
        musicplayer = self.get_musicplayer(ctx.guild.id)
        success = False
        if musicplayer is None or musicplayer.voice is None:
            success = await self._summon(ctx, create_task=False)
            if not success:
                return

        await self.play_song(ctx, song_name, priority=True)
        if success:
            musicplayer.start_playlist()

    @cooldown(1, 3, type=BucketType.guild)
    @slash_command(aliases=['p'], name='pause')
    @guild_only()
    async def pause_slash(self, inter: ApplicationCommandInteraction):
        """Pauses the currently playing song."""
        await self.pause(inter)

    @cooldown(1, 3, type=BucketType.guild)
    @command(aliases=['p'], name='pause')
    @guild_only()
    async def pause_cmd(self, ctx: Context):
        """Pauses the currently playing song."""
        await self.pause(ctx)

    async def pause(self, ctx: ApplicationCommandInteraction | Context):
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer:
            musicplayer.pause()
        else:
            if isinstance(ctx, ApplicationCommandInteraction):
                await ctx.send('❌', ephemeral=True)
            return

        if isinstance(ctx, ApplicationCommandInteraction):
            await ctx.send('✅')

    @cooldown(1, 60, type=BucketType.guild)
    @command(enabled=False, hidden=True)
    async def save_playlist(self, ctx, *name):
        if name:
            name = ' '.join(name)

        musicplayer = self.get_musicplayer(ctx.guild.id)
        await musicplayer.playlist.current_to_file(name, ctx.message.channel)

    @cooldown(1, 3, type=BucketType.guild)
    @slash_command(name='resume', aliases=['r'])
    @guild_only()
    async def resume_slash(self, inter: ApplicationCommandInteraction):
        """Resumes the currently played song."""
        await self.resume(inter)

    @cooldown(1, 3, type=BucketType.guild)
    @command(name='resume', aliases=['r'])
    @guild_only()
    async def resume_cmd(self, ctx: Context):
        """Resumes the currently played song."""
        await self.resume(ctx)

    async def resume(self, ctx: ApplicationCommandInteraction | Context):
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            if isinstance(ctx, ApplicationCommandInteraction):
                await ctx.send('❌', ephemeral=True)
            return

        await musicplayer.resume()

        if isinstance(ctx, ApplicationCommandInteraction):
            await ctx.send('✅')

    @cooldown(1, 4, type=BucketType.guild)
    @slash_command()
    async def shuffle(self, ctx: ApplicationCommandInteraction):
        """Shuffles the current playlist"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return
        await musicplayer.playlist.shuffle()
        await musicplayer.reset_gapless()
        await ctx.send('Playlist shuffled')

    async def shutdown(self):
        self.clear_cache()

    @staticmethod
    async def close_player(musicplayer: MusicPlayer):
        if musicplayer is None:
            return

        musicplayer.gapless = False

        if musicplayer.player:
            musicplayer.player.after = None

        if musicplayer.is_playing():
            musicplayer.stop()

        try:
            if musicplayer.audio_player is not None:
                musicplayer.audio_player.cancel()

            if musicplayer.voice is not None:
                await musicplayer.voice.disconnect(force=True)
                musicplayer.voice = None

            if musicplayer.guild.voice_client:
                await musicplayer.guild.voice_client.disconnect(force=True)

        except Exception:
            terminal.exception('Error while stopping voice')

    async def disconnect_voice(self, musicplayer: MusicPlayer):
        try:
            del self.musicplayers[musicplayer.channel.guild.id]
        except (KeyError, AttributeError):
            pass

        await self.close_player(musicplayer)
        if not self.musicplayers:
            await self.bot.change_presence(activity=disnake.Activity(**self.bot.config.default_activity))

    @slash_command(description="Forces voice to be stopped no matter what state the bot is in as long as it's connected to voice")
    @cooldown(1, 6, BucketType.guild)
    async def force_stop(self, ctx: ApplicationCommandInteraction):
        """
        Forces voice to be stopped no matter what state the bot is in
        as long as it's connected to voice and the internal state is in sync.
        Not meant to be used for normal disconnecting
        """
        await ctx.response.defer()
        try:
            await self.stop(ctx)
        except Exception as e:
            terminal.exception('Failed to force stop')

        # Just to be sure, delete every single musicplayer related to this server
        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        while musicplayer is not None:
            try:
                self.musicplayers.pop(ctx.guild.id)
            except KeyError:
                pass

            MusicPlayer.__instances__.discard(musicplayer)
            musicplayer.selfdestruct()
            del musicplayer

            musicplayer = self.get_musicplayer(ctx.guild.id, False)

        del musicplayer

        import gc
        gc.collect()

        if ctx.guild.voice_client:
            await ctx.guild.voice_client.disconnect(force=True)
            await ctx.send('Forced disconnect')
        else:
            await ctx.send('Disconnected')

    @commands.cooldown(1, 6, BucketType.user)
    @slash_command(name='stop')
    async def stop_slash(self, inter: ApplicationCommandInteraction):
        """Stops playing audio and leaves the voice channel."""
        await self.stop(inter)

    @commands.cooldown(1, 6, BucketType.user)
    @command(name='stop')
    async def stop_cmd(self, ctx: Context):
        """Stops playing audio and leaves the voice channel."""
        await self.stop(ctx)

    async def stop(self, ctx: ApplicationCommandInteraction | Context):
        if isinstance(ctx, ApplicationCommandInteraction):
            await ctx.response.defer()

        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.disconnect(force=True)
                return

        await self.disconnect_voice(musicplayer)

        # Legacy code
        if not self.musicplayers:
            self.clear_cache()

        await ctx.send('✅')

    @slash_command()
    async def votestop(self, ctx: ApplicationCommandInteraction):
        """Stops the bot if enough people vote for it. Votes expire in 60s"""
        musicplayer = self.get_musicplayer(ctx.guild.id, False)
        if not musicplayer:
            if ctx.guild.voice_client:
                await ctx.guild.voice_client.disconnect(force=False)
                return

        resp = await musicplayer.votestop(ctx.author)

        if resp is True:
            await ctx.send('Votes reached disconnecting')
            await self.disconnect_voice(musicplayer)
        else:
            await ctx.send(f'{resp} votes until disconnect')

    @cooldown(1, 5, type=BucketType.user)
    @slash_command(name='skip')
    @guild_only()
    async def skip_slash(self, inter: ApplicationCommandInteraction):
        """Skips the current song"""
        await self.skip(inter)

    @cooldown(1, 5, type=BucketType.user)
    @command(aliases=['skipsen', 'skipperino', 's'], name='skip')
    @guild_only()
    async def skip_cmd(self, ctx: Context):
        """Skips the current song"""
        await self.skip(ctx)

    async def skip(self, ctx: ApplicationCommandInteraction | Context):
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            if isinstance(ctx, ApplicationCommandInteraction):
                await ctx.send('❌', ephemeral=True)
            return

        if not await self.check_voice(ctx):
            return

        if not musicplayer.is_playing():
            await ctx.send('Not playing any music right now...')
            return

        await musicplayer.skip(ctx.author, ctx.channel)

    @cooldown(1, 5, type=BucketType.user)
    @slash_command(name='force_skip', description='Force skips this song no matter who queued it without requiring any votes')
    @guild_only()
    async def force_skip_slash(self, inter: ApplicationCommandInteraction):
        await self.force_skip(inter)

    @cooldown(1, 5, type=BucketType.user)
    @command(aliases=['force_skipsen', 'force_skipperino', 'fs'], name='force_skip')
    @guild_only()
    async def force_skip_cmd(self, ctx: Context):
        """
        Force skips this song no matter who queued it without requiring any votes
        For public servers it's recommended you blacklist this from your server
        and only give some people access to it
        """
        await self.force_skip(ctx)

    async def force_skip(self, ctx: ApplicationCommandInteraction | Context):
        if not await self.check_voice(ctx):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            return

        if not musicplayer.is_playing():
            await ctx.send('Not playing any music right now...')
            return

        await musicplayer.skip(None, ctx)
        if isinstance(ctx, ApplicationCommandInteraction) and not ctx.response.is_done():
            await ctx.send('✅')

    async def send_playlist(self, ctx: Union[ApplicationCommandInteraction, Context],
                            playlist, musicplayer, page_index=0, accurate_indices=True,
                            partial=False):
        """
        Sends a paged message containing all playlist songs.
        When accurate_indices is set to True we will check the index of each
        song manually by checking its position in the guilds playlist.
        When false will use values based on page index.

        If partial is set to true we will assume PartialSong is being used
        """
        if partial and accurate_indices:
            raise ValueError('Cant have partial and accurate indices set to True at the same time')

        if not playlist:
            return await ctx.send('Empty playlist')

        pages = []
        for i in range(0, len(playlist), 10):
            pages.append(playlist[i:i + 10])

        if not pages:
            pages.append([])

        embeds = list(pages)

        if not partial:
            time_left = self.list_length(musicplayer)
        else:
            time_left = self.playlist_length(playlist)

        duration = format_timedelta(time_left, accuracy=DateAccuracy.Hour-DateAccuracy.Second, long_format=False)

        def add_song(song: Union[Song, PartialSong], idx, dur):
            title = song.title.replace('*', '\\*')
            if partial:
                return f'\n{idx}. **{title}** (Duration: {format_timedelta(dur, 3, long_format=False)}) <{song.webpage_url}>'
            else:
                requested_by = f'{song.requested_by.mention} ' if song.requested_by else ''
                return f'\n{idx}. **{title}** {requested_by}(ETA: {format_timedelta(dur, 3, long_format=False)})'

        def generate_page(idx):
            page = pages[idx]
            response = ''
            if not partial:
                full_playlist = list(musicplayer.playlist.playlist)  # good variable naming
                if not full_playlist and musicplayer.current is None:
                    return 'Nothing playing atm'

                if musicplayer.current is not None:
                    dur = get_track_pos(musicplayer.current.duration, musicplayer.duration)
                    response = f'Currently playing **{musicplayer.current.title}** {dur}'
                    if musicplayer.current.requested_by:
                        response += f' enqueued by {musicplayer.current.requested_by.mention}\n'

            if accurate_indices:
                # This block is never reached if partial is true, so we don't have
                # to worry about variables being undefined
                songs = []
                indices = []
                redo_pages = False
                for song in page:
                    try:
                        idx = full_playlist.index(song)  # skipcq: PYL-W0621
                    except ValueError:
                        redo_pages = True
                        playlist.remove(song)
                        continue

                    songs.append(song)
                    indices.append(idx)

                if not songs:
                    return 'Nothing playing atm'

                if redo_pages:
                    # If these songs have been cleared or otherwise passed by we remove them
                    # and recreate the list
                    pages.clear()
                    for i in range(0, len(playlist), 10):
                        pages[i] = playlist[i:i + 10]

                durations = self.song_durations(musicplayer, until=max(indices) + 1)

                for song, idx in zip(songs, indices):
                    dur = int(durations[idx])
                    response += add_song(song, idx + 1, dur)

            elif partial:
                for _idx, song in enumerate(page):
                    response += add_song(song, _idx + 1 + 10 * idx, song.duration)
            else:
                durations = self.song_durations(musicplayer, until=idx * 10 + 10)
                durations = durations[-10:]

                for _idx, song_dur in enumerate(zip(page, durations)):
                    song, dur = song_dur
                    dur = int(dur)
                    response += add_song(song, _idx + 1 + 10 * idx, dur)

            title = f'Total length {duration}  |  {len(playlist)} songs in queue'

            embeds[idx] = disnake.Embed(
                title=title,
                description=response
            )

        paginator = Paginator(embeds, generate_page=generate_page, initial_page=page_index)

        await paginator.send(ctx)

    @slash_command(name='queue', description='View current song queue with or without filters')
    async def queue(self, _):
        pass

    @cooldown(1, 5, type=BucketType.guild)
    @queue.sub_command(name='view')
    async def playlist_view(self, ctx: ApplicationCommandInteraction, page_index: int=0):
        """Get a list of the current queue. To skip to a certain page set the page_index argument"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        playlist = list(musicplayer.playlist.playlist)  # good variable naming
        if not playlist and musicplayer.current is None:
            return await ctx.send('Nothing playing atm')

        await self.send_playlist(ctx, playlist, musicplayer, page_index, accurate_indices=False)

    @queue.sub_command(name='from')
    @cooldown(1, 5)
    async def queue_by_user(self, ctx: ApplicationCommandInteraction, user: disnake.User, page_index: int=0):
        """Filters playlist to the songs queued by user"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        selected = musicplayer.playlist.select_by_predicate(check_who_queued(user))
        if not selected:
            await ctx.send(f'No songs enqueued by {user}')
            return

        await self.send_playlist(ctx, selected, musicplayer, page_index)

    @queue.sub_command(name='length', description='Filters playlist by song duration.')
    @cooldown(1, 5)
    async def queue_by_time(self, ctx: ApplicationCommandInteraction, duration: timedelta = Duration, longer_than: bool=True):
        """Filters playlist by song duration.
        Usage:
        `{prefix}{name} no 10m` will select all songs under 10min and
        `{prefix}{name} 10m` will select songs over 10min"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        selected = musicplayer.playlist.select_by_predicate(check_duration(duration.total_seconds(), longer_than))
        if not selected:
            await ctx.send(f'No songs {"longer" if longer_than else "shorter"} than {duration}')
            return

        await self.send_playlist(ctx, selected, musicplayer)

    @queue.sub_command(name='name', description='Filter playlist by song name. Regex can be used for this.')
    @cooldown(1, 5)
    async def queue_by_name(self, ctx: ApplicationCommandInteraction, song_name):
        """Filter playlist by song name. Regex can be used for this.
        Trying to kill the bot with regex will get u botbanned tho"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        matches = await self.prepare_regex_search(ctx, musicplayer.playlist.playlist, song_name)
        if matches is False:
            return

        if not matches:
            return await ctx.send(f'No songs found with `{song_name}`')

        def pred(song):
            return song.title in matches

        selected = musicplayer.playlist.select_by_predicate(pred)
        if not selected:
            # We have this 2 times in case the playlist changes while we are checking
            await ctx.send(f'No songs found with `{song_name}`')
            return

        await self.send_playlist(ctx, selected, musicplayer)

    @cooldown(1, 3, type=BucketType.guild)
    @slash_command()
    async def length(self, ctx: ApplicationCommandInteraction):
        """Gets the length of the current queue"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        if musicplayer.current is None or not musicplayer.playlist.playlist:
            return await ctx.send('No songs in queue')

        time_left = self.list_length(musicplayer)
        minutes, seconds = divmod(floor(time_left), 60)
        hours, minutes = divmod(minutes, 60)

        return await ctx.send('The length of the playlist is about {0}h {1}m {2}s'.format(hours, minutes, seconds))

    @command(auth=Auth.BOT_MOD)
    @guild_only()
    async def ds(self, ctx: Context):
        """Delete song from autoplaylist and skip it"""
        await ctx.invoke(self.delete_from_ap)
        await ctx.invoke(self.skip)

    @staticmethod
    def list_length(musicplayer: MusicPlayer, index=None):
        playlist = musicplayer.playlist
        if not playlist:
            return
        time_left = musicplayer.current.duration - musicplayer.duration
        time_left += Audio.playlist_length(playlist, index)

        return time_left

    @staticmethod
    def playlist_length(playlist, index: int=None) -> int:
        t = 0
        for song in list(playlist)[:index]:
            t += song.duration

        return t

    @staticmethod
    def song_durations(musicplayer, until=None):
        playlist = musicplayer.playlist
        if not playlist:
            return None

        durations = []
        if musicplayer.current:
            time_left = musicplayer.current.duration - musicplayer.duration
        else:
            time_left = 0

        for song in list(playlist)[:until]:
            durations.append(time_left)
            time_left += song.duration

        return durations

    @slash_command()
    @cooldown(2, 6)
    async def autoplay(self, ctx: ApplicationCommandInteraction, value: bool = OptionalBool):
        """Determines if YouTube autoplay should be emulated. If no value is passed current value is output"""
        musicplayer = await self.check_player(ctx)

        if not musicplayer:
            return await ctx.send('Not playing any music right now')

        if not await self.check_voice(ctx):
            return

        if value is None:
            return await ctx.send(f'Autoplay currently {"on" if musicplayer.autoplay else "off"}')

        musicplayer.autoplay = value
        s = f'Autoplay set {"on" if value else "off"}'
        await ctx.send(s)

    @slash_command(name='volume_multiplier')
    @cooldown(1, 4, type=BucketType.guild)
    async def vol_multiplier(self, ctx: ApplicationCommandInteraction, value: float=None):
        """The multiplier that is used when dynamically calculating the volume"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not value:
            return await ctx.send('Current volume multiplier is %s' % str(musicplayer.volume_multiplier))
        try:
            value = float(value)
            musicplayer.volume_multiplier = value
            await ctx.send(f'Volume multiplier set to {value}')
        except ValueError:
            await ctx.send('Value is not a number', delete_after=60)

    @slash_command()
    @cooldown(2, 4, type=BucketType.guild)
    async def auto_volm(self, ctx: ApplicationCommandInteraction):
        """Automagically set the volume multiplier value based on current volume"""
        musicplayer = await self.check_player(ctx)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        if not await self.check_voice(ctx):
            return

        current = musicplayer.current
        if not current:
            return await ctx.send('Not playing anything right now')

        old = musicplayer.volume_multiplier
        if not current.rms:
            for h in musicplayer.history:
                if not h.rms:
                    continue

                new = round(h.rms * h.volume, 1)
                await ctx.send("Current song hadn't been processed yet so used song history to determine volm\n"
                               f"{old} -> {new}")
                musicplayer.volume_multiplier = new
                return

            await ctx.send('Failed to set volm. No mean volume calculated for songs.')
            return

        new = round(current.rms * musicplayer.current_volume, 1)
        musicplayer.volume_multiplier = new
        await ctx.send(f'volm changed automagically {old} -> {new}')

    @slash_command()
    @cooldown(1, 10, type=BucketType.guild)
    async def link(self, ctx: ApplicationCommandInteraction):
        """Link to the current song"""
        if not await self.check_voice(ctx, user_connected=False):
            return

        musicplayer = self.get_musicplayer(ctx.guild.id)
        if musicplayer is None:
            await ctx.send('❌', ephemeral=True)
            return

        current = musicplayer.current
        if not current:
            return await ctx.send('Not playing anything')
        await ctx.send('Link to **{0.title}** {0.webpage_url}'.format(current), allowed_mentions=AllowedMentions.none())

    @command(name='delete', aliases=['del', 'd'], auth=Auth.BOT_MOD)
    @guild_only()
    async def delete_from_ap(self, ctx, *name):
        """Puts a song to the queue to be deleted from autoplaylist"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not name:
            if not musicplayer or not musicplayer.current:
                await ctx.send('Nothing playing and no link given')
                return

            name = [musicplayer.current.webpage_url]

            if name is None:
                terminal.debug('No name specified in delete_from')
                await ctx.send('No song to delete', delete_after=60)
                return

        with open(DELETE_AUTOPLAYLIST, 'a', encoding='utf-8') as f:
            f.write(' '.join(name) + '\n')

        terminal.info(f'Added entry {name} to the deletion list')
        await ctx.send(f'Added entry {" ".join(name)} to the deletion list', delete_after=60)

    @command(name='add', auth=Auth.BOT_MOD)
    @guild_only()
    async def add_to_ap(self, ctx, *name):
        """Puts a song to the queue to be added to autoplaylist"""
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if name:
            name = ' '.join(name)
        if not name:
            if not musicplayer:
                return

            current = musicplayer.current
            if current is None or current.webpage_url is None:
                terminal.debug('No name specified in add_to')
                await ctx.send('No song to add', delete_after=30)
                return

            data = current.webpage_url
            name = data

        elif 'playlist' in name or 'channel' in name:
            async def on_error(e):
                await ctx.send('Failed to get playlist %s' % e)

            info = await self.downloader.extract_info(self.bot.loop, url=name, download=False,
                                                      on_error=on_error)
            if info is None:
                return

            links = await Playlist.process_playlist(info, channel=ctx.message.channel)
            if links is None:
                await ctx.send('Incompatible playlist')

            data = '\n'.join(links)

        else:
            data = name

        with open(ADD_AUTOPLAYLIST, 'a', encoding='utf-8') as f:
            f.write(data + '\n')

        terminal.info(f'Added entry {name} to autoplaylist')
        await ctx.send(f'Added entry {name}', delete_after=60)

    @slash_command()
    @cooldown(1, 5, type=BucketType.guild)
    async def autoplaylist(self, ctx: ApplicationCommandInteraction, value: bool = True):
        """Set the autoplaylist on or off"""
        if not await self.check_voice(ctx, user_connected=False):
            return
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        if value:
            musicplayer.autoplaylist = True
        else:
            musicplayer.autoplaylist = False

        await ctx.send(f'Autoplaylist set {"on" if value else "off"}')

    @slash_command()
    @cooldown(1, 5, type=BucketType.guild)
    async def gapless(self, ctx: ApplicationCommandInteraction, value: bool = OptionalBool):
        """EXPERIMENTAL: Set the gapless playback on or off. Might break other features"""
        if not await self.check_voice(ctx, user_connected=False):
            return
        musicplayer = self.get_musicplayer(ctx.guild.id)
        if not musicplayer:
            await ctx.send('❌', ephemeral=True)
            return

        if value is None:
            musicplayer.gapless = not musicplayer.gapless
        elif value:
            musicplayer.gapless = True
        else:
            musicplayer.gapless = False

        await ctx.send(f'Gapless playback set {"on" if musicplayer.gapless else "off"}')

    def clear_cache(self):
        songs = []
        for musicplayer in self.musicplayers.values():
            for song in musicplayer.playlist.playlist:
                songs += [song.id]
        cachedir = os.path.join(os.getcwd(), 'data', 'audio', 'cache')
        try:
            files = os.listdir(cachedir)
        except (OSError, FileNotFoundError):
            return

        def check_list(string):
            if song.id is not None and song.id in string:
                return True
            return False

        dont_delete = []
        for song in songs:
            file = list(filter(check_list, files))
            if file:
                dont_delete += file

        for file in files:
            if file not in dont_delete:
                try:
                    os.remove(os.path.join(cachedir, file))
                except os.error:
                    pass


def setup(bot):
    bot.add_cog(Audio(bot))

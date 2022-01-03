UPDATE command_blacklist SET command='again_play_now' WHERE command='queue_now_playing';

UPDATE command_blacklist
SET command='playlist'
WHERE command IN
      (
       'play_playlist',
       'play_random_playlist',
       'play_viewed_playlist',
       'add_to_playlist',
       'delete_from_playlist',
       'create_playlist',
       'copy_playlist',
       'list_playlists',
       'clear_playlist_duplicates',
       'view_playlist',
       'delete_playlist'
    );

UPDATE command_blacklist SET command='remove_silence' WHERE command='cutsilence';

###Data
This bot needs to collect data that the discord api provides
in order to function properly. This data consist mainly of your user id combined with other ids such as 
server and role ids. Non moderation uses include the first date a user joined a server,
stats with the mute_roll command, commands you have used, 
the date you last interacted in a server (e.g. by sending a message)
and image urls for image manipulation commands (only the url and channel are stored here).
Moderation uses include timeouts, reasons for the timeouts and mutes,
temproles, command permissions, saving roles and botbans. 
Message ids are also saved in a handful of server for message purging reasons.

The bot also saves the latest image links sent in a channel for up to 1 day.
This is to make the image commands more convenient to use.

Message content is saved in memory for a short amount of time. 
This is used for message delete and edit tracking for servers that have it enabled.

###Agreement
By having this bot in your guild you agree to inform users that
this bot collects data that the discord api provides in order to function.
The creator of this bot is not responsible for any damage this bot causes
including but not limited to failure of a service this bot provides

You can get the support server invite with a command name `support` or use the command `delete_data` if you want 
your data removed (not including moderation data) and command `do_not_track` will prevent the bot from saving data of you (does not include data used for moderation).

from cogs.cog import Cog
import re
import logging

logger = logging.getLogger('debug')

class NNLogger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._prefixes = {'.', '!', 't!', '?', '!!'}
        self._prefixes.add(self.bot.command_prefix)
        self.emote_regex = re.compile(r'<:(\w+):\d+>')

    @staticmethod
    def alnum(s):
        return ''.join(filter(str.isalnum, s))

    async def on_message(self, msg):
        # Only one channel for now
        if msg.channel.id != '297061271205838848':
            return

        # Don't wanna log bot messages
        if msg.author.bot:
            return

        # No need to log bot commands
        if list(filter(lambda prefix: content.startswith(prefix), self._prefixes)):
            return

        # Gets the content like you see in the client
        content = msg.clean_content

        if not content:
            return

        # Remove zalgo text
        content = self.alnum(content)

        # Emotes as just names
        content = self.emote_regex.sub(r'\1', content)

        # Don't want too short text messing things up
        if len(content) < 5:
            return

        session = self.bot.get_session
        sql = 'INSERT INTO `nn_text` (`message`) VALUES (:message)'
        try:
            session.execute(sql, params={'message': content})
            session.commit()
        except:
            logger.exception('Failed to log message to nn table')

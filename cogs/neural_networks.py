from cogs.cog import Cog
import re
import logging
from utils import unzalgo

logger = logging.getLogger('debug')


class NNLogger(Cog):
    def __init__(self, bot):
        super().__init__(bot)
        self._prefixes = {'.', '!', 't!', '?', '!!', '+'}
        self.emote_regex = re.compile(r'<:(\w+):\d+>')

    @staticmethod
    def alnum(s):
        return ' '.join([''.join(filter(str.isalnum, ss)) for ss in s.split(' ')])

    async def on_message(self, msg):
        if self.bot.test_mode:
            return

        # Only one channel for now
        if msg.channel.id != '297061271205838848':
            return

        # Don't wanna log bot messages
        if msg.author.bot:
            return

        # Gets the content like you see in the client
        content = msg.clean_content

        # No need to log bot commands
        if list(filter(lambda prefix: content.startswith(prefix), self._prefixes)):
            return
        prefixes = self.bot.get_command_prefix(self.bot, msg)
        if isinstance(prefixes, str):
            prefixes = (prefixes, )
        if list(filter(lambda prefix: content.startswith(prefix), prefixes)):
            return

        if not content:
            return

        # Remove zalgo text
        content = unzalgo.unzalgo(content)

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
            session.rollback()
            logger.exception('Failed to log message to nn table')


def setup(bot):
    bot.add_cog(NNLogger(bot))

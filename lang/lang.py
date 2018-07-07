import builtins
import inspect
import logging

terminal = logging.getLogger('terminal')


def _get_variable(name):
    stack = inspect.stack()
    for frame in stack:
        pass


class Translations:
    def __init__(self):
        self._translations = {}


    def install(self):
        builtins.__dict__['_'] = self.gettext

    def gettext(self, message, domain=None):
        domain = domain.lower() if domain else None
        if domain is None or domain == 'en':  # No need to change the messages in default lang
            return message

        translation = self._translations.get(domain, None)
        if translation is None:
            terminal.debug(f'Domain {domain} not found')
            return message

        return translation.gettext(message)

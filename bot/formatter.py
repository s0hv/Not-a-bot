import inspect
import itertools
from bot.bot import Command
from discord.ext.commands.formatter import HelpFormatter
from discord import Embed


class Formatter(HelpFormatter):
    Generic = 0
    Cog = 1
    Command = 2

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format_help_for(self, context, command_or_bot, is_owner=False, type=Generic):
        self.context = context
        self.command = command_or_bot
        self.type = type
        return self.format(is_owner=is_owner)

    def format(self, is_owner=False, generic=False):
        """Handles the actual behaviour involved with formatting.

        To change the behaviour, this method should be overridden.

        Returns
        --------
        list
            A paginated output of the help command.
        """
        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)

        self._paginator = Paginator(title='Help')

        if isinstance(self.command, Command):
            # <signature portion>
            signature = self.get_command_signature()
            if self.command.owner_only:
                signature = 'This command is owner only\n' + signature

            signature = description + '\n' + signature

            # <long doc> section
            if self.command.help:
                self._paginator.add_page(self.command.name, self.command.help)

            self._paginator.add_page('signature', signature)

            # end it here if it's just a regular command
            if not self.has_subcommands():
                return self._paginator.pages

        max_width = self.max_name_size

        def category(tup):
            cog = tup[1].cog_name
            # we insert the zero width space there to give it approximate
            # last place sorting position.
            return cog + ':' if cog is not None else '\u200bNo Category:'

        if self.is_bot():
            data = sorted(self.filter_command_list(), key=category)
            for category, commands in itertools.groupby(data, key=category):
                # there simply is no prettier way of doing this.
                commands = list(commands)
                if len(commands) > 0:
                    self._paginator.add_line('#' + category)

                self._add_subcommands_to_page(max_width, commands, is_owner=is_owner)
        else:
            self._paginator.add_line('Commands:')
            self._add_subcommands_to_page(max_width, self.filter_command_list(), is_owner=is_owner)

        # add the ending note
        self._paginator.add_line()
        ending_note = self.get_ending_note()
        self._paginator.add_line(ending_note)
        return self._paginator.pages

    def _add_subcommands_to_page(self, max_width, commands, is_owner=False):
        for name, command in commands:
            if name in command.aliases:
                # skip aliases
                continue

            if command.owner_only and not is_owner:
                continue

            entry = '  {0:<{width}} {1}'.format(name, command.short_doc, width=max_width)
            shortened = self.shorten(entry)
            self._paginator.add_line(shortened)


class Limits:
    Field = 1024
    Name = 256
    Title = 256
    Description = 2048
    Fields = 25
    Total = 6000


class Paginator:
    def __init__(self, title=None, description=None):
        self._fields = 0
        self._pages = []
        self.title = title
        self.description = description
        self._current_page = -1
        self._char_count = 0
        self._current_field = None

    @property
    def pages(self):
        return self._pages

    def add_page(self, title=None, description=None):
        title = title or self.title
        description = description or self.description
        self._pages.append(Embed(title=title, description=description))
        self._current_page += 1
        self._fields = 0
        self._char_count = 0
        self._char_count += len(title) if title else 0
        self._char_count += len(description) if description else 0
        self.title = title
        self.description = description

    def _add_field(self, name, value):
        self.pages[self._current_page].add_field(**self._current_field)
        self._fields += 1
        self._current_field = None
        self._char_count += len(name) + len(value)

    def add_field(self, name, value):
        if self._current_field is not None and self._fields < 25:
            self._add_field(**self._current_field)

        name = name[:Limits.Title]
        value = value[:Limits.Field]
        l = len(name) + len(value)

        if self._fields == 25:
            self._pages.append(Embed(title=self.title))
            self._current_page += 1
            self._fields = 0
            self._char_count = len(self.title)
            if self._current_field is not None:
                self._add_field(**self._current_field)

        elif l + self._char_count > Limits.Total:
            self._pages.append(Embed(title=self.title))
            self._current_page += 1
            self._fields = 0
            self._char_count = len(self.title) + l

        self._current_field = {'name': name, 'value': value}

    def add_to_field(self, value):
        v = self._current_field['value']
        if len(v) + len(value) > Limits.Field:
            self.add_field(self._current_field['name'], value)
        else:
            self._current_field['value'] += value

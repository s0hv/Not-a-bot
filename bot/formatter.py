import inspect
import itertools
from discord.ext.commands import Command
from discord.ext.commands.formatter import HelpFormatter
from discord import Embed
from discord.ext.commands.errors import CommandError
from utils.utilities import check_perms, is_superset
from sqlalchemy.exc import SQLAlchemyError
import logging
import colors

logger = logging.getLogger('debug')


class Formatter(HelpFormatter):
    Generic = 0
    Cog = 1
    Command = 2
    Filtered = 3  # Show only the commands that the caller can use based on required discord permissions
    ExtendedFilter = 4  # Include database black/whitelist to filter

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def format_help_for(self, context, command_or_bot, is_owner=False, type=Generic):
        self.context = context
        self.command = command_or_bot
        self.type = type
        if self.type not in (self.ExtendedFilter, self.Filtered):
            self.show_check_failure = True  # Don't check command checks if no filters are on
        else:
            self.show_check_failure = False

        return self.format(is_owner=is_owner)

    def format(self, is_owner=False):
        """Handles the actual behaviour involved with formatting.

        To change the behaviour, this method should be overridden.

        Returns
        --------
        list
            A paginated output of the help command.
        """
        description = self.command.description if not self.is_cog() else inspect.getdoc(self.command)

        self._paginator = Paginator(title='Help')

        ctx = self.context
        user = ctx.message.author
        channel = ctx.message.channel
        if user.roles:
            roles = '(role IS NULL OR role IN ({}))'.format(', '.join(map(lambda r: r.id, user.roles)))
        else:
            roles = 'role IS NULL'

        if isinstance(self.command, Command):
            # <signature portion>
            signature = self.get_command_signature()
            if getattr(self.command, 'owner_only', False):
                signature = 'This command is owner only\n' + signature
            elif self.type == self.Filtered or self.type == self.ExtendedFilter:
                try:
                    can_run = self.command.can_run(ctx) and ctx.bot.can_run(ctx)
                except CommandError:
                    can_run = False

                if self.type == self.ExtendedFilter:
                    sql = 'SELECT `type`, `role`, `user`, `channel`  FROM `command_blacklist` WHERE server=:server AND (command=:command OR command IS NULL) ' \
                          'AND (user IS NULL OR user=:user) AND {} AND (channel IS NULL OR channel=:channel)'.format(roles)
                    session = ctx.bot.get_session
                    try:
                        rows = session.execute(sql, params={'server': int(user.server.id), 'command': self.command.name, 'user': user.id, 'channel': channel.id}).fetchall()
                        if rows:
                            can_run = check_perms(rows)
                    except SQLAlchemyError:
                        session.rollback()
                        logger.exception('Failed to use extended filter in help')
                        can_run = True

                if not can_run:
                    signature = "You don't have the required perms to use this command or it's blacklisted for you\n" + signature

            signature = description + '\n' + signature

            # <long doc> section
            if self.command.help:
                self._paginator.edit_page(self.command.name, self.command.help.format(prefix=self.context.prefix, name=self.context.invoked_with))

            self._paginator.add_field('Usage', signature)

            # end it here if it's just a regular command
            if not self.has_subcommands():
                self._paginator.finalize()
                return self._paginator.pages

        def category(tup):
            cog = tup[1].cog_name
            return cog if cog is not None else 'No Category'

        if self.is_bot():
            if self.type == self.ExtendedFilter:
                sql = 'SELECT `type`, `role`, `user`, `channel`, `command` FROM `command_blacklist` WHERE server=:server ' \
                      'AND (user IS NULL OR user=:user) AND {} AND (channel IS NULL OR channel=:channel)'.format(roles)
                session = ctx.bot.get_session
                command_blacklist = {}
                try:
                    rows = session.execute(sql,
                                           params={'server': int(user.server.id),
                                                   'user': user.id,
                                                   'channel': channel.id}).fetchall()
                    command_blacklist = {}
                    for row in rows:
                        name = row['command']
                        if name in command_blacklist:
                            command_blacklist[name].append(row)
                        else:
                            command_blacklist[name] = [row]

                except SQLAlchemyError:
                    session.rollback()
                    logger.exception('Failed to get role blacklist for help command')

            data = sorted(self.filter_command_list(), key=category)

            if self.type == self.ExtendedFilter:
                def check(command):
                    rows = command_blacklist.get(command.name, None)
                    if not rows:
                        return True
                    return check_perms(rows)
            else:
                check = None

            for category_, commands in itertools.groupby(data, key=category):
                # there simply is no prettier way of doing this.
                commands = list(commands)

                def inline(entries):
                    if len(entries) > 5:
                        return False
                    else:
                        return True

                self._add_subcommands_and_page(category_, commands, is_owner=is_owner, inline=inline, predicate=check)
        else:
            self._add_subcommands_and_page('Commands:', self.filter_command_list(), is_owner=is_owner)

        # add the ending note
        ending_note = self.get_ending_note()
        self._paginator.add_field('Note', ending_note)
        self._paginator.finalize()
        return self._paginator.pages

    def _add_subcommands_and_page(self, page, commands, is_owner=False, inline=None, predicate=None):
        # Like _add_subcommands_to_page but doesn't leave empty fields in the embed
        # Can be extended to include other filters too

        entries = []
        for name, command in commands:
            if name in command.aliases:
                # skip aliases
                continue

            if command.owner_only and not is_owner:
                continue

            if self.type == self.ExtendedFilter and predicate and not predicate(command):
                continue

            entry = '`{0}` '.format(name)
            entries.append(entry)

        if not entries:
            return

        if callable(inline):
            inline = inline(entries)

        self._paginator.add_field(page, inline=inline)
        for entry in entries:
            self._paginator.add_to_field(entry)

    def _add_subcommands_to_page(self, commands, is_owner=False):
        for name, command in commands:
            if name in command.aliases:
                # skip aliases
                continue

            if command.owner_only and not is_owner:
                continue

            entry = '`{0}` '.format(name)
            self._paginator.add_to_field(entry)


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
        self.add_page(title, description)

    @property
    def pages(self):
        return self._pages

    def finalize(self):
        self._add_field()

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

    def edit_page(self, title=None, description=None):
        page = self.pages[self._current_page]
        if title:
            self._char_count -= len(str(title))
            page.title = str(title)
            self.title = title
            self._char_count += len(title)
        if description:
            self._char_count -= len(str(description))
            page.description = str(description)
            self.description = description
            self._char_count += len(description)

    def _add_field(self):
        if not self._current_field:
            return

        if not self._current_field['value']:
            self._current_field['value'] = 'Emptiness'

        self.pages[self._current_page].add_field(**self._current_field)
        self._fields += 1
        self._char_count += len(self._current_field['name']) + len(self._current_field['value'])
        self._current_field = None

    def add_field(self, name, value='', inline=False):
        if self._current_field is not None and self._fields < 25:
            self._add_field()

        name = name[:Limits.Title]
        value = value[:Limits.Field]
        length = len(name) + len(value)

        if self._fields == 25:
            self._pages.append(Embed(title=self.title))
            self._current_page += 1
            self._fields = 0
            self._char_count = len(self.title)
            if self._current_field is not None:
                self._add_field()

        elif length + self._char_count > Limits.Total:
            self._pages.append(Embed(title=self.title))
            self._current_page += 1
            self._fields = 0
            self._char_count = len(self.title)

        self._current_field = {'name': name, 'value': value, 'inline': inline}

    def add_to_field(self, value):
        v = self._current_field['value']
        if len(v) + len(value) > Limits.Field:
            self.add_field(self._current_field['name'], value)
        else:
            self._current_field['value'] += value


def get_color(fg=None, bg=None, style=None):
    """
    Get the ANSI color based on params

    :param str|int|tuple fg: Foreground color specification.
    :param str|int|tuple bg: Background color specification.
    :param str style: Style names, separated by '+'
    :returns: ANSI color code
    :rtype: str
    """
    codes = []

    if fg:
        codes.append(colors.colors._color_code(fg, 30))
    if bg:
        codes.append(colors.colors._color_code(bg, 40))
    if style:
        for style_part in style.split('+'):
            if style_part in colors.STYLES:
                codes.append(colors.STYLES.index(style_part))
            else:
                raise ValueError('Invalid style "%s"' % style_part)

    if codes:
        template = '\x1b[{0}m'
        return template.format(colors.colors._join(*codes))
    else:
        return ''


class LoggingFormatter(logging.Formatter):
    def __init__(self, fmt=None, datefmt=None, style='%', override_colors: dict=None):
        super().__init__(fmt, datefmt, style)

        self.colors = {logging.NOTSET: {'fg': 'default'},
                       logging.DEBUG: {'fg': 'CYAN'},
                       logging.INFO: {'fg': 'GREEN'},
                       logging.WARNING: {'fg': 'YELLOW'},
                       logging.ERROR: {'fg': 'red'},
                       logging.CRITICAL: {'fg': 'RED', 'style': 'negative'},
                       'EXCEPTION': {'fg': 'RED'}}  # Style for exception traceback

        if override_colors:
            self.colors.update(override_colors)

    def format(self, record):
        """
        Format the specified record as text.

        The record's attribute dictionary is used as the operand to a
        string formatting operation which yields the returned string.
        Before formatting the dictionary, a couple of preparatory steps
        are carried out. The message attribute of the record is computed
        using LogRecord.getMessage(). If the formatting string uses the
        time (as determined by a call to usesTime(), formatTime() is
        called to format the event time. If there is exception information,
        it is formatted using formatException() and appended to the message.
        """
        record.message = record.getMessage()
        if self.usesTime():
            record.asctime = self.formatTime(record, self.datefmt)
        color = get_color(**self.colors.get(record.levelno, {}))
        if color:
            record.color = color
            record.colorend = '\x1b[0m'

        s = self.formatMessage(record)
        if record.exc_info:
            # Cache the traceback text to avoid converting it multiple times
            # (it's constant anyway)
            if not record.exc_text:
                record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            if s[-1:] != "\n":
                s = s + "\n"
            color = get_color(**self.colors.get('EXCEPTION', {}))
            if color:
                s = s + color + record.exc_text + '\x1b[0m'
            else:
                s = s + record.exc_text
        if record.stack_info:
            if s[-1:] != "\n":
                s = s + "\n"
            s = s + self.formatStack(record.stack_info)
        return s


class PagedMessage:
    def __init__(self, pages, prev='◀', next='▶', test_check=False):
        """
        Paged message where pages can be changed by reacting to a message

        Args:
            test_check: Set to False when the checks are done by other means
        """
        self._pages = pages
        self._idx = 0
        self._prev = prev
        self._next = next
        self.test_check = test_check

    def check(self, reaction, user):
        if reaction not in (self._prev, self._next):
            return False
        else:
            return True

    def reaction_changed(self, reaction, user):
        if self.test_check and not self.check(reaction, user):
            return

        if reaction == self._next:
            try:
                page = self._pages[self._idx + 1]
                self._idx += 1
            except IndexError:
                page = None

        else:
            idx = self._idx - 1
            if idx < 0:
                idx = len(self._pages) - 1
                if idx == self._idx:
                    return

            self._idx = idx
            page = self._pages[idx]

        return page

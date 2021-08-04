import itertools
import logging
import operator

import colors
import discord
from asyncpg.exceptions import PostgresError
from discord import Embed
from discord.embeds import EmptyEmbed
from discord.ext.commands import help, BucketType
from discord.ext.commands.errors import CommandError

from bot.commands import Command
from bot.cooldowns import Cooldown
from bot.exceptions import CommandBlacklisted
from utils.utilities import check_perms

terminal = logging.getLogger('terminal')

# Inject our custom Command class
help._HelpCommandImpl.__bases__ = (Command, *Command.__bases__)


class HelpCommand(help.HelpCommand):
    """Help command implementation that tries to be thread safe.
    Will overwrite all aliases given to it before init"""
    Generic = 0
    Filtered = 1  # Show only the commands that the caller can use based on required discord permissions
    ExtendedFilter = 2  # Include database black/whitelist to filter

    def __init__(self, **options):
        options.setdefault('command_attrs', {})
        options['command_attrs']['aliases'] = ['helpall']
        options['command_attrs']['cooldown'] = Cooldown(2, 10, BucketType.guild)
        super().__init__(**options)

    def show_all(self):
        return self.context.invoked_with == 'helpall'

    @staticmethod
    async def _get_db_perms(ctx):
        user = ctx.author
        channel = ctx.channel
        is_guild = ctx.guild is not None

        if isinstance(user, discord.Member) and len(user.roles) > 1:
            roles = '(role IS NULL OR role IN ({}))'.format(', '.join(map(lambda r: str(r.id), user.roles)))
        else:
            roles = 'role IS NULL'

        guild_owner = False if (not is_guild or not ctx.guild.owner_id) else user.id == ctx.guild.owner_id
        command_blacklist = {}

        # Filter by custom blacklist
        if not guild_owner and is_guild:
            sql = 'SELECT type, role, uid, channel, command FROM command_blacklist WHERE guild=$1 ' \
                  'AND (uid IS NULL OR uid=$2) AND {} AND (channel IS NULL OR channel=$3)'.format(roles)

            try:
                rows = await ctx.bot.dbutil.fetch(sql, (ctx.guild.id, user.id, channel.id))

                for row in rows:
                    name = row['command']
                    if name in command_blacklist:
                        command_blacklist[name].append(row)
                    else:
                        command_blacklist[name] = [row]

            except PostgresError:
                terminal.exception('Failed to get role blacklist for help command')

        return command_blacklist

    @staticmethod
    def check_blacklist(commands, command_blacklist):
        def check(command):
            rows = command_blacklist.get(command.name, None)
            if not rows:
                return None
            return check_perms(rows)

        new_commands = []
        whitelist = []
        for cmd in commands:
            retval = check(cmd)
            if retval:
                whitelist.append(cmd)
            elif retval is None:
                new_commands.append(cmd)

        return new_commands, whitelist

    def get_destination(self):
        return self.context

    @staticmethod
    async def send_messages(dest, paginator, can_undo=True):
        for page in paginator.pages:
            try:
                await dest.send(embed=page, undoable=can_undo)
            except discord.HTTPException:
                return

    async def send_bot_help(self, mapping):
        """
        Handles the implementation of the bot command page in the help command.
        This function is called when the help command is called with no arguments.

        It should be noted that this method does not return anything -- rather the
        actual message sending should be done inside this method. Well behaved subclasses
        should use :meth:`get_destination` to know where to send, as this is a customisation
        point for other users.

        You can override this method to customise the behaviour.

        Parameters
        ------------
        mapping: Mapping[Optional[:class:`Cog`], List[:class:`Command`]
            A mapping of cogs to commands that have been requested by the user for help.
            The key of the mapping is the :class:`~.commands.Cog` that the command belongs to, or
            ``None`` if there isn't one, and the value is a list of commands that belongs to that cog.
        """
        ctx = self.context
        dest = self.get_destination()

        paginator = Paginator(title='Help')
        skip_checks = self.show_all() or not self.verify_checks
        commands = ctx.bot.commands

        def get_category(command):
            cog = command.cog
            return cog.qualified_name + ':' if cog is not None else 'No category'

        if not skip_checks:
            command_blacklist = await self._get_db_perms(ctx)
            whitelisted = ()
            if command_blacklist:
                commands, whitelisted = self.check_blacklist(commands, command_blacklist)

            # We dont wanna check db perms again for each individual command
            ctx.skip_check = True

            commands = await self.filter_commands(commands, sort=True, key=get_category)

            # We also dont wanna leave it on
            ctx.skip_check = False
            commands.extend(whitelisted)

        else:
            commands = commands if self.show_hidden else filter(lambda c: not c.hidden, commands)
            commands = sorted(commands, key=get_category)

        def inline(entries):
            if len(entries) > 5:
                return False
            else:
                return True

        for category, commands in itertools.groupby(commands, key=get_category):
            # there simply is no prettier way of doing this.
            commands = list(commands)
            self._add_commands_to_field(paginator, category, commands, inline=inline(commands))

        # add the ending note
        ending_note = self.get_ending_note(ctx)
        paginator.add_field('Note', ending_note)
        # Flush page buffer
        paginator.finalize()

        await self.send_messages(dest, paginator)

    async def send_cog_help(self, cog):
        ctx = self.context
        dest = self.get_destination()

        paginator = Paginator(title='Help', description=cog.description)
        skip_checks = self.show_all() or not self.verify_checks
        commands = cog.get_commands()

        if not skip_checks:
            command_blacklist = await self._get_db_perms(ctx)
            whitelisted = ()
            if command_blacklist:
                commands, whitelisted = self.check_blacklist(commands, command_blacklist)

            # We dont wanna check db perms again for each individual command
            ctx.skip_check = True

            commands = await self.filter_commands(commands)

            # We also dont wanna leave it on
            ctx.skip_check = False
            commands.extend(whitelisted)

        else:
            commands = commands if self.show_hidden else filter(lambda c: not c.hidden, commands)

        if commands:
            self._add_commands_to_field(paginator, 'Commands', commands)

        # add the ending note
        ending_note = self.get_ending_note(ctx)
        paginator.add_field('Note', ending_note)
        paginator.finalize()

        await self.send_messages(dest, paginator)

    async def send_group_help(self, group):
        ctx = self.context
        dest = self.get_destination()
        paginator = await self.create_command_page(ctx, group)
        skip_checks = self.show_all() or not self.verify_checks

        if not skip_checks:
            commands = await self.filter_commands(group.commands)
        else:
            commands = group.commands

        if commands:
            paginator.add_field('Subcommands')
            for cmd in sorted(commands, key=operator.attrgetter('name')):
                paginator.add_to_field(f' {cmd.name} ● ')

        # add the ending note
        ending_note = self.get_ending_note(ctx)
        paginator.add_field('Note', ending_note)
        paginator.finalize()

        await self.send_messages(dest, paginator)

    async def send_command_help(self, command):
        ctx = self.context
        dest = self.get_destination()
        paginator = await self.create_command_page(ctx, command)

        paginator.finalize()

        await self.send_messages(dest, paginator)

    async def create_command_page(self, ctx, command):
        """
        Creates a paginator for a command and creates the correct
        description and usage fields
        """
        cmd_name = command.qualified_name

        if command.help:
            description = command.help.format(prefix=self.context.prefix, name=cmd_name.strip())
        else:
            description = Embed.Empty

        paginator = Paginator(title=command.name, description=description)
        signature = self.get_command_signature(command)
        if getattr(command, 'owner_only', False):
            signature = 'This command is owner only\n' + signature

        try:
            can_run = await command.can_run(ctx) and await ctx.bot.can_run(ctx)
        except CommandBlacklisted as e:
            signature = e.full_message + '\n\n' + signature
            # Workaround to get past the next if
            can_run = True

        except CommandError as e:
            signature = str(e) + '\n\n' + signature
            can_run = True

        if not can_run:
            signature = "This command is blacklisted for you\n\n" + signature

        signature = command.description + '\n' + signature

        paginator.add_field('Usage', signature)

        return paginator

    def get_ending_note(self, ctx=None):
        ctx = ctx or self.context
        command_name = ctx.command.root_parent or ctx.invoked_with
        s = "Type `{0}{1} command` for more info on a command.\n"\
            "You can also type `{0}{1} Category` for more info on a category.\n" \
            "You can use the `{0}feedback` command to send a message if something is not clear or some feature is missing.\n".format(ctx.prefix, command_name)

        if ctx.invoked_with != 'helpall':
            s += "This list is filtered based on your and the bots permissions. Use `{}helpall` to skip checks".format(ctx.prefix)
        return s

    @staticmethod
    def _add_commands_to_field(paginator, field, commands, inline=False):
        """
        Adds commands to a new field in the paginator
        Args:
            paginator (Paginator):
                Paginator to be used
            field (str):
                Name of the field being added. Usually category name
            commands (list of Command):
                List of commands that will be added under this field
            inline(bool):
                Whether field is inline or not. Defaults to False

        """
        entries = []
        for command in sorted(commands, key=operator.attrgetter('name')):
            entries.append(f'{command.name} ● ')

        if not entries:
            return

        if callable(inline):
            inline = inline(entries)

        paginator.add_field(field, inline=inline)
        for entry in entries:
            paginator.add_to_field(entry)


class EmbedLimits:
    Field = 1024
    Name = 256
    Title = 256
    Description = 2048
    Fields = 25
    Total = 6000


class Paginator:
    def __init__(self, title=None, description=EmptyEmbed, page_count=True, init_page=True):
        """
        Args:
            title: title of the embed
            description: description of the embed
            page_count: whether to show page count in the footer or not
            init_page: create a page in the init method
        """
        self._fields = 0
        self._pages = []
        self.title = title
        self.description = description
        self.set_page_count = page_count
        self._current_page = -1
        self._char_count = 0
        self._current_field = None
        if init_page:
            self.add_page(title, description)

    @property
    def pages(self):
        return self._pages

    def finalize(self):
        self._add_field()
        if not self.set_page_count:
            return

        total = len(self.pages)
        for idx, embed in enumerate(self.pages):
            embed.set_footer(text=f'{idx+1}/{total}')

    def add_page(self, title=None, description=EmptyEmbed, paginate_description=False):
        """
        Args:
            title:
            description:
            paginate_description:
                If set to true will split description based on max description length
                into multiple embeds
        """
        title = title or self.title
        description = description or self.description
        overflow = None
        if description:
            if paginate_description:
                description_ = description[:EmbedLimits.Description]
                overflow = description[EmbedLimits.Description:]
                description = description_
            else:
                description = description[:EmbedLimits.Description]

        self._pages.append(Embed(title=title, description=description))
        self._current_page += 1
        self._fields = 0
        self._char_count = 0
        self._char_count += len(title) if title else 0
        self._char_count += len(description) if description else 0
        self.title = title
        self.description = description

        if overflow:
            self.add_page(title=title, description=overflow, paginate_description=True)

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

        name = name[:EmbedLimits.Title]
        leftovers = value[EmbedLimits.Field:]
        value = value[:EmbedLimits.Field]
        length = len(name) + len(value)

        if self._fields == 25:
            self._pages.append(Embed(title=self.title))
            self._current_page += 1
            self._fields = 0
            self._char_count = len(self.title)
            if self._current_field is not None:
                self._add_field()

        elif length + self._char_count > EmbedLimits.Total:
            self._pages.append(Embed(title=self.title))
            self._current_page += 1
            self._fields = 0
            self._char_count = len(self.title)

        self._current_field = {'name': name, 'value': value, 'inline': inline}

        if leftovers:
            self.add_field(name, leftovers, inline=inline)

    def add_to_field(self, value):
        v = self._current_field['value']
        if len(v) + len(value) > EmbedLimits.Field:
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

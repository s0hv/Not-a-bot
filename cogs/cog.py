from datetime import timezone
from typing import Callable

from disnake import ApplicationCommandInteraction, SlashCommand
from disnake.ext import commands
from disnake.ext.commands import Command, CommandOnCooldown

from bot.botbase import BotBase
from bot.types import BotContext


class Cog[TBot: BotBase = BotBase](commands.Cog):
    def __init__(self, bot: TBot):
        super().__init__()
        self._bot = bot

    async def cog_load(self) -> None:
        # Add all commands to cmdstats db table
        cmds = set()
        for cmd in self.walk_commands():
            if not isinstance(cmd, SlashCommand):
                cmds.add(cmd)

        data = []
        for cmd in cmds:
            entries = []
            command = cmd
            while command.parent is not None:
                command = command.parent
                entries.append(command.name)
            entries = list(reversed(entries))
            entries.append(cmd.name)
            data.append((entries[0], ' '.join(entries[1:]) or ""))

        if hasattr(self.bot, 'dbutil'):
            await self.bot.dbutil.add_commands(data)

    def reset_cooldown(self, ctx: BotContext) -> None:
        """Reset the cooldown for a command."""
        if isinstance(ctx, ApplicationCommandInteraction):
            ctx.application_command.reset_cooldown(ctx)
        else:
            ctx.command.reset_cooldown(ctx)

    def share_cooldown(self, command: Command, inter: ApplicationCommandInteraction) -> None:
        """Share the cooldown for a command."""
        if command._buckets.valid:
            dt = inter.created_at
            current = dt.replace(tzinfo=timezone.utc).timestamp()
            bucket = command._buckets.get_bucket(inter, current)
            if bucket is not None:  # pyright: ignore[reportUnnecessaryComparison]
                retry_after = bucket.update_rate_limit(current)
                if retry_after:
                    raise CommandOnCooldown(bucket, retry_after, command._buckets.type)

    async def run_with_typing[T](self, ctx: BotContext, method: Callable[..., T], *args) -> T:
        """Run a long operation in a separate thread with typing if not an interaction."""
        if not isinstance(ctx, ApplicationCommandInteraction):
            async with ctx.typing():
                return await self.bot.run_async(method, *args)

        return await self.bot.run_async(method, *args)

    @property
    def bot(self) -> TBot:
        return self._bot

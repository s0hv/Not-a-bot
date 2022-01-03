from typing import Union, List, Optional, Callable, NoReturn

import discord
from discord import ApplicationContext
from discord.ext.pages import Paginator

from bot.bot import Context


class ViewPaginator(Paginator):
    def __init__(
            self,
            pages: Union[List[str], List[discord.Embed]],
            show_disabled=True,
            show_indicator=True,
            author_check=True,
            disable_on_timeout=True,
            custom_view: Optional[discord.ui.View] = None,
            timeout: Optional[float] = 180.0,
            generate_page: Callable[[int], NoReturn]=None
    ) -> None:
        super().__init__(
            pages,
            show_disabled=show_disabled,
            show_indicator=show_indicator,
            author_check=author_check,
            disable_on_timeout=disable_on_timeout,
            custom_view=custom_view,
            timeout=timeout
        )
        self.generate_page = generate_page

    async def send(self, ctx: Union[ApplicationContext, Context], ephemeral: bool = False, starting_page: int=0):
        if self.generate_page:
            self.generate_page(starting_page)
        await super().send(ctx, ephemeral=ephemeral)

    async def goto_page(self, interaction: discord.Interaction, page_number=0) -> None:
        if self.generate_page is not None:
            self.generate_page(page_number)

        await super().goto_page(interaction, page_number)

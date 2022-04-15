from typing import Union, List, Optional, Callable, NoReturn, Any

import disnake
from disnake import MessageInteraction
from disnake.ui import View

from bot.bot import Context


class Paginator(View):
    def __init__(
            self,
            pages: List[str | disnake.Embed | Any],
            author_check=True,
            disable_on_timeout=True,
            show_stop_button=False,
            hide_page_count=False,
            timeout: Optional[float] = 180,
            initial_page: int = 0,
            generate_page: Callable[[int], NoReturn]=None
    ) -> None:
        super().__init__(timeout=timeout)
        self.pages = pages
        self.page_idx = initial_page
        self.author_check = author_check
        self.generate_page = generate_page
        self.disable_on_timeout = disable_on_timeout
        self.message: Optional[disnake.InteractionMessage | disnake.Message] = None
        self.author: Optional[disnake.User] = None

        if not show_stop_button:
            self.children.remove(self.stop_button)

        if hide_page_count:
            idx = self.children.index(self.page_btn)
            self.remove_item(self.page_btn)

            if show_stop_button:
                # This just seems like less work overall even though I'm breaking stuff
                self.children.remove(self.stop_button)
                self.children.insert(idx, self.stop_button)
                self.stop_button.row = 0
                self.stop_button._rendered_row = 0

        self.update_button_states()

    async def interaction_check(self, interaction: MessageInteraction) -> bool:
        if self.author_check and interaction.author != self.author:
            return False

        return True

    async def on_timeout(self) -> None:
        if not self.disable_on_timeout or self.message is None:
            return

        self.prev_page.disabled = True
        self.first_page.disabled = True
        self.next_page.disabled = True
        self.last_page.disabled = True

        page = self.get_current_page()
        if isinstance(page, disnake.Embed):
            await self.message.edit(embed=page, view=self)
        else:
            await self.message.edit(content=page, view=self)

    def update_button_states(self):
        self.next_page.disabled = False
        self.last_page.disabled = False
        self.prev_page.disabled = False
        self.first_page.disabled = False

        if self.page_idx == 0:
            self.prev_page.disabled = True
            self.first_page.disabled = True

        elif self.page_idx == len(self.pages) - 1:
            self.next_page.disabled = True
            self.last_page.disabled = True

        if len(self.pages) < 3:
            self.last_page.disabled = True
            self.first_page.disabled = True

        self.page_btn.label = self.get_page_text()

    def get_page_text(self):
        return f'{self.page_idx+1}/{len(self.pages)}'

    async def send(self, ctx: Union[Context, disnake.ApplicationCommandInteraction], **kwargs):
        page = self.get_current_page()
        args = (page,) if isinstance(page, str) else ()
        if isinstance(page, disnake.Embed):
            kwargs['embed'] = page

        msg = await ctx.send(*args, view=self, **kwargs)
        if isinstance(ctx, disnake.ApplicationCommandInteraction):
            msg = await ctx.original_message()

        self.author = ctx.author
        self.message = msg

    def get_current_page(self) -> Union[str, disnake.Embed]:
        if self.generate_page:
            self.generate_page(self.page_idx)

        return self.pages[self.page_idx]

    async def update_view(self, interaction: MessageInteraction):
        page = self.get_current_page()
        self.update_button_states()

        if isinstance(page, disnake.Embed):
            await interaction.response.edit_message(embed=page, view=self)
        else:
            await interaction.response.edit_message(page, view=self)

    @disnake.ui.button(label='<<', style=disnake.ButtonStyle.blurple)
    async def first_page(self, _, interaction: MessageInteraction):
        self.page_idx = 0
        await self.update_view(interaction)

    @disnake.ui.button(label='<', style=disnake.ButtonStyle.red)
    async def prev_page(self, _, interaction: MessageInteraction):
        self.page_idx -= 1
        await self.update_view(interaction)

    @disnake.ui.button(label='', disabled=True)
    async def page_btn(self, _, interaction: MessageInteraction):
        pass

    @disnake.ui.button(label='>', style=disnake.ButtonStyle.green)
    async def next_page(self, _, interaction: MessageInteraction):
        self.page_idx += 1
        await self.update_view(interaction)

    @disnake.ui.button(label='>>', style=disnake.ButtonStyle.blurple)
    async def last_page(self, _, interaction: MessageInteraction):
        self.page_idx = len(self.pages) - 1
        await self.update_view(interaction)

    @disnake.ui.button(emoji='🛑', style=disnake.ButtonStyle.red)
    async def stop_button(self, *_):
        if self.message:
            await self.message.delete()
            self.message = None
            self.stop()

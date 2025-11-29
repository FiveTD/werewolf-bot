#!/usr/bin/env -S uv run --script

import discord
from discord import app_commands
import asyncio

import logging
from dotenv import load_dotenv
from os import environ
# from typing import Literal

from channel_config import *

# ============================================================
# MODEL DEFINITIONS
# ============================================================

class WerewolfGame:
    players: list[discord.Member]
    
    def __init__(self, players: list[discord.Member]):
        self.players = players
        
    def lobby_message(self, started=False) -> str:
        msg = "**Werewolf**\n"
        if not started: msg += "*Players detected:*\n"
        msg += f"{'\n'.join([member.display_name for member in self.players]) if self.players else 'None'}\n"
        if not started: msg += f"\nPress 'Start Game' when ready."
        else: msg += "\n*The game has started!*"
        return msg

# ============================================================
# DISCORD CLIENT SETUP
# ============================================================

load_dotenv()
TEST_GUILD = discord.Object(id=int(environ.get("DISCORD_GUILD_ID", 0)))

class WerewolfClient(discord.Client):
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        
    async def setup_hook(self):
        # This copies the global commands over to your guild.
        self.tree.copy_global_to(guild=TEST_GUILD)
        await self.tree.sync(guild=TEST_GUILD)

intents = discord.Intents.default()
intents.message_content = True
client = WerewolfClient(intents=intents)

@client.event
async def on_ready():
    logging.info(f'Logged in as {client.user}')

# ============================================================
# COMMANDS
# ============================================================

@client.tree.command(name="test-channel-config", description="Pings every channel to test config setup.", guild=TEST_GUILD)
async def test_channel_config(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.")
        return
    
    for channel in TEXT_ID:
        discord_channel = guild.get_channel(channel)
        if discord_channel is None or discord_channel.type != discord.ChannelType.text:
            await interaction.response.send_message(f"Text channel for {channel.name} with ID {channel} not found.")
        else:
            try:
                await discord_channel.send(f"This is a test message for the {channel.name} channel.")
            except discord.errors.Forbidden as e:
                await interaction.response.send_message(f"Failed to send message to {channel.name} channel: does the bot have permission?")
    
    await interaction.response.send_message("Sent a test message to all configured channels.")
    
class NewGameView(discord.ui.View):
    def __init__(self, update_task: asyncio.Task, model: WerewolfGame):
        super().__init__(timeout=None)
        self.update_task = update_task
        self.model = model
        
    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.green)
    async def start_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.update_task.cancel()
        await interaction.response.edit_message(content=self.model.lobby_message(started=True), view=None)
            
@client.tree.command(name="new-game", description="Opens a new game of Werewolf. Detects players based on voice channel members.", guild=TEST_GUILD)
async def new_game(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.")
        return
    
    if interaction.channel is None or interaction.channel.id != TEXT_ID.NARRATOR_CONTROL:
        await interaction.response.send_message("This command can only be used in the NARRATOR_CONTROL text channel.")
        return
    
    voice_channel = guild.get_channel(VOICE_ID.GENERAL)
    if voice_channel is None or voice_channel.type != discord.ChannelType.voice:
        await interaction.response.send_message("Voice channel for GENERAL not found.")
        return
    
    game = WerewolfGame(players=voice_channel.members)
    async def update_message():
        nonlocal game
        while True:
            try:
                game.players = voice_channel.members
                await interaction.edit_original_response(content=game.lobby_message())
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                break
            
    update_task = asyncio.create_task(update_message())
    view = NewGameView(update_task, game)
    await interaction.response.send_message("**Werewolf**", view=view)
    
class WerewolfConfirm(discord.ui.View):
    def __init__(self):
        super().__init__()
        self.value = None

    # When the confirm button is pressed, set the inner value to `True` and
    # stop the View from listening to more input.
    # We also send the user an ephemeral message that we're confirming their choice.
    @discord.ui.button(label='Confirm', style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Confirming', ephemeral=True)
        self.value = True
        self.stop()

    # This one is similar to the confirmation button except sets the inner value to `False`
    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.grey)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message('Cancelling', ephemeral=True)
        self.value = False
        self.stop()
        
@client.tree.command(name="feedback", description="Submit feedback about the bot.", guild=TEST_GUILD)
async def feedback(interaction: discord.Interaction):
    """Sends a feedback modal to the user."""
    view = WerewolfConfirm()
    await interaction.response.send_message('Do you want to continue?', view=view, ephemeral=True)
    await view.wait()
    if view.value is None:
        logging.info('Timed out...')
    elif view.value:
        logging.info('Confirmed...')
    else:
        logging.info('Canceled...')

# ============================================================
# MAIN
# ============================================================

def main():
    token = environ["DISCORD_BOT_TOKEN"]
    
    logging.basicConfig(level=logging.DEBUG)
    handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
    
    client.run(token, log_handler=handler, log_level=logging.DEBUG)

if __name__ == "__main__":
    main()

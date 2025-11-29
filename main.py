#!/usr/bin/env -S uv run --script

import discord
from discord import app_commands
import asyncio

import logging
from dotenv import load_dotenv
from os import environ
from typing import Literal

from guild_config import *

# ============================================================
# MODEL DEFINITIONS
# ============================================================

class WerewolfGame:
    players: list[discord.Member]
    narrators: list[discord.Member] = []
    spectators: list[discord.Member] = []
    
    def __init__(self, players: list[discord.Member]):
        self.set_players(players)
    
    def add_spectator(self, member: discord.Member) -> bool:
        if member not in self.spectators and member not in self.narrators:
            self.spectators.append(member)
            self.set_players()
            return True
        return False
    
    def remove_spectator(self, member: discord.Member) -> bool:
        if member in self.spectators and member not in self.narrators:
            self.spectators.remove(member)
            self.set_players()
            return True
        return False
            
    def set_players(self, members: list[discord.Member] | None = None):
        if members is None: members = self.players
        self.narrators = [m for m in members if m.get_role(NARRATOR_ROLE) is not None]
        print(f"n: {len(self.narrators)}")
        self.players = [m for m in members if m not in self.spectators and m not in self.narrators]
        print(f"p: {len(self.players)}")
    
    def lobby_message(self, started=False) -> str:
        msg = "**Werewolf**\n"
        msg += "*Narrators:*\n"
        msg += f"{'\n'.join([member.display_name for member in self.narrators]) if self.narrators else 'None'}\n\n"
        msg += "*Players:*\n"
        msg += f"{'\n'.join([member.display_name for member in self.players]) if self.players else 'None'}\n\n"
        if self.spectators:
            msg += "*Spectators:*\n"
            msg += f"{'\n'.join([member.display_name for member in self.spectators])}\n\n"
        if not started: msg += f"Press 'Start Game' when ready."
        else: msg += "*The game has started!*"
        return msg

# ============================================================
# DISCORD CLIENT SETUP
# ============================================================

load_dotenv()
TEST_GUILD = discord.Object(id=int(environ.get("DISCORD_GUILD_ID", 0)))

class WerewolfClient(discord.Client):
    game: WerewolfGame | None
    
    def __init__(self, *, intents: discord.Intents):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.game = None
        
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
                await interaction.response.send_message(content=f"Failed to send message to {channel.name} channel: does the bot have permission?")
    
    await interaction.response.send_message("Sent a test message to all configured channels.", ephemeral=True)
    
class NewGameView(discord.ui.View):
    def __init__(self, update_task: asyncio.Task, model: WerewolfGame):
        super().__init__(timeout=None)
        self.update_task = update_task
        self.model = model
        
    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.green)
    async def start_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.update_task.cancel()
        await interaction.response.edit_message(content=self.model.lobby_message(started=True), view=None)
        
    @discord.ui.button(label="Cancel Game", style=discord.ButtonStyle.red)
    async def cancel_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.update_task.cancel()
        await interaction.response.edit_message(content="**Werewolf**\n*Game canceled*", view=None)
            
@client.tree.command(name="new-game", description="Opens a new game of Werewolf. Detects players based on voice channel members.", guild=TEST_GUILD)
async def new_game(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    if interaction.channel is None or interaction.channel.id != TEXT_ID.NARRATOR_CONTROL:
        await interaction.response.send_message("This command can only be used in the NARRATOR_CONTROL text channel.", ephemeral=True)
        return
    
    if client.game is not None:
        await interaction.response.send_message("A game is already in progress. Please wait for it to finish before starting a new one.", ephemeral=True)
        return
    
    voice_channel = guild.get_channel(VOICE_ID.GENERAL)
    if voice_channel is None or voice_channel.type != discord.ChannelType.voice:
        await interaction.response.send_message("Voice channel for GENERAL not found.", ephemeral=True)
        return
    
    client.game = WerewolfGame(players=voice_channel.members)
    async def update_lobby_message():
        if client.game is None: raise Exception("Game model is None in lobby task.")
        while True:
            try:
                client.game.set_players(voice_channel.members)
                # view.start_game_button.disabled = len(client.game.players) < 1 or len(client.game.narrators) < 1
                await interaction.edit_original_response(content=client.game.lobby_message(), view=view)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            
    update_task = asyncio.create_task(update_lobby_message())
    view = NewGameView(update_task, client.game)
    await interaction.response.send_message(client.game.lobby_message(), view=view)


@client.tree.command(name="spectate", description="Join or leave the spectator list for the current game.", guild=TEST_GUILD)
async def spectate(interaction: discord.Interaction, action: Literal["join", "leave"]):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    if client.game is None:
        await interaction.response.send_message("There is no active game to spectate.", ephemeral=True)
        return
    
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message("This command can only be used by guild members.", ephemeral=True)
        return
    if not member in client.game.players and not member in client.game.spectators and not member in client.game.narrators:
        await interaction.response.send_message("You are not part of the current game.", ephemeral=True)
        return
    
    if action == "join":
        success = client.game.add_spectator(member)
        if success:
            await interaction.response.send_message(f"You have joined the spectator list.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Failed to join: you are already a spectator or a narrator.", ephemeral=True)
    elif action == "leave":
        success = client.game.remove_spectator(member)
        if success:
            await interaction.response.send_message(f"You have left the spectator list.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Failed to leave: you are not currently a spectator or you are a narrator.", ephemeral=True)

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

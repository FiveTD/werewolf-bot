#!/usr/bin/env -S uv run --script

import discord
from discord import app_commands
import asyncio
import random

import logging
from dotenv import load_dotenv
from os import environ
from typing import Literal

from guild_config import *
from game_config import *

# ============================================================
# MODEL DEFINITIONS
# ============================================================

class Player:
    id: int
    name: str
    role: Role | None
    dead: bool = False
    
    def __init__(self, id: int, name: str):
        self.id = id
        self.name = name
        self.role = None

class WerewolfGame:
    call_members: list[discord.Member] = []
    narrators: list[discord.Member] = []
    spectators: list[discord.Member] = []
    players: list[Player] = []
    roles: list[Role] = []
    
    # Debug features
    dummies: list[Player] = []
    debug_narrator: discord.Member | None = None
    
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
        if members is None: members = self.call_members
        else: self.call_members = members
        self.narrators = [m for m in members if m.get_role(NARRATOR_ROLE) is not None]
        self.narrators += [self.debug_narrator] if self.debug_narrator is not None else []
        self.players = [Player(m.id, m.display_name) for m in members if m not in self.spectators and m not in self.narrators]
        self.players += self.dummies
        
    def setup_roles(self):
        num_players = len(self.players)
        num_werewolves = max(1, num_players // WOLF_RATIO)
        self.roles = [Role.WEREWOLF] * num_werewolves
        remaining_roles = [role for role in Role if role != Role.WEREWOLF and role != Role.VILLAGER]
        while remaining_roles and len(self.roles) < num_players:
            role_pick = random.choice(remaining_roles)
            remaining_roles.remove(role_pick)
            self.roles.append(role_pick)
        self.roles += [Role.VILLAGER] * (num_players - len(self.roles))
        self.shuffle_roles()
        
    def shuffle_roles(self):
        random.shuffle(self.roles)
        for i, player in enumerate(self.players):
            player.role = self.roles[i]
        
    def add_role(self, role: Role) -> bool:
        if Role.VILLAGER in self.roles:
            self.roles.remove(Role.VILLAGER)
            self.roles.append(role)
            self.shuffle_roles()
            return True
        return False
    
    def remove_role(self, role: Role) -> bool:
        if role in self.roles:
            if role == Role.WEREWOLF and self.roles.count(Role.WEREWOLF) == 1:
                return False
            self.roles.remove(role)
            self.roles.append(Role.VILLAGER)
            self.shuffle_roles()
            return True
        return False
    
    def lobby_msg(self, started=False) -> str:
        msg = "**Werewolf**\n"
        msg += f"*Narrators ({len(self.narrators)}/1):*\n"
        msg += f"{'\n'.join([member.display_name for member in self.narrators]) if self.narrators else 'None'}\n\n"
        msg += f"*Players ({len(self.players)}/{MIN_PLAYERS}):*\n"
        msg += f"{'\n'.join([member.name for member in self.players]) if self.players else 'None'}\n\n"
        if self.spectators:
            msg += "*Spectators:*\n"
            msg += f"{'\n'.join([member.display_name for member in self.spectators])}\n\n"
        if not started: msg += f"Press 'Start Game' when ready."
        else: msg += "*The game has started!*"
        return msg
    
    def role_msg(self, started=False) -> str:
        if not started: msg = "**Werewolf - Role Assignment**\n"
        else: msg = "**Werewolf - Roles Assigned**\n"
        for player in self.players:
            role = player.role
            if role is not None:
                msg += f"- {player.name}: {role.value}\n"
                
        msg += f"\n*Werewolves: {self.roles.count(Role.WEREWOLF)}/{len(self.players)}*"
        if not started:
            msg += "\n*Use '/role' to adjust role counts.*"
        return msg

# ============================================================
# DISCORD CLIENT SETUP
# ============================================================

load_dotenv()
TEST_GUILD = discord.Object(id=int(environ.get("DISCORD_GUILD_ID", 0)))

class WerewolfClient(discord.Client):
    game: WerewolfGame | None = None
    
    role_msg: discord.Message | None = None
    role_view: discord.ui.View | None = None
    
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
                await interaction.response.send_message(content=f"Failed to send message to {channel.name} channel: does the bot have permission?")
    
    await interaction.response.send_message("Sent a test message to all configured channels.", ephemeral=True)
    
class NewGameView(discord.ui.View):
    def __init__(self, update_task: asyncio.Task, game: WerewolfGame):
        super().__init__(timeout=None)
        self.update_task = update_task
        self.game = game
        self.value = None
        
    @discord.ui.button(label="Start Game", style=discord.ButtonStyle.green)
    async def start_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.update_task.cancel()
        await interaction.response.edit_message(content=self.game.lobby_msg(started=True), view=None)
        self.value = 'start'
        self.stop()
        
    @discord.ui.button(label="Cancel Game", style=discord.ButtonStyle.red)
    async def cancel_game_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.update_task.cancel()
        await interaction.response.edit_message(content="**Werewolf**\n*Game canceled*", view=None)
        self.value = 'cancel'
        self.stop()
        
class AssignRolesView(discord.ui.View):
    def __init__(self, game: WerewolfGame):
        super().__init__(timeout=None)
        self.game = game
        self.accept = False
    
    @discord.ui.button(label="Assign Roles", style=discord.ButtonStyle.green)
    async def assign_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.accept = True
        self.stop()
        
    @discord.ui.button(label="Shuffle Roles", style=discord.ButtonStyle.blurple)
    async def shuffle_roles_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.game.shuffle_roles()
        await interaction.response.edit_message(content=self.game.role_msg(), view=self)
            
@client.tree.command(name="new-game", description="Opens a new game of Werewolf. Detects players based on voice channel members.", guild=TEST_GUILD)
async def new_game(interaction: discord.Interaction):
    print("NEW GAME COMMAND INVOKED")
    
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    if interaction.channel is None or interaction.channel.id != TEXT_ID.NARRATOR_CONTROL or interaction.channel.type != discord.ChannelType.text:
        await interaction.response.send_message("This command can only be used in the NARRATOR_CONTROL text channel.", ephemeral=True)
        return
    
    if client.game is not None:
        await interaction.response.send_message("A game is already in progress. Please wait for it to finish before starting a new one.", ephemeral=True)
        return
    
    voice_channel = guild.get_channel(VOICE_ID.GENERAL)
    if voice_channel is None or voice_channel.type != discord.ChannelType.voice:
        await interaction.response.send_message("Voice channel for GENERAL not found.", ephemeral=True)
        return
    
    # === Lobby Setup ===
    print("Setting up new game lobby...")
    client.game = WerewolfGame(players=voice_channel.members)
    async def update_lobby_message():
        if client.game is None: raise Exception("Game model is None in lobby task.")
        while True:
            try:
                client.game.set_players(voice_channel.members)
                lobby_view.start_game_button.disabled = len(client.game.players) < MIN_PLAYERS or len(client.game.narrators) < 1
                await interaction.edit_original_response(content=client.game.lobby_msg(), view=lobby_view)
                await asyncio.sleep(1)
            except asyncio.CancelledError:
                break
            
    update_task = asyncio.create_task(update_lobby_message())
    lobby_view = NewGameView(update_task, client.game)
    await interaction.response.send_message(client.game.lobby_msg(), view=lobby_view)
    await lobby_view.wait()
    print("View awaited")
    if lobby_view.value is None or lobby_view.value == 'cancel':
        client.game = None
        print("Game canceled.")
        return
    
    print("Game started with players:", [p.name for p in client.game.players])
    
    # === Role Assignment ===
    client.game.setup_roles()
    
    client.role_view = AssignRolesView(client.game)
    client.role_msg = await interaction.channel.send(client.game.role_msg(), view=client.role_view)
    await client.role_view.wait()
    await client.role_msg.edit(content=client.game.role_msg(started=True), view=None)
    
    print("Roles assigned.")
    
    # === Game Setup ===
    for player in client.game.players:
        if player.role is None:
            raise Exception("Player with None role after role setup")
        if player.id < 0: continue # Dummy player
        if player.role.name in TEXT_ID.__members__:
            player_member = guild.get_member(player.id)
            if player_member is None:
                raise Exception("Unable to get member for player")
            channel_id = TEXT_ID[player.role.name]
            role_channel = guild.get_channel(channel_id)
            if role_channel is None:
                raise Exception("Unable to get role channel")
            await role_channel.set_permissions(player_member, read_messages=True, send_messages=True)
    
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
            
@client.tree.command(name="role", description="Add or remove a role from the game.", guild=TEST_GUILD)
async def role(interaction: discord.Interaction, action: Literal["add", "remove", "replace"], role: Role, with_role: Role | None = None):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    if interaction.channel is None or interaction.channel.id != TEXT_ID.NARRATOR_CONTROL:
        await interaction.response.send_message("This command can only be used in the NARRATOR_CONTROL text channel.", ephemeral=True)
        return
    
    if client.game is None:
        await interaction.response.send_message("There is no active game to modify roles for.", ephemeral=True)
        return
    
    if client.role_msg is None:
        await interaction.response.send_message("Cannot modify roles: not in role selection stage.", ephemeral=True)
        return
    
    if action == "add":
        if role == Role.VILLAGER:
            await interaction.response.send_message(f"Cannot add Villager role directly. Remove a role instead.", ephemeral=True)
            return
        success = client.game.add_role(role)
        if success:
            await interaction.response.send_message(f"Added role {role.value}.", ephemeral=True)
        else:
            await interaction.response.send_message(f"Failed to add role {role.value}: no Villager roles left to replace.", ephemeral=True)
    elif action == "remove" or action == "replace":
        if role == Role.VILLAGER:
            await interaction.response.send_message(f"Cannot remove Villager role directly. Add a role instead.", ephemeral=True)
            return
        if with_role == Role.VILLAGER: action = "remove"
        elif with_role is None and action == "replace":
            await interaction.response.send_message(f"Please specify a role to replace with.", ephemeral=True)
            return
        success = client.game.remove_role(role)
        if success:
            if action == "remove":
                await interaction.response.send_message(f"Removed role {role.value}.", ephemeral=True)
            elif action == "replace":
                success_add = client.game.add_role(with_role) # type: ignore
                if success_add:
                    await interaction.response.send_message(f"Replaced role {role.value} with {with_role.value}.", ephemeral=True) # type: ignore
                else:
                    await interaction.response.send_message(f"Failed to add role {with_role.value}.", ephemeral=True) # type: ignore
        else:
            if role == Role.WEREWOLF:
                await interaction.response.send_message(f"Failed to remove role {role.value}: cannot remove last Werewolf.", ephemeral=True)
            else:
                await interaction.response.send_message(f"Failed to remove role {role.value}: role not in game.", ephemeral=True)
        
    await client.role_msg.edit(content=client.game.role_msg())

@client.tree.command(name="dummies", description="Set a number of dummy players.", guild=TEST_GUILD)
async def dummies(interaction: discord.Interaction, count: int):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    if interaction.channel is None or interaction.channel.id != TEXT_ID.NARRATOR_CONTROL:
        await interaction.response.send_message("This command can only be used in the NARRATOR_CONTROL text channel.", ephemeral=True)
        return
    
    if client.game is None:
        await interaction.response.send_message("There is no active game to set dummies for.", ephemeral=True)
        return
    
    if count < 0:
        await interaction.response.send_message("Dummy count cannot be negative.", ephemeral=True)
        return
    
    client.game.dummies = [Player(id=-(i+1), name=f"Dummy {i+1}") for i in range(count)]
    client.game.set_players()
    await interaction.response.send_message(f"Set {count} dummy players for the game.", ephemeral=True)
    
@client.tree.command(name="debug-narrator", description="Set yourself as a narrator (without joining the call).", guild=TEST_GUILD)
async def debug_narrator(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    if interaction.channel is None or interaction.channel.id != TEXT_ID.NARRATOR_CONTROL:
        await interaction.response.send_message("This command can only be used in the NARRATOR_CONTROL text channel.", ephemeral=True)
        return
    
    if client.game is None:
        await interaction.response.send_message("There is no active game to set a debug narrator for.", ephemeral=True)
        return
    
    member = interaction.user
    if not isinstance(member, discord.Member):
        await interaction.response.send_message("This command can only be used by guild members.", ephemeral=True)
        return
    
    client.game.debug_narrator = member
    client.game.set_players()
    await interaction.response.send_message(f"You have been set as a debug narrator for the game.", ephemeral=True)

@client.tree.command(name="cleanup", description="Clean up any setup from a previous game of Werewolf.")
async def cleanup(interaction: discord.Interaction):
    guild = interaction.guild
    if guild is None or guild.id != TEST_GUILD.id:
        await interaction.response.send_message("This command can only be used in the configured guild.", ephemeral=True)
        return
    
    for channel_id in TEXT_ID:
        if channel_id == TEXT_ID.NARRATOR_CONTROL or channel_id == TEXT_ID.GENERAL: continue
        channel = guild.get_channel(channel_id)
        if channel is None:
            await interaction.response.send_message(f"Unable to locate {channel_id.name} channel.", ephemeral=True)
            return
        
        for target, overwrite in list(channel.overwrites.items()):
            if isinstance(target, discord.Member):
                await channel.set_permissions(target, overwrite=None)
                
    await interaction.response.send_message("Cleaned up access setup.")

# ============================================================
# MAIN
# ============================================================

def main():
    token = environ["DISCORD_BOT_TOKEN"]
    
    # logging.basicConfig(level=logging.DEBUG)
    handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
    
    client.run(token, log_handler=handler, log_level=logging.INFO)

if __name__ == "__main__":
    main()

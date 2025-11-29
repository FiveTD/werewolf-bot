#!/usr/bin/env -S uv run --script

import discord
from discord import app_commands

import logging
from dotenv import load_dotenv
from os import environ

from channel_config import *

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

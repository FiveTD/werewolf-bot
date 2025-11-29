#!/usr/bin/env -S uv run --script

import discord
from discord import app_commands

import logging
from typing import Optional
from dotenv import load_dotenv
from os import environ

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

@client.tree.command(name="ping", description="Responds with Pong!", guild=TEST_GUILD)
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message('Pong!')
    
@client.tree.command(name="echo", description="Echoes your message", guild=TEST_GUILD)
async def echo(interaction: discord.Interaction, message: str):
    await interaction.response.send_message(message)

def main():
    token = environ["DISCORD_BOT_TOKEN"]
    
    logging.basicConfig(level=logging.DEBUG)
    handler = logging.FileHandler(filename='discord.log', encoding='utf-8', mode='w')
    
    client.run(token, log_handler=handler, log_level=logging.DEBUG)

if __name__ == "__main__":
    main()

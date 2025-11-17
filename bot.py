import discord
from discord.ext import commands
import json
import os
import asyncio
from mcrcon import MCRcon
from dotenv import load_dotenv
import uuid
import hashlib

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
# WHITELIST_PATH = os.getenv("WHITELIST_PATH") # <<< CHANGE: No longer needed.
RCON_HOST = os.getenv("RCON_HOST")
RCON_PORT = int(os.getenv("RCON_PORT", 25575))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

# --- BOT & SERVER IDS ---
MC_WL_CHANNEL_ID = 1438763824760225882
REVIEW_CHANNEL_ID = 1438763882154819624
APPROVED_CHANNEL_ID = 1438763962496712764
REJECTED_CHANNEL_ID = 1438764012895735941
LOG_CHANNEL_ID = 1438793262994423838
MC_WHITELISTED_ROLE_ID = 1438789711023046718
DEV_ROLE_NAME = "Staff"

SETUP_FILE = "whitelist_setup.json"

# --- AESTHETICS ---
SERVER_ICON_URL = "https://cdn.discordapp.com/icons/1132719558231793744/a_d78d4615a72f0b7c7ed14b301c34a243.gif"
EMBED_COLORS = {
    "info": discord.Color.gold(),
    "pending": discord.Color.blue(),
    "success": discord.Color.green(),
    "error": discord.Color.red(),
}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


# <<< CHANGE: All old file/UUID functions have been removed.
# This new function directly whitelists players via RCON.

def add_player_via_rcon(username: str, device: str):
    """
    Adds a player to the server's whitelist using RCON.
    Returns a status and the final username used.
    """
    original_username = username.strip()
    final_username = original_username

    # Handle Bedrock/Geyser prefix
    if "bedrock" in device.lower():
        final_username = f"1{original_username}"
    
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            # The server will handle the UUID lookup automatically
            resp = mcr.command(f"whitelist add {final_username}")
            print(f"RCON: whitelist add {final_username} ->", resp)

            if "already whitelisted" in resp.lower():
                return "already_whitelisted", final_username
            elif "added" in resp.lower():
                return "success", final_username
            else:
                # Handle unexpected responses from the server
                return "rcon_error", final_username
                
    except Exception as e:
        print("RCON error:", e)
        return "rcon_error", final_username


# --- HELPER FUNCTIONS ---

def get_app_data_from_embed(embed: discord.Embed):
    """Extracts application data from review embed by field name."""
    user_id, mc_username, device = None, None, "Java" # Default device to Java
    for field in embed.fields:
        if field.name == "User": user_id = int(field.value.strip("<@!>"))
        elif field.name == "Minecraft Username": mc_username = field.value
        elif field.name == "Device": device = field.value
    return user_id, mc_username, device


# --- MODALS ---
class WhitelistModal(discord.ui.Modal, title="Minecraft Whitelist Application"):
    mc_username = discord.ui.TextInput(label="Minecraft Username (Case-Sensitive)", placeholder="Steve123")
    device = discord.ui.TextInput(label="Device (Java / Bedrock)", placeholder="Java")
    played_before = discord.ui.TextInput(label="Played Minecraft before? (Yes / No)", placeholder="Yes")
    notes = discord.ui.TextInput(label="Anything you'd like to add?", required=False, style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        mc_role = interaction.guild.get_role(MC_WHITELISTED_ROLE_ID)
        if mc_role and mc_role in interaction.user.roles:
            return await interaction.response.send_message("You are already whitelisted and cannot reapply.", ephemeral=True)

        embed = discord.Embed(title="📝 New Whitelist Application", color=EMBED_COLORS["pending"])
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
        embed.add_field(name="User", value=interaction.user.mention, inline=False)
        embed.add_field(name="Minecraft Username", value=self.mc_username.value, inline=False)
        embed.add_field(name="Device", value=self.device.value, inline=True)
        embed.add_field(name="Played Before", value=self.played_before.value, inline=True)
        embed.add_field(name="Notes", value=self.notes.value or "N/A", inline=False)
        embed.set_footer(text="Status: Pending Review ⏳", icon_url=SERVER_ICON_URL)

        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        await review_channel.send(embed=embed, view=ReviewView())
        await interaction.response.send_message("Your application has been submitted for review.", ephemeral=True)


class RejectionModal(discord.ui.Modal, title="Rejection Reason"):
    reason = discord.ui.TextInput(label="Please provide the reason for rejection.", style=discord.TextStyle.paragraph)

    def __init__(self, original_interaction: discord.Interaction):
        super().__init__()
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        review_message = self.original_interaction.message
        original_embed = review_message.embeds[0]
        original_embed.color = EMBED_COLORS["error"]
        original_embed.set_footer(text=f"Rejected by {interaction.user.display_name} ❌", icon_url=SERVER_ICON_URL)
        await review_message.edit(embed=original_embed, view=None)

        user_id, mc_username, _ = get_app_data_from_embed(original_embed)
        member = await bot.fetch_user(user_id)

        log_embed = discord.Embed(title="Whitelist Rejected", color=EMBED_COLORS["error"])
        log_embed.add_field(name="User", value=member.mention)
        log_embed.add_field(name="Minecraft Username", value=mc_username)
        log_embed.add_field(name="Rejected By", value=interaction.user.mention)
        log_embed.add_field(name="Reason", value=self.reason.value, inline=False)
        
        await bot.get_channel(REJECTED_CHANNEL_ID).send(embed=log_embed)
        await bot.get_channel(LOG_CHANNEL_ID).send(embed=log_embed)
        await interaction.response.send_message("Application has been rejected.", ephemeral=True)


# --- VIEWS ---
class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="review_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        # We run the blocking RCON command in an executor to not freeze the bot
        await interaction.response.defer(ephemeral=True, thinking=True)
        loop = asyncio.get_running_loop()

        user_id, mc_username, device = get_app_data_from_embed(interaction.message.embeds[0])
        
        # <<< CHANGE: Using the new RCON function
        status, final_username = await loop.run_in_executor(None, add_player_via_rcon, mc_username, device)

        if status == "rcon_error":
            return await interaction.followup.send("❌ **Error:** Could not connect to the server via RCON. The player was not whitelisted.", ephemeral=True)

        # The rest of the logic can continue even if the player was already whitelisted
        embed = interaction.message.embeds[0]
        embed.color = EMBED_COLORS["success"]
        embed.set_footer(text=f"Approved by {interaction.user.display_name} ✅", icon_url=SERVER_ICON_URL)
        await interaction.message.edit(embed=embed, view=None)

        guild = interaction.guild
        member = guild.get_member(user_id)
        mc_role = guild.get_role(MC_WHITELISTED_ROLE_ID)
        if member and mc_role:
            await member.add_roles(mc_role)

        log_embed = discord.Embed(title="Whitelist Approved", color=EMBED_COLORS["success"])
        log_embed.add_field(name="User", value=member.mention if member else f"ID: {user_id}")
        log_embed.add_field(name="Minecraft Username", value=f"`{final_username}`")
        log_embed.add_field(name="Approved By", value=interaction.user.mention)
        
        await bot.get_channel(APPROVED_CHANNEL_ID).send(embed=log_embed)
        await bot.get_channel(LOG_CHANNEL_ID).send(embed=log_embed)
        
        if status == "already_whitelisted":
            await interaction.followup.send(f"✅ Player `{final_username}` is already whitelisted. Role has been assigned/re-synced.", ephemeral=True)
        else: # success
            await interaction.followup.send(f"✅ Player `{final_username}` has been added to the whitelist and given the role.", ephemeral=True)


    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="review_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RejectionModal(original_interaction=interaction))


class WhitelistView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Apply for Whitelist", style=discord.ButtonStyle.green, custom_id="whitelist_apply_button")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(WhitelistModal())


# --- BOT EVENTS & COMMANDS ---
@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")
    bot.add_view(WhitelistView())
    bot.add_view(ReviewView())
    print("Persistent views registered.")
    try:
        # A check for DEV_ROLE_NAME before syncing can be good practice
        # to prevent accidental command registration on wrong servers
        if DEV_ROLE_NAME:
            synced = await bot.tree.sync()
            print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

@bot.tree.command(name="setup", description="Create the whitelist application embed (DEV only)")
@commands.has_role(DEV_ROLE_NAME)
async def setup_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Minecraft Whitelist Application",
        description="Click the button below to open the application form. \n\nPlease make sure your Minecraft username is correct, as it is case-sensitive.",
        color=EMBED_COLORS["info"]
    )
    embed.set_author(name=interaction.guild.name, icon_url=SERVER_ICON_URL)
    channel = bot.get_channel(MC_WL_CHANNEL_ID)
    await channel.send(embed=embed, view=WhitelistView())
    await interaction.response.send_message(f"Whitelist embed created in {channel.mention}.", ephemeral=True)

@setup_cmd.error
async def setup_error(interaction: discord.Interaction, error: commands.CommandError):
    if isinstance(error, commands.MissingRole):
        await interaction.response.send_message("You do not have the required role to use this command.", ephemeral=True)
    else:
        # It's good practice to log other unexpected errors
        print(f"An error occurred in setup_cmd: {error}")
        await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)


# --- RUN BOT ---
bot.run(TOKEN)

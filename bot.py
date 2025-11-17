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
WHITELIST_PATH = os.getenv("WHITELIST_PATH")
RCON_HOST = os.getenv("RCON_HOST")
RCON_PORT = int(os.getenv("RCON_PORT", 25575)) # Added a default port
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


# <<< CRITICAL FIX: Restored correct offline-mode UUID generation
def generate_offline_uuid(username: str) -> str:
    """Generates the correct offline-mode UUID for a given username."""
    base = f"OfflinePlayer:{username}"
    md5 = hashlib.md5(base.encode("utf-8")).hexdigest()
    return str(uuid.UUID(md5))


# <<< PERFORMANCE FIX: Made file/network operations non-blocking
def _add_to_whitelist_sync(username: str, device: str):
    """Synchronous function for file I/O. DO NOT CALL DIRECTLY."""
    original_username = username.strip()
    final_username = original_username

    # <<< CRITICAL FIX: Restored Bedrock/Geyser prefix support
    if "bedrock" in device.lower():
        final_username = f"1{original_username}"

    try:
        with open(WHITELIST_PATH, "r+", encoding="utf-8") as f:
            data = json.load(f)
            if any(entry["name"].lower() == final_username.lower() for entry in data):
                return "already_exists", final_username

            # <<< CRITICAL FIX: Use the correct offline UUID generation
            offline_uuid = generate_offline_uuid(final_username)
            data.append({"uuid": offline_uuid, "name": final_username})

            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
        return "success", final_username
    except FileNotFoundError:
        return "file_not_found", original_username
    except Exception as e:
        print(f"Error writing whitelist: {e}")
        return "write_error", original_username

async def add_to_whitelist(username: str, device: str):
    """Async wrapper to run the file I/O in a separate thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _add_to_whitelist_sync, username, device)


def _reload_whitelist_sync():
    """Synchronous function for RCON. DO NOT CALL DIRECTLY."""
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            resp = mcr.command("whitelist reload")
            print("RCON: whitelist reload ->", resp)
            return True
    except Exception as e:
        print("RCON error:", e)
        return False

async def reload_whitelist():
    """Async wrapper to run RCON in a separate thread."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _reload_whitelist_sync)


# <<< ROBUSTNESS FIX: Safer data parsing from embeds
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
    @commands.has_role(DEV_ROLE_NAME)
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        user_id, mc_username, device = get_app_data_from_embed(interaction.message.embeds[0])
        status, final_username = await add_to_whitelist(mc_username, device)

        if status != "success":
            feedback = "An unknown error occurred."
            if status == "already_exists": feedback = f"User `{final_username}` is already in the whitelist file."
            elif status == "file_not_found": feedback = "ERROR: `whitelist.json` file not found!"
            return await interaction.followup.send(feedback, ephemeral=True)

        if not await reload_whitelist():
            await interaction.followup.send("User added to file, but **failed to reload server via RCON**.", ephemeral=True)

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

        await interaction.followup.send("Application approved. User whitelisted and role assigned.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="review_reject")
    @commands.has_role(DEV_ROLE_NAME)
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
        raise error

# --- RUN BOT ---
bot.run(TOKEN)

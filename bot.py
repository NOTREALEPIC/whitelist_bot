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
RCON_PORT = int(os.getenv("RCON_PORT"))
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


# -----------------------------
# OFFLINE UUID GENERATION FIX
# -----------------------------
def generate_offline_uuid(username: str) -> str:
    """Generates the correct offline-mode UUID for a given username."""
    base = f"OfflinePlayer:{username}"
    md5 = hashlib.md5(base.encode("utf-8")).hexdigest()
    return str(uuid.UUID(md5))


# --- HELPER FUNCTIONS ---
def add_to_whitelist(username: str, device: str):
    """
    Adds a username to whitelist.json
    Includes correct offline UUID generation.
    """
    original_username = username.strip()
    final_username = original_username

    # Bedrock support: prefix "1"
    if "bedrock" in device.lower():
        final_username = f"1{original_username}"

    try:
        with open(WHITELIST_PATH, "r+", encoding="utf-8") as f:
            data = json.load(f)

            # Already exists?
            if any(entry["name"].lower() == final_username.lower() for entry in data):
                return "already_exists", final_username

            # Generate correct offline UUID
            offline_uuid = generate_offline_uuid(final_username)

            data.append({
                "uuid": offline_uuid,
                "name": final_username
            })

            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()

        return "success", final_username

    except FileNotFoundError:
        return "file_not_found", original_username
    except Exception as e:
        print(f"Error writing whitelist: {e}")
        return "write_error", original_username


def reload_whitelist():
    """Reload whitelist via RCON."""
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            resp = mcr.command("whitelist reload")
            print("Reload response:", resp)
            return True
    except Exception as e:
        print("RCON error:", e)
        return False


def get_app_data_from_embed(embed):
    """Extracts application data from review embed."""
    user_id = None
    mc_username = None
    device = "Java"

    for field in embed.fields:
        if field.name == "User":
            user_id = int(field.value.strip("<@!>"))
        elif field.name == "Minecraft Username":
            mc_username = field.value
        elif field.name == "Minecraft Edition":
            device = field.value

    return user_id, mc_username, device


# --- MODALS ---
class WhitelistModal(discord.ui.Modal, title="Minecraft Whitelist Application"):
    mc_username = discord.ui.TextInput(label="Minecraft Username (Case-Sensitive)", placeholder="Steve")
    device = discord.ui.TextInput(label="Minecraft Edition (Java / Bedrock)", placeholder="Java")
    played_before = discord.ui.TextInput(label="Played Minecraft Before? (Yes / No)")
    notes = discord.ui.TextInput(label="Anything you'd like to add?", required=False, style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📝 New Whitelist Application",
            color=EMBED_COLORS["pending"],
            timestamp=discord.utils.utcnow()
        )
        embed.set_author(name=interaction.user, icon_url=interaction.user.avatar.url)
        embed.set_thumbnail(url=interaction.user.avatar.url)

        embed.add_field(name="User", value=interaction.user.mention, inline=False)
        embed.add_field(name="Minecraft Username", value=self.mc_username.value, inline=False)
        embed.add_field(name="Minecraft Edition", value=self.device.value, inline=True)
        embed.add_field(name="Played Before", value=self.played_before.value, inline=True)
        embed.add_field(name="Notes", value=self.notes.value or "N/A", inline=False)
        embed.set_footer(text="Status: Pending Review ⏳", icon_url=SERVER_ICON_URL)

        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        await review_channel.send(embed=embed, view=ReviewView())

        await interaction.response.send_message("Your application has been submitted!", ephemeral=True)


class RejectionModal(discord.ui.Modal, title="Rejection Reason"):
    reason = discord.ui.TextInput(label="Reason for rejection", style=discord.TextStyle.paragraph)

    def __init__(self, original_interaction):
        super().__init__()
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        review_message = self.original_interaction.message
        embed = review_message.embeds[0]

        embed.color = EMBED_COLORS["error"]
        embed.set_footer(text=f"Rejected by {interaction.user.display_name} ❌", icon_url=SERVER_ICON_URL)
        await review_message.edit(embed=embed, view=None)

        user_id, mc_username, _ = get_app_data_from_embed(embed)
        member = await bot.fetch_user(user_id)

        rejected_embed = discord.Embed(
            title="Whitelist Application Rejected",
            color=EMBED_COLORS["error"],
            timestamp=discord.utils.utcnow()
        )
        rejected_embed.set_author(name=member, icon_url=member.avatar.url)
        rejected_embed.add_field(name="User", value=member.mention)
        rejected_embed.add_field(name="Minecraft Username", value=mc_username)
        rejected_embed.add_field(name="Rejected By", value=interaction.user.mention)
        rejected_embed.add_field(name="Reason", value=self.reason.value, inline=False)
        rejected_embed.set_footer(text="Rejection Log", icon_url=SERVER_ICON_URL)

        bot.get_channel(REJECTED_CHANNEL_ID).send(embed=rejected_embed)
        bot.get_channel(LOG_CHANNEL_ID).send(embed=rejected_embed)

        await interaction.response.send_message("Application rejected.", ephemeral=True)


# --- REVIEW BUTTONS ---
class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="review_approve")
    async def approve(self, interaction, button):
        await interaction.response.defer(ephemeral=True)

        user_id, mc_username, device = get_app_data_from_embed(interaction.message.embeds[0])
        status, final_username = add_to_whitelist(mc_username, device)

        if status != "success":
            msg = "Unknown error."
            if status == "already_exists":
                msg = f"`{final_username}` is already whitelisted."
            elif status == "file_not_found":
                msg = "Whitelist file not found!"
            return await interaction.followup.send(msg, ephemeral=True)

        reload_whitelist()

        embed = interaction.message.embeds[0]
        embed.color = EMBED_COLORS["success"]
        embed.set_footer(text=f"Approved by {interaction.user.display_name} ✅", icon_url=SERVER_ICON_URL)
        await interaction.message.edit(embed=embed, view=None)

        guild = interaction.guild
        member = guild.get_member(user_id)
        mc_role = guild.get_role(MC_WHITELISTED_ROLE_ID)

        if member and mc_role:
            await member.add_roles(mc_role)

        approved_embed = discord.Embed(
            title="Whitelist Application Approved",
            color=EMBED_COLORS["success"],
            timestamp=discord.utils.utcnow()
        )
        approved_embed.add_field(name="User", value=member.mention if member else f"ID: {user_id}")
        approved_embed.add_field(name="Minecraft Username", value=f"`{final_username}`")
        approved_embed.add_field(name="Approved By", value=interaction.user.mention)
        approved_embed.set_footer(text="Approval Log", icon_url=SERVER_ICON_URL)

        bot.get_channel(APPROVED_CHANNEL_ID).send(embed=approved_embed)
        bot.get_channel(LOG_CHANNEL_ID).send(embed=approved_embed)

        await interaction.followup.send(f"`{final_username}` has been whitelisted!", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="review_reject")
    async def reject(self, interaction, button):
        await interaction.response.send_modal(RejectionModal(interaction))


class WhitelistView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    @discord.ui.button(label="Request Whitelist", style=discord.ButtonStyle.green, custom_id="persistent_whitelist_button")
    async def whitelist_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("This button is now persistent!", ephemeral=True)


# --- BOT EVENTS ---
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    bot.add_view(WhitelistView())
    bot.add_view(ReviewView())


# --- SETUP COMMAND ---
@bot.tree.command(name="setup", description="Create the whitelist application menu")
async def setup_cmd(interaction):
    dev_role = discord.utils.get(interaction.guild.roles, name=DEV_ROLE_NAME)
    if not dev_role or dev_role not in interaction.user.roles:
        return await interaction.response.send_message("DEV only.", ephemeral=True)

    guild_icon = interaction.guild.icon.url if interaction.guild.icon else SERVER_ICON_URL

    embed = discord.Embed(
        title="Minecraft Server Whitelist",
        description="Click **Apply** to submit your whitelist application.",
        color=EMBED_COLORS["info"]
    )
    embed.set_author(name=interaction.guild.name, icon_url=guild_icon)
    embed.set_footer(text="We look forward to seeing you!", icon_url=SERVER_ICON_URL)

    channel = bot.get_channel(MC_WL_CHANNEL_ID)
    msg = await channel.send(embed=embed, view=WhitelistView())

    with open(SETUP_FILE, "w") as f:
        json.dump({"message_id": msg.id}, f)

    await interaction.response.send_message("Whitelist menu created!", ephemeral=True)


# --- RUN BOT ---
bot.run(TOKEN)

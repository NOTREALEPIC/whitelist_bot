import discord
from discord.ext import commands
import json
import os
import asyncio
from mcrcon import MCRcon
from dotenv import load_dotenv
import time # Used for timestamps

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
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
    "info": discord.Color.from_rgb(255, 193, 7),      # Gold
    "pending": discord.Color.from_rgb(54, 150, 226),  # Blue
    "success": discord.Color.from_rgb(76, 175, 80),   # Green
    "error": discord.Color.from_rgb(244, 67, 54),     # Red
}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# --- RCON & HELPER FUNCTIONS ---
def add_player_via_rcon(username: str, device: str):
    """Adds a player to the server's whitelist using RCON."""
    original_username = username.strip()
    final_username = original_username
    if "bedrock" in device.lower():
        final_username = f"1{original_username}"
    
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            resp = mcr.command(f"whitelist add {final_username}")
            print(f"RCON: whitelist add {final_username} ->", resp)
            if "already whitelisted" in resp.lower(): return "already_whitelisted", final_username
            elif "added" in resp.lower(): return "success", final_username
            else: return "rcon_error", final_username
    except Exception as e:
        print("RCON error:", e)
        return "rcon_error", final_username

def get_app_data_from_embed(embed: discord.Embed):
    """Extracts application data from review embed by field name."""
    user_id, mc_username, device = None, None, "Java"
    for field in embed.fields:
        if "Applicant" in field.name: user_id = int(field.value.split('`')[1])
        elif "Minecraft Username" in field.name: mc_username = field.value
        elif "Edition" in field.name: device = field.value
    return user_id, mc_username, device

# --- MODALS ---
class WhitelistModal(discord.ui.Modal, title="Minecraft Whitelist Application"):
    mc_username = discord.ui.TextInput(label="Minecraft Username (Case-Sensitive)", placeholder="Steve123")
    device = discord.ui.TextInput(label="Edition (Java / Bedrock)", placeholder="Java")
    played_before = discord.ui.TextInput(label="Played Minecraft before? (Yes / No)", placeholder="Yes")
    notes = discord.ui.TextInput(label="Anything you'd like to add?", required=False, style=discord.TextStyle.paragraph, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        mc_role = interaction.guild.get_role(MC_WHITELISTED_ROLE_ID)
        if mc_role and mc_role in interaction.user.roles:
            return await interaction.response.send_message("You are already whitelisted and cannot reapply.", ephemeral=True)

        embed = discord.Embed(title="📝 New Whitelist Application", color=EMBED_COLORS["pending"], timestamp=discord.utils.utcnow())
        embed.set_author(name=interaction.user.display_name, icon_url=interaction.user.display_avatar.url)
        embed.add_field(name="👤 Applicant", value=f"{interaction.user.mention} (`{interaction.user.id}`)", inline=False)
        embed.add_field(name="⛏️ Minecraft Username", value=self.mc_username.value, inline=False)
        embed.add_field(name="🎮 Edition", value=self.device.value, inline=True)
        embed.add_field(name="🗓️ Played Before?", value=self.played_before.value, inline=True)
        if self.notes.value:
            embed.add_field(name="🗒️ Notes", value=self.notes.value, inline=False)
        embed.set_footer(text="Status: Pending Review", icon_url=SERVER_ICON_URL)

        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        await review_channel.send(embed=embed, view=ReviewView())
        await interaction.response.send_message("✅ Your application has been submitted for review!", ephemeral=True)


class RejectionModal(discord.ui.Modal, title="Rejection Reason"):
    reason = discord.ui.TextInput(label="Please provide the reason for rejection.", style=discord.TextStyle.paragraph, min_length=10)

    def __init__(self, original_interaction: discord.Interaction):
        super().__init__()
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        review_message = self.original_interaction.message
        original_embed = review_message.embeds[0]
        original_embed.color = EMBED_COLORS["error"]
        original_embed.set_footer(text=f"Rejected by {interaction.user.display_name}", icon_url=SERVER_ICON_URL)
        original_embed.timestamp = discord.utils.utcnow()
        await review_message.edit(embed=original_embed, view=None)

        user_id, mc_username, _ = get_app_data_from_embed(original_embed)
        member = await bot.fetch_user(user_id)
        
        log_embed = discord.Embed(title="❌ Application Rejected", description=f"{member.mention}'s application was rejected.", color=EMBED_COLORS["error"])
        log_embed.set_thumbnail(url=member.display_avatar.url)
        log_embed.add_field(name="👤 Applicant", value=f"{member.mention} (`{member.id}`)", inline=False)
        log_embed.add_field(name="⛏️ Minecraft Username", value=mc_username, inline=False)
        log_embed.add_field(name="📝 Reason", value=self.reason.value, inline=False)
        log_embed.add_field(name="👨‍⚖️ Rejected By", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="⏰ Timestamp", value=f"<t:{int(time.time())}:F>", inline=True)
        log_embed.set_footer(text=f"{interaction.guild.name} | Whitelist Logs", icon_url=SERVER_ICON_URL)
        
        await bot.get_channel(REJECTED_CHANNEL_ID).send(embed=log_embed)
        await bot.get_channel(LOG_CHANNEL_ID).send(embed=log_embed)
        await interaction.response.send_message("Application has been rejected.", ephemeral=True)


# --- VIEWS ---
class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="review_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True, thinking=True)

        user_id, mc_username, device = get_app_data_from_embed(interaction.message.embeds[0])
        
        # <<< FINAL FIX: Removed the `run_in_executor` to prevent the `signal` error.
        # This RCON command now runs directly in the main thread, which is safe.
        status, final_username = add_player_via_rcon(mc_username, device)

        if status == "rcon_error":
            return await interaction.followup.send("❌ **Error:** Could not connect to the server via RCON.", ephemeral=True)

        embed = interaction.message.embeds[0]
        embed.color = EMBED_COLORS["success"]
        embed.set_footer(text=f"Approved by {interaction.user.display_name}", icon_url=SERVER_ICON_URL)
        embed.timestamp = discord.utils.utcnow()
        await interaction.message.edit(embed=embed, view=None)

        guild = interaction.guild
        member = guild.get_member(user_id)
        mc_role = guild.get_role(MC_WHITELISTED_ROLE_ID)
        if member and mc_role:
            await member.add_roles(mc_role)
        
        applicant = await bot.fetch_user(user_id)
        
        log_embed = discord.Embed(title="✅ Application Approved", description=f"{applicant.mention}'s application has been approved!", color=EMBED_COLORS["success"])
        log_embed.set_thumbnail(url=applicant.display_avatar.url)
        log_embed.add_field(name="👤 Applicant", value=f"{applicant.mention} (`{applicant.id}`)", inline=False)
        log_embed.add_field(name="⛏️ Whitelisted As", value=f"`{final_username}`", inline=False)
        log_embed.add_field(name="👨‍⚖️ Approved By", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="⏰ Timestamp", value=f"<t:{int(time.time())}:F>", inline=True)
        log_embed.set_footer(text=f"{interaction.guild.name} | Whitelist Logs", icon_url=SERVER_ICON_URL)
        
        await bot.get_channel(APPROVED_CHANNEL_ID).send(embed=log_embed)
        await bot.get_channel(LOG_CHANNEL_ID).send(embed=log_embed)
        
        if status == "already_whitelisted":
            await interaction.followup.send(f"✅ Player `{final_username}` is already whitelisted. Role re-synced.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Player `{final_username}` added to the whitelist.", ephemeral=True)


    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="review_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RejectionModal(original_interaction=interaction))


class WhitelistView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Apply for Whitelist", style=discord.ButtonStyle.primary, custom_id="whitelist_apply_button", emoji="📝")
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

@bot.tree.command(name="setup", description="Create the whitelist application embed (Staff only)")
@commands.has_role(DEV_ROLE_NAME)
async def setup_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Server Whitelist Application",
        description=(
            "Ready to join the adventure? Click the **📝 Apply for Whitelist** button below to get started.\n\n"
            "**Please ensure:**\n"
            "• Your Minecraft username is spelled correctly (it's case-sensitive).\n"
            "• You select the correct edition (Java or Bedrock)."
        ),
        color=EMBED_COLORS["info"]
    )
    embed.set_thumbnail(url=SERVER_ICON_URL)
    embed.set_footer(text=f"Welcome to {interaction.guild.name}!", icon_url=SERVER_ICON_URL)

    channel = bot.get_channel(MC_WL_CHANNEL_ID)
    await channel.send(embed=embed, view=WhitelistView())
    await interaction.response.send_message(f"Whitelist embed created in {channel.mention}.", ephemeral=True)

@setup_cmd.error
async def setup_error(interaction: discord.Interaction, error: commands.CommandError):
    if isinstance(error, commands.MissingRole):
        await interaction.response.send_message("You do not have the required role to use this command.", ephemeral=True)
    else:
        print(f"An error occurred in setup_cmd: {error}")
        await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)


# --- RUN BOT ---
bot.run(TOKEN)

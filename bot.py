import discord
from discord.ext import commands, tasks
import json
import os
import asyncio
from mcrcon import MCRcon
from dotenv import load_dotenv
import time 
import re
from itertools import cycle 

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
RCON_HOST = os.getenv("RCON_HOST")
RCON_PORT = int(os.getenv("RCON_PORT", 25575))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

# !!! --- USER CONFIGURATION --- !!!
BOT_DEV_ID = 891355913271771146  

# Server details for the "Connect" buttons
SERVER_IP = "140.245.16.178" 
SERVER_PORT_JAVA = "25565"
SERVER_PORT_BEDROCK = "25565"

# --- BOT & SERVER IDS ---
MC_WL_CHANNEL_ID = 1438763824760225882
REVIEW_CHANNEL_ID = 1438763882154819624
APPROVED_CHANNEL_ID = 1438763962496712764
REJECTED_CHANNEL_ID = 1438764012895735941
LOG_CHANNEL_ID = 1438793262994423838
MC_WHITELISTED_ROLE_ID = 1438789711023046718
DEV_ROLE_NAME = "Staff"

# Files to store data
ADMIN_FILE = "mc_admins.json"
STATUS_FILE = "status_config.json"

# --- AESTHETICS ---
SERVER_ICON_URL = "https://cdn.discordapp.com/icons/1132719558231793744/a_d78d4615a72f0b7c7ed14b301c34a243.gif"
EMBED_COLORS = {
    "info": discord.Color.from_rgb(255, 193, 7),
    "pending": discord.Color.from_rgb(54, 150, 226),
    "success": discord.Color.from_rgb(76, 175, 80),
    "error": discord.Color.from_rgb(244, 67, 54),
    "admin": discord.Color.dark_purple(),
    "live": discord.Color.brand_green(),
    "offline": discord.Color.dark_grey()
}

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Bot Status Cycle
bot_statuses = cycle([
    discord.Activity(type=discord.ActivityType.watching, name="DIVINE HUB"),
    discord.Game(name="DIVINE HUB MC"),
    discord.Game(name="⚽🏆DIVINE EPIC SOCCER🏆⚽"),
    discord.Game(name="🧬⚡Divine vs Senior Non Epic Teams⚡🧬"),
    discord.Game(name="🥊|DIVINE SUPER SMASH|🥊"),
    discord.Game(name="🧬⚡DIVINE VS ISHOWPP EPIC TEAMS⚡🧬"),
    discord.Game(name="Clash of Clans")
])

# --- HELPER FUNCTIONS (JSON & RCON) ---

def load_admins():
    if not os.path.exists(ADMIN_FILE):
        with open(ADMIN_FILE, "w") as f: json.dump([], f)
        return []
    try:
        with open(ADMIN_FILE, "r") as f: return json.load(f)
    except: return []

def save_admins(admin_list):
    with open(ADMIN_FILE, "w") as f: json.dump(admin_list, f)

def is_bot_dev(user_id):
    return user_id == BOT_DEV_ID

def is_mc_admin(user_id):
    admins = load_admins()
    return user_id in admins or is_bot_dev(user_id)

def rcon_command(command):
    """Helper to send raw RCON commands."""
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            resp = mcr.command(command)
            return resp
    except Exception as e:
        print(f"RCON Error ({command}): {e}")
        return None

def add_player_via_rcon(username: str, device: str):
    """Adds a player to the server's whitelist using RCON."""
    original_username = username.strip()
    final_username = original_username
    if "bedrock" in device.lower():
        final_username = f"1{original_username}"
    
    resp = rcon_command(f"whitelist add {final_username}")
    if resp is None: return "rcon_error", final_username
    
    if "already whitelisted" in resp.lower(): return "already_whitelisted", final_username
    elif "added" in resp.lower(): return "success", final_username
    else: return "rcon_error", final_username

def get_app_data_from_embed(embed: discord.Embed):
    user_id, mc_username, device = None, None, "Java"
    for field in embed.fields:
        if "Applicant" in field.name: user_id = int(field.value.split('`')[1])
        elif "Minecraft Username" in field.name: mc_username = field.value
        elif "Edition" in field.name: device = field.value
    return user_id, mc_username, device

# --- 1. ADMIN PANEL MODALS (Kept from your Original Code) ---
class BanModal(discord.ui.Modal, title="🔨 Ban Player"):
    username = discord.ui.TextInput(label="Minecraft Username")
    reason = discord.ui.TextInput(label="Reason", style=discord.TextStyle.paragraph)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        resp = rcon_command(f"ban {self.username.value} {self.reason.value}")
        await interaction.followup.send(f"**Console:** `{resp}`", ephemeral=True)

class UnbanModal(discord.ui.Modal, title="🔓 Unban Player"):
    username = discord.ui.TextInput(label="Minecraft Username")
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        resp = rcon_command(f"pardon {self.username.value}")
        await interaction.followup.send(f"**Console:** `{resp}`", ephemeral=True)

class BroadcastModal(discord.ui.Modal, title="📢 Broadcast Message"):
    message = discord.ui.TextInput(label="Message", style=discord.TextStyle.paragraph)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        rcon_command(f'tellraw @a {{"text":"[Discord] {self.message.value}","color":"aqua"}}')
        await interaction.followup.send(f"📢 Sent: `{self.message.value}`", ephemeral=True)

class KickModal(discord.ui.Modal, title="💀 Kick Player"):
    username = discord.ui.TextInput(label="Minecraft Username")
    reason = discord.ui.TextInput(label="Reason", required=False)
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cmd = f"kick {self.username.value} {self.reason.value}" if self.reason.value else f"kick {self.username.value}"
        resp = rcon_command(cmd)
        await interaction.followup.send(f"**Console:** `{resp}`", ephemeral=True)

# --- 2. WHITELIST MODALS (UPDATED) ---
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
        await interaction.response.defer(ephemeral=True)
        
        # Update original Review Message
        review_message = self.original_interaction.message
        original_embed = review_message.embeds[0]
        original_embed.color = EMBED_COLORS["error"]
        original_embed.set_footer(text=f"Rejected by {interaction.user.display_name}", icon_url=SERVER_ICON_URL)
        original_embed.timestamp = discord.utils.utcnow()
        await review_message.edit(embed=original_embed, view=None)

        # Get Data for Logging
        user_id, mc_username, _ = get_app_data_from_embed(original_embed)
        try:
            member = await bot.fetch_user(user_id)
        except:
            member = None
        
        # Create Fancy Log Embed
        log_embed = discord.Embed(title="❌ Application Rejected", description=f"<@{user_id}>'s application was rejected.", color=EMBED_COLORS["error"])
        if member: log_embed.set_thumbnail(url=member.display_avatar.url)
        log_embed.add_field(name="👤 Applicant", value=f"<@{user_id}> (`{user_id}`)", inline=False)
        log_embed.add_field(name="⛏️ Minecraft Username", value=mc_username, inline=False)
        log_embed.add_field(name="📝 Reason", value=self.reason.value, inline=False)
        log_embed.add_field(name="👨‍⚖️ Rejected By", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="⏰ Timestamp", value=f"<t:{int(time.time())}:F>", inline=True)
        log_embed.set_footer(text=f"{interaction.guild.name} | Whitelist Logs", icon_url=SERVER_ICON_URL)
        
        # Send Logs
        await bot.get_channel(REJECTED_CHANNEL_ID).send(embed=log_embed)
        await bot.get_channel(LOG_CHANNEL_ID).send(embed=log_embed)
        await interaction.followup.send("Application has been rejected.", ephemeral=True)

# --- VIEWS ---

class AdminPanelView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    async def check(self, interaction):
        if not is_mc_admin(interaction.user.id):
            await interaction.response.send_message("❌ **Access Denied.**", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Ban", style=discord.ButtonStyle.danger, emoji="🔨", row=0, custom_id="ap_ban")
    async def ban(self, interaction, button): 
        if await self.check(interaction): await interaction.response.send_modal(BanModal())

    @discord.ui.button(label="Unban", style=discord.ButtonStyle.success, emoji="🔓", row=0, custom_id="ap_unban")
    async def unban(self, interaction, button):
        if await self.check(interaction): await interaction.response.send_modal(UnbanModal())
        
    @discord.ui.button(label="Kick", style=discord.ButtonStyle.secondary, emoji="💀", row=1, custom_id="ap_kick")
    async def kick(self, interaction, button):
        if await self.check(interaction): await interaction.response.send_modal(KickModal())

    @discord.ui.button(label="Broadcast", style=discord.ButtonStyle.primary, emoji="📢", row=1, custom_id="ap_say")
    async def say(self, interaction, button):
        if await self.check(interaction): await interaction.response.send_modal(BroadcastModal())

class ConnectView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    @discord.ui.button(label="Connect (Java)", style=discord.ButtonStyle.blurple, custom_id="conn_java", emoji="☕")
    async def java(self, interaction, button):
        msg = f"**☕ Java Connection:**\nIP: `{SERVER_IP}:{SERVER_PORT_JAVA}`"
        await interaction.response.send_message(msg, ephemeral=True)
        
    @discord.ui.button(label="Connect (Bedrock)", style=discord.ButtonStyle.green, custom_id="conn_bedrock", emoji="📱")
    async def bedrock(self, interaction, button):
        msg = f"**📱 Bedrock Connection:**\nIP: `{SERVER_IP}`\nPort: `{SERVER_PORT_BEDROCK}`"
        await interaction.response.send_message(msg, ephemeral=True)

class ReviewView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    
    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="review_approve")
    async def approve(self, interaction: discord.Interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        user_id, mc_username, device = get_app_data_from_embed(interaction.message.embeds[0])
        status, final_username = add_player_via_rcon(mc_username, device)
        
        if status == "rcon_error": 
            return await interaction.followup.send("❌ **Error:** Could not connect to the server via RCON.", ephemeral=True)
        
        # Update Review Embed
        embed = interaction.message.embeds[0]
        embed.color = EMBED_COLORS["success"]
        embed.set_footer(text=f"Approved by {interaction.user.display_name}", icon_url=SERVER_ICON_URL)
        embed.timestamp = discord.utils.utcnow()
        await interaction.message.edit(embed=embed, view=None)
        
        # Add Role
        guild = interaction.guild
        member = guild.get_member(user_id)
        mc_role = guild.get_role(MC_WHITELISTED_ROLE_ID)
        if member and mc_role: await member.add_roles(mc_role)
        
        try: applicant = await bot.fetch_user(user_id)
        except: applicant = None

        # Create Fancy Log Embed
        log_embed = discord.Embed(title="✅ Application Approved", description=f"<@{user_id}>'s application has been approved!", color=EMBED_COLORS["success"])
        if applicant: log_embed.set_thumbnail(url=applicant.display_avatar.url)
        log_embed.add_field(name="👤 Applicant", value=f"<@{user_id}> (`{user_id}`)", inline=False)
        log_embed.add_field(name="⛏️ Whitelisted As", value=f"`{final_username}`", inline=False)
        log_embed.add_field(name="👨‍⚖️ Approved By", value=interaction.user.mention, inline=True)
        log_embed.add_field(name="⏰ Timestamp", value=f"<t:{int(time.time())}:F>", inline=True)
        log_embed.set_footer(text=f"{interaction.guild.name} | Whitelist Logs", icon_url=SERVER_ICON_URL)
        
        # Send Logs
        await bot.get_channel(APPROVED_CHANNEL_ID).send(embed=log_embed)
        await bot.get_channel(LOG_CHANNEL_ID).send(embed=log_embed)
        
        if status == "already_whitelisted":
            await interaction.followup.send(f"✅ Player `{final_username}` is already whitelisted. Role re-synced.", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Player `{final_username}` added to the whitelist.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="review_reject")
    async def reject(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(RejectionModal(original_interaction=interaction))

class WhitelistView(discord.ui.View):
    def __init__(self): super().__init__(timeout=None)
    @discord.ui.button(label="Apply for Whitelist", style=discord.ButtonStyle.primary, custom_id="whitelist_apply_button", emoji="📝")
    async def apply(self, interaction: discord.Interaction, button):
        await interaction.response.send_modal(WhitelistModal())

# --- TASKS ---

@tasks.loop(seconds=10)
async def change_status():
    await bot.change_presence(activity=next(bot_statuses))

@tasks.loop(seconds=30)
async def update_live_status():
    if not os.path.exists(STATUS_FILE): return
    try:
        with open(STATUS_FILE, "r") as f: data = json.load(f)
        cid, mid = data.get("channel_id"), data.get("message_id")
        if not cid or not mid: return
        
        resp = rcon_command("list")
        
        # Defaults
        online, max_p, players = "0", "0", "No players online."
        is_online = False
        
        if resp:
            is_online = True
            # Regex to parse "There are 5 of 20 players online:..."
            match = re.search(r'(\d+)\s*of\s*(\d+)', resp)
            if match:
                online, max_p = match.groups()
            
            if ":" in resp:
                p_part = resp.split(":", 1)[1].strip()
                if p_part: players = p_part.replace(", ", "\n")
        
        embed = discord.Embed(
            title="🔴 LIVE SERVER STATUS" if is_online else "⚫ SERVER OFFLINE",
            color=EMBED_COLORS["live"] if is_online else EMBED_COLORS["offline"],
            timestamp=discord.utils.utcnow()
        )
        embed.set_thumbnail(url=SERVER_ICON_URL)
        
        if is_online:
            embed.add_field(name="🟢 Status", value="**ONLINE**", inline=True)
            embed.add_field(name="👥 Players", value=f"**{online} / {max_p}**", inline=True)
            embed.add_field(name="📜 Online List", value=f"```{players}```", inline=False)
        else:
            embed.description = "**The server is currently offline or restarting.**"
        
        embed.set_footer(text="Updates every 30 seconds")
        
        chan = bot.get_channel(cid)
        if chan:
            msg = await chan.fetch_message(mid)
            await msg.edit(embed=embed, view=ConnectView())
            
    except Exception as e:
        print(f"Status Loop Error: {e}")

# --- COMMANDS ---

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")
    # Register all persistent views
    bot.add_view(WhitelistView())
    bot.add_view(ReviewView())
    bot.add_view(AdminPanelView())
    bot.add_view(ConnectView())
    
    change_status.start()
    update_live_status.start()
    try: await bot.tree.sync()
    except Exception as e: print(e)

# 1. WHITELIST SETUP (Updated Text)
@bot.tree.command(name="setup", description="Create whitelist embed")
async def setup(interaction: discord.Interaction):
    if not is_bot_dev(interaction.user.id): return await interaction.response.send_message("❌ Bot Dev Only.", ephemeral=True)
    
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
    
    chan = bot.get_channel(MC_WL_CHANNEL_ID)
    await chan.send(embed=embed, view=WhitelistView())
    await interaction.response.send_message(f"✅ Setup Complete in {chan.mention}", ephemeral=True)

# 2. ADD MC ADMIN (Bot Dev Only)
@bot.tree.command(name="add_mc_admin", description="Add user to Admin Panel access")
async def add_mc_admin(interaction: discord.Interaction, user: discord.User):
    if not is_bot_dev(interaction.user.id): return await interaction.response.send_message("❌ Bot Dev Only.", ephemeral=True)
    
    admins = load_admins()
    if user.id not in admins:
        admins.append(user.id)
        save_admins(admins)
        await interaction.response.send_message(f"✅ {user.mention} added to Admin Panel.", ephemeral=True)
    else:
        await interaction.response.send_message("⚠️ Already an admin.", ephemeral=True)

# 3. ADMIN PANEL CHANNEL (Bot Dev Only)
@bot.tree.command(name="setup_admin_panel", description="Create Admin Buttons (Ban/Kick/Say)")
async def setup_admin(interaction: discord.Interaction):
    if not is_bot_dev(interaction.user.id): return await interaction.response.send_message("❌ Bot Dev Only.", ephemeral=True)
    
    embed = discord.Embed(title="🛡️ MC Admin Control", description="Manage the server via RCON.", color=EMBED_COLORS["admin"])
    await interaction.channel.send(embed=embed, view=AdminPanelView())
    await interaction.response.send_message("✅ Admin Panel Created", ephemeral=True)

# 4. LIVE STATUS CHANNEL (Bot Dev Only)
@bot.tree.command(name="setup_status", description="Create Live Status Embed")
async def setup_status(interaction: discord.Interaction):
    if not is_bot_dev(interaction.user.id): return await interaction.response.send_message("❌ Bot Dev Only.", ephemeral=True)
    
    embed = discord.Embed(title="🔴 LIVE STATUS", description="Initializing...", color=EMBED_COLORS["live"])
    msg = await interaction.channel.send(embed=embed, view=ConnectView())
    
    with open(STATUS_FILE, "w") as f:
        json.dump({"channel_id": interaction.channel_id, "message_id": msg.id}, f)
        
    await interaction.response.send_message("✅ Live Status Created", ephemeral=True)

bot.run(TOKEN)

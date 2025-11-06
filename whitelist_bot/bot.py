import discord
from discord.ext import commands
import json
import os
import asyncio
from mcrcon import MCRcon
from dotenv import load_dotenv

# --- CONFIGURATION ---
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
WHITELIST_PATH = os.getenv("WHITELIST_PATH")
RCON_HOST = os.getenv("RCON_HOST")
RCON_PORT = int(os.getenv("RCON_PORT"))
RCON_PASSWORD = os.getenv("RCON_PASSWORD")

# Channel and Role IDs (replace with your actual IDs)
MC_WL_CHANNEL_ID = 1435715105101713448
REVIEW_CHANNEL_ID = 1435715218322882782
APPROVED_CHANNEL_ID = 1435715300761800764
REJECTED_CHANNEL_ID = 1435715381510537268
LOG_CHANNEL_ID = 1435715442856689674
MC_WHITELISTED_ROLE_ID = 1391402495519096933
DEV_ROLE_NAME = "DEV" # Or use a role ID for more reliability

SETUP_FILE = "whitelist_setup.json"

intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True # REQUIRED to fetch members for role assignment
bot = commands.Bot(command_prefix="!", intents=intents)


# --- HELPER FUNCTIONS ---

def add_to_whitelist(username: str):
    """Adds a username to the whitelist.json file."""
    try:
        with open(WHITELIST_PATH, "r+", encoding="utf-8") as f:
            data = json.load(f)
            # Check if user is already in the list (case-insensitive)
            if any(entry["name"].lower() == username.lower() for entry in data):
                print(f"User '{username}' is already in the whitelist file.")
                return "already_exists"
            
            data.append({"uuid": "00000000-0000-0000-0000-000000000000", "name": username})
            f.seek(0)
            json.dump(data, f, indent=2)
            f.truncate()
        return "success"
    except FileNotFoundError:
        print(f"ERROR: Whitelist file not found at {WHITELIST_PATH}")
        return "file_not_found"
    except Exception as e:
        print(f"ERROR: Failed to write to whitelist file: {e}")
        return "write_error"

def reload_whitelist():
    """Sends 'whitelist reload' command via RCON."""
    try:
        with MCRcon(RCON_HOST, RCON_PASSWORD, port=RCON_PORT) as mcr:
            resp = mcr.command("whitelist reload")
            print(f"RCON: whitelist reload -> {resp}")
            return True
    except Exception as e:
        print(f"ERROR: RCON reload failed: {e}")
        return False

# NEW: Helper to parse the embed and get application data
def get_app_data_from_embed(embed: discord.Embed):
    """Parses the review embed to get user_id and mc_username."""
    user_id = int(embed.fields[0].value.strip("<@!>"))
    mc_username = embed.fields[1].value
    return user_id, mc_username

# --- MODALS ---

class WhitelistModal(discord.ui.Modal, title="Minecraft Whitelist Application"):
    mc_username = discord.ui.TextInput(label="Minecraft Username", placeholder="Steve123")
    device = discord.ui.TextInput(label="Device (Java / Bedrock)")
    played_before = discord.ui.TextInput(label="Played Minecraft before? (Yes / No)")
    notes = discord.ui.TextInput(label="Anything you'd like to add?", required=False, style=discord.TextStyle.paragraph)

    async def on_submit(self, interaction: discord.Interaction):
        mc_role = interaction.guild.get_role(MC_WHITELISTED_ROLE_ID)
        if mc_role in interaction.user.roles:
            await interaction.response.send_message("You are already whitelisted and cannot reapply.", ephemeral=True)
            return

        # Create the review embed
        embed = discord.Embed(title="Whitelist Request", color=discord.Color.blurple())
        embed.add_field(name="User", value=interaction.user.mention, inline=False)
        embed.add_field(name="Minecraft Username", value=self.mc_username.value, inline=False)
        embed.add_field(name="Device", value=self.device.value, inline=True)
        embed.add_field(name="Played Before", value=self.played_before.value, inline=True)
        embed.add_field(name="Notes", value=self.notes.value or "N/A", inline=False)
        embed.set_footer(text="Status: Pending")

        review_channel = bot.get_channel(REVIEW_CHANNEL_ID)
        await review_channel.send(embed=embed, view=ReviewView())

        await interaction.response.send_message("Your whitelist application has been submitted for review.", ephemeral=True)

# NEW: Modal for rejection reason
class RejectionModal(discord.ui.Modal, title="Rejection Reason"):
    reason = discord.ui.TextInput(label="Please provide the reason for rejection.", style=discord.TextStyle.paragraph)

    def __init__(self, original_interaction: discord.Interaction):
        super().__init__()
        self.original_interaction = original_interaction

    async def on_submit(self, interaction: discord.Interaction):
        # We now have the reason, proceed with the rejection logic
        review_message = self.original_interaction.message
        
        # 1. Update the original review embed to "Rejected"
        original_embed = review_message.embeds[0]
        original_embed.color = discord.Color.red()
        original_embed.set_footer(text=f"Rejected by {interaction.user.display_name}")
        await review_message.edit(embed=original_embed, view=None) # Remove buttons

        # 2. Get application data from the embed
        user_id, mc_username = get_app_data_from_embed(original_embed)
        member = await bot.fetch_user(user_id) # Fetch user for mentioning

        # 3. Log to rejected and log channels
        rejected_channel = bot.get_channel(REJECTED_CHANNEL_ID)
        log_channel = bot.get_channel(LOG_CHANNEL_ID)

        embed = discord.Embed(title="Whitelist Rejected", color=discord.Color.red())
        embed.add_field(name="User", value=member.mention)
        embed.add_field(name="Minecraft Username", value=mc_username)
        embed.add_field(name="Rejected By", value=interaction.user.mention)
        embed.add_field(name="Reason", value=self.reason.value, inline=False)
        
        await rejected_channel.send(embed=embed)
        await log_channel.send(f"❌ {interaction.user.mention} rejected {member.mention} (`{mc_username}`). Reason: {self.reason.value}")

        # 4. Inform the admin
        await interaction.response.send_message("Application has been rejected.", ephemeral=True)


# --- VIEWS ---

# FIXED: This view is now stateless and persistent
class ReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent view

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        # Simple permission check for all buttons in this view
        if not interaction.user.guild_permissions.manage_guild:
            await interaction.response.send_message("You do not have permission to manage whitelist requests.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, custom_id="review_approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True) # Defer to prevent timeout

        # Get application data from the embed
        user_id, mc_username = get_app_data_from_embed(interaction.message.embeds[0])
        
        # Add to whitelist.json
        result = add_to_whitelist(mc_username)
        if result != "success":
            feedback = "An error occurred."
            if result == "already_exists":
                feedback = f"User `{mc_username}` is already in the whitelist file. No action was taken."
            elif result == "file_not_found":
                feedback = "ERROR: `whitelist.json` file not found. Please check server config."
            return await interaction.followup.send(feedback, ephemeral=True)

        # Reload server whitelist
        if not reload_whitelist():
            await interaction.followup.send("User added to `whitelist.json`, but **failed to reload the server via RCON**. Please reload it manually.", ephemeral=True)
            # We continue anyway to give role etc.
        
        # Update the review embed
        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.set_footer(text=f"Approved by {interaction.user.display_name}")
        await interaction.message.edit(embed=embed, view=None) # Remove buttons

        # FIXED: Get member object to assign role
        guild = interaction.guild
        member = guild.get_member(user_id)
        mc_role = guild.get_role(MC_WHITELISTED_ROLE_ID)

        if member and mc_role:
            try:
                await member.add_roles(mc_role)
            except discord.Forbidden:
                 await interaction.followup.send("Approved, but I lack permissions to assign the role.", ephemeral=True)
                 return
        elif not member:
            await interaction.followup.send(f"Approved, but the user (`{user_id}`) is no longer in the server so I could not assign the role.", ephemeral=True)
            return

        # Send logs
        approved_channel = bot.get_channel(APPROVED_CHANNEL_ID)
        log_channel = bot.get_channel(LOG_CHANNEL_ID)

        log_embed = discord.Embed(title="Whitelist Approved", color=discord.Color.green())
        log_embed.add_field(name="Discord User", value=member.mention)
        log_embed.add_field(name="Minecraft Username", value=mc_username)
        log_embed.add_field(name="Approved By", value=interaction.user.mention)
        await approved_channel.send(embed=log_embed)
        await log_channel.send(f"✅ {interaction.user.mention} approved {member.mention} (`{mc_username}`).")

        await interaction.followup.send("Application approved. User has been whitelisted and given the role.", ephemeral=True)

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, custom_id="review_reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        # NEW: Show the rejection modal instead of waiting for a message
        await interaction.response.send_modal(RejectionModal(original_interaction=interaction))

# FIXED: This view is now persistent
class WhitelistView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None) # Persistent view

    @discord.ui.button(label="Apply for Whitelist", style=discord.ButtonStyle.green, custom_id="whitelist_apply_button")
    async def apply(self, interaction: discord.Interaction, button: discord.ui.Button):
        mc_role = interaction.guild.get_role(MC_WHITELISTED_ROLE_ID)
        if mc_role in interaction.user.roles:
            await interaction.response.send_message("You are already whitelisted and cannot reapply.", ephemeral=True)
            return

        await interaction.response.send_modal(WhitelistModal())

# --- BOT EVENTS & COMMANDS ---

@bot.event
async def on_ready():
    print(f"Bot connected as {bot.user}")
    
    # FIXED: Register persistent views so they work after a restart
    bot.add_view(WhitelistView())
    bot.add_view(ReviewView())
    
    print("Persistent views registered.")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash command(s).")
    except Exception as e:
        print(f"Failed to sync slash commands: {e}")

@bot.tree.command(name="setup", description="Create or update the whitelist application embed (DEV only)")
async def setup_cmd(interaction: discord.Interaction):
    # Check for role by name. Using ID is more reliable if the name changes.
    dev_role = discord.utils.get(interaction.guild.roles, name=DEV_ROLE_NAME)
    if not dev_role or dev_role not in interaction.user.roles:
        return await interaction.response.send_message("Only members with the DEV role can use this command.", ephemeral=True)

    embed = discord.Embed(
        title="Minecraft Whitelist Application",
        description="Click the button below to open the application form. \n\nPlease make sure your Minecraft username is correct, as it is case-sensitive.",
        color=discord.Color.gold()
    )
    channel = bot.get_channel(MC_WL_CHANNEL_ID)
    view = WhitelistView()

    # Try to find and edit an existing message to prevent clutter
    message_id = None
    if os.path.exists(SETUP_FILE):
        with open(SETUP_FILE, "r") as f:
            data = json.load(f)
            message_id = data.get("message_id")

    if message_id:
        try:
            msg = await channel.fetch_message(message_id)
            await msg.edit(embed=embed, view=view)
            await interaction.response.send_message("Successfully updated the existing whitelist embed.", ephemeral=True)
            return
        except discord.NotFound:
            print("Old setup message not found, will create a new one.")
        except discord.Forbidden:
            await interaction.response.send_message("I don't have permissions to edit the old message in that channel.", ephemeral=True)
            return


    # If no message ID or old message not found, send a new one
    msg = await channel.send(embed=embed, view=view)
    with open(SETUP_FILE, "w") as f:
        json.dump({"message_id": msg.id}, f)

    await interaction.response.send_message(f"New whitelist embed created in {channel.mention} and its ID has been saved.", ephemeral=True)

# --- RUN BOT ---
bot.run(TOKEN)
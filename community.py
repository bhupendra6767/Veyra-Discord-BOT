import discord
from discord import app_commands
import datetime
import asyncio
from typing import Optional, Dict, Any

from database import db
from logger import get_logger
from embeds import VeyraEmbed
from premium import premium_welcome, premium_goodbye, premium_announcement
from permissions import has_veyra_level, PermissionLevel
from commands import safe_reply
from setup_system import get_server_layout
from tasks import task_manager

log = get_logger("COMMUNITY")

# --- Persistent Configuration UI ---

class AutomationConfigView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Toggle Welcome", style=discord.ButtonStyle.primary, custom_id="veyra:auto_toggle_welcome", emoji="👋")
    async def toggle_welcome(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_feature(interaction, "welcome_enabled")

    @discord.ui.button(label="Toggle Leave", style=discord.ButtonStyle.primary, custom_id="veyra:auto_toggle_leave", emoji="🚪")
    async def toggle_leave(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._toggle_feature(interaction, "leave_enabled")
        
    @discord.ui.button(label="Refresh Status", style=discord.ButtonStyle.secondary, custom_id="veyra:auto_refresh_status", emoji="🔄")
    async def refresh_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._check_perms(interaction): return
        embed = await build_automation_status_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=self)

    async def _check_perms(self, interaction: discord.Interaction) -> bool:
        if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
            await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to configure automation."), ephemeral=True)
            return False
        return True

    async def _toggle_feature(self, interaction: discord.Interaction, feature_key: str):
        if not await self._check_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        current = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = ?", (interaction.guild.id, feature_key))
        new_val = "0" if current == "1" else "1"
        await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (interaction.guild.id, feature_key, new_val))
        
        embed = await build_automation_status_embed(interaction.guild)
        await interaction.message.edit(embed=embed, view=self)
        await interaction.followup.send(embed=VeyraEmbed.success("Toggled", f"{feature_key.replace('_', ' ').title()} is now {'Enabled' if new_val == '1' else 'Disabled'}."), ephemeral=True)


async def build_automation_status_embed(guild: discord.Guild) -> discord.Embed:
    welcome_enabled = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'welcome_enabled'", (guild.id,))
    leave_enabled = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'leave_enabled'", (guild.id,))
    welcome_channel_id = await get_server_layout(guild.id, "channel", "📌・welcome")
    leave_channel_id = await get_server_layout(guild.id, "channel", "👋・goodbye")
    
    welcome_ch = guild.get_channel(welcome_channel_id) if welcome_channel_id else None
    leave_ch = guild.get_channel(leave_channel_id) if leave_channel_id else None

    embed = VeyraEmbed.info("Automation Status", "Premium Community Automation overview.")
    
    # Welcome Status
    w_status = "🟢 Enabled" if welcome_enabled == "1" else "🔴 Disabled"
    w_ch_str = welcome_ch.mention if welcome_ch else "⚠️ Missing Channel (`/auto repair`)"
    embed.add_field(name="Welcome Automation", value=f"**Status:** {w_status}\n**Channel:** {w_ch_str}", inline=True)
    
    # Leave Status
    l_status = "🟢 Enabled" if leave_enabled == "1" else "🔴 Disabled"
    l_ch_str = leave_ch.mention if leave_ch else "⚠️ Missing Channel (`/auto repair`)"
    embed.add_field(name="Leave Automation", value=f"**Status:** {l_status}\n**Channel:** {l_ch_str}", inline=True)
    
    # Scheduled Announcements
    jobs = await db.fetch_all("SELECT name, next_run FROM automation_jobs WHERE guild_id = ? AND enabled = 1", (guild.id,))
    if jobs:
        jobs_str = ""
        for j in jobs:
            next_run_str = f"<t:{int(datetime.datetime.fromisoformat(j['next_run']).timestamp())}:R>" if j['next_run'] else "Pending"
            jobs_str += f"• **{j['name']}** (Next: {next_run_str})\n"
        embed.add_field(name="Active Announcements", value=jobs_str, inline=False)
    else:
        embed.add_field(name="Active Announcements", value="No active scheduled announcements.", inline=False)
        
    return embed

# --- Event Handlers ---

async def on_member_join(member: discord.Member):
    if member.bot: return
    
    # Track lifecycle
    now = datetime.datetime.now(datetime.timezone.utc)
    await db.execute(
        "INSERT INTO member_lifecycle (guild_id, user_id, joined_at) VALUES (?, ?, ?) ON CONFLICT(guild_id, user_id) DO UPDATE SET joined_at = ?, left_at = NULL",
        (member.guild.id, member.id, now, now)
    )
    
    enabled = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'welcome_enabled'", (member.guild.id,))
    if enabled != "1":
        return
        
    channel_id = await get_server_layout(member.guild.id, "channel", "📌・welcome")
    if not channel_id:
        return
        
    channel = member.guild.get_channel(channel_id)
    if not channel:
        return
        
    # Get custom message or use default
    custom_msg = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'welcome_message'", (member.guild.id,))
    custom_title = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'welcome_title'", (member.guild.id,))
    
    embed = premium_welcome(member, custom_title, custom_msg)
    
    try:
        await channel.send(content=member.mention, embed=embed)
    except discord.Forbidden:
        log.warning(f"Missing permissions to send welcome message in {channel.id}")
    except Exception as e:
        log.error(f"Error sending welcome message in {channel.id}: {e}")

async def on_member_remove(member: discord.Member):
    if member.bot: return
    
    # Track lifecycle
    now = datetime.datetime.now(datetime.timezone.utc)
    await db.execute(
        "UPDATE member_lifecycle SET left_at = ? WHERE guild_id = ? AND user_id = ?",
        (now, member.guild.id, member.id)
    )
    
    enabled = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'leave_enabled'", (member.guild.id,))
    if enabled != "1":
        return
        
    channel_id = await get_server_layout(member.guild.id, "channel", "👋・goodbye")
    if not channel_id:
        return
        
    channel = member.guild.get_channel(channel_id)
    if not channel:
        return
        
    custom_msg = await db.fetch_val("SELECT value FROM guild_config WHERE guild_id = ? AND key = 'leave_message'", (member.guild.id,))
    
    embed = premium_goodbye(member, custom_msg)
    
    try:
        await channel.send(embed=embed)
    except discord.Forbidden:
        log.warning(f"Missing permissions to send leave message in {channel.id}")
    except Exception as e:
        log.error(f"Error sending leave message in {channel.id}: {e}")

# --- Background Task: Announcements ---

async def announcement_scheduler_task(client: discord.Client):
    log.info("Announcement scheduler task started.")
    while True:
        try:
            now = datetime.datetime.now(datetime.timezone.utc)
            now_iso = now.isoformat()
            
            # Find jobs that need to run
            jobs = await db.fetch_all("SELECT guild_id, job_id, name, interval_seconds, payload FROM automation_jobs WHERE enabled = 1 AND (next_run IS NULL OR next_run <= ?)", (now_iso,))
            
            for job in jobs:
                # Basic claiming mechanism
                execution_id = f"{job['job_id']}-{int(now.timestamp())}"
                
                # Check if we already executed recently (to avoid duplicates due to rapid loops)
                # But we just use next_run update to prevent duplicate.
                # Update next_run immediately to claim it
                next_run = now + datetime.timedelta(seconds=job["interval_seconds"])
                rowcount = await db.execute(
                    "UPDATE automation_jobs SET next_run = ?, last_run = ? WHERE job_id = ? AND (next_run IS NULL OR next_run <= ?)",
                    (next_run.isoformat(), now_iso, job["job_id"], now_iso)
                )
                
                if rowcount == 0:
                    continue # Someone else claimed it or it was updated
                    
                guild = client.get_guild(job["guild_id"])
                if not guild:
                    continue
                    
                # We assume payload contains channel_id and message
                import json
                try:
                    payload = json.loads(job["payload"] or "{}")
                    channel_id = payload.get("channel_id")
                    message = payload.get("message")
                    
                    if channel_id and message:
                        channel = guild.get_channel(channel_id)
                        if channel:
                            embed = premium_announcement(guild, job['name'], message)
                            await channel.send(embed=embed)
                            
                            # Record execution
                            await db.execute(
                                "INSERT INTO automation_executions (guild_id, job_id, execution_id, timestamp, status, details) VALUES (?, ?, ?, ?, ?, ?)",
                                (guild.id, job["job_id"], execution_id, now.isoformat(), "success", "Message sent")
                            )
                            await db.execute("UPDATE automation_jobs SET failure_count = 0 WHERE job_id = ?", (job["job_id"],))
                except discord.Forbidden:
                    log.warning(f"Forbidden to send announcement in {channel_id}")
                    await db.execute(
                        "INSERT INTO automation_executions (guild_id, job_id, execution_id, timestamp, status, details) VALUES (?, ?, ?, ?, ?, ?)",
                        (guild.id, job["job_id"], execution_id, now.isoformat(), "failed", "Forbidden")
                    )
                    await db.execute("UPDATE automation_jobs SET failure_count = failure_count + 1 WHERE job_id = ?", (job["job_id"],))
                except Exception as e:
                    log.error(f"Error executing announcement job {job['job_id']}: {e}")
                    await db.execute(
                        "INSERT INTO automation_executions (guild_id, job_id, execution_id, timestamp, status, details) VALUES (?, ?, ?, ?, ?, ?)",
                        (guild.id, job["job_id"], execution_id, now.isoformat(), "failed", str(e))
                    )
                    await db.execute("UPDATE automation_jobs SET failure_count = failure_count + 1 WHERE job_id = ?", (job["job_id"],))
                    
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Error in announcement scheduler: {e}")
            
        await asyncio.sleep(60) # Run every minute

def start_automation_scheduler(client: discord.Client):
    task_manager.register("announcement_scheduler", announcement_scheduler_task, client)

# --- Commands ---

class AutomationGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="automation", description="Community Automation System")

    async def _check_perms(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await safe_reply(interaction, VeyraEmbed.error("Guild Only", "This command can only be used in a server."), ephemeral=True)
            return False
        if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
            await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to configure automation."), ephemeral=True)
            return False
        return True

    @app_commands.command(name="status", description="Show the automation status panel")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        if not await self._check_perms(interaction): return
        
        await interaction.response.defer(ephemeral=False)
        embed = await build_automation_status_embed(interaction.guild)
        await interaction.followup.send(embed=embed, view=AutomationConfigView())

    @app_commands.command(name="welcome", description="Configure the welcome message")
    @app_commands.default_permissions(manage_guild=True)
    async def welcome(self, interaction: discord.Interaction, title: Optional[str] = None, message: Optional[str] = None):
        if not await self._check_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        if title:
            await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (interaction.guild.id, "welcome_title", title))
        if message:
            await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (interaction.guild.id, "welcome_message", message))
            
        await interaction.followup.send(embed=VeyraEmbed.success("Welcome Configured", "Welcome message configuration saved."), ephemeral=True)

    @app_commands.command(name="leave", description="Configure the leave message")
    @app_commands.default_permissions(manage_guild=True)
    async def leave(self, interaction: discord.Interaction, message: Optional[str] = None):
        if not await self._check_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        if message:
            await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (interaction.guild.id, "leave_message", message))
            
        await interaction.followup.send(embed=VeyraEmbed.success("Leave Configured", "Leave message configuration saved."), ephemeral=True)

    @app_commands.command(name="announcement", description="Schedule a new repeating announcement")
    @app_commands.default_permissions(manage_guild=True)
    async def announcement(self, interaction: discord.Interaction, name: str, channel: discord.TextChannel, interval_hours: int, message: str):
        if not await self._check_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        
        if interval_hours < 1:
            return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Interval must be at least 1 hour."), ephemeral=True)
            
        import uuid
        import json
        job_id = f"ann_{uuid.uuid4().hex[:8]}"
        payload = json.dumps({"channel_id": channel.id, "message": message})
        interval_seconds = interval_hours * 3600
        
        await db.execute(
            "INSERT INTO automation_jobs (guild_id, job_id, name, interval_seconds, payload, enabled) VALUES (?, ?, ?, ?, ?, 1)",
            (interaction.guild.id, job_id, name, interval_seconds, payload)
        )
        
        await interaction.followup.send(embed=VeyraEmbed.success("Announcement Scheduled", f"Scheduled **{name}** in {channel.mention} every {interval_hours} hours."), ephemeral=True)

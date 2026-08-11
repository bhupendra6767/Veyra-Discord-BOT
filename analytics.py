import discord
from discord import app_commands
import datetime
from typing import Optional

from embeds import VeyraEmbed
from database import db
from permissions import has_veyra_level, PermissionLevel
from commands import safe_reply
from health import health_system
from services import registry
import logger

log = logger.get_logger("ANALYTICS")

async def _check_analytics_perms(interaction: discord.Interaction) -> bool:
    if not interaction.guild:
        await safe_reply(interaction, VeyraEmbed.error("Error", "This command must be run in a server."), ephemeral=True)
        return False
    if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
        await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to view analytics."), ephemeral=True)
        return False
    return True

def _get_time_delta(period: str) -> datetime.timedelta:
    if period == "24h":
        return datetime.timedelta(days=1)
    elif period == "7d":
        return datetime.timedelta(days=7)
    elif period == "30d":
        return datetime.timedelta(days=30)
    return datetime.timedelta(days=7) # Default

class AnalyticsNavigationView(discord.ui.View):
    def __init__(self, current_view: str = "overview"):
        super().__init__(timeout=None)
        
        # Overview button
        btn_overview = discord.ui.Button(label="Overview", style=discord.ButtonStyle.primary if current_view == "overview" else discord.ButtonStyle.secondary, custom_id="veyra:analytics:overview")
        btn_overview.callback = self.on_overview
        self.add_item(btn_overview)
        
        # Members button
        btn_members = discord.ui.Button(label="Members", style=discord.ButtonStyle.primary if current_view == "members" else discord.ButtonStyle.secondary, custom_id="veyra:analytics:members")
        btn_members.callback = self.on_members
        self.add_item(btn_members)
        
        # Activity button
        btn_activity = discord.ui.Button(label="Activity", style=discord.ButtonStyle.primary if current_view == "activity" else discord.ButtonStyle.secondary, custom_id="veyra:analytics:activity")
        btn_activity.callback = self.on_activity
        self.add_item(btn_activity)
        
        # Tickets button
        btn_tickets = discord.ui.Button(label="Tickets", style=discord.ButtonStyle.primary if current_view == "tickets" else discord.ButtonStyle.secondary, custom_id="veyra:analytics:tickets")
        btn_tickets.callback = self.on_tickets
        self.add_item(btn_tickets)
        
        # Automation button
        btn_auto = discord.ui.Button(label="Automation", style=discord.ButtonStyle.primary if current_view == "automation" else discord.ButtonStyle.secondary, custom_id="veyra:analytics:automation")
        btn_auto.callback = self.on_auto
        self.add_item(btn_auto)

        # Health button
        btn_health = discord.ui.Button(label="Health", style=discord.ButtonStyle.primary if current_view == "health" else discord.ButtonStyle.secondary, custom_id="veyra:analytics:health")
        btn_health.callback = self.on_health
        self.add_item(btn_health)

    async def on_overview(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        embed = await build_overview_embed(interaction.guild, "7d")
        await interaction.response.edit_message(embed=embed, view=AnalyticsNavigationView("overview"))

    async def on_members(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        embed = await build_members_embed(interaction.guild, "7d")
        await interaction.response.edit_message(embed=embed, view=AnalyticsNavigationView("members"))

    async def on_activity(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        embed = await build_activity_embed(interaction.guild, "7d")
        await interaction.response.edit_message(embed=embed, view=AnalyticsNavigationView("activity"))

    async def on_tickets(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        embed = await build_tickets_embed(interaction.guild, "7d")
        await interaction.response.edit_message(embed=embed, view=AnalyticsNavigationView("tickets"))

    async def on_auto(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        embed = await build_automation_embed(interaction.guild, "7d")
        await interaction.response.edit_message(embed=embed, view=AnalyticsNavigationView("automation"))
        
    async def on_health(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        embed = await build_health_embed(interaction.guild)
        await interaction.response.edit_message(embed=embed, view=AnalyticsNavigationView("health"))


# Embed builders
async def build_overview_embed(guild: discord.Guild, period: str) -> discord.Embed:
    delta = _get_time_delta(period)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - delta).isoformat()
    
    # Member Stats
    joins = await db.fetch_val("SELECT COUNT(*) FROM member_lifecycle WHERE guild_id = ? AND joined_at >= ?", (guild.id, cutoff)) or 0
    leaves = await db.fetch_val("SELECT COUNT(*) FROM member_lifecycle WHERE guild_id = ? AND left_at >= ?", (guild.id, cutoff)) or 0
    net_growth = joins - leaves
    
    verifications = await db.fetch_val("SELECT COUNT(*) FROM analytics_events WHERE guild_id = ? AND event_type = 'member_verify' AND timestamp >= ?", (guild.id, cutoff)) or 0
    
    # Ticket Stats
    tickets_opened = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND created_at >= ?", (guild.id, cutoff)) or 0
    tickets_closed = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND closed_at >= ?", (guild.id, cutoff)) or 0
    open_tickets = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status != 'closed'", (guild.id,)) or 0
    
    # Automation Stats
    auto_success = await db.fetch_val("SELECT COUNT(*) FROM automation_executions WHERE guild_id = ? AND status = 'success' AND timestamp >= ?", (guild.id, cutoff)) or 0
    auto_failed = await db.fetch_val("SELECT COUNT(*) FROM automation_executions WHERE guild_id = ? AND status = 'failed' AND timestamp >= ?", (guild.id, cutoff)) or 0
    
    # Activity Stats
    command_usage = await db.fetch_val("SELECT COUNT(*) FROM analytics_events WHERE guild_id = ? AND event_type LIKE 'command_%' AND timestamp >= ?", (guild.id, cutoff)) or 0

    embed = VeyraEmbed.info("Community Overview", f"System metrics over the past {period}.")
    embed.add_field(name="👥 Community", value=f"**Joins:** {joins}\n**Leaves:** {leaves}\n**Net Growth:** {net_growth:+d}\n**Verifications:** {verifications}", inline=True)
    embed.add_field(name="📩 Support", value=f"**Tickets Opened:** {tickets_opened}\n**Tickets Closed:** {tickets_closed}\n**Currently Open:** {open_tickets}", inline=True)
    embed.add_field(name="⚙️ Automation", value=f"**Successful Jobs:** {auto_success}\n**Failed Jobs:** {auto_failed}\n**Command Usage:** {command_usage}", inline=True)
    
    # Health Score
    health_score = 100
    if auto_failed > 0:
        health_score -= min(20, int((auto_failed / (auto_success + auto_failed)) * 100))
    if leaves > joins and joins > 0:
        health_score -= 10
    if tickets_opened > 0 and tickets_closed == 0:
        health_score -= 5

    health_score = max(0, min(100, health_score))
    health_indicator = "🟢" if health_score >= 80 else "🟡" if health_score >= 50 else "🔴"
    
    embed.add_field(name="❤️ Community Health", value=f"{health_indicator} **{health_score}/100** — {'Excellent' if health_score >= 80 else 'Fair' if health_score >= 50 else 'Needs Attention'}", inline=False)
    
    return embed

async def build_members_embed(guild: discord.Guild, period: str) -> discord.Embed:
    delta = _get_time_delta(period)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - delta).isoformat()
    past_cutoff = (datetime.datetime.now(datetime.timezone.utc) - (delta * 2)).isoformat()
    
    joins = await db.fetch_val("SELECT COUNT(*) FROM member_lifecycle WHERE guild_id = ? AND joined_at >= ?", (guild.id, cutoff)) or 0
    past_joins = await db.fetch_val("SELECT COUNT(*) FROM member_lifecycle WHERE guild_id = ? AND joined_at >= ? AND joined_at < ?", (guild.id, past_cutoff, cutoff)) or 0
    
    leaves = await db.fetch_val("SELECT COUNT(*) FROM member_lifecycle WHERE guild_id = ? AND left_at >= ?", (guild.id, cutoff)) or 0
    
    verifications = await db.fetch_val("SELECT COUNT(*) FROM analytics_events WHERE guild_id = ? AND event_type = 'member_verify' AND timestamp >= ?", (guild.id, cutoff)) or 0
    
    net = joins - leaves
    trend = "📈" if joins > past_joins else "📉" if joins < past_joins else "➡️"
    
    embed = VeyraEmbed.info("Member Insights", f"Community growth metrics over the past {period}.")
    embed.add_field(name="Growth Statistics", value=f"**New Members:** {joins} {trend}\n**Departures:** {leaves}\n**Net Growth:** {net:+d}", inline=True)
    
    conversion = f"{(verifications / joins * 100):.1f}%" if joins > 0 else "N/A"
    embed.add_field(name="Verification", value=f"**Verified:** {verifications}\n**Conversion Rate:** {conversion}", inline=True)
    return embed

async def build_activity_embed(guild: discord.Guild, period: str) -> discord.Embed:
    delta = _get_time_delta(period)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - delta).isoformat()
    
    cmd_usage = await db.fetch_all("SELECT event_type, COUNT(*) as count FROM analytics_events WHERE guild_id = ? AND event_type LIKE 'command_%' AND timestamp >= ? GROUP BY event_type ORDER BY count DESC LIMIT 5", (guild.id, cutoff))
    
    top_cmds = "\n".join([f"`/{row['event_type'].replace('command_', '')}`: {row['count']} uses" for row in cmd_usage]) if cmd_usage else "No commands used."
    total_cmds = sum(row['count'] for row in cmd_usage) if cmd_usage else 0
    
    embed = VeyraEmbed.info("Activity Insights", f"Community engagement over the past {period}.")
    embed.add_field(name="Command Usage", value=f"**Total Executions:** {total_cmds}\n\n**Top Commands:**\n{top_cmds}", inline=False)
    return embed

async def build_tickets_embed(guild: discord.Guild, period: str) -> discord.Embed:
    delta = _get_time_delta(period)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - delta).isoformat()
    
    opened = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND created_at >= ?", (guild.id, cutoff)) or 0
    closed = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND closed_at >= ?", (guild.id, cutoff)) or 0
    active = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status != 'closed'", (guild.id,)) or 0
    
    closure_rate = f"{(closed / opened * 100):.1f}%" if opened > 0 else "N/A"
    
    embed = VeyraEmbed.info("Support Insights", f"Ticket metrics over the past {period}.")
    embed.add_field(name="Volume", value=f"**Tickets Opened:** {opened}\n**Tickets Closed:** {closed}\n**Currently Active:** {active}", inline=True)
    embed.add_field(name="Performance", value=f"**Closure Rate:** {closure_rate}", inline=True)
    return embed

async def build_automation_embed(guild: discord.Guild, period: str) -> discord.Embed:
    delta = _get_time_delta(period)
    cutoff = (datetime.datetime.now(datetime.timezone.utc) - delta).isoformat()
    
    success = await db.fetch_val("SELECT COUNT(*) FROM automation_executions WHERE guild_id = ? AND status = 'success' AND timestamp >= ?", (guild.id, cutoff)) or 0
    failed = await db.fetch_val("SELECT COUNT(*) FROM automation_executions WHERE guild_id = ? AND status = 'failed' AND timestamp >= ?", (guild.id, cutoff)) or 0
    total = success + failed
    
    failure_rate = f"{(failed / total * 100):.1f}%" if total > 0 else "0.0%"
    
    jobs_count = await db.fetch_val("SELECT COUNT(*) FROM automation_jobs WHERE guild_id = ? AND enabled = 1", (guild.id,)) or 0
    
    embed = VeyraEmbed.info("Automation Insights", f"Background processing over the past {period}.")
    embed.add_field(name="Execution Stats", value=f"**Total Runs:** {total}\n**Successful:** {success}\n**Failed:** {failed}\n**Failure Rate:** {failure_rate}", inline=True)
    embed.add_field(name="Configuration", value=f"**Active Jobs:** {jobs_count}", inline=True)
    return embed

async def build_health_embed(guild: discord.Guild) -> discord.Embed:
    from health import HealthState, health_system
    
    uptime = datetime.datetime.now(datetime.timezone.utc) - health_system.start_time
    hours, remainder = divmod(int(uptime.total_seconds()), 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime_str = f"{hours}h {minutes}m {seconds}s"
    
    db_status = "🟢 Connected" if health_system.db_connected else "🔴 Disconnected"
    task_status = "🟢 Running" if registry.get("tasks") else "🔴 Unavailable"
    
    embed = VeyraEmbed.info("System Health", "Veyra operational status.")
    embed.add_field(name="Core", value=f"**Status:** {health_system.state.name}\n**Uptime:** {uptime_str}", inline=True)
    embed.add_field(name="Services", value=f"**Database:** {db_status}\n**Task Manager:** {task_status}", inline=True)
    return embed


class AnalyticsGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="analytics", description="Community Intelligence & Analytics", default_permissions=discord.Permissions(manage_guild=True))

    @app_commands.command(name="overview", description="View the overall community health dashboard.")
    @app_commands.choices(period=[
        app_commands.Choice(name="24 Hours", value="24h"),
        app_commands.Choice(name="7 Days", value="7d"),
        app_commands.Choice(name="30 Days", value="30d"),
    ])
    async def overview(self, interaction: discord.Interaction, period: app_commands.Choice[str] = None):
        if not await _check_analytics_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        p = period.value if period else "7d"
        embed = await build_overview_embed(interaction.guild, p)
        await interaction.followup.send(embed=embed, view=AnalyticsNavigationView("overview"), ephemeral=True)

    @app_commands.command(name="members", description="View member growth and retention insights.")
    @app_commands.choices(period=[
        app_commands.Choice(name="24 Hours", value="24h"),
        app_commands.Choice(name="7 Days", value="7d"),
        app_commands.Choice(name="30 Days", value="30d"),
    ])
    async def members(self, interaction: discord.Interaction, period: app_commands.Choice[str] = None):
        if not await _check_analytics_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        p = period.value if period else "7d"
        embed = await build_members_embed(interaction.guild, p)
        await interaction.followup.send(embed=embed, view=AnalyticsNavigationView("members"), ephemeral=True)

    @app_commands.command(name="activity", description="View community activity and engagement.")
    @app_commands.choices(period=[
        app_commands.Choice(name="24 Hours", value="24h"),
        app_commands.Choice(name="7 Days", value="7d"),
        app_commands.Choice(name="30 Days", value="30d"),
    ])
    async def activity(self, interaction: discord.Interaction, period: app_commands.Choice[str] = None):
        if not await _check_analytics_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        p = period.value if period else "7d"
        embed = await build_activity_embed(interaction.guild, p)
        await interaction.followup.send(embed=embed, view=AnalyticsNavigationView("activity"), ephemeral=True)

    @app_commands.command(name="tickets", description="View support and ticket performance metrics.")
    @app_commands.choices(period=[
        app_commands.Choice(name="24 Hours", value="24h"),
        app_commands.Choice(name="7 Days", value="7d"),
        app_commands.Choice(name="30 Days", value="30d"),
    ])
    async def tickets(self, interaction: discord.Interaction, period: app_commands.Choice[str] = None):
        if not await _check_analytics_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        p = period.value if period else "7d"
        embed = await build_tickets_embed(interaction.guild, p)
        await interaction.followup.send(embed=embed, view=AnalyticsNavigationView("tickets"), ephemeral=True)

    @app_commands.command(name="automation", description="View automation reliability and execution rates.")
    @app_commands.choices(period=[
        app_commands.Choice(name="24 Hours", value="24h"),
        app_commands.Choice(name="7 Days", value="7d"),
        app_commands.Choice(name="30 Days", value="30d"),
    ])
    async def automation(self, interaction: discord.Interaction, period: app_commands.Choice[str] = None):
        if not await _check_analytics_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        p = period.value if period else "7d"
        embed = await build_automation_embed(interaction.guild, p)
        await interaction.followup.send(embed=embed, view=AnalyticsNavigationView("automation"), ephemeral=True)

    @app_commands.command(name="health", description="View bot and system health metrics.")
    async def health(self, interaction: discord.Interaction):
        if not await _check_analytics_perms(interaction): return
        await interaction.response.defer(ephemeral=True)
        embed = await build_health_embed(interaction.guild)
        await interaction.followup.send(embed=embed, view=AnalyticsNavigationView("health"), ephemeral=True)

async def log_command_usage(interaction: discord.Interaction):
    """Global hook to track command usage into analytics."""
    if interaction.type == discord.InteractionType.application_command and interaction.guild:
        command_name = interaction.command.name if interaction.command else "unknown"
        now = datetime.datetime.now(datetime.timezone.utc)
        try:
            await db.execute(
                "INSERT INTO analytics_events (guild_id, event_type, user_id, timestamp) VALUES (?, ?, ?, ?)",
                (interaction.guild.id, f"command_{command_name}", interaction.user.id, now.isoformat())
            )
        except Exception as e:
            log.error(f"Failed to log command usage: {e}")
    return True

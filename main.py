import discord
from discord.ext import commands
import platform
import asyncio
import sys

from config import config
from logger import get_logger
from database import db
from embeds import VeyraEmbed
from health import health_system, HealthState
from services import registry
from tasks import task_manager
from errors import global_app_command_error
from commands import safe_reply

log = get_logger("VEYRA")

class VeyraBot(commands.AutoShardedBot):
    def __init__(self):
        # Configure exact intents required
        intents = discord.Intents.default()
        intents.message_content = False # Disabled per Phase 1.1 requirements
        intents.members = True          # Required for join security/verification
        intents.presences = False       # Explicitly disabled per requirements
        
        super().__init__(
            command_prefix=commands.when_mentioned_or("v!"), # Fallback prefix
            intents=intents,
            help_command=None
        )
        # Register global error handler
        self.tree.on_error = global_app_command_error

    async def setup_hook(self):
        """Lifecycle hook called before bot connects to Discord."""
        log.info("Initializing Veyra Lifecycle...")
        health_system.state = HealthState.STARTING
        
        # 1. Initialize Database
        try:
            await db.connect()
            health_system.db_connected = True
        except Exception as e:
            log.critical(f"Database initialization failed: {e}")
            health_system.state = HealthState.FAILED
            sys.exit(1)
            
        # 2. Service Initialization & Registration
        try:
            registry.register("database", db)
            registry.register("health", health_system)
            registry.register("tasks", task_manager)
            health_system.services_initialized = True
        except Exception as e:
            log.critical(f"Service registration failed: {e}")
            health_system.state = HealthState.FAILED
            sys.exit(1)
            
        # 3. Command Registration
        self.tree.add_command(SystemStatus())
        from setup_system import AutoGroup
        from verification import VerificationGroup, VerificationView, on_member_join as verification_on_member_join
        from tickets import TicketGroup, TicketPanelView, TicketCloseView
        from community import AutomationGroup, AutomationConfigView, on_member_join as community_on_member_join, on_member_remove as community_on_member_remove, start_automation_scheduler
        from analytics import AnalyticsGroup, AnalyticsNavigationView, log_command_usage
        from content import ContentGroup, ContentSourceView, start_content_scheduler
        
        self.tree.add_command(AutoGroup())
        self.tree.add_command(VerificationGroup())
        self.tree.add_command(TicketGroup())
        self.tree.add_command(AutomationGroup())
        self.tree.add_command(AnalyticsGroup())
        self.tree.add_command(ContentGroup())
        
        self.add_view(VerificationView())
        self.add_view(TicketPanelView())
        self.add_view(TicketCloseView())
        self.add_view(AutomationConfigView())
        self.add_view(AnalyticsNavigationView())
        self.add_view(ContentSourceView())
        start_automation_scheduler(self)
        start_content_scheduler(self)
        
        self.tree.interaction_check = log_command_usage
        
        # 4. Command Synchronization
        log.info("Synchronizing command tree globally...")
        try:
            synced = await self.tree.sync()
            log.info(f"Successfully synced {len(synced)} commands.")
        except Exception as e:
            log.error(f"Failed to sync commands: {e}")

    async def on_member_join(self, member: discord.Member):
        await verification_on_member_join(member)
        await community_on_member_join(member)

    async def on_member_remove(self, member: discord.Member):
        await community_on_member_remove(member)

    async def on_ready(self):
        log.info(f"Veyra is online as {self.user} (ID: {self.user.id})")
        log.info(f"Connected to {len(self.guilds)} guilds.")
        health_system.discord_ready = True
        health_system.state = HealthState.READY

    async def close(self):
        """Graceful shutdown handler."""
        log.info("Initiating Veyra shutdown sequence...")
        health_system.state = HealthState.SHUTTING_DOWN
        
        # Stop background tasks
        await task_manager.shutdown()
        
        # Close database
        await db.close()
        
        # Disconnect Discord
        log.info("Disconnecting Discord client...")
        await super().close()
        log.info("Shutdown complete.")

class SystemStatus(discord.app_commands.Command):
    """Diagnostics command to display Veyra core engine status."""
    def __init__(self):
        super().__init__(
            name="system-status",
            description="Displays Veyra core engine diagnostics and status.",
            callback=self.callback
        )

    async def callback(self, interaction: discord.Interaction):
        uptime_seconds = health_system.uptime
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours}h {minutes}m {seconds}s"
        
        latency_ms = round(interaction.client.latency * 1000)
        
        embed = VeyraEmbed.status(
            title="Veyra Core Engine Status",
            description="Core systems diagnostics."
        )
        
        embed.add_field(name="State", value=health_system.state.value, inline=True)
        embed.add_field(name="Bot Status", value="🟢 Online" if health_system.discord_ready else "🔴 Offline", inline=True)
        embed.add_field(name="Latency", value=f"{latency_ms}ms", inline=True)
        
        embed.add_field(name="Uptime", value=uptime_str, inline=True)
        embed.add_field(name="Python Version", value=platform.python_version(), inline=True)
        embed.add_field(name="discord.py Version", value=discord.__version__, inline=True)
        
        db_status = "🟢 Connected" if health_system.db_connected else "🔴 Disconnected"
        embed.add_field(name="Database", value=db_status, inline=True)
        
        svc_status = "🟢 Registered" if health_system.services_initialized else "🔴 Failed"
        embed.add_field(name="Services", value=svc_status, inline=True)
        
        embed.add_field(name="Guilds", value=str(len(interaction.client.guilds)), inline=True)
        
        embed.set_footer(text=f"Environment: {config.ENVIRONMENT.capitalize()}")
        
        await safe_reply(interaction, embed)

async def main():
    # Validate environment variables
    if not config.validate():
        sys.exit(1)
        
    bot = VeyraBot()
    
    try:
        await bot.start(config.DISCORD_TOKEN)
    except discord.LoginFailure:
        log.critical("Failed to log in: Invalid token.")
    except Exception as e:
        log.critical(f"An unexpected error occurred: {e}")
    finally:
        if not bot.is_closed():
            await bot.close()

if __name__ == "__main__":
    # Ensure graceful exit on interrupt
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Received interrupt signal. Exiting cleanly.")

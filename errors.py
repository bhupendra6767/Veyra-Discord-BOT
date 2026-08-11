import discord
import traceback
from logger import get_logger
from embeds import VeyraEmbed

log = get_logger("ERROR")

class VeyraError(Exception):
    """Base exception for all Veyra errors."""
    pass

class ConfigurationError(VeyraError):
    pass

class DatabaseError(VeyraError):
    pass

class PermissionError(VeyraError):
    pass

class ValidationError(VeyraError):
    pass

class ServiceError(VeyraError):
    pass

class UserFacingError(VeyraError):
    """Errors that should be shown directly to the user."""
    pass

async def global_app_command_error(interaction: discord.Interaction, error: discord.app_commands.AppCommandError):
    """Global error handler for all slash commands."""
    
    if isinstance(error, discord.app_commands.CommandOnCooldown):
        embed = VeyraEmbed.warning(
            "Command on Cooldown",
            f"Please wait {error.retry_after:.1f} seconds before using this command again."
        )
    elif isinstance(error, discord.app_commands.MissingPermissions):
        embed = VeyraEmbed.error("Permission Denied", "You lack the required Discord permissions to use this command.")
    elif isinstance(error, discord.app_commands.CheckFailure):
        embed = VeyraEmbed.error("Access Denied", "You do not meet the requirements to use this command.")
    else:
        # Extract original error if it's wrapped
        original = getattr(error, 'original', error)
        if isinstance(original, UserFacingError):
            embed = VeyraEmbed.error("Error", str(original))
        else:
            log.error(f"Unhandled command error in {interaction.command.name if interaction.command else 'unknown'}: {error}")
            traceback.print_exception(type(error), error, error.__traceback__)
            embed = VeyraEmbed.error("Internal Error", "An unexpected error occurred while processing your request.")
            
    try:
        from commands import safe_reply
        await safe_reply(interaction, embed, ephemeral=True)
    except Exception as e:
        log.error(f"Failed to send error message to user: {e}")

import discord
from logger import get_logger

log = get_logger("COMMANDS")

async def safe_reply(interaction: discord.Interaction, embed: discord.Embed, ephemeral: bool = True) -> None:
    """
    Safely responds to a Discord interaction, handling deferred, expired, 
    and already-acknowledged states without throwing unhandled exceptions.
    """
    try:
        if interaction.is_expired():
            log.warning(f"Attempted to respond to an expired interaction for command '{interaction.command.name if interaction.command else 'unknown'}'.")
            return

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.NotFound:
        log.warning("Interaction not found (likely expired).")
    except discord.HTTPException as e:
        if e.code == 10062:
            log.warning("Unknown Interaction (10062) while replying.")
        elif e.code == 40060:
            log.warning("Interaction already acknowledged (40060).")
        else:
            log.error(f"HTTPException in safe_reply: {e}")
            raise

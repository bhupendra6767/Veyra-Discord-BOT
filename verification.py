import discord
from discord import app_commands
import asyncio
from database import db
from embeds import VeyraEmbed
from premium import premium_verification
from logger import get_logger
from commands import safe_reply
from permissions import has_veyra_level, PermissionLevel
from setup_system import get_server_layout
import time

log = get_logger("VERIFICATION")

# Simple in-memory cooldown: user_id -> timestamp
_verification_cooldowns = {}
COOLDOWN_SECONDS = 10

class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
    
    @discord.ui.button(label="Verify", style=discord.ButtonStyle.success, custom_id="veyra:verify_button")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await safe_reply(interaction, VeyraEmbed.error("Error", "This can only be used in a server."), ephemeral=True)
            
        user_id = interaction.user.id
        now = time.time()
        
        # Cooldown check
        last_attempt = _verification_cooldowns.get(user_id, 0)
        if now - last_attempt < COOLDOWN_SECONDS:
            return await safe_reply(interaction, VeyraEmbed.warning("Cooldown", f"Please wait a few seconds before trying again."), ephemeral=True)
            
        _verification_cooldowns[user_id] = now
        
        # Cleanup expired cooldowns to prevent memory leaks
        expired = [k for k, v in _verification_cooldowns.items() if now - v > COOLDOWN_SECONDS]
        for k in expired:
            del _verification_cooldowns[k]

        
        await interaction.response.defer(ephemeral=True)
        
        try:
            # Check settings
            settings = await db.fetch_one("SELECT role_id, active FROM verification_settings WHERE guild_id = ?", (interaction.guild.id,))
            if not settings or not settings["active"] or not settings["role_id"]:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Verification is not active or fully configured on this server."), ephemeral=True)
                
            verified_role_id = settings["role_id"]
            verified_role = interaction.guild.get_role(verified_role_id)
            
            if not verified_role:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "The configured verification role no longer exists. Please contact an administrator."), ephemeral=True)
                
            # Check bot perms
            bot_member = interaction.guild.me
            if not bot_member.guild_permissions.manage_roles:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra is missing the 'Manage Roles' permission."), ephemeral=True)
                
            if bot_member.top_role <= verified_role:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra's role must be higher than the Verified role."), ephemeral=True)
                
            # Check if already verified
            if verified_role in interaction.user.roles:
                return await interaction.followup.send(embed=VeyraEmbed.info("Already Verified", "You are already verified in this server."), ephemeral=True)
                
            # Find Unverified role to remove
            unverified_role_id = await get_server_layout(interaction.guild.id, "role", "Unverified")
            unverified_role = interaction.guild.get_role(unverified_role_id) if unverified_role_id else None
            
            # Add/Remove roles
            roles_to_add = [verified_role]
            roles_to_remove = [unverified_role] if unverified_role and unverified_role in interaction.user.roles else []
            
            try:
                if roles_to_remove:
                    await interaction.user.remove_roles(*roles_to_remove, reason="Veyra Verification")
                await interaction.user.add_roles(*roles_to_add, reason="Veyra Verification")
                
                # Log analytics event
                try:
                    await db.execute(
                        "INSERT INTO analytics_events (guild_id, event_type, user_id, timestamp) VALUES (?, ?, ?, ?)",
                        (interaction.guild.id, "member_verify", interaction.user.id, datetime.datetime.now(datetime.timezone.utc).isoformat())
                    )
                except Exception:
                    pass
            except discord.Forbidden:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra lacks permissions to modify your roles. Ensure Veyra's role is placed highest in the server settings."), ephemeral=True)
                
            # Success
            embed = premium_verification(interaction.user)
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except Exception as e:
            log.error(f"Verification error for {interaction.user.id}: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Internal Error", "An unexpected error occurred during verification."), ephemeral=True)

class VerificationGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="verification", description="Verification System commands")

    async def _check_prerequisites(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await safe_reply(interaction, VeyraEmbed.error("Guild Only", "This command can only be used in a server."))
            return False
            
        if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
            await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to configure verification."))
            return False
            
        return True

    @app_commands.command(name="setup", description="Configure or repair the verification system")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction):
            return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            # Look for Verified role and Verification channel from server_layout
            verified_role_id = await get_server_layout(interaction.guild.id, "role", "Verified")
            verification_ch_id = await get_server_layout(interaction.guild.id, "channel", "🔐・verification")
            
            if not verified_role_id or not verification_ch_id:
                return await interaction.followup.send(embed=VeyraEmbed.error("Setup Incomplete", "Verification infrastructure is incomplete. Please run `/auto repair` and try again."))
                
            # Check if they exist in guild
            verified_role = interaction.guild.get_role(verified_role_id)
            verification_ch = interaction.guild.get_channel(verification_ch_id)
            
            if not verified_role or not verification_ch:
                return await interaction.followup.send(embed=VeyraEmbed.error("Objects Missing", "The required role or channel could not be found. Please run `/auto repair`."))
                
            # Save settings
            await db.execute(
                "INSERT OR REPLACE INTO verification_settings (guild_id, channel_id, role_id, active) VALUES (?, ?, ?, ?)",
                (interaction.guild.id, verification_ch_id, verified_role_id, 1)
            )
            
            await interaction.followup.send(embed=VeyraEmbed.success("Verification Setup", "Verification system has been successfully configured and activated."))
            
        except Exception as e:
            log.error(f"Verification setup failed: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "An unexpected error occurred while setting up verification."))

    @app_commands.command(name="panel", description="Post the verification panel to the configured channel")
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction):
            return
            
        await interaction.response.defer(ephemeral=True)
        
        try:
            settings = await db.fetch_one("SELECT channel_id, active FROM verification_settings WHERE guild_id = ?", (interaction.guild.id,))
            if not settings or not settings["active"] or not settings["channel_id"]:
                return await interaction.followup.send(embed=VeyraEmbed.error("Not Configured", "Verification is not active. Run `/verification setup` first."))
                
            channel = interaction.guild.get_channel(settings["channel_id"])
            if not channel:
                return await interaction.followup.send(embed=VeyraEmbed.error("Channel Missing", "The verification channel no longer exists. Run `/auto repair`."))
                
            embed = VeyraEmbed(
                title="Welcome to Veylora",
                description="To gain access to the rest of the server, you must complete verification.\n\nBy clicking the button below, you agree to follow the community rules.",
                color=VeyraEmbed.INFO_COLOR
            )
            
            await channel.send(embed=embed, view=VerificationView())
            await interaction.followup.send(embed=VeyraEmbed.success("Success", f"Verification panel posted to {channel.mention}."))
            
        except Exception as e:
            log.error(f"Failed to post verification panel: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "An unexpected error occurred while posting the panel."))

    @app_commands.command(name="status", description="Check the status of the verification system")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction):
            return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            settings = await db.fetch_one("SELECT channel_id, role_id, active FROM verification_settings WHERE guild_id = ?", (interaction.guild.id,))
            
            if not settings:
                return await interaction.followup.send(embed=VeyraEmbed.info("Verification Status", "Verification system has not been configured."))
                
            active = bool(settings["active"])
            ch_id = settings["channel_id"]
            role_id = settings["role_id"]
            
            channel = interaction.guild.get_channel(ch_id) if ch_id else None
            role = interaction.guild.get_role(role_id) if role_id else None
            
            embed = VeyraEmbed.info("Verification Status", "Current configuration for the verification system.")
            embed.add_field(name="Status", value="🟢 Enabled" if active else "🔴 Disabled", inline=True)
            embed.add_field(name="Channel", value=channel.mention if channel else f"Missing ({ch_id})", inline=True)
            embed.add_field(name="Role", value=role.mention if role else f"Missing ({role_id})", inline=True)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            log.error(f"Verification status error: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "Failed to retrieve verification status."))

async def on_member_join(member: discord.Member):
    """Event handler for when a member joins the guild."""
    try:
        settings = await db.fetch_one("SELECT active FROM verification_settings WHERE guild_id = ?", (member.guild.id,))
        if not settings or not settings["active"]:
            return
            
        # If verification is active, apply the Unverified role if it exists
        unverified_role_id = await get_server_layout(member.guild.id, "role", "Unverified")
        if unverified_role_id:
            unverified_role = member.guild.get_role(unverified_role_id)
            if unverified_role:
                try:
                    await member.add_roles(unverified_role, reason="Veyra Verification (Auto-Assign)")
                except discord.Forbidden:
                    log.warning(f"Missing permissions to assign Unverified role in guild {member.guild.id}")
                    
    except Exception as e:
        log.error(f"Error in verification on_member_join: {e}")


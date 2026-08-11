import discord
from discord import app_commands
import asyncio
import time
import io
import datetime
from database import db
from embeds import VeyraEmbed
from premium import premium_ticket_created, premium_ticket_closed
from logger import get_logger
from commands import safe_reply
from permissions import has_veyra_level, PermissionLevel
from setup_system import get_server_layout
from errors import global_app_command_error

log = get_logger("TICKETS")

# Cooldown to prevent spam ticket creation: user_id -> timestamp
_ticket_cooldowns = {}
TICKET_COOLDOWN_SECONDS = 10

async def generate_transcript(channel: discord.TextChannel) -> str:
    transcript = f"--- Transcript for #{channel.name} ---\n"
    transcript += f"Generated: {datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
    
    try:
        messages = [message async for message in channel.history(limit=500, oldest_first=True)]
        for msg in messages:
            time_str = msg.created_at.strftime('%Y-%m-%d %H:%M:%S')
            author = f"{msg.author.name}#{msg.author.discriminator}" if hasattr(msg.author, 'discriminator') and msg.author.discriminator != '0' else msg.author.name
            content = msg.clean_content or "[Attachment/Embed]"
            transcript += f"[{time_str}] {author}: {content}\n"
    except Exception as e:
        transcript += f"\nError generating complete transcript: {e}\n"
        
    return transcript

async def close_ticket_impl(interaction: discord.Interaction, channel: discord.TextChannel):
    try:
        ticket_info = await db.fetch_one("SELECT ticket_id, user_id, status FROM tickets WHERE guild_id = ? AND channel_id = ?", (interaction.guild.id, channel.id))
        if not ticket_info:
            return await interaction.followup.send(embed=VeyraEmbed.error("Error", "This channel is not recognized as a ticket."), ephemeral=True)
            
        if ticket_info["status"] != "open":
            return await interaction.followup.send(embed=VeyraEmbed.warning("Closing", "This ticket is already being closed."), ephemeral=True)
            
        if interaction.user.id != ticket_info["user_id"] and not await has_veyra_level(interaction.user, PermissionLevel.MODERATOR) and interaction.guild.owner_id != interaction.user.id:
            return await interaction.followup.send(embed=VeyraEmbed.error("Permission Denied", "You don't have permission to close this ticket."), ephemeral=True)
            
        rowcount = await db.execute("UPDATE tickets SET status = ? WHERE guild_id = ? AND ticket_id = ? AND status = ?", ("closing", interaction.guild.id, ticket_info["ticket_id"], "open"))
        if rowcount == 0:
            return await interaction.followup.send(embed=VeyraEmbed.warning("Closing", "This ticket is already being closed."), ephemeral=True)
            
        await interaction.followup.send(embed=VeyraEmbed.info("Closing Ticket", "Gathering transcript and closing ticket in a few seconds..."))
        
        transcript = await generate_transcript(channel)
        settings = await db.fetch_one("SELECT log_channel_id FROM ticket_settings WHERE guild_id = ?", (interaction.guild.id,))
        
        if settings and settings["log_channel_id"]:
            log_channel = interaction.guild.get_channel(settings["log_channel_id"])
            if log_channel:
                creator = interaction.guild.get_member(ticket_info["user_id"])
                creator_name = creator.name if creator else f"Unknown User ({ticket_info['user_id']})"
                
                log_embed = VeyraEmbed.info(
                    "Ticket Closed",
                    f"**Ticket:** `{ticket_info['ticket_id']}`\n**Creator:** {creator_name}\n**Closed By:** {interaction.user.mention}"
                )
                
                try:
                    file = discord.File(fp=io.BytesIO(transcript.encode('utf-8')), filename=f"transcript-{ticket_info['ticket_id']}.txt")
                    await log_channel.send(embed=log_embed, file=file)
                except Exception as e:
                    log.error(f"Failed to send transcript for ticket {ticket_info['ticket_id']}: {e}")
                    
        closed_at = datetime.datetime.now(datetime.timezone.utc)
        await db.execute(
            "UPDATE tickets SET status = ?, closed_at = ? WHERE guild_id = ? AND ticket_id = ?",
            ("closed", closed_at, interaction.guild.id, ticket_info["ticket_id"])
        )
        
        await asyncio.sleep(3)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user.id}")
        except discord.Forbidden:
            log.warning(f"Could not delete ticket channel {channel.id} due to missing permissions.")
        except discord.NotFound:
            pass
            
    except Exception as e:
        log.error(f"Error closing ticket in {channel.id}: {e}")
        try:
            await db.execute("UPDATE tickets SET status = ? WHERE guild_id = ? AND channel_id = ?", ("open", interaction.guild.id, channel.id))
            await interaction.followup.send(embed=VeyraEmbed.error("Internal Error", "An unexpected error occurred while closing the ticket."), ephemeral=True)
        except:
            pass

class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="Close Ticket", style=discord.ButtonStyle.danger, custom_id="veyra:ticket_close_btn", emoji="🔒")
    async def close_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await safe_reply(interaction, VeyraEmbed.error("Error", "This can only be used in a server."), ephemeral=True)
        await interaction.response.defer(ephemeral=False)
        if isinstance(interaction.channel, discord.TextChannel):
            await close_ticket_impl(interaction, interaction.channel)
        else:
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "Cannot close ticket here."))


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        
        self.ticket_types = [
            discord.SelectOption(label="General Support", description="Get general help with the server", emoji="❓", value="general"),
            discord.SelectOption(label="Technical Support", description="Report a bug or technical issue", emoji="💻", value="technical"),
            discord.SelectOption(label="Report", description="Report a user or incident", emoji="⚠️", value="report"),
            discord.SelectOption(label="Partnership", description="Discuss partnership opportunities", emoji="🤝", value="partnership")
        ]
        
        self.select = discord.ui.Select(
            placeholder="Select a ticket type...",
            min_values=1,
            max_values=1,
            options=self.ticket_types,
            custom_id="veyra:ticket_select"
        )
        self.select.callback = self.ticket_select_callback
        self.add_item(self.select)

    async def ticket_select_callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await safe_reply(interaction, VeyraEmbed.error("Error", "This can only be used in a server."), ephemeral=True)
            
        user_id = interaction.user.id
        now = time.time()
        
        last_attempt = _ticket_cooldowns.get(user_id, 0)
        if now - last_attempt < TICKET_COOLDOWN_SECONDS:
            return await safe_reply(interaction, VeyraEmbed.warning("Cooldown", "Please wait a few seconds before opening another ticket."), ephemeral=True)
            
        _ticket_cooldowns[user_id] = now
        
        expired = [k for k, v in _ticket_cooldowns.items() if now - v > TICKET_COOLDOWN_SECONDS]
        for k in expired:
            del _ticket_cooldowns[k]
        
        if len(_ticket_cooldowns) > 1000:
            _ticket_cooldowns.clear()
            
        ticket_type = self.select.values[0]
        await interaction.response.defer(ephemeral=True)
        
        try:
            settings = await db.fetch_one("SELECT category_id, active FROM ticket_settings WHERE guild_id = ?", (interaction.guild.id,))
            if not settings or not settings["active"] or not settings["category_id"]:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "The ticket system is not active or fully configured on this server."), ephemeral=True)
                
            existing_ticket = await db.fetch_one("SELECT ticket_id, channel_id FROM tickets WHERE guild_id = ? AND user_id = ? AND status = ?", (interaction.guild.id, user_id, "open"))
            if existing_ticket:
                existing_channel = interaction.guild.get_channel(existing_ticket["channel_id"])
                if not existing_channel:
                    import datetime
                    closed_at = datetime.datetime.now(datetime.timezone.utc)
                    await db.execute("UPDATE tickets SET status = 'closed', closed_at = ? WHERE guild_id = ? AND ticket_id = ?", (closed_at, interaction.guild.id, existing_ticket["ticket_id"]))
                else:
                    return await interaction.followup.send(embed=VeyraEmbed.warning("Ticket Open", f"You already have an open ticket: {existing_channel.mention}"), ephemeral=True)
                
            category = interaction.guild.get_channel(settings["category_id"])
            if not category or not isinstance(category, discord.CategoryChannel):
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "The configured ticket category no longer exists. Please contact an administrator."), ephemeral=True)
                
            bot_member = interaction.guild.me
            if not bot_member.guild_permissions.manage_channels or not bot_member.guild_permissions.manage_roles:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra is missing the 'Manage Channels' or 'Manage Roles' permission."), ephemeral=True)
                
            ticket_id = f"ticket-{user_id}-{int(now)}"
            channel_name = f"{ticket_type}-{interaction.user.name}"
            
            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(read_messages=False),
                interaction.user: discord.PermissionOverwrite(read_messages=True, send_messages=True, attach_files=True, embed_links=True),
                bot_member: discord.PermissionOverwrite(read_messages=True, send_messages=True, manage_channels=True, manage_permissions=True)
            }
            
            support_roles = ["Support", "Moderator", "Administrator", "Manager", "Owner", "Founder"]
            for role_name in support_roles:
                role_id = await get_server_layout(interaction.guild.id, "role", role_name)
                if role_id:
                    role = interaction.guild.get_role(role_id)
                    if role:
                        overwrites[role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
                        
            try:
                ticket_channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    topic=f"Ticket for {interaction.user.mention} | Type: {ticket_type}"
                )
            except discord.Forbidden:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra lacks permissions to create the ticket channel."), ephemeral=True)
                
            created_at = datetime.datetime.now(datetime.timezone.utc)
            try:
                await db.execute(
                    "INSERT INTO tickets (guild_id, ticket_id, channel_id, user_id, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (interaction.guild.id, ticket_id, ticket_channel.id, user_id, "open", created_at)
                )
                
                await db.execute(
                    "INSERT INTO ticket_members (guild_id, ticket_id, user_id) VALUES (?, ?, ?)",
                    (interaction.guild.id, ticket_id, user_id)
                )
            except Exception as e:
                try:
                    await ticket_channel.delete(reason="Database error during ticket creation")
                except:
                    pass
                raise e
            
            embed = premium_ticket_created(interaction.guild, interaction.user)
            embed.title = f"Ticket: {ticket_type.capitalize()} Support"
            embed.set_footer(text=f"Ticket ID: {ticket_id}")
            
            await ticket_channel.send(content=interaction.user.mention, embed=embed, view=TicketCloseView())
            await interaction.followup.send(embed=VeyraEmbed.success("Ticket Created", f"Your ticket has been created at {ticket_channel.mention}."), ephemeral=True)
            
        except Exception as e:
            log.error(f"Ticket creation error for {interaction.user.id}: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Internal Error", "An unexpected error occurred while creating your ticket."), ephemeral=True)

class TicketGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="ticket", description="Ticketing & Support System commands")

    async def _check_prerequisites(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await safe_reply(interaction, VeyraEmbed.error("Guild Only", "This command can only be used in a server."))
            return False
        return True
        
    async def _check_manager(self, interaction: discord.Interaction) -> bool:
        if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
            await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to configure tickets."))
            return False
        return True

    @app_commands.command(name="setup", description="Configure the ticketing system")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction): return
        if not await self._check_manager(interaction): return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            category_id = await get_server_layout(interaction.guild.id, "category", "SUPPORT")
            log_ch_id = await get_server_layout(interaction.guild.id, "channel", "📋・staff-logs")
            
            if not category_id:
                return await interaction.followup.send(embed=VeyraEmbed.error("Setup Incomplete", "Support category is missing. Please run `/auto repair` and try again."))
                
            category = interaction.guild.get_channel(category_id)
            if not category:
                return await interaction.followup.send(embed=VeyraEmbed.error("Objects Missing", "The Support category could not be found. Please run `/auto repair`."))
                
            await db.execute(
                "INSERT OR REPLACE INTO ticket_settings (guild_id, category_id, log_channel_id, active) VALUES (?, ?, ?, ?)",
                (interaction.guild.id, category_id, log_ch_id, 1)
            )
            
            await interaction.followup.send(embed=VeyraEmbed.success("Ticket Setup", "Ticketing system has been successfully configured and activated."))
            
        except Exception as e:
            log.error(f"Ticket setup failed: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "An unexpected error occurred while setting up tickets."))

    @app_commands.command(name="panel", description="Post the ticket creation panel")
    @app_commands.default_permissions(manage_guild=True)
    async def panel(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction): return
        if not await self._check_manager(interaction): return
            
        await interaction.response.defer(ephemeral=True)
        
        try:
            settings = await db.fetch_one("SELECT active FROM ticket_settings WHERE guild_id = ?", (interaction.guild.id,))
            if not settings or not settings["active"]:
                return await interaction.followup.send(embed=VeyraEmbed.error("Not Configured", "Ticket system is not active. Run `/ticket setup` first."))
                
            embed = VeyraEmbed(
                title="Support Tickets",
                description="Select an option from the dropdown below to open a ticket.\n\nPlease be patient, our support staff will assist you as soon as possible.",
                color=VeyraEmbed.INFO_COLOR
            )
            
            await interaction.channel.send(embed=embed, view=TicketPanelView())
            await interaction.followup.send(embed=VeyraEmbed.success("Success", "Ticket panel posted."))
            
        except Exception as e:
            log.error(f"Failed to post ticket panel: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "An unexpected error occurred while posting the panel."))

    @app_commands.command(name="add_user", description="Add a user to the current ticket")
    async def add_user(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._check_prerequisites(interaction): return
        await interaction.response.defer(ephemeral=False)
        
        try:
            ticket_info = await db.fetch_one("SELECT ticket_id, user_id FROM tickets WHERE guild_id = ? AND channel_id = ? AND status = 'open'", (interaction.guild.id, interaction.channel.id))
            if not ticket_info:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "This channel is not an open ticket."))
                
            if interaction.user.id != ticket_info["user_id"] and not await has_veyra_level(interaction.user, PermissionLevel.SUPPORT) and interaction.guild.owner_id != interaction.user.id:
                return await interaction.followup.send(embed=VeyraEmbed.error("Permission Denied", "You don't have permission to add users to this ticket."))
                
            existing = await db.fetch_val("SELECT user_id FROM ticket_members WHERE guild_id = ? AND ticket_id = ? AND user_id = ?", (interaction.guild.id, ticket_info["ticket_id"], user.id))
            if existing:
                return await interaction.followup.send(embed=VeyraEmbed.warning("Already Added", f"{user.mention} is already in this ticket."))
                
            try:
                await interaction.channel.set_permissions(user, read_messages=True, send_messages=True, attach_files=True, embed_links=True)
            except discord.Forbidden:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra lacks permissions to modify channel overwrites."))
                
            await db.execute("INSERT INTO ticket_members (guild_id, ticket_id, user_id) VALUES (?, ?, ?)", (interaction.guild.id, ticket_info["ticket_id"], user.id))
            
            await interaction.followup.send(embed=VeyraEmbed.success("User Added", f"{user.mention} has been added to the ticket by {interaction.user.mention}."))
            
        except Exception as e:
            log.error(f"Error adding user to ticket: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "Failed to add user to the ticket."))

    @app_commands.command(name="remove_user", description="Remove a user from the current ticket")
    async def remove_user(self, interaction: discord.Interaction, user: discord.Member):
        if not await self._check_prerequisites(interaction): return
        await interaction.response.defer(ephemeral=False)
        
        try:
            ticket_info = await db.fetch_one("SELECT ticket_id, user_id FROM tickets WHERE guild_id = ? AND channel_id = ? AND status = 'open'", (interaction.guild.id, interaction.channel.id))
            if not ticket_info:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "This channel is not an open ticket."))
                
            if user.id == ticket_info["user_id"]:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "You cannot remove the ticket creator."))
                
            if interaction.user.id != ticket_info["user_id"] and not await has_veyra_level(interaction.user, PermissionLevel.SUPPORT) and interaction.guild.owner_id != interaction.user.id:
                return await interaction.followup.send(embed=VeyraEmbed.error("Permission Denied", "You don't have permission to remove users."))
                
            existing = await db.fetch_val("SELECT user_id FROM ticket_members WHERE guild_id = ? AND ticket_id = ? AND user_id = ?", (interaction.guild.id, ticket_info["ticket_id"], user.id))
            if not existing:
                return await interaction.followup.send(embed=VeyraEmbed.warning("Not in Ticket", f"{user.mention} is not in this ticket."))
                
            try:
                await interaction.channel.set_permissions(user, overwrite=None)
            except discord.Forbidden:
                return await interaction.followup.send(embed=VeyraEmbed.error("Error", "Veyra lacks permissions to modify channel overwrites."))
                
            await db.execute("DELETE FROM ticket_members WHERE guild_id = ? AND ticket_id = ? AND user_id = ?", (interaction.guild.id, ticket_info["ticket_id"], user.id))
            
            await interaction.followup.send(embed=VeyraEmbed.success("User Removed", f"{user.mention} has been removed from the ticket."))
            
        except Exception as e:
            log.error(f"Error removing user from ticket: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "Failed to remove user from the ticket."))

    @app_commands.command(name="close", description="Close the current ticket")
    async def close(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction): return
        await interaction.response.defer(ephemeral=False)
        if isinstance(interaction.channel, discord.TextChannel):
            await close_ticket_impl(interaction, interaction.channel)
        else:
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "Cannot close ticket here."))

    @app_commands.command(name="status", description="Check the status of the ticket system")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction): return
        if not await self._check_manager(interaction): return
            
        await interaction.response.defer(ephemeral=False)
        
        try:
            settings = await db.fetch_one("SELECT category_id, log_channel_id, active FROM ticket_settings WHERE guild_id = ?", (interaction.guild.id,))
            
            if not settings:
                return await interaction.followup.send(embed=VeyraEmbed.info("Ticket Status", "Ticket system has not been configured."))
                
            active = bool(settings["active"])
            cat_id = settings["category_id"]
            log_id = settings["log_channel_id"]
            
            category = interaction.guild.get_channel(cat_id) if cat_id else None
            log_channel = interaction.guild.get_channel(log_id) if log_id else None
            
            open_count = await db.fetch_val("SELECT COUNT(*) FROM tickets WHERE guild_id = ? AND status = 'open'", (interaction.guild.id,))
            
            embed = VeyraEmbed.info("Ticket System Status", "Current configuration for the ticket system.")
            embed.add_field(name="Status", value="🟢 Enabled" if active else "🔴 Disabled", inline=True)
            embed.add_field(name="Category", value=category.mention if category else f"Missing ({cat_id})", inline=True)
            embed.add_field(name="Log Channel", value=log_channel.mention if log_channel else f"Missing ({log_id})", inline=True)
            embed.add_field(name="Open Tickets", value=str(open_count or 0), inline=False)
            
            await interaction.followup.send(embed=embed)
            
        except Exception as e:
            log.error(f"Ticket status error: {e}")
            await interaction.followup.send(embed=VeyraEmbed.error("Error", "Failed to retrieve ticket status."))

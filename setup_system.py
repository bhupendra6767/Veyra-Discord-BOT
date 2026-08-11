import discord
from discord import app_commands
import asyncio
from typing import Dict, List, Any, Optional

from database import db
from logger import get_logger
from embeds import VeyraEmbed
from permissions import has_veyra_level, PermissionLevel
from commands import safe_reply
from errors import VeyraError

log = get_logger("SETUP")

SETUP_STATE_NOT_STARTED = "NOT_STARTED"
SETUP_STATE_IN_PROGRESS = "IN_PROGRESS"
SETUP_STATE_PARTIAL = "PARTIAL"
SETUP_STATE_COMPLETE = "COMPLETE"
SETUP_STATE_FAILED = "FAILED"
SETUP_STATE_REPAIR_REQUIRED = "REPAIR_REQUIRED"

_setup_locks = set()

ROLES = [
    {"name": "Founder", "level": PermissionLevel.FOUNDER, "color": discord.Color.purple(), "hoist": True, "perms": discord.Permissions(administrator=True)},
    {"name": "Owner", "level": PermissionLevel.OWNER, "color": discord.Color.gold(), "hoist": True, "perms": discord.Permissions(administrator=True)},
    {"name": "Manager", "level": PermissionLevel.MANAGER, "color": discord.Color.red(), "hoist": True, "perms": discord.Permissions(manage_guild=True, manage_roles=True, manage_channels=True, moderate_members=True, kick_members=True, ban_members=True)},
    {"name": "Administrator", "level": PermissionLevel.ADMINISTRATOR, "color": discord.Color.dark_red(), "hoist": True, "perms": discord.Permissions(manage_guild=True, manage_roles=True, manage_channels=True, moderate_members=True, kick_members=True, ban_members=True)},
    {"name": "Moderator", "level": PermissionLevel.MODERATOR, "color": discord.Color.blue(), "hoist": True, "perms": discord.Permissions(moderate_members=True, kick_members=True, ban_members=True, manage_messages=True)},
    {"name": "Support", "level": PermissionLevel.SUPPORT, "color": discord.Color.green(), "hoist": True, "perms": discord.Permissions(manage_messages=True)},
    {"name": "Developer", "level": PermissionLevel.DEVELOPER, "color": discord.Color.dark_gray(), "hoist": True, "perms": discord.Permissions.none()},
    {"name": "Verified", "level": PermissionLevel.VERIFIED, "color": discord.Color.default(), "hoist": False, "perms": discord.Permissions.none()},
    {"name": "Unverified", "level": PermissionLevel.MEMBER, "color": discord.Color.default(), "hoist": False, "perms": discord.Permissions.none()},
    {"name": "Member", "level": PermissionLevel.MEMBER, "color": discord.Color.default(), "hoist": False, "perms": discord.Permissions.none()},
]

def safe_permissions(bot_perms: discord.Permissions, target_perms: discord.Permissions) -> discord.Permissions:
    """Ensures the bot does not attempt to grant permissions it does not possess."""
    return discord.Permissions(target_perms.value & bot_perms.value)

def generate_layout(role_map: Dict[str, discord.Role], guild: discord.Guild) -> List[Dict]:
    default_role = guild.default_role
    verified_role = role_map.get("Verified")
    
    # VERIFICATION: Everyone can read, nobody can send except bots.
    verification_overwrites = {
        default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False)
    }
    if verified_role:
        verification_overwrites[verified_role] = discord.PermissionOverwrite(read_messages=False)
    
    # PUBLIC: Unverified cannot read. Verified can read and send.
    public_overwrites = {
        default_role: discord.PermissionOverwrite(read_messages=False)
    }
    if verified_role:
        public_overwrites[verified_role] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
        
    # STAFF: Only Staff can read.
    staff_overwrites = {
        default_role: discord.PermissionOverwrite(read_messages=False)
    }
    for staff_name in ["Founder", "Owner", "Manager", "Administrator", "Moderator", "Support"]:
        if staff_name in role_map:
            staff_overwrites[role_map[staff_name]] = discord.PermissionOverwrite(read_messages=True, send_messages=True)
            
    # MANAGER LOUNGE: Only Founder, Owner, Manager
    manager_lounge_overwrites = {
        default_role: discord.PermissionOverwrite(read_messages=False)
    }
    for senior in ["Founder", "Owner", "Manager"]:
        if senior in role_map:
            manager_lounge_overwrites[role_map[senior]] = discord.PermissionOverwrite(read_messages=True, send_messages=True)

    # VEYRA SYSTEM: Only Founder, Owner, Manager, Developer (Read-only for logs usually)
    system_overwrites = {
        default_role: discord.PermissionOverwrite(read_messages=False)
    }
    for r in ["Founder", "Owner", "Manager", "Developer"]:
        if r in role_map:
            system_overwrites[role_map[r]] = discord.PermissionOverwrite(read_messages=True, send_messages=False)
            
    return [
        {
            "type": "category",
            "name": "VERIFICATION",
            "overwrites": verification_overwrites,
            "channels": [
                {"type": "text", "name": "🔐・verification", "purpose": "verification_channel_id"},
                {"type": "text", "name": "📜・verification-rules"}
            ]
        },
        {
            "type": "category",
            "name": "VEY LORA INFORMATION",
            "overwrites": public_overwrites,
            "channels": [
                {"type": "text", "name": "📌・welcome", "purpose": "welcome_channel_id", "topic": "Welcome to Veylora!"},
                {"type": "text", "name": "👋・goodbye", "purpose": "leave_channel_id", "topic": "Farewell from Veylora!"},
                {"type": "text", "name": "📜・rules", "topic": "Read the Veylora community rules before participating."},
                {"type": "text", "name": "📢・announcements", "purpose": "announcement_channel_id", "topic": "Official Veylora announcements and important updates."},
                {"type": "text", "name": "📰・minecraft-news", "topic": "Latest Minecraft news and official updates."},
                {"type": "text", "name": "🔗・links"}
            ]
        },
        {
            "type": "category",
            "name": "COMMUNITY",
            "overwrites": public_overwrites,
            "channels": [
                {"type": "text", "name": "💬・general"},
                {"type": "text", "name": "🎮・minecraft"},
                {"type": "text", "name": "📸・media"},
                {"type": "text", "name": "🤖・bot-commands"},
                {"type": "text", "name": "🎉・events"}
            ]
        },
        {
            "type": "category",
            "name": "MINECRAFT CONTENT",
            "overwrites": public_overwrites,
            "channels": [
                {"type": "text", "name": "📰・news"},
                {"type": "text", "name": "🧩・mods", "topic": "Discover new Minecraft mods and releases."},
                {"type": "text", "name": "🔧・plugins", "topic": "Discover Minecraft plugins and server tools."},
                {"type": "text", "name": "📦・modpacks"},
                {"type": "text", "name": "🎨・resource-packs"},
                {"type": "text", "name": "🗺️・datapacks"},
                {"type": "text", "name": "📺・youtube"},
                {"type": "text", "name": "🔥・trending"}
            ]
        },
        {
            "type": "category",
            "name": "SUPPORT",
            "purpose": "ticket_category_id",
            "overwrites": public_overwrites,
            "channels": [
                {"type": "text", "name": "🎫・create-ticket"},
                {"type": "text", "name": "❓・help"}
            ]
        },
        {
            "type": "category",
            "name": "STAFF",
            "overwrites": staff_overwrites,
            "channels": [
                {"type": "text", "name": "💼・manager-lounge", "overwrites": manager_lounge_overwrites},
                {"type": "text", "name": "🛡️・staff-chat"},
                {"type": "text", "name": "🔨・moderation"},
                {"type": "text", "name": "📋・staff-logs", "purpose": "staff_log_channel_id"}
            ]
        },
        {
            "type": "category",
            "name": "VEYRA SYSTEM",
            "overwrites": system_overwrites,
            "channels": [
                {"type": "text", "name": "🤖・veyra-logs", "purpose": "log_channel_id"},
                {"type": "text", "name": "🔐・security-logs", "purpose": "security_log_channel_id"},
                {"type": "text", "name": "📊・analytics"}
            ]
        }
    ]

async def get_setup_state(guild_id: int) -> str:
    res = await db.fetch_one("SELECT value FROM guild_config WHERE guild_id = ? AND key = ?", (guild_id, "auto_setup_state"))
    return res["value"] if res else SETUP_STATE_NOT_STARTED

async def set_setup_state(guild_id: int, state: str):
    await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (guild_id, "auto_setup_state", state))

async def save_server_layout(guild_id: int, obj_type: str, obj_name: str, discord_id: int, parent_id: Optional[int] = None):
    await db.execute(
        """
        INSERT OR REPLACE INTO server_layout 
        (guild_id, object_type, object_name, discord_id, parent_id) 
        VALUES (?, ?, ?, ?, ?)
        """,
        (guild_id, obj_type, obj_name, discord_id, parent_id)
    )

async def get_server_layout(guild_id: int, obj_type: str, obj_name: str) -> Optional[int]:
    row = await db.fetch_one(
        "SELECT discord_id FROM server_layout WHERE guild_id = ? AND object_type = ? AND object_name = ?",
        (guild_id, obj_type, obj_name)
    )
    return row["discord_id"] if row else None


class AutoSetupEngine:
    def __init__(self, guild: discord.Guild):
        self.guild = guild
        self.role_map: Dict[str, discord.Role] = {}

    async def run(self, interaction: discord.Interaction, is_repair: bool = False):
        state = await get_setup_state(self.guild.id)
        if state == SETUP_STATE_COMPLETE and not is_repair:
            await safe_reply(interaction, VeyraEmbed.info("Setup Status", "Setup is already complete. Use `/auto repair` if you need to fix missing objects."), ephemeral=False)
            return
            
        await set_setup_state(self.guild.id, SETUP_STATE_IN_PROGRESS)
        
        try:
            # Step 1: Roles
            await self._process_roles()
            
            # Step 2: Categories & Channels
            layout = generate_layout(self.role_map, self.guild)
            await self._process_layout(layout)
            
            from permissions import clear_permission_cache
            clear_permission_cache(self.guild.id)
            
            await set_setup_state(self.guild.id, SETUP_STATE_COMPLETE)
            
            embed = VeyraEmbed.success("Setup Complete", "The Veylora baseline structure is fully configured.")
            await safe_reply(interaction, embed, ephemeral=False)
            
        except Exception as e:
            log.error(f"Setup failed for guild {self.guild.id}: {e}")
            await set_setup_state(self.guild.id, SETUP_STATE_PARTIAL)
            embed = VeyraEmbed.error("Setup Failed", f"An error occurred: {e}\n\nState is marked as PARTIAL. Run `/auto repair` to resume.")
            await safe_reply(interaction, embed, ephemeral=False)

    async def _process_roles(self):
        bot_perms = self.guild.me.guild_permissions
        existing_roles = {r.name: r for r in self.guild.roles}
        
        for rdef in ROLES:
            name = rdef["name"]
            stored_id = await get_server_layout(self.guild.id, "role", name)
            
            role = None
            if stored_id:
                role = self.guild.get_role(stored_id)
                
            if not role and name in existing_roles:
                role = existing_roles[name]
                
            if not role:
                log.info(f"Creating role: {name}")
                safe_perms = safe_permissions(bot_perms, rdef["perms"])
                try:
                    role = await self.guild.create_role(
                        name=name, 
                        color=rdef["color"], 
                        hoist=rdef["hoist"], 
                        permissions=safe_perms,
                        reason="Veyra Auto Setup"
                    )
                except discord.Forbidden:
                    raise VeyraError(f"Missing permissions to create role: {name}")
                
            self.role_map[name] = role
            await save_server_layout(self.guild.id, "role", name, role.id)
            
            # Update role_hierarchy table
            await db.execute(
                "INSERT OR REPLACE INTO role_hierarchy (guild_id, role_id, role_level, description) VALUES (?, ?, ?, ?)",
                (self.guild.id, role.id, rdef["level"], name)
            )
            # Special case for Verified role storage
            if name == "Verified":
                await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (self.guild.id, "verified_role_id", str(role.id)))

    async def _process_layout(self, layout: List[Dict]):
        existing_categories = {c.name: c for c in self.guild.categories}
        existing_channels = {c.name: c for c in self.guild.channels}
        
        for cat_def in layout:
            cat_name = cat_def["name"]
            stored_cat_id = await get_server_layout(self.guild.id, "category", cat_name)
            
            category = None
            if stored_cat_id:
                category = self.guild.get_channel(stored_cat_id)
                
            if not category and cat_name in existing_categories:
                category = existing_categories[cat_name]
                
            if not category:
                log.info(f"Creating category: {cat_name}")
                overwrites = cat_def.get("overwrites", {})
                try:
                    category = await self.guild.create_category(
                        name=cat_name,
                        overwrites=overwrites,
                        reason="Veyra Auto Setup"
                    )
                except discord.Forbidden:
                    raise VeyraError(f"Missing permissions to create category: {cat_name}")
                    
            await save_server_layout(self.guild.id, "category", cat_name, category.id)
            
            if "purpose" in cat_def:
                await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (self.guild.id, cat_def["purpose"], str(category.id)))

            for ch_def in cat_def.get("channels", []):
                ch_name = ch_def["name"]
                stored_ch_id = await get_server_layout(self.guild.id, "channel", ch_name)
                
                channel = None
                if stored_ch_id:
                    channel = self.guild.get_channel(stored_ch_id)
                    
                if not channel and ch_name in existing_channels:
                    channel = existing_channels[ch_name]
                    # Attempt best-effort category realignment if misaligned
                    if channel.category_id != category.id:
                        try:
                            await channel.edit(category=category, reason="Veyra Auto Setup category realignment")
                        except discord.Forbidden:
                            pass 
                            
                if not channel:
                    log.info(f"Creating channel: {ch_name}")
                    topic = ch_def.get("topic", None)
                    ch_overwrites = ch_def.get("overwrites", category.overwrites)
                    try:
                        channel = await self.guild.create_text_channel(
                            name=ch_name,
                            category=category,
                            topic=topic,
                            overwrites=ch_overwrites,
                            reason="Veyra Auto Setup"
                        )
                    except discord.Forbidden:
                        raise VeyraError(f"Missing permissions to create channel: {ch_name}")
                        
                await save_server_layout(self.guild.id, "channel", ch_name, channel.id, category.id)
                
                if "purpose" in ch_def:
                    await db.execute("INSERT OR REPLACE INTO guild_config (guild_id, key, value) VALUES (?, ?, ?)", (self.guild.id, ch_def["purpose"], str(channel.id)))


class AutoGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="auto", description="Veylora Auto-Setup and Auto-Repair commands")

    async def _check_prerequisites(self, interaction: discord.Interaction) -> bool:
        if not interaction.guild:
            await safe_reply(interaction, VeyraEmbed.error("Guild Only", "This command can only be used in a server."))
            return False
            
        if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
            await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to run setup."))
            return False
            
        required_perms = ["manage_channels", "manage_roles", "view_audit_log", "send_messages", "embed_links", "read_message_history"]
        missing = [p for p in required_perms if not getattr(interaction.guild.me.guild_permissions, p, False)]
        if missing:
            await safe_reply(interaction, VeyraEmbed.error("Bot Missing Permissions", f"Veyra is missing required Discord permissions: {', '.join(missing)}"))
            return False
            
        if interaction.guild.id in _setup_locks:
            await safe_reply(interaction, VeyraEmbed.warning("Setup in Progress", "Veyra setup is already running for this guild."))
            return False
            
        return True

    @app_commands.command(name="setup", description="Run the Veylora Auto-Setup process")
    @app_commands.default_permissions(manage_guild=True)
    async def setup(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction):
            return
            
        _setup_locks.add(interaction.guild.id)
        try:
            await interaction.response.defer(thinking=True, ephemeral=False)
            engine = AutoSetupEngine(interaction.guild)
            await engine.run(interaction, is_repair=False)
        finally:
            _setup_locks.remove(interaction.guild.id)

    @app_commands.command(name="repair", description="Repair missing or broken Veylora server structures")
    @app_commands.default_permissions(manage_guild=True)
    async def repair(self, interaction: discord.Interaction):
        if not await self._check_prerequisites(interaction):
            return
            
        _setup_locks.add(interaction.guild.id)
        try:
            await interaction.response.defer(thinking=True, ephemeral=False)
            engine = AutoSetupEngine(interaction.guild)
            await engine.run(interaction, is_repair=True)
        finally:
            _setup_locks.remove(interaction.guild.id)

    @app_commands.command(name="status", description="Check the status of the Veylora server structure")
    @app_commands.default_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await safe_reply(interaction, VeyraEmbed.error("Guild Only", "This command can only be used in a server."))
            
        if not await has_veyra_level(interaction.user, PermissionLevel.MANAGER) and interaction.guild.owner_id != interaction.user.id:
            return await safe_reply(interaction, VeyraEmbed.error("Permission Denied", "You must be a Manager or higher to run setup."))

        await interaction.response.defer(thinking=True, ephemeral=False)
        
        state = await get_setup_state(interaction.guild.id)
        
        rows = await db.fetch_all("SELECT object_type, object_name, discord_id FROM server_layout WHERE guild_id = ?", (interaction.guild.id,))
        
        expected = len(rows)
        existing = 0
        missing = []
        
        for row in rows:
            obj_type = row["object_type"]
            obj_id = row["discord_id"]
            name = row["object_name"]
            
            found = False
            if obj_type == "role":
                found = interaction.guild.get_role(obj_id) is not None
            elif obj_type in ("category", "channel"):
                found = interaction.guild.get_channel(obj_id) is not None
                
            if found:
                existing += 1
            else:
                missing.append(f"{obj_type.capitalize()}: {name}")
                
        embed = VeyraEmbed.info("Auto Setup Status", f"**State:** {state}")
        embed.add_field(name="Expected Objects", value=str(expected), inline=True)
        embed.add_field(name="Existing Objects", value=str(existing), inline=True)
        embed.add_field(name="Missing Objects", value=str(len(missing)), inline=True)
        
        if missing:
            missing_str = "\n".join(missing[:10])
            if len(missing) > 10:
                missing_str += f"\n... and {len(missing)-10} more."
            embed.add_field(name="Missing Details", value=missing_str, inline=False)
            
        await safe_reply(interaction, embed, ephemeral=False)

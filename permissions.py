import discord
from config import config
from database import db
from embeds import VeyraEmbed
from typing import Dict, Optional

class PermissionLevel:
    """Permission levels for Veyra RBAC system."""
    FOUNDER = 9
    OWNER = 8
    MANAGER = 7
    ADMINISTRATOR = 6
    MODERATOR = 5
    SUPPORT = 4
    DEVELOPER = 3
    VERIFIED = 2
    MEMBER = 1
    UNVERIFIED = 0

_role_level_cache: Dict[int, Dict[int, int]] = {} # guild_id -> {role_id -> level}

def clear_permission_cache(guild_id: Optional[int] = None):
    """Clears the RBAC permission cache."""
    if guild_id:
        _role_level_cache.pop(guild_id, None)
    else:
        _role_level_cache.clear()

async def get_guild_role_levels(guild_id: int) -> Dict[int, int]:
    """Gets the role level mapping for a guild, using cache."""
    if guild_id in _role_level_cache:
        return _role_level_cache[guild_id]
        
    rows = await db.fetch_all("SELECT role_id, role_level FROM role_hierarchy WHERE guild_id = ?", (guild_id,))
    mapping = {row["role_id"]: row["role_level"] for row in rows}
    _role_level_cache[guild_id] = mapping
    return mapping

def is_founder(user_id: int) -> bool:
    """Checks if a user ID matches the configured Founder ID."""
    founder_id = config.get_founder_id()
    return founder_id is not None and user_id == founder_id

def is_guild_owner(member: discord.Member) -> bool:
    """Checks if a member is the Discord guild owner."""
    return member.guild.owner_id == member.id

async def get_highest_veyra_role(member: discord.Member) -> int:
    """Calculates the highest Veyra RBAC level for a member based on role mapping."""
    if is_founder(member.id):
        return PermissionLevel.FOUNDER
    if is_guild_owner(member):
        return PermissionLevel.OWNER
        
    guild_roles = await get_guild_role_levels(member.guild.id)
    
    max_level = PermissionLevel.UNVERIFIED
    for role in member.roles:
        if role.id in guild_roles:
            max_level = max(max_level, guild_roles[role.id])
            
    return max_level

async def get_veyra_level(member: discord.Member) -> int:
    """Alias for get_highest_veyra_role."""
    return await get_highest_veyra_role(member)

async def has_veyra_level(member: discord.Member, required_level: int) -> bool:
    """Checks if a member has the required Veyra RBAC permission level."""
    return await get_veyra_level(member) >= required_level

async def can_execute(member: discord.Member, required_level: int) -> bool:
    """Checks if a member can execute a command requiring a specific level."""
    return await has_veyra_level(member, required_level)

def can_manage_member(bot_member: discord.Member, target_member: discord.Member) -> bool:
    """Checks if the bot's hierarchy permits managing the target member."""
    if is_guild_owner(target_member):
        return False
    if bot_member == target_member:
        return False
    return bot_member.top_role > target_member.top_role

def can_manage_role(bot_member: discord.Member, target_role: discord.Role) -> bool:
    """Checks if the bot's hierarchy permits managing the target role."""
    return bot_member.top_role > target_role

async def can_target(issuer: discord.Member, target_member: discord.Member) -> bool:
    """Checks if the issuer is allowed to target the target member based on Veyra RBAC and Discord Hierarchy."""
    if is_founder(target_member.id) and not is_founder(issuer.id):
        return False
    if is_guild_owner(target_member) and not is_founder(issuer.id):
        return False
    if issuer == target_member:
        return False
        
    issuer_level = await get_veyra_level(issuer)
    target_level = await get_veyra_level(target_member)
    
    if target_level >= issuer_level and not is_founder(issuer.id):
        return False
        
    return issuer.top_role > target_member.top_role

def has_native_permission(bot_member: discord.Member, perm_name: str) -> bool:
    """Checks if the bot has a specific Discord native permission."""
    return getattr(bot_member.guild_permissions, perm_name, False)

def permission_denied_response(reason: str) -> discord.Embed:
    """Generates a standard permission denied embed."""
    return VeyraEmbed.error("Permission Denied", reason)

# Custom app_commands checks
def check_is_founder():
    async def predicate(interaction: discord.Interaction) -> bool:
        return is_founder(interaction.user.id)
    return discord.app_commands.check(predicate)

def check_has_level(level: int):
    async def predicate(interaction: discord.Interaction) -> bool:
        if isinstance(interaction.user, discord.Member):
            return await has_veyra_level(interaction.user, level)
        return False
    return discord.app_commands.check(predicate)

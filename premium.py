import discord
import random
from typing import Optional, Dict, List
from embeds import VeyraEmbed

# Bounded history to prevent repetition per guild
_recent_gifs: Dict[int, List[str]] = {}
MAX_HISTORY = 10

# Note: These are placeholder URLs for the premium presentation engine.
# In a real DisCloud production environment, these should be replaced with
# fully verified Minecraft-themed GIF URLs from Tenor/Giphy.
# ============================================================
# MANUAL MINECRAFT GIF LIBRARY
# Paste your own verified Minecraft GIF URLs below.
#
# Example:
# "https://example.com/my-minecraft-gif.gif"
#
# Do NOT remove the quotes.
# Do NOT paste image pages instead of direct media URLs.
# ============================================================
MINECRAFT_MEDIA: Dict[str, List[str]] = {
    # --- EVENT MEDIA ---
    "welcome": [
        "{PASTE_WELCOME_MINECRAFT_GIF_URL_HERE}"
    ],
    "goodbye": [
        "{PASTE_GOODBYE_MINECRAFT_GIF_URL_HERE}"
    ],
    "verification": [
        "{PASTE_VERIFICATION_MINECRAFT_GIF_URL_HERE}"
    ],
    "role_upgrade": [
        "{PASTE_RANK_UP_MINECRAFT_GIF_URL_HERE}"
    ],
    "role_downgrade": [
        "{PASTE_RANK_DOWN_MINECRAFT_GIF_URL_HERE}"
    ],
    "ticket": [
        "{PASTE_TICKET_MINECRAFT_GIF_URL_HERE}"
    ],
    "ticket_closed": [
        "{PASTE_TICKET_CLOSED_MINECRAFT_GIF_URL_HERE}"
    ],
    "announcement": [
        "{PASTE_ANNOUNCEMENT_MINECRAFT_GIF_URL_HERE}"
    ],

    # --- MINECRAFT KEYWORD MEDIA ---
    "steve": [
        "{PASTE_STEVE_MINECRAFT_GIF_URL_HERE}"
    ],
    "alex": [
        "{PASTE_ALEX_MINECRAFT_GIF_URL_HERE}"
    ],
    "creeper": [
        "{PASTE_CREEPER_MINECRAFT_GIF_URL_HERE}"
    ],
    "zombie": [
        "{PASTE_ZOMBIE_MINECRAFT_GIF_URL_HERE}"
    ],
    "skeleton": [
        "{PASTE_SKELETON_MINECRAFT_GIF_URL_HERE}"
    ],
    "enderman": [
        "{PASTE_ENDERMAN_MINECRAFT_GIF_URL_HERE}"
    ],
    "warden": [
        "{PASTE_WARDEN_MINECRAFT_GIF_URL_HERE}"
    ],
    "villager": [
        "{PASTE_VILLAGER_MINECRAFT_GIF_URL_HERE}"
    ],
    "diamond": [
        "{PASTE_DIAMOND_MINECRAFT_GIF_URL_HERE}"
    ],
    "netherite": [
        "{PASTE_NETHERITE_MINECRAFT_GIF_URL_HERE}"
    ],
    "ender": [
        "{PASTE_ENDER_MINECRAFT_GIF_URL_HERE}"
    ],
    "enderdragon": [
        "{PASTE_ENDER_DRAGON_MINECRAFT_GIF_URL_HERE}"
    ],
    "dragon": [
        "{PASTE_DRAGON_MINECRAFT_GIF_URL_HERE}"
    ],
    "wither": [
        "{PASTE_WITHER_MINECRAFT_GIF_URL_HERE}"
    ],
    "bedrock": [
        "{PASTE_BEDROCK_MINECRAFT_GIF_URL_HERE}"
    ],
    "redstone": [
        "{PASTE_REDSTONE_MINECRAFT_GIF_URL_HERE}"
    ],
    "tnt": [
        "{PASTE_TNT_MINECRAFT_GIF_URL_HERE}"
    ],
    "pvp": [
        "{PASTE_PVP_MINECRAFT_GIF_URL_HERE}"
    ],
    "sword": [
        "{PASTE_SWORD_MINECRAFT_GIF_URL_HERE}"
    ],
    "crystal": [
        "{PASTE_CRYSTAL_PVP_MINECRAFT_GIF_URL_HERE}"
    ],
    "totem": [
        "{PASTE_TOTEM_MINECRAFT_GIF_URL_HERE}"
    ],
    "elytra": [
        "{PASTE_ELYTRA_MINECRAFT_GIF_URL_HERE}"
    ],
    "nether": [
        "{PASTE_NETHER_MINECRAFT_GIF_URL_HERE}"
    ],
    "end": [
        "{PASTE_END_MINECRAFT_GIF_URL_HERE}"
    ],
    "overworld": [
        "{PASTE_OVERWORLD_MINECRAFT_GIF_URL_HERE}"
    ],
    "mining": [
        "{PASTE_MINING_MINECRAFT_GIF_URL_HERE}"
    ],
    "crafting": [
        "{PASTE_CRAFTING_MINECRAFT_GIF_URL_HERE}"
    ],
    "building": [
        "{PASTE_BUILDING_MINECRAFT_GIF_URL_HERE}"
    ],
    "raid": [
        "{PASTE_RAID_MINECRAFT_GIF_URL_HERE}"
    ],
    "raidboss": [
        "{PASTE_RAIDBOSS_MINECRAFT_GIF_URL_HERE}"
    ],
    "pro": [
        "{PASTE_PRO_MINECRAFT_GIF_URL_HERE}"
    ],
    "legend": [
        "{PASTE_LEGEND_MINECRAFT_GIF_URL_HERE}"
    ],
    "king": [
        "{PASTE_KING_MINECRAFT_GIF_URL_HERE}"
    ],
    "queen": [
        "{PASTE_QUEEN_MINECRAFT_GIF_URL_HERE}"
    ]
}

def is_valid_media_url(url: str) -> bool:
    """Checks if a URL is a valid media URL, rejecting placeholders and empty strings."""
    if not url or not isinstance(url, str):
        return False
    url = url.strip()
    if not url.startswith("http://") and not url.startswith("https://"):
        return False
    if "{" in url or "}" in url or "PASTE_" in url or "HERE" in url:
        return False
    return True

def get_minecraft_gif(guild_id: int, category: str, username: str = None) -> Optional[str]:
    """Selects a random Minecraft GIF based on category and intelligent username matching."""
    candidates = []
    
    # 1. Intelligent Username Matching
    if username:
        norm_name = username.lower().strip()
        
        # Exact/Strong Keyword Match & Display-name fragment match & Character match
        for key in MINECRAFT_MEDIA.keys():
            if key in norm_name:
                candidates = [url for url in MINECRAFT_MEDIA.get(key, []) if is_valid_media_url(url)]
                if candidates:
                    break
                    
    # 2. Event Category Fallback
    if not candidates:
        candidates = [url for url in MINECRAFT_MEDIA.get(category, []) if is_valid_media_url(url)]
        
    # 3. Global Fallback
    if not candidates:
        candidates = [url for url in MINECRAFT_MEDIA.get("welcome", []) if is_valid_media_url(url)]
        
    if not candidates:
        return None
        
    return _select_and_record_gif(guild_id, candidates)

def _select_and_record_gif(guild_id: int, candidates: List[str]) -> str:
    if guild_id not in _recent_gifs:
        _recent_gifs[guild_id] = []
        
    recent = _recent_gifs[guild_id]
    available = [c for c in candidates if c not in recent]
    
    if not available:
        available = candidates  # Reset pool if all have been recently used
        
    selected = random.choice(available)
    
    recent.append(selected)
    if len(recent) > MAX_HISTORY:
        recent.pop(0)
        
    return selected

def premium_welcome(member: discord.Member, custom_title: Optional[str] = None, custom_message: Optional[str] = None) -> discord.Embed:
    """Builds a premium Minecraft-themed welcome embed."""
    title = custom_title or "✨ WELCOME TO THE SERVER"
    title = title.replace("{server}", member.guild.name)
    
    desc = custom_message or f"Welcome, **{member.display_name}**!\n\nYou are now member **#{member.guild.member_count:,}** of our community.\n\n🎮 Explore the community\n🛡️ Complete verification\n💎 Check out the latest content"
    desc = desc.replace("{user}", member.mention).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count))
    
    embed = VeyraEmbed(title=title, description=desc, color=VeyraEmbed.SUCCESS_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    gif_url = get_minecraft_gif(member.guild.id, "welcome", member.display_name)
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{member.guild.name} • Premium Community", icon_url=member.guild.icon.url if member.guild.icon else None)
    return embed

def premium_goodbye(member: discord.Member, custom_message: Optional[str] = None) -> discord.Embed:
    """Builds a premium Minecraft-themed goodbye embed."""
    desc = custom_message or f"Farewell, **{member.display_name}**.\n\nWe hope to see you again soon."
    desc = desc.replace("{user}", member.display_name).replace("{server}", member.guild.name).replace("{count}", str(member.guild.member_count))
    
    embed = VeyraEmbed(title="👋 MEMBER DEPARTED", description=desc, color=VeyraEmbed.ERROR_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    gif_url = get_minecraft_gif(member.guild.id, "goodbye", member.display_name)
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{member.guild.name} • Remaining: {member.guild.member_count:,}", icon_url=member.guild.icon.url if member.guild.icon else None)
    return embed

def premium_verification(member: discord.Member) -> discord.Embed:
    """Builds a premium Minecraft-themed verification success embed."""
    embed = VeyraEmbed.success("🏆 Achievement Unlocked!", f"Welcome to the community, **{member.display_name}**.\n\nYour access has been verified.")
    embed.set_thumbnail(url=member.display_avatar.url)
    
    gif_url = get_minecraft_gif(member.guild.id, "verification", member.display_name)
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{member.guild.name} • Verified", icon_url=member.guild.icon.url if member.guild.icon else None)
    return embed

def premium_role_upgrade(member: discord.Member, old_role: str, new_role: str) -> discord.Embed:
    """Builds a premium Minecraft-themed role upgrade embed."""
    embed = VeyraEmbed(title="⭐ Rank Up!", description=f"Congratulations, **{member.display_name}**!\n\nYou have been promoted.\n\n`{old_role}` ➔ `{new_role}`", color=VeyraEmbed.SUCCESS_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    gif_url = get_minecraft_gif(member.guild.id, "role_upgrade", member.display_name)
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{member.guild.name} • Promotion", icon_url=member.guild.icon.url if member.guild.icon else None)
    return embed

def premium_role_downgrade(member: discord.Member, old_role: str, new_role: str) -> discord.Embed:
    """Builds a premium Minecraft-themed role downgrade embed."""
    embed = VeyraEmbed(title="📉 Role Updated", description=f"**{member.display_name}**'s role has been updated.\n\n`{old_role}` ➔ `{new_role}`", color=VeyraEmbed.WARNING_COLOR)
    embed.set_thumbnail(url=member.display_avatar.url)
    
    gif_url = get_minecraft_gif(member.guild.id, "role_downgrade", member.display_name)
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{member.guild.name} • Role Update", icon_url=member.guild.icon.url if member.guild.icon else None)
    return embed

def premium_ticket_created(guild: discord.Guild, user: discord.Member) -> discord.Embed:
    """Builds a premium Minecraft-themed ticket creation embed."""
    embed = VeyraEmbed.info("📩 Support Ticket Created", f"Welcome to support, {user.mention}.\n\nEmeralds at the ready! Our support staff will be with you shortly. Please describe your issue clearly.")
    embed.set_thumbnail(url=user.display_avatar.url)
    
    gif_url = get_minecraft_gif(guild.id, "ticket")
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{guild.name} • Support", icon_url=guild.icon.url if guild.icon else None)
    return embed

def premium_ticket_closed(guild: discord.Guild, user_name: str) -> discord.Embed:
    """Builds a premium Minecraft-themed ticket closed embed."""
    embed = VeyraEmbed.success("🔒 Ticket Closed", f"This ticket was closed by **{user_name}**.\n\nThank you for reaching out.")
    
    gif_url = get_minecraft_gif(guild.id, "verification") # Use achievement gif for closure
    if gif_url:
        embed.set_image(url=gif_url)
        
    embed.set_footer(text=f"{guild.name} • Support", icon_url=guild.icon.url if guild.icon else None)
    return embed

def premium_announcement(guild: discord.Guild, title: str, message: str) -> discord.Embed:
    """Builds a premium Minecraft-themed announcement embed."""
    embed = VeyraEmbed.info(f"📢 {title}", message)
    
    # Use generic 'ticket' category since it usually implies communication/village for announcements
    # or let's add an 'announcement' category to the get_minecraft_gif fallback?
    # Actually, we can just use the global fallback or a specific one.
    gif_url = get_minecraft_gif(guild.id, "ticket")
    if gif_url:
        embed.set_thumbnail(url=gif_url)
        
    embed.set_footer(text=f"{guild.name} • Announcement", icon_url=guild.icon.url if guild.icon else None)
    return embed

import discord
from discord.ext import commands
from discord import app_commands
import json
import hashlib
from typing import Optional, Dict, List, Any
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging

from database import db
from embeds import VeyraEmbed
from permissions import PermissionLevel, require_permission, is_manager_or_higher
from registry import registry

log = logging.getLogger("veyra.content")

class ContentType(Enum):
    MINECRAFT_NEWS = "MINECRAFT_NEWS"
    MINECRAFT_UPDATE = "MINECRAFT_UPDATE"
    MOD = "MOD"
    MODPACK = "MODPACK"
    PLUGIN = "PLUGIN"
    RESOURCE_PACK = "RESOURCE_PACK"
    DATAPACK = "DATAPACK"
    YOUTUBE = "YOUTUBE"
    REDDIT = "REDDIT"
    OTHER = "OTHER"

@dataclass
class ContentItem:
    """Normalized internal representation for discovered content."""
    source_id: str
    external_id: str
    url: str
    title: str
    content_type: ContentType
    author: Optional[str] = None
    description: Optional[str] = None
    thumbnail_url: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    version: Optional[str] = None
    published_at: Optional[datetime] = None
    
    @property
    def fingerprint(self) -> str:
        """Deterministic fingerprint for duplicate detection."""
        # Simple SHA-256 of source + external_id
        # If no external_id, use url.
        unique_str = f"{self.source_id}::{self.external_id or self.url}"
        return hashlib.sha256(unique_str.encode('utf-8')).hexdigest()

class ContentSourceAdapter:
    """Base interface for all future content source adapters."""
    
    def __init__(self, source_id: str, guild_id: int, config: Dict[str, Any]):
        self.source_id = source_id
        self.guild_id = guild_id
        self.config = config
        
    async def fetch(self) -> List[ContentItem]:
        """Fetches raw data from the external source."""
        raise NotImplementedError("Subclasses must implement fetch()")
        
    def normalize(self, raw_data: Any) -> ContentItem:
        """Converts raw external data into a normalized ContentItem."""
        raise NotImplementedError("Subclasses must implement normalize()")
        
    def validate(self, item: ContentItem) -> bool:
        """Validates a normalized item before processing."""
        raise NotImplementedError("Subclasses must implement validate()")


class ContentService:
    """Core service for managing content sources and processing."""
    
    async def add_source(self, guild_id: int, source_id: str, source_type: str, url: str, channel_id: int, category: str = None) -> bool:
        """Registers a new content source for a guild."""
        try:
            await db.execute(
                '''INSERT INTO content_sources (guild_id, source_id, type, url, target_channel_id, category, enabled, config_json)
                   VALUES (?, ?, ?, ?, ?, ?, 1, '{}')
                   ON CONFLICT(guild_id, source_id) DO UPDATE SET
                   type=excluded.type, url=excluded.url, target_channel_id=excluded.target_channel_id, category=excluded.category, enabled=1''',
                (guild_id, source_id, source_type, url, channel_id, category)
            )
            return True
        except Exception as e:
            log.error(f"Failed to add content source: {e}")
            return False

    async def get_sources(self, guild_id: int) -> List[dict]:
        """Gets all content sources for a guild."""
        rows = await db.fetch_all("SELECT * FROM content_sources WHERE guild_id = ?", (guild_id,))
        return [dict(r) for r in rows]

    async def set_source_status(self, guild_id: int, source_id: str, enabled: bool) -> bool:
        """Enables or disables a content source."""
        res = await db.execute("UPDATE content_sources SET enabled = ? WHERE guild_id = ? AND source_id = ?", (int(enabled), guild_id, source_id))
        return res > 0
        
    async def check_duplicate(self, guild_id: int, item_hash: str) -> bool:
        """Checks if a content item already exists."""
        row = await db.fetch_one("SELECT 1 FROM content_items WHERE guild_id = ? AND item_hash = ?", (guild_id, item_hash))
        return row is not None

    async def save_item(self, guild_id: int, item: ContentItem) -> bool:
        """Saves a discovered content item into the database."""
        try:
            await db.execute(
                '''INSERT INTO content_items (
                    guild_id, item_hash, source_id, title, url, published_at, 
                    category, external_id, author, content_type, description, 
                    thumbnail_url, tags, version, discord_published
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)''',
                (
                    guild_id, item.fingerprint, item.source_id, item.title, item.url, 
                    item.published_at, None, item.external_id, item.author, 
                    item.content_type.name, item.description, item.thumbnail_url, 
                    ",".join(item.tags) if item.tags else None, item.version
                )
            )
            return True
        except Exception as e:
            log.error(f"Failed to save content item {item.external_id}: {e}")
            return False

    async def mark_published(self, guild_id: int, item_hash: str, message_id: int):
        await db.execute(
            "UPDATE content_items SET discord_published = 1, discord_message_id = ? WHERE guild_id = ? AND item_hash = ?",
            (message_id, guild_id, item_hash)
        )

    async def update_source_status(self, guild_id: int, source_id: str, success: bool):
        if success:
            await db.execute(
                "UPDATE content_sources SET last_fetch = CURRENT_TIMESTAMP, last_success = CURRENT_TIMESTAMP, failure_count = 0 WHERE guild_id = ? AND source_id = ?",
                (guild_id, source_id)
            )
        else:
            await db.execute(
                "UPDATE content_sources SET last_fetch = CURRENT_TIMESTAMP, failure_count = failure_count + 1 WHERE guild_id = ? AND source_id = ?",
                (guild_id, source_id)
            )

    async def get_due_sources(self) -> List[dict]:
        # Sources enabled and either never fetched or fetched > 15 mins ago
        # And exponential backoff: failure_count limits fetching
        query = '''
            SELECT * FROM content_sources 
            WHERE enabled = 1 
            AND (
                last_fetch IS NULL 
                OR strftime('%s', 'now') - strftime('%s', last_fetch) > (900 * (1 + failure_count))
            )
        '''
        rows = await db.fetch_all(query)
        return [dict(r) for r in rows]

content_service = ContentService()
registry.register("content", content_service)

class ContentSourceView(discord.ui.View):
    """Persistent view for content source management UI."""
    def __init__(self):
        super().__init__(timeout=None)
        
    @discord.ui.button(label="Refresh Status", style=discord.ButtonStyle.secondary, custom_id="veyra:content:refresh")
    async def refresh_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await is_manager_or_higher(interaction.user):
            await interaction.response.send_message(embed=VeyraEmbed.error("Permission Denied", "You must be a manager to use this."), ephemeral=True)
            return
            
        sources = await content_service.get_sources(interaction.guild_id)
        embed = build_content_embed(interaction.guild, sources)
        await interaction.response.edit_message(embed=embed)

def build_content_embed(guild: discord.Guild, sources: List[dict]) -> discord.Embed:
    """Builds the premium UI for content source configuration."""
    embed = VeyraEmbed.info("⛏️ Content Intelligence", f"Content sources configured for **{guild.name}**.")
    
    if not sources:
        embed.description += "\n\n*No sources currently configured.*"
    else:
        for s in sources:
            status = "🟢 Enabled" if s["enabled"] else "🔴 Disabled"
            channel_mention = f"<#{s['target_channel_id']}>" if s.get("target_channel_id") else "None"
            failures = f"\n⚠️ Failures: {s['failure_count']}" if s.get("failure_count", 0) > 0 else ""
            embed.add_field(
                name=f"{s['source_id']} ({s['type']})",
                value=f"**Status:** {status}\n**Channel:** {channel_mention}\n**URL:** {s['url']}{failures}",
                inline=False
            )
            
    embed.set_footer(text="Veyra Content Foundation", icon_url=guild.icon.url if guild.icon else None)
    return embed

from tasks import task_manager

def format_content_embed(item: ContentItem, guild_id: int) -> discord.Embed:
    from premium import get_minecraft_gif
    # Map ContentType to a nice icon
    type_icons = {
        ContentType.MINECRAFT_NEWS: "📰 Minecraft News",
        ContentType.MOD: "🧩 Mod",
        ContentType.MODPACK: "📦 Modpack",
        ContentType.RESOURCE_PACK: "🎨 Resource Pack",
        ContentType.DATAPACK: "⚙️ Datapack",
        ContentType.YOUTUBE: "🎥 YouTube",
        ContentType.REDDIT: "💬 Reddit",
        ContentType.OTHER: "🏷️ Content"
    }
    
    title = item.title
    if len(title) > 256: title = title[:253] + "..."
    
    desc = item.description or "No description provided."
    embed = VeyraEmbed.info(type_icons.get(item.content_type, "🏷️ Content"), title)
    embed.description = desc
    embed.url = item.url
    
    if item.author:
        embed.add_field(name="Author", value=item.author, inline=True)
    if item.version:
        embed.add_field(name="Version", value=item.version, inline=True)
        
    tags_str = ", ".join(item.tags[:3]) if item.tags else ""
    if tags_str:
        embed.add_field(name="Tags", value=tags_str, inline=True)
        
    if item.thumbnail_url:
        embed.set_thumbnail(url=item.thumbnail_url)
        
    if item.published_at:
        embed.timestamp = item.published_at
        
    embed.set_footer(text=f"Source: {item.source_id}")
    
    # Try to find a relevant Minecraft GIF based on tags or title
    search_term = (",".join(item.tags) + " " + item.title).lower()
    gif_url = get_minecraft_gif(guild_id, "announcement", search_term)
    if gif_url:
        embed.set_image(url=gif_url)
        
    return embed


async def _send_with_retry(channel: discord.abc.Messageable, embed: discord.Embed, view: Optional[discord.ui.View], source_id: str, item_external_id: str, max_attempts: int = 2) -> Optional[discord.Message]:
    """
    Conservative retry helper for sending messages to Discord.
    - Retries only on clearly retryable HTTP errors (429 or 5xx when surfaced by discord.py).
    - Does not retry on NotFound/Forbidden or ambiguous errors to avoid duplicates.
    - Returns the discord.Message on success, or None on permanent failure.
    """
    attempt = 0
    backoffs = [1, 3]
    while attempt < max_attempts:
        try:
            msg = await channel.send(embed=embed, view=view)
            return msg
        except discord.HTTPException as he:
            # discord.HTTPException may have status attribute in some cases
            status = getattr(he, 'status', None)
            # If rate-limited or server error, consider retrying once
            retryable = False
            if status == 429:
                retryable = True
            elif isinstance(status, int) and status >= 500:
                retryable = True

            # Log and record retry attempt
            try:
                await db.execute(
                    "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (channel.guild.id if getattr(channel, 'guild', None) else 0, "publish_retry_attempt", json.dumps({"source": source_id, "item": item_external_id, "attempt": attempt + 1, "error": str(status or he)}))
                )
            except: pass

            if not retryable or attempt + 1 >= max_attempts:
                # Permanent failure; record and return None
                try:
                    await db.execute(
                        "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                        (channel.guild.id if getattr(channel, 'guild', None) else 0, "publish_permanent_failure", json.dumps({"source": source_id, "item": item_external_id, "error": str(status or he)}))
                    )
                except: pass
                log.error(f"Permanent publish failure for source {source_id} item {item_external_id}: {he}")
                return None

            # Otherwise backoff and retry
            wait = backoffs[min(attempt, len(backoffs)-1)]
            await asyncio.sleep(wait)
            attempt += 1
            continue
        except Exception as e:
            # For ambiguous errors, do not retry to avoid duplicate posts
            try:
                await db.execute(
                    "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (getattr(channel, 'guild', None).id if getattr(channel, 'guild', None) else 0, "publish_permanent_failure", json.dumps({"source": source_id, "item": item_external_id, "error": str(e)}))
                )
            except: pass
            log.error(f"Non-retryable publish error for source {source_id} item {item_external_id}: {e}")
            return None


async def process_content_source(bot: commands.Bot, source: dict) -> int:
    guild_id = source['guild_id']
    source_id = source['source_id']
    source_type = source['type']
    url = source['url']
    channel_id = source['target_channel_id']
    
    import json
    config = {}
    if source.get('config_json'):
        try: config = json.loads(source['config_json'])
        except: pass

    from content_adapters import get_adapter
    adapter = get_adapter(source_type, source_id, guild_id, url, config)
    if not adapter:
        log.error(f"Unknown adapter type {source_type} for source {source_id}")
        await content_service.update_source_status(guild_id, source_id, False)
        return 0

    try:
        items = await adapter.fetch()
    except Exception as e:
        log.error(f"Failed to fetch {source_id}: {e}")
        await content_service.update_source_status(guild_id, source_id, False)
        try:
            await db.execute(
                "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                (guild_id, "content_fetch_failure", json.dumps({"source": source_id}))
            )
        except: pass
        return 0
        
    published_count = 0
    # Bound processing to avoid unbounded work per source
    PROCESS_MAX_ITEMS = 15
    if not isinstance(items, list):
        items = []

    for item in items[:PROCESS_MAX_ITEMS]:
        try:
            # Validate item via adapter (defensive)
            try:
                is_valid = adapter.validate(item)
            except Exception as e:
                log.warning(f"Adapter validation failed for item from {source_id}: {e}")
                continue

            if not is_valid:
                continue

            # Compute fingerprint defensively
            try:
                fp = item.fingerprint
            except Exception as e:
                log.warning(f"Failed to compute fingerprint for item {getattr(item, 'external_id', None)}: {e}")
                continue

            # Duplicate check
            try:
                if await content_service.check_duplicate(guild_id, fp):
                    continue
            except Exception as e:
                log.warning(f"Duplicate check failed for {fp}: {e}")
                # Skip this item rather than aborting the entire source
                continue
            
            # Persist item
            try:
                saved = await content_service.save_item(guild_id, item)
            except Exception as e:
                log.error(f"save_item raised for {getattr(item, 'external_id', None)}: {e}")
                saved = False

            if not saved:
                continue

            # Publish to Discord if channel configured
            if channel_id:
                channel = bot.get_channel(channel_id)
                if channel:
                    try:
                        embed = format_content_embed(item, guild_id)
                        view = discord.ui.View()
                        view.add_item(discord.ui.Button(label="View Content", url=item.url, style=discord.ButtonStyle.link))

                        # Use conservative retry helper
                        msg = await _send_with_retry(channel, embed, view, source_id, item.external_id, max_attempts=2)

                        if msg:
                            try:
                                await content_service.mark_published(guild_id, fp, msg.id)
                                published_count += 1
                                try:
                                    await db.execute(
                                        "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                                        (guild_id, "content_published", json.dumps({"source": source_id, "item": item.external_id}))
                                    )
                                except: pass
                            except Exception as e:
                                log.warning(f"Failed to mark_published for {fp}: {e}")
                    except Exception as e:
                        log.error(f"Unhandled publishing error for source {source_id}: {e}")
                else:
                    log.warning(f"Channel {channel_id} not found for {source_id}")

            # Log discovery (best-effort)
            try:
                await db.execute(
                    "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (guild_id, "content_discovered", json.dumps({"source": source_id, "item": item.external_id}))
                )
            except: pass

        except Exception as e:
            # Catch-all per-item to ensure one bad item cannot stop the whole source
            log.error(f"Error processing item from source {source_id}: {e}")
            continue
                    
    # Mark source as successfully processed (fetch & processing completed)
    try:
        await content_service.update_source_status(guild_id, source_id, True)
    except Exception as e:
        log.warning(f"Failed to update source status for {source_id}: {e}")

    try:
        await db.execute(
            "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
            (guild_id, "content_fetch_success", json.dumps({"source": source_id, "published": published_count}))
        )
    except: pass
    return published_count

import asyncio

async def content_polling_task(bot: commands.Bot):
    log.info("Content polling task started.")
    while True:
        try:
            sources = await content_service.get_due_sources()
            if sources:
                log.info(f"Polling {len(sources)} due content sources...")
                for source in sources:
                    try:
                        await process_content_source(bot, source)
                    except Exception as e:
                        log.error(f"Unhandled error in content source {source['source_id']}: {e}")
        except Exception as e:
            log.error(f"Error in content polling loop: {e}")
        
        await asyncio.sleep(60)

def start_content_scheduler(bot: commands.Bot):
    task_manager.register("content_polling", content_polling_task, bot)

class ContentGroup(app_commands.Group):
    """Manage Minecraft content discovery and publishing."""
    def __init__(self):
        super().__init__(name="content", description="Manage Minecraft content discovery and publishing.")

    @app_commands.command(name="sources", description="View content intelligence sources and their status.")
    async def sources(self, interaction: discord.Interaction):
        await self.status(interaction)

    @app_commands.command(name="status", description="View content intelligence status.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction):
        if not await is_manager_or_higher(interaction.user):
            await interaction.response.send_message(embed=VeyraEmbed.error("Permission Denied", "You need Manager permissions to view this."), ephemeral=True)
            return
            
        sources = await content_service.get_sources(interaction.guild_id)
        embed = build_content_embed(interaction.guild, sources)
        await interaction.response.send_message(embed=embed, view=ContentSourceView())

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
        """
        Determine which enabled sources are due for fetching.

        Behavior:
        - Read per-source `config_json` and use `poll_interval_seconds` when present and valid.
        - Default poll interval is 900 seconds when missing/invalid.
        - Preserve exponential backoff via `failure_count` by multiplying the interval by (1 + failure_count).
        - If `last_fetch` is NULL/None/unparseable, the source is considered due.
        - Returns a list of dict rows for sources that should be fetched now.
        """
        # Fetch all enabled sources and apply per-source logic in Python for safety and flexibility
        rows = await db.fetch_all("SELECT * FROM content_sources WHERE enabled = 1")
        now = datetime.now(timezone.utc)
        due_sources: List[dict] = []

        for row in rows:
            try:
                s = dict(row)
            except Exception:
                # Defensive: if row cannot be converted, skip it
                continue

            # Default poll interval (seconds)
            poll_interval = 900

            # Parse config_json safely
            cfg_json = s.get('config_json')
            if cfg_json:
                try:
                    cfg = json.loads(cfg_json)
                    pi = cfg.get('poll_interval_seconds')
                    if isinstance(pi, (int, float)):
                        poll_interval = int(pi)
                    elif isinstance(pi, str) and pi.isdigit():
                        poll_interval = int(pi)
                    # guard against non-positive values
                    if poll_interval <= 0:
                        poll_interval = 900
                except Exception:
                    log.warning(f"Invalid config_json for content source {s.get('source_id')}")
                    poll_interval = 900

            # Failure count exponential backoff multiplier
            try:
                failure_count = int(s.get('failure_count') or 0)
                if failure_count < 0:
                    failure_count = 0
            except Exception:
                failure_count = 0

            effective_interval = poll_interval * (1 + failure_count)

            # Parse last_fetch timestamp safely — SQLite CURRENT_TIMESTAMP commonly returns 'YYYY-MM-DD HH:MM:SS'
            last_fetch_ts = s.get('last_fetch')
            last_fetch_dt: Optional[datetime] = None
            if last_fetch_ts:
                try:
                    # Try ISO parsing first
                    last_fetch_dt = datetime.fromisoformat(last_fetch_ts)
                    if last_fetch_dt.tzinfo is None:
                        last_fetch_dt = last_fetch_dt.replace(tzinfo=timezone.utc)
                except Exception:
                    try:
                        # Fallback to common SQLite format without timezone
                        last_fetch_dt = datetime.strptime(last_fetch_ts, "%Y-%m-%d %H:%M:%S")
                        last_fetch_dt = last_fetch_dt.replace(tzinfo=timezone.utc)
                    except Exception:
                        log.warning(f"Unable to parse last_fetch '{last_fetch_ts}' for source {s.get('source_id')}; treating as never fetched")
                        last_fetch_dt = None

            # Decide due-ness
            if last_fetch_dt is None:
                due_sources.append(s)
                continue

            elapsed = (now - last_fetch_dt).total_seconds()
            if elapsed > effective_interval:
                due_sources.append(s)

        return due_sources

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

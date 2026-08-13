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

# Phase 10.7: threshold for automatic disabling of repeatedly failing sources
FAILURE_DISABLE_THRESHOLD = 5

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
        """Update last_fetch/failure_count and automatically disable repeat failures.

        Behavior:
        - On success: reset failure_count and update last_success (no disabling).
        - On failure: increment failure_count. If failure_count reaches FAILURE_DISABLE_THRESHOLD
          and the source is still enabled, disable it and record an analytics event.
        """
        if success:
            await db.execute(
                "UPDATE content_sources SET last_fetch = CURRENT_TIMESTAMP, last_success = CURRENT_TIMESTAMP, failure_count = 0 WHERE guild_id = ? AND source_id = ?",
                (guild_id, source_id)
            )
            return

        # On failure: increment failure_count first
        try:
            await db.execute(
                "UPDATE content_sources SET last_fetch = CURRENT_TIMESTAMP, failure_count = failure_count + 1 WHERE guild_id = ? AND source_id = ?",
                (guild_id, source_id)
            )
        except Exception as e:
            log.warning(f"Failed to increment failure_count for source {source_id} in guild {guild_id}: {e}")
            return

        # Read back the updated failure_count and enabled state
        try:
            row = await db.fetch_one("SELECT failure_count, enabled FROM content_sources WHERE guild_id = ? AND source_id = ?", (guild_id, source_id))
            if not row:
                return
            s = dict(row)
            fc = int(s.get('failure_count') or 0)
            enabled = int(s.get('enabled') or 0)
        except Exception as e:
            log.warning(f"Failed to read failure_count for source {source_id} in guild {guild_id}: {e}")
            return

        # If threshold reached and source is currently enabled, disable it and record analytics
        if fc >= FAILURE_DISABLE_THRESHOLD and enabled == 1:
            try:
                await db.execute("UPDATE content_sources SET enabled = 0 WHERE guild_id = ? AND source_id = ?", (guild_id, source_id))
            except Exception as e:
                log.warning(f"Failed to disable source {source_id} in guild {guild_id}: {e}")

            # Record a single analytics event for the auto-disable
            try:
                await db.execute(
                    "INSERT INTO analytics_events (guild_id, event_type, metadata, timestamp) VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    (guild_id, "content_auto_disabled", json.dumps({"source": source_id, "failure_count": fc}))
                )
            except Exception:
                pass

            log.warning(f"Auto-disabled content source {source_id} for guild {guild_id} after {fc} consecutive failures")

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

import aiohttp
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import logging
from typing import List, Any, Dict, Optional
import os

from content import ContentSourceAdapter, ContentItem, ContentType

log = logging.getLogger("veyra.content.adapters")

def _parse_xml_date(date_str: str) -> datetime:
    try:
        # basic parsing, RSS usually RFC-822, Atom usually ISO-8601
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(date_str)
    except:
        return datetime.now(timezone.utc)

class MinecraftNewsAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        url = "https://launchercontent.mojang.com/news.json"
        async with aiohttp.ClientSession(headers={"User-Agent": "Veyra Discord Bot"}) as session:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
            except Exception as e:
                log.error(f"Failed to fetch Minecraft News: {e}")
                return []
        
        entries = data.get("entries", [])
        items = []
        for entry in entries[:15]:
            try:
                items.append(self.normalize(entry))
            except Exception as e:
                log.error(f"Failed to normalize Minecraft News entry: {e}")
        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        # raw_data is a dict
        id_str = raw_data.get("id")
        title = raw_data.get("title", "Minecraft News")
        desc = raw_data.get("text", "")
        if len(desc) > 200: desc = desc[:197] + "..."
        url = raw_data.get("readMoreLink", "https://www.minecraft.net")
        
        thumb = None
        img_data = raw_data.get("newsPageImage") or raw_data.get("playPageImage")
        if img_data and img_data.get("url"):
            thumb = "https://launchercontent.mojang.com" + img_data.get("url")

        date_str = raw_data.get("date")
        pub_date = datetime.now(timezone.utc)
        if date_str:
            try:
                pub_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except:
                pass

        return ContentItem(
            source_id=self.source_id,
            external_id=id_str or title,
            url=url,
            title=title,
            content_type=ContentType.MINECRAFT_NEWS,
            description=desc,
            thumbnail_url=thumb,
            tags=raw_data.get("newsType", []),
            published_at=pub_date
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)

class ModrinthAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        slug = self.url.split('/')[-1] if 'modrinth.com' in self.url else self.url
        project_url = f"https://api.modrinth.com/v2/project/{slug}"
        versions_url = f"https://api.modrinth.com/v2/project/{slug}/version"
        
        async with aiohttp.ClientSession(headers={"User-Agent": "Veyra Discord Bot"}) as session:
            try:
                async with session.get(url, timeout=10) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
            except Exception as e:
                log.error(f"Failed to fetch Minecraft News: {e}")
                return []
                
        items = []
        mod_data = data.get("data")
        if mod_data:
            latest_files = mod_data.get("latestFilesIndexes", [])
            for f in latest_files[:5]:
                try:
                    items.append(self.normalize((mod_data, f)))
                except Exception as e:
                    pass
        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        mod, file_index = raw_data
        class_id = mod.get("classId")
        ct = ContentType.OTHER
        if class_id == 6: ct = ContentType.MOD
        elif class_id == 4471: ct = ContentType.MODPACK
        elif class_id == 12: ct = ContentType.RESOURCE_PACK
        
        desc = mod.get("summary", "")
        if len(desc) > 200: desc = desc[:197] + "..."
        
        thumb = None
        if mod.get("logo"):
            thumb = mod["logo"].get("url")
            
        return ContentItem(
            source_id=self.source_id,
            external_id=str(file_index.get("fileId", "")),
            url=mod.get("links", {}).get("websiteUrl", self.url),
            title=f"{mod.get('name')} {file_index.get('filename', '')}",
            content_type=ct,
            description=desc,
            thumbnail_url=thumb,
            version=file_index.get("gameVersion"),
            published_at=datetime.now(timezone.utc)
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)

class YouTubeAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        channel_id = self.url.split('channel/')[-1] if 'channel/' in self.url else self.url
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        if "feeds/videos.xml" in self.url:
            rss_url = self.url
            
        async with aiohttp.ClientSession(headers={'User-Agent': 'Veyra Discord Bot'}) as session:
            try:
                async with session.get(rss_url, timeout=10) as resp:
                    if resp.status != 200:
                        return []
                    xml_data = await resp.text()
            except Exception as e:
                log.error(f"Failed to fetch YouTube: {e}")
                return []
                
        root = ET.fromstring(xml_data)
        ns = {'yt': 'http://www.youtube.com/xml/schemas/2015', 'ns': 'http://www.w3.org/2005/Atom', 'media': 'http://search.yahoo.com/mrss/'}
        
        items = []
        for entry in root.findall('ns:entry', ns)[:10]:
            try:
                items.append(self.normalize((entry, ns)))
            except Exception as e:
                pass
        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        entry, ns = raw_data
        video_id = entry.find('yt:videoId', ns).text
        title = entry.find('ns:title', ns).text
        url = entry.find('ns:link', ns).attrib['href']
        author_el = entry.find('ns:author', ns)
        author = author_el.find('ns:name', ns).text if author_el is not None else None
        
        pub_date = _parse_xml_date(entry.find('ns:published', ns).text)
        
        media_group = entry.find('media:group', ns)
        desc = ""
        thumb = None
        if media_group is not None:
            desc_el = media_group.find('media:description', ns)
            if desc_el is not None and desc_el.text:
                desc = desc_el.text
            thumb_el = media_group.find('media:thumbnail', ns)
            if thumb_el is not None:
                thumb = thumb_el.attrib['url']
                
        if len(desc) > 200: desc = desc[:197] + "..."
        
        return ContentItem(
            source_id=self.source_id,
            external_id=video_id,
            url=url,
            title=title,
            content_type=ContentType.YOUTUBE,
            author=author,
            description=desc,
            thumbnail_url=thumb,
            published_at=pub_date
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)

class RedditAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        # URL should be a subreddit like https://www.reddit.com/r/Minecraft/new.rss
        rss_url = self.url
        if not rss_url.endswith(".rss"):
            rss_url = rss_url.rstrip("/") + "/new.rss"
            
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Veyra Discord Bot"}
        async with aiohttp.ClientSession(headers={'User-Agent': 'Veyra Discord Bot'}) as session:
            try:
                async with session.get(rss_url, timeout=10) as resp:
                    if resp.status != 200:
                        return []
                    xml_data = await resp.text()
            except Exception as e:
                log.error(f"Failed to fetch YouTube: {e}")
                return []
                
        root = ET.fromstring(xml_data)
        ns = {'ns': 'http://www.w3.org/2005/Atom'}
        
        items = []
        for entry in root.findall('ns:entry', ns)[:10]:
            try:
                items.append(self.normalize((entry, ns)))
            except Exception as e:
                pass
        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        entry, ns = raw_data
        post_id = entry.find('ns:id', ns).text
        title = entry.find('ns:title', ns).text
        url = entry.find('ns:link', ns).attrib['href']
        
        author_el = entry.find('ns:author', ns)
        author = author_el.find('ns:name', ns).text if author_el is not None else None
        
        pub_date = _parse_xml_date(entry.find('ns:updated', ns).text)
        
        content_el = entry.find('ns:content', ns)
        desc = content_el.text if content_el is not None and content_el.text else ""
        # Strip HTML rudimentarily for brief description
        import re
        desc_clean = re.sub('<[^<]+>', ' ', desc).strip()
        if len(desc_clean) > 200: desc_clean = desc_clean[:197] + "..."
        
        return ContentItem(
            source_id=self.source_id,
            external_id=post_id,
            url=url,
            title=title,
            content_type=ContentType.REDDIT,
            author=author,
            description=desc_clean,
            published_at=pub_date
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)


ADAPTERS = {
    "MINECRAFT_NEWS": MinecraftNewsAdapter,
    "MODRINTH": ModrinthAdapter,
    "CURSEFORGE": CurseForgeAdapter,
    "YOUTUBE": YouTubeAdapter,
    "REDDIT": RedditAdapter
}

def get_adapter(source_type: str, source_id: str, guild_id: int, url: str, config: Dict[str, Any]) -> Optional[ContentSourceAdapter]:
    adapter_class = ADAPTERS.get(source_type.upper())
    if adapter_class:
        adapter = adapter_class(source_id, guild_id, config)
        adapter.url = url
        return adapter
    return None

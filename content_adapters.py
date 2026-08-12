import aiohttp
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import logging
from typing import List, Any, Dict, Optional
import os
import asyncio
import time
from urllib.parse import urlparse

from content import ContentSourceAdapter, ContentItem, ContentType

log = logging.getLogger("veyra.content.adapters")

# Network / fetch helpers ----------------------------------------------------

DEFAULT_TIMEOUT = 10  # seconds per request
MAX_RETRIES = 2
MAX_ITEMS_PER_SOURCE = 15


def _is_valid_http_url(u: Optional[str]) -> bool:
    if not u or not isinstance(u, str):
        return False
    p = urlparse(u)
    return p.scheme in ("http", "https") and bool(p.netloc)


async def _fetch_with_retries(session: aiohttp.ClientSession, method: str, url: str, *, max_retries: int = MAX_RETRIES, **kwargs) -> Optional[aiohttp.ClientResponse]:
    """
    Perform a single HTTP request with bounded retries and respect for 429 Retry-After.
    Returns the final response object (caller must .read()/.text()/.json()) or None on permanent failure.
    """
    attempt = 0
    while attempt <= max_retries:
        try:
            timeout = kwargs.pop("timeout", aiohttp.ClientTimeout(total=DEFAULT_TIMEOUT))
            async with session.request(method, url, timeout=timeout, **kwargs) as resp:
                # Respect basic success and rate limiting
                if resp.status == 429:
                    retry_after = None
                    try:
                        ra = resp.headers.get("Retry-After")
                        if ra:
                            retry_after = int(ra)
                    except Exception:
                        retry_after = None

                    backoff = retry_after if retry_after is not None else (2 ** attempt)
                    backoff = min(backoff, 60)
                    log.warning(f"Rate limited when requesting {url}; retrying after {backoff}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue

                # For 5xx we may retry a bounded number of times
                if 500 <= resp.status < 600 and attempt < max_retries:
                    backoff = min(2 ** attempt, 30)
                    log.warning(f"Server error {resp.status} for {url}; retrying after {backoff}s (attempt {attempt + 1}/{max_retries})")
                    await asyncio.sleep(backoff)
                    attempt += 1
                    continue

                # Return the response for all other statuses; caller will handle non-200
                return resp
        except asyncio.TimeoutError:
            log.warning(f"Timeout fetching {url} (attempt {attempt + 1}/{max_retries})")
            attempt += 1
            await asyncio.sleep(min(2 ** attempt, 30))
        except aiohttp.ClientError as e:
            log.warning(f"Network error fetching {url}: {e} (attempt {attempt + 1}/{max_retries})")
            attempt += 1
            await asyncio.sleep(min(2 ** attempt, 30))
        except Exception as e:
            log.error(f"Unexpected error fetching {url}: {e}")
            return None

    log.error(f"Exceeded retries fetching {url}")
    return None


async def _fetch_json(session: aiohttp.ClientSession, url: str, **kwargs) -> Optional[Dict[str, Any]]:
    resp = await _fetch_with_retries(session, "GET", url, **kwargs)
    if not resp:
        return None
    try:
        if 200 <= resp.status < 300:
            return await resp.json()
        else:
            log.warning(f"Non-success HTTP {resp.status} for JSON at {url}")
            return None
    except Exception as e:
        log.warning(f"Failed to parse JSON from {url}: {e}")
        return None


async def _fetch_text(session: aiohttp.ClientSession, url: str, **kwargs) -> Optional[str]:
    resp = await _fetch_with_retries(session, "GET", url, **kwargs)
    if not resp:
        return None
    try:
        if 200 <= resp.status < 300:
            return await resp.text()
        else:
            log.warning(f"Non-success HTTP {resp.status} for text at {url}")
            return None
    except Exception as e:
        log.warning(f"Failed to read text from {url}: {e}")
        return None


# Adapters -------------------------------------------------------------------

class MinecraftNewsAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        url = "https://launchercontent.mojang.com/news.json"
        items: List[ContentItem] = []

        async with aiohttp.ClientSession(headers={"User-Agent": "Veyra Discord Bot"}) as session:
            data = await _fetch_json(session, url)
            if not data:
                return []

            entries = data.get("entries") or []
            count = min(len(entries), MAX_ITEMS_PER_SOURCE)
            for entry in entries[:count]:
                try:
                    ci = self.normalize(entry)
                    if ci:
                        items.append(ci)
                except Exception as e:
                    log.warning(f"MinecraftNewsAdapter.normalize failed for entry: {e}")
                    continue
        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        id_str = raw_data.get("id")
        title = raw_data.get("title") or "Minecraft News"
        desc = raw_data.get("text") or ""
        if isinstance(desc, str) and len(desc) > 200:
            desc = desc[:197] + "..."
        url = raw_data.get("readMoreLink") or "https://www.minecraft.net"
        if not _is_valid_http_url(url):
            url = "https://www.minecraft.net"

        thumb = None
        img_data = raw_data.get("newsPageImage") or raw_data.get("playPageImage")
        if isinstance(img_data, dict) and img_data.get("url"):
            # Keep remote URL only
            img_url = img_data.get("url")
            if img_url and img_url.startswith("/"):
                thumb = "https://launchercontent.mojang.com" + img_url
            elif _is_valid_http_url(img_url):
                thumb = img_url

        date_str = raw_data.get("date")
        pub_date = datetime.now(timezone.utc)
        if date_str:
            try:
                pub_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            except Exception:
                pass

        return ContentItem(
            source_id=self.source_id,
            external_id=id_str or title,
            url=url,
            title=title,
            content_type=ContentType.MINECRAFT_NEWS,
            description=desc or None,
            thumbnail_url=thumb,
            tags=raw_data.get("newsType") if isinstance(raw_data.get("newsType"), list) else [],
            published_at=pub_date
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)


class ModrinthAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        # Determine slug from provided URL or treat url as slug
        slug = self.url.split('/')[-1] if 'modrinth.com' in (self.url or "") else (self.url or "")
        if not slug:
            return []

        project_url = f"https://api.modrinth.com/v2/project/{slug}"
        versions_url = f"https://api.modrinth.com/v2/project/{slug}/version"

        items: List[ContentItem] = []
        async with aiohttp.ClientSession(headers={"User-Agent": "Veyra Discord Bot"}) as session:
            proj = await _fetch_json(session, project_url)
            if not proj:
                return []

            # The Modrinth API returns either a dict with project fields or a wrapper — try to be defensive
            try:
                mod_data = proj.get("data") if isinstance(proj, dict) and "data" in proj else proj
            except Exception:
                mod_data = proj

            if not isinstance(mod_data, dict):
                return []

            # Fetch versions (bounded)
            ver_list = await _fetch_json(session, versions_url)
            versions = []
            if isinstance(ver_list, list):
                versions = ver_list[:5]
            elif isinstance(ver_list, dict) and "data" in ver_list:
                versions = ver_list.get("data")[:5]

            count = min(len(versions), MAX_ITEMS_PER_SOURCE)
            for v in versions[:count]:
                try:
                    items.append(self.normalize((mod_data, v)))
                except Exception as e:
                    log.warning(f"ModrinthAdapter.normalize failed: {e}")
                    continue

        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        mod, file_index = raw_data
        # Determine content type by category/class id if present
        ct = ContentType.OTHER
        class_id = None
        try:
            class_id = mod.get("classId")
        except Exception:
            class_id = None

        if class_id == 6:
            ct = ContentType.MOD
        elif class_id == 4471:
            ct = ContentType.MODPACK
        elif class_id == 12:
            ct = ContentType.RESOURCE_PACK

        desc = mod.get("summary") or ""
        if isinstance(desc, str) and len(desc) > 200:
            desc = desc[:197] + "..."

        thumb = None
        logo = mod.get("logo")
        if isinstance(logo, dict):
            logo_url = logo.get("url")
            if _is_valid_http_url(logo_url):
                thumb = logo_url

        external_id = None
        try:
            external_id = str(file_index.get("fileId") or file_index.get("version_id") or file_index.get("project_id") or mod.get("project_id") or mod.get("id"))
        except Exception:
            external_id = None

        title = f"{mod.get('title') or mod.get('name') or ''} {file_index.get('filename', '')}".strip()
        if not title:
            title = mod.get('name') or mod.get('title') or 'Modrinth Project'

        url = mod.get("links", {}).get("websiteUrl") if isinstance(mod.get("links"), dict) else None
        if not _is_valid_http_url(url):
            # Fallback to modrinth project page
            project_page = f"https://modrinth.com/project/{mod.get('slug') or mod.get('id') or ''}"
            url = project_page if _is_valid_http_url(project_page) else ""

        published_at = datetime.now(timezone.utc)
        return ContentItem(
            source_id=self.source_id,
            external_id=external_id or title,
            url=url,
            title=title,
            content_type=ct,
            description=desc or None,
            thumbnail_url=thumb,
            version=file_index.get("gameVersion") if isinstance(file_index, dict) else None,
            published_at=published_at
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)


class YouTubeAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        channel_id = self.url.split('channel/')[-1] if 'channel/' in (self.url or "") else (self.url or "")
        rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        if "feeds/videos.xml" in (self.url or ""):
            rss_url = self.url

        items: List[ContentItem] = []
        async with aiohttp.ClientSession(headers={'User-Agent': 'Veyra Discord Bot'}) as session:
            xml_data = await _fetch_text(session, rss_url)
            if not xml_data:
                return []

            try:
                root = ET.fromstring(xml_data)
            except Exception as e:
                log.warning(f"YouTubeAdapter: failed to parse XML: {e}")
                return []

            ns = {'yt': 'http://www.youtube.com/xml/schemas/2015', 'ns': 'http://www.w3.org/2005/Atom', 'media': 'http://search.yahoo.com/mrss/'}

            entries = root.findall('ns:entry', ns)[:10]
            for entry in entries:
                try:
                    ci = self.normalize((entry, ns))
                    items.append(ci)
                except Exception as e:
                    log.warning(f"YouTubeAdapter.normalize failed: {e}")
                    continue

        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        entry, ns = raw_data
        video_id_el = entry.find('yt:videoId', ns)
        video_id = video_id_el.text if video_id_el is not None else None
        title_el = entry.find('ns:title', ns)
        title = title_el.text if title_el is not None else "YouTube Video"
        link_el = entry.find('ns:link', ns)
        url = link_el.attrib['href'] if link_el is not None and 'href' in link_el.attrib else None

        author_el = entry.find('ns:author', ns)
        author = None
        if author_el is not None:
            n = author_el.find('ns:name', ns)
            author = n.text if n is not None else None

        pub_el = entry.find('ns:published', ns)
        published_at = None
        if pub_el is not None and pub_el.text:
            try:
                published_at = datetime.fromisoformat(pub_el.text.replace('Z', '+00:00'))
            except Exception:
                try:
                    published_at = datetime.strptime(pub_el.text, '%Y-%m-%dT%H:%M:%S%z')
                except Exception:
                    published_at = datetime.now(timezone.utc)

        media_group = entry.find('media:group', ns)
        desc = None
        thumb = None
        if media_group is not None:
            desc_el = media_group.find('media:description', ns)
            if desc_el is not None and desc_el.text:
                desc = desc_el.text
            thumb_el = media_group.find('media:thumbnail', ns)
            if thumb_el is not None and 'url' in thumb_el.attrib and _is_valid_http_url(thumb_el.attrib['url']):
                thumb = thumb_el.attrib['url']

        if isinstance(desc, str) and len(desc) > 200:
            desc = desc[:197] + '...'

        return ContentItem(
            source_id=self.source_id,
            external_id=video_id or title,
            url=url,
            title=title,
            content_type=ContentType.YOUTUBE,
            author=author,
            description=desc,
            thumbnail_url=thumb,
            published_at=published_at
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)


class RedditAdapter(ContentSourceAdapter):
    async def fetch(self) -> List[ContentItem]:
        rss_url = self.url
        if not (rss_url or '').endswith('.rss'):
            rss_url = (rss_url or '').rstrip('/') + '/new.rss'

        items: List[ContentItem] = []
        async with aiohttp.ClientSession(headers={'User-Agent': 'Veyra Discord Bot'}) as session:
            xml_data = await _fetch_text(session, rss_url)
            if not xml_data:
                return []

            try:
                root = ET.fromstring(xml_data)
            except Exception as e:
                log.warning(f"RedditAdapter: failed to parse XML: {e}")
                return []

            ns = {'ns': 'http://www.w3.org/2005/Atom'}
            entries = root.findall('ns:entry', ns)[:10]
            for entry in entries:
                try:
                    items.append(self.normalize((entry, ns)))
                except Exception as e:
                    log.warning(f"RedditAdapter.normalize failed: {e}")
                    continue

        return items

    def normalize(self, raw_data: Any) -> ContentItem:
        entry, ns = raw_data
        post_id_el = entry.find('ns:id', ns)
        post_id = post_id_el.text if post_id_el is not None else None

        title_el = entry.find('ns:title', ns)
        title = title_el.text if title_el is not None else 'Reddit Post'

        link_el = entry.find('ns:link', ns)
        url = link_el.attrib['href'] if link_el is not None and 'href' in link_el.attrib else None

        author_el = entry.find('ns:author', ns)
        author = None
        if author_el is not None:
            n = author_el.find('ns:name', ns)
            author = n.text if n is not None else None

        pub_el = entry.find('ns:updated', ns)
        published_at = None
        if pub_el is not None and pub_el.text:
            try:
                published_at = datetime.fromisoformat(pub_el.text.replace('Z', '+00:00'))
            except Exception:
                try:
                    published_at = _parse_xml_date(pub_el.text)
                except Exception:
                    published_at = datetime.now(timezone.utc)

        content_el = entry.find('ns:content', ns)
        desc = None
        if content_el is not None and content_el.text:
            import re
            desc_clean = re.sub('<[^<]+>', ' ', content_el.text).strip()
            if len(desc_clean) > 200:
                desc_clean = desc_clean[:197] + '...'
            desc = desc_clean

        return ContentItem(
            source_id=self.source_id,
            external_id=post_id or title,
            url=url,
            title=title,
            content_type=ContentType.REDDIT,
            author=author,
            description=desc,
            published_at=published_at
        )

    def validate(self, item: ContentItem) -> bool:
        return bool(item.title and item.url and item.external_id)


class CurseForgeAdapter(ContentSourceAdapter):
    """
    Safe placeholder adapter for CurseForge. The real CurseForge API often requires an API key
    (x-api-key). If no api_key is present in the source config, this adapter will fail gracefully
    and return an empty list. If an api_key is provided via config_json, a minimal attempt will be
    made but callers should not expect full feature parity.
    """
    async def fetch(self) -> List[ContentItem]:
        cfg = self.config or {}
        api_key = cfg.get('api_key')
        # If no api_key, fail gracefully
        if not api_key:
            log.warning(f"CurseForgeAdapter: no api_key provided in config for source {self.source_id}; skipping.")
            return []

        # Basic behavior: if self.url contains an addon id or slug, attempt to fetch minimal data.
        # NOTE: CurseForge endpoints and authentication vary; this is a conservative best-effort.
        url = self.url
        if not url:
            return []

        # Do not implement aggressive crawling — attempt a single call to a documented endpoint
        # if possible. This code will try to interpret numeric ID at end of URL otherwise skip.
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        candidate_id = None
        if path_parts:
            last = path_parts[-1]
            if last.isdigit():
                candidate_id = last

        if not candidate_id:
            log.warning(f"CurseForgeAdapter: unable to determine addon id from URL {url} for source {self.source_id}")
            return []

        api_endpoint = f"https://api.curseforge.com/v1/mods/{candidate_id}"
        headers = {'x-api-key': api_key, 'User-Agent': 'Veyra Discord Bot'}

        items: List[ContentItem] = []
        async with aiohttp.ClientSession() as session:
            resp = await _fetch_with_retries(session, 'GET', api_endpoint, headers=headers)
            if not resp:
                return []
            if resp.status != 200:
                log.warning(f"CurseForgeAdapter: non-200 {resp.status} for {api_endpoint}")
                return []
            try:
                data = await resp.json()
            except Exception as e:
                log.warning(f"CurseForgeAdapter: failed to parse json: {e}")
                return []

            # Minimal normalization
            mod = data.get('data') if isinstance(data, dict) and 'data' in data else data
            if not isinstance(mod, dict):
                return []

            title = mod.get('name') or mod.get('title') or f"CurseForge-{candidate_id}"
            desc = mod.get('summary') or None
            thumb = None
            if isinstance(mod.get('logo'), dict) and mod.get('logo').get('url') and _is_valid_http_url(mod.get('logo').get('url')):
                thumb = mod.get('logo').get('url')

            items.append(ContentItem(
                source_id=self.source_id,
                external_id=str(candidate_id),
                url=url,
                title=title,
                content_type=ContentType.MOD,
                description=desc,
                thumbnail_url=thumb,
                published_at=datetime.now(timezone.utc)
            ))

        return items

    def validate(self, item: ContentItem) -> bool:
        # Be conservative: require title, url, external_id
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
        # Preserve provided URL on the adapter instance (some adapters use it)
        adapter.url = url
        return adapter
    return None

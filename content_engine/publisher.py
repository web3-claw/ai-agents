"""
content_engine/publisher.py — Publishing to Paragraph, WhatsApp (via Matrix bridge),
and YouTube Shorts.

All publishers include retry logic, dedup via lock files, and structured logging.
"""

import datetime
import json
import logging
import os
import pathlib
import sys
import time
from typing import Optional

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.constants import MATRIX_BASE, ADMIN_TOKEN
from lib.matrix_client import send_message

log = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────

PARAGRAPH_API_KEY = os.getenv("PARAGRAPH_API_KEY", "")
PARAGRAPH_API_URL = "https://public.api.paragraph.com/api/v1/posts"

# WhatsApp room on Matrix bridge
WA_ROOM_ID = os.getenv("WHATSAPP_ROOM_ID", "")

# Lock directory for dedup
LOCK_DIR = pathlib.Path(
    os.getenv("CONTENT_ENGINE_LOCK_DIR", "/tmp/content_engine_locks")
)

# YouTube OAuth credentials path
YOUTUBE_CLIENT_SECRETS = os.getenv(
    "YOUTUBE_CLIENT_SECRETS",
    os.path.expanduser("~/.config/content_engine/youtube_client_secrets.json"),
)
YOUTUBE_TOKEN_PATH = os.getenv(
    "YOUTUBE_TOKEN_PATH",
    os.path.expanduser("~/.config/content_engine/youtube_token.json"),
)


def _ensure_lock_dir() -> None:
    """Create lock directory if it doesn't exist."""
    LOCK_DIR.mkdir(parents=True, exist_ok=True)


def _is_deduped(platform: str, content_key: str) -> bool:
    """Check if content was already published today for this key."""
    _ensure_lock_dir()
    today = datetime.date.today().isoformat()
    lock_file = LOCK_DIR / f"{platform}_{content_key}_{today}.lock"
    return lock_file.exists()


def _mark_published(platform: str, content_key: str, metadata: dict = None) -> None:
    """Mark content as published for dedup."""
    _ensure_lock_dir()
    today = datetime.date.today().isoformat()
    lock_file = LOCK_DIR / f"{platform}_{content_key}_{today}.lock"
    data = {
        "published_at": datetime.datetime.now().isoformat(),
        "platform": platform,
        "key": content_key,
        **(metadata or {}),
    }
    lock_file.write_text(json.dumps(data))


# ── Paragraph Publisher ─────────────────────────────────────────────────────

def publish_paragraph(
    title: str,
    markdown: str,
    tags: list[str] = None,
    cover_image_url: str = None,
    dedup_key: str = None,
    max_retries: int = 3,
) -> tuple[Optional[str], Optional[str]]:
    """Publish article to Paragraph.com.

    Args:
        title: Article title
        markdown: Full markdown content
        tags: Optional list of tags
        cover_image_url: Optional cover image URL
        dedup_key: Optional dedup key (defaults to title hash)
        max_retries: Number of retry attempts

    Returns:
        (post_id, published_url) on success, (None, None) on failure.
    """
    if not PARAGRAPH_API_KEY:
        log.error("PARAGRAPH_API_KEY not configured")
        return None, None

    key = dedup_key or title[:50].replace(" ", "_").lower()
    if _is_deduped("paragraph", key):
        log.info("Paragraph dedup hit: %s — skipping", key)
        return None, None

    payload = {
        "title": title,
        "markdown": markdown,
        "sendNewsletter": False,
    }
    if tags:
        payload["tags"] = tags
    if cover_image_url:
        payload["coverImage"] = cover_image_url

    headers = {
        "Authorization": f"Bearer {PARAGRAPH_API_KEY}",
        "Content-Type": "application/json",
    }

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                PARAGRAPH_API_URL,
                headers=headers,
                json=payload,
                timeout=30,
            )

            if resp.status_code in (200, 201):
                data = resp.json()
                post_id = data.get("id", "unknown")
                slug = data.get("slug") or data.get("url_slug") or ""
                published_url = data.get("url") or data.get("canonical_url") or (
                    f"https://paragraph.xyz/@web3claw/{slug}" if slug
                    else f"https://paragraph.xyz/@web3claw/{post_id}"
                )
                _mark_published("paragraph", key, {
                    "post_id": post_id,
                    "url": published_url,
                    "title": title,
                })
                log.info("Paragraph published: %s (ID: %s)", title, post_id)
                return post_id, published_url

            if resp.status_code == 429:
                wait = min(30, 5 * attempt)
                log.warning(
                    "Paragraph rate limited, waiting %ds (attempt %d/%d)",
                    wait, attempt, max_retries,
                )
                time.sleep(wait)
                continue

            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            log.error(
                "Paragraph API error (attempt %d/%d): %s",
                attempt, max_retries, last_error,
            )

        except requests.RequestException as exc:
            last_error = str(exc)
            log.error(
                "Paragraph request failed (attempt %d/%d): %s",
                attempt, max_retries, exc,
            )

        if attempt < max_retries:
            time.sleep(2 * attempt)

    log.error("Paragraph publish failed after %d attempts: %s", max_retries, last_error)
    return None, None


# ── WhatsApp Publisher (via Matrix Bridge) ──────────────────────────────────

def publish_whatsapp(
    message: str,
    room_id: str = None,
    dedup_key: str = None,
    max_retries: int = 2,
) -> bool:
    """Send message to WhatsApp group via Matrix bridge.

    Args:
        message: Plain text message
        room_id: Matrix room ID (defaults to WA group)
        dedup_key: Optional dedup key
        max_retries: Number of retry attempts

    Returns:
        True on success, False on failure.
    """
    target_room = room_id or WA_ROOM_ID
    token = ADMIN_TOKEN

    if not token:
        log.error("MATRIX_ADMIN_TOKEN not configured for WhatsApp publishing")
        return False

    key = dedup_key or f"wa_{datetime.datetime.now().strftime('%H')}"
    if _is_deduped("whatsapp", key):
        log.info("WhatsApp dedup hit: %s — skipping", key)
        return False

    for attempt in range(1, max_retries + 1):
        event_id = send_message(
            room_id=target_room,
            body=message,
            token=token,
            homeserver=MATRIX_BASE,
        )
        if event_id:
            _mark_published("whatsapp", key, {"event_id": event_id})
            log.info("WhatsApp message sent: event=%s", event_id)
            return True

        log.warning(
            "WhatsApp send failed (attempt %d/%d)",
            attempt, max_retries,
        )
        if attempt < max_retries:
            time.sleep(3)

    log.error("WhatsApp publish failed after %d attempts", max_retries)
    return False


# ── YouTube Shorts Publisher ────────────────────────────────────────────────

def _get_youtube_service():
    """Build authenticated YouTube Data API v3 service.

    Requires google-auth, google-auth-oauthlib, google-api-python-client.
    First run requires browser OAuth flow. After that, token is cached.
    """
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        log.error(
            "YouTube upload requires: pip install "
            "google-auth google-auth-oauthlib google-api-python-client"
        )
        return None

    scopes = ["https://www.googleapis.com/auth/youtube.upload"]
    creds = None

    token_path = pathlib.Path(YOUTUBE_TOKEN_PATH)
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), scopes)

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            log.warning("YouTube token refresh failed: %s", exc)
            creds = None

    if not creds or not creds.valid:
        secrets_path = pathlib.Path(YOUTUBE_CLIENT_SECRETS)
        if not secrets_path.exists():
            log.error(
                "YouTube client secrets not found at %s. "
                "Download from Google Cloud Console.",
                secrets_path,
            )
            return None
        flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), scopes)
        creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
        log.info("YouTube OAuth token saved to %s", token_path)

    return build("youtube", "v3", credentials=creds)


def publish_youtube_short(
    video_path: str,
    title: str,
    description: str,
    tags: list[str] = None,
    dedup_key: str = None,
) -> Optional[str]:
    """Upload a video as a YouTube Short.

    Args:
        video_path: Path to the video file (must be vertical 9:16, <60s)
        title: Video title (max 100 chars)
        description: Video description
        tags: Optional list of tags
        dedup_key: Optional dedup key

    Returns:
        YouTube video ID on success, None on failure.
    """
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError:
        log.error("YouTube upload requires google-api-python-client")
        return None

    video_file = pathlib.Path(video_path)
    if not video_file.exists():
        log.error("Video file not found: %s", video_path)
        return None

    key = dedup_key or title[:40].replace(" ", "_").lower()
    if _is_deduped("youtube", key):
        log.info("YouTube dedup hit: %s — skipping", key)
        return None

    youtube = _get_youtube_service()
    if not youtube:
        return None

    # YouTube Shorts detection: add #Shorts to title/description
    short_title = title[:95]
    if "#Shorts" not in short_title:
        short_title = f"{short_title} #Shorts"

    if "#Shorts" not in description:
        description = f"{description}\n\n#Shorts"

    body = {
        "snippet": {
            "title": short_title,
            "description": description,
            "tags": tags or ["web3", "crypto", "sonic", "blockchain"],
            "categoryId": "28",  # Science & Technology
        },
        "status": {
            "privacyStatus": "public",
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(
        str(video_file),
        mimetype="video/mp4",
        resumable=True,
        chunksize=1024 * 1024,
    )

    try:
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                log.info("YouTube upload progress: %d%%", int(status.progress() * 100))

        video_id = response.get("id")
        if video_id:
            _mark_published("youtube", key, {
                "video_id": video_id,
                "title": short_title,
            })
            log.info(
                "YouTube Short uploaded: %s (https://youtube.com/shorts/%s)",
                short_title, video_id,
            )
            return video_id

        log.error("YouTube upload returned no video ID: %s", response)
        return None

    except Exception as exc:
        log.error("YouTube upload failed: %s", exc)
        return None


# ── Batch Publisher ─────────────────────────────────────────────────────────

def publish_to_platforms(
    platforms: list[str],
    content: dict,
) -> dict:
    """Publish content to multiple platforms.

    Args:
        platforms: List of platform names ("paragraph", "whatsapp", "youtube")
        content: Dict with keys depending on platform:
            - paragraph: title, markdown, tags, cover_image_url
            - whatsapp: message
            - youtube: video_path, title, description, tags

    Returns:
        Dict mapping platform name to result (success info or error).
    """
    results = {}

    for platform in platforms:
        try:
            if platform == "paragraph":
                post_id, url = publish_paragraph(
                    title=content.get("title", ""),
                    markdown=content.get("markdown", ""),
                    tags=content.get("tags"),
                    cover_image_url=content.get("cover_image_url"),
                )
                results[platform] = {
                    "success": post_id is not None,
                    "post_id": post_id,
                    "url": url,
                }

            elif platform == "whatsapp":
                ok = publish_whatsapp(
                    message=content.get("message", ""),
                    room_id=content.get("room_id"),
                )
                results[platform] = {"success": ok}

            elif platform == "youtube":
                video_id = publish_youtube_short(
                    video_path=content.get("video_path", ""),
                    title=content.get("title", ""),
                    description=content.get("description", ""),
                    tags=content.get("tags"),
                )
                results[platform] = {
                    "success": video_id is not None,
                    "video_id": video_id,
                }

            else:
                results[platform] = {
                    "success": False,
                    "error": f"Unknown platform: {platform}",
                }

        except Exception as exc:
            log.error("Publish to %s failed: %s", platform, exc)
            results[platform] = {"success": False, "error": str(exc)}

    return results

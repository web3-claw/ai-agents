"""
content_engine/video_pipeline.py — Video assembly for YouTube Shorts.

Pipeline: script -> voiceover (TTS) -> visuals (AI video) -> assembly (FFmpeg)
Output: 9:16 vertical video with burned-in captions, ready for YouTube Shorts.
"""

import base64
import json
import logging
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional

import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.constants import NVIDIA_KEY

log = logging.getLogger(__name__)

# ── API Configuration ───────────────────────────────────────────────────────

XAI_KEY = os.getenv("XAI_API_KEY", "")
MUAPI_KEY = os.getenv("MUAPI_KEY", "")
MUAPI_BASE = "https://api.muapi.ai/api/v1"
COSMOS_ENDPOINT = (
    "https://ai.api.nvidia.com/v1/cosmos/nvidia/cosmos-1_0-diffusion-text2world"
)
XAI_VIDEO_ENDPOINT = "https://api.x.ai/v1/videos/generations"
XAI_IMAGE_ENDPOINT = "https://api.x.ai/v1/images/generations"

# Output directory
OUTPUT_DIR = pathlib.Path(
    os.getenv("CONTENT_ENGINE_OUTPUT_DIR", "/tmp/content_engine_output")
)

# Agent color palette for captions / thumbnails
AGENT_COLORS = {
    "pixel": {"primary": "#4ECDC4", "bg": "#1A1A2E"},
    "orion": {"primary": "#FFD700", "bg": "#0D1117"},
    "vega": {"primary": "#00FF88", "bg": "#0A0A0A"},
    "forge": {"primary": "#FF6B35", "bg": "#16213E"},
    "pulse": {"primary": "#E040FB", "bg": "#1B0033"},
    "nova": {"primary": "#00B4D8", "bg": "#03071E"},
}

# Voice mapping per agent
AGENT_VOICES = {
    "pixel": "en-female-1",
    "orion": "en-male-2",
    "vega": "en-male-1",
    "forge": "en-male-3",
    "pulse": "en-female-2",
    "nova": "en-male-1",
}


def _ensure_output_dir() -> pathlib.Path:
    """Create output directory and return it."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUT_DIR


def _check_ffmpeg() -> bool:
    """Verify FFmpeg is available on PATH."""
    return shutil.which("ffmpeg") is not None


def _poll_muapi_job(
    request_id: str,
    max_attempts: int = 120,
    delay: float = 5.0,
) -> Optional[list]:
    """Poll a MuAPI async job until completion. Returns output URLs or None."""
    poll_url = f"{MUAPI_BASE}/predictions/{request_id}/result"
    headers = {"x-api-key": MUAPI_KEY}

    for attempt in range(max_attempts):
        time.sleep(delay)
        try:
            r = requests.get(poll_url, headers=headers, timeout=30)
            data = r.json()
            status = data.get("status", "")
            if status == "completed":
                outputs = data.get("outputs") or data.get("output") or []
                if isinstance(outputs, str):
                    outputs = [outputs]
                return outputs
            if status in ("failed", "error", "cancelled"):
                log.error("MuAPI job %s failed: %s", request_id, status)
                return None
        except Exception as exc:
            log.warning("MuAPI poll attempt %d failed: %s", attempt, exc)
            continue

    log.error("MuAPI job %s timed out after %d attempts", request_id, max_attempts)
    return None


# ── Voiceover Generation ───────────────────────────────────────────────────

def generate_voiceover(
    script: str,
    agent_name: str = "pixel",
    output_path: str = None,
) -> Optional[str]:
    """Generate TTS voiceover from script text.

    Uses MuAPI speech-2.6-hd endpoint.

    Args:
        script: Text to convert to speech (cleaned of formatting markers)
        agent_name: Agent name for voice selection
        output_path: Optional output file path

    Returns:
        Path to the generated audio file, or None on failure.
    """
    if not MUAPI_KEY:
        log.error("MUAPI_KEY not configured for TTS")
        return None

    # Clean script of formatting markers
    clean_text = script
    for marker in ["[HOOK]", "[VALUE]", "[CTA]", "[INTRO]", "[OUTRO]"]:
        clean_text = clean_text.replace(marker, "")
    clean_text = clean_text.strip()

    # Truncate if needed (API limit)
    if len(clean_text) > 2000:
        clean_text = clean_text[:2000]

    voice = AGENT_VOICES.get(agent_name, "en-male-1")

    try:
        r = requests.post(
            f"{MUAPI_BASE}/speech-2.6-hd",
            headers={
                "Content-Type": "application/json",
                "x-api-key": MUAPI_KEY,
            },
            json={"text": clean_text, "voice": voice},
            timeout=30,
        )

        if r.status_code != 200:
            log.error("MuAPI TTS submit failed: %s %s", r.status_code, r.text[:200])
            return None

        data = r.json()
        request_id = data.get("request_id") or data.get("id")

        if not request_id:
            # Might be a direct response with URL
            outputs = data.get("outputs") or data.get("output", [])
            if isinstance(outputs, str):
                outputs = [outputs]
            audio_url = outputs[0] if outputs else None
        else:
            result = _poll_muapi_job(request_id, max_attempts=60, delay=3.0)
            audio_url = result[0] if result else None

        if not audio_url:
            log.error("TTS generation returned no audio URL")
            return None

        # Download audio file
        out_dir = _ensure_output_dir()
        if output_path:
            out_file = pathlib.Path(output_path)
        else:
            out_file = out_dir / f"voiceover_{agent_name}_{int(time.time())}.mp3"

        audio_resp = requests.get(audio_url, timeout=60)
        audio_resp.raise_for_status()
        out_file.write_bytes(audio_resp.content)

        log.info("Voiceover generated: %s (%d KB)", out_file, len(audio_resp.content) // 1024)
        return str(out_file)

    except Exception as exc:
        log.error("Voiceover generation failed: %s", exc)
        return None


# ── Visual Generation ───────────────────────────────────────────────────────

def generate_visuals(
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "9:16",
    method: str = "grok",
    output_path: str = None,
) -> Optional[str]:
    """Generate AI video visuals for the Short.

    Args:
        prompt: Visual description
        duration: Desired duration in seconds
        aspect_ratio: Video aspect ratio (9:16 for Shorts)
        method: "grok" (xAI), "cosmos" (NVIDIA), or "seedance" (ByteDance)
        output_path: Optional output file path

    Returns:
        Path to the generated video file, or None on failure.
    """
    out_dir = _ensure_output_dir()
    if output_path:
        out_file = pathlib.Path(output_path)
    else:
        out_file = out_dir / f"visuals_{method}_{int(time.time())}.mp4"

    # Enhance prompt for Shorts format
    enhanced_prompt = (
        f"{prompt}. Vertical format (9:16 portrait), "
        f"cinematic quality, smooth motion, vibrant colors."
    )

    if method == "grok":
        return _generate_visuals_grok(enhanced_prompt, duration, aspect_ratio, out_file)
    elif method == "cosmos":
        return _generate_visuals_cosmos(enhanced_prompt, out_file)
    elif method == "seedance":
        return _generate_visuals_seedance(enhanced_prompt, duration, aspect_ratio, out_file)
    else:
        log.error("Unknown visual generation method: %s", method)
        return None


def _generate_visuals_grok(
    prompt: str,
    duration: int,
    aspect_ratio: str,
    out_file: pathlib.Path,
) -> Optional[str]:
    """Generate video via xAI Grok Imagine."""
    if not XAI_KEY:
        log.error("XAI_API_KEY not configured")
        return None

    try:
        r = requests.post(
            XAI_VIDEO_ENDPOINT,
            headers={
                "Authorization": f"Bearer {XAI_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "grok-imagine-video",
                "prompt": prompt,
                "duration": min(duration, 10),
                "resolution": "720p",
                "aspect_ratio": aspect_ratio,
            },
            timeout=30,
        )

        if r.status_code not in (200, 201, 202):
            log.error("Grok video submit failed: %s %s", r.status_code, r.text[:200])
            return None

        data = r.json()
        request_id = data.get("request_id") or data.get("id")

        if not request_id:
            # Synchronous response
            video_url = data.get("data", [{}])[0].get("url") or data.get("url")
            if video_url:
                vid_bytes = requests.get(video_url, timeout=120).content
                out_file.write_bytes(vid_bytes)
                log.info("Grok visuals generated: %s", out_file)
                return str(out_file)
            return None

        # Poll for async result
        poll_url = f"{XAI_VIDEO_ENDPOINT}/{request_id}"
        headers = {"Authorization": f"Bearer {XAI_KEY}"}

        for _ in range(20):
            time.sleep(15)
            try:
                poll_r = requests.get(poll_url, headers=headers, timeout=30)
                poll_data = poll_r.json()
                status = poll_data.get("status", "")
                if status == "completed":
                    video_url = (
                        poll_data.get("data", [{}])[0].get("url")
                        or poll_data.get("url")
                        or poll_data.get("video_url")
                    )
                    if video_url:
                        vid_bytes = requests.get(video_url, timeout=120).content
                        out_file.write_bytes(vid_bytes)
                        log.info("Grok visuals generated: %s (%d KB)", out_file, len(vid_bytes) // 1024)
                        return str(out_file)
                if status in ("failed", "error", "cancelled"):
                    log.error("Grok video failed: %s", status)
                    return None
            except Exception as exc:
                log.warning("Grok poll failed: %s", exc)

        log.error("Grok video timed out")
        return None

    except Exception as exc:
        log.error("Grok visuals generation failed: %s", exc)
        return None


def _generate_visuals_cosmos(
    prompt: str,
    out_file: pathlib.Path,
) -> Optional[str]:
    """Generate video via NVIDIA Cosmos (5s, physics-aware)."""
    if not NVIDIA_KEY:
        log.error("NVIDIA_KEY not configured")
        return None

    try:
        r = requests.post(
            COSMOS_ENDPOINT,
            headers={
                "Authorization": f"Bearer {NVIDIA_KEY}",
                "Content-Type": "application/json",
            },
            json={"prompt": prompt, "seed": 42},
            timeout=300,
        )

        if r.status_code != 200:
            log.error("Cosmos video failed: %s %s", r.status_code, r.text[:200])
            return None

        data = r.json()
        b64_video = data.get("b64_video")
        if not b64_video:
            log.error("Cosmos returned no b64_video")
            return None

        video_bytes = base64.b64decode(b64_video)
        out_file.write_bytes(video_bytes)
        log.info("Cosmos visuals generated: %s (%d KB)", out_file, len(video_bytes) // 1024)
        return str(out_file)

    except Exception as exc:
        log.error("Cosmos visuals generation failed: %s", exc)
        return None


def _generate_visuals_seedance(
    prompt: str,
    duration: int,
    aspect_ratio: str,
    out_file: pathlib.Path,
) -> Optional[str]:
    """Generate video via Seedance 2.0 (ByteDance)."""
    if not MUAPI_KEY:
        log.error("MUAPI_KEY not configured")
        return None

    try:
        r = requests.post(
            f"{MUAPI_BASE}/seedance-v2.0-t2v",
            headers={
                "x-api-key": MUAPI_KEY,
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "aspect_ratio": aspect_ratio,
                "duration": duration,
                "quality": "basic",
            },
            timeout=30,
        )

        if r.status_code not in (200, 201, 202):
            log.error("Seedance submit failed: %s %s", r.status_code, r.text[:200])
            return None

        data = r.json()
        request_id = data.get("request_id") or data.get("id")

        if not request_id:
            outputs = data.get("outputs", [])
            video_url = outputs[0] if outputs else data.get("url")
            if video_url:
                vid_bytes = requests.get(video_url, timeout=120).content
                out_file.write_bytes(vid_bytes)
                return str(out_file)
            return None

        result = _poll_muapi_job(request_id, max_attempts=60, delay=10.0)
        if result:
            vid_bytes = requests.get(result[0], timeout=120).content
            out_file.write_bytes(vid_bytes)
            log.info("Seedance visuals generated: %s (%d KB)", out_file, len(vid_bytes) // 1024)
            return str(out_file)

        return None

    except Exception as exc:
        log.error("Seedance visuals generation failed: %s", exc)
        return None


# ── Caption Generation ──────────────────────────────────────────────────────

def _generate_caption_segments(script: str, duration_secs: float) -> list[dict]:
    """Break script into timed caption segments.

    Returns list of dicts: {"text": str, "start": float, "end": float}
    """
    # Clean markers
    clean = script
    for marker in ["[HOOK]", "[VALUE]", "[CTA]", "[INTRO]", "[OUTRO]"]:
        clean = clean.replace(marker, "")

    # Split into sentences
    sentences = []
    for line in clean.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        # Split long lines into sentences
        for part in line.replace(". ", ".\n").split("\n"):
            part = part.strip()
            if part:
                sentences.append(part)

    if not sentences:
        return []

    # Distribute time evenly across sentences
    time_per_sentence = duration_secs / len(sentences)
    segments = []
    for i, sentence in enumerate(sentences):
        segments.append({
            "text": sentence,
            "start": i * time_per_sentence,
            "end": (i + 1) * time_per_sentence,
        })

    return segments


def _write_ass_subtitles(
    segments: list[dict],
    output_path: str,
    agent_name: str = "pixel",
    font_size: int = 18,
) -> str:
    """Write ASS subtitle file with styled captions.

    Uses agent-specific colors for branded look.
    """
    colors = AGENT_COLORS.get(agent_name, AGENT_COLORS["pixel"])
    # ASS uses BGR hex format: &HBBGGRR&
    primary_hex = colors["primary"].lstrip("#")
    # Convert RGB to BGR for ASS
    r, g, b = primary_hex[0:2], primary_hex[2:4], primary_hex[4:6]
    ass_color = f"&H00{b}{g}{r}&"

    header = f"""[Script Info]
Title: Content Engine Captions
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Arial,{font_size},{ass_color},&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,2,1,2,40,40,120,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    events = []
    for seg in segments:
        start = _secs_to_ass_time(seg["start"])
        end = _secs_to_ass_time(seg["end"])
        # Wrap long lines
        text = seg["text"]
        if len(text) > 40:
            mid = len(text) // 2
            space_idx = text.rfind(" ", 0, mid + 10)
            if space_idx > 0:
                text = text[:space_idx] + "\\N" + text[space_idx + 1:]
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}")

    content = header + "\n".join(events) + "\n"
    pathlib.Path(output_path).write_text(content)
    return output_path


def _secs_to_ass_time(secs: float) -> str:
    """Convert seconds to ASS time format: H:MM:SS.CC"""
    h = int(secs // 3600)
    m = int((secs % 3600) // 60)
    s = int(secs % 60)
    cs = int((secs % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


# ── Video Assembly ──────────────────────────────────────────────────────────

def assemble_short(
    voiceover_path: str,
    visual_path: str,
    script: str,
    agent_name: str = "pixel",
    music_path: str = None,
    output_path: str = None,
) -> Optional[str]:
    """Assemble final YouTube Short from components.

    Combines voiceover audio with AI visuals, burns in captions,
    and optionally mixes in background music.

    Args:
        voiceover_path: Path to voiceover audio file
        visual_path: Path to visual video file
        script: Original script text (for caption generation)
        agent_name: Agent name for styling
        music_path: Optional background music path
        output_path: Optional output file path

    Returns:
        Path to the assembled video, or None on failure.
    """
    if not _check_ffmpeg():
        log.error("FFmpeg not found on PATH — required for video assembly")
        return None

    vo_file = pathlib.Path(voiceover_path)
    vis_file = pathlib.Path(visual_path)

    if not vo_file.exists():
        log.error("Voiceover file not found: %s", voiceover_path)
        return None
    if not vis_file.exists():
        log.error("Visual file not found: %s", visual_path)
        return None

    out_dir = _ensure_output_dir()
    if output_path:
        out_file = pathlib.Path(output_path)
    else:
        out_file = out_dir / f"short_{agent_name}_{int(time.time())}.mp4"

    # Get voiceover duration for caption timing
    try:
        probe_cmd = [
            "ffprobe", "-v", "quiet", "-show_entries",
            "format=duration", "-of", "json", str(vo_file),
        ]
        probe_result = subprocess.run(
            probe_cmd, capture_output=True, text=True, timeout=10,
        )
        duration = float(json.loads(probe_result.stdout)["format"]["duration"])
    except Exception:
        duration = 45.0  # fallback
        log.warning("Could not probe voiceover duration, using %ds", duration)

    # Generate caption segments and ASS subtitle file
    segments = _generate_caption_segments(script, duration)
    with tempfile.NamedTemporaryFile(suffix=".ass", delete=False, mode="w") as tmp:
        sub_path = tmp.name
    _write_ass_subtitles(segments, sub_path, agent_name)

    try:
        # Build FFmpeg command
        # Step 1: Scale visual to 1080x1920 (9:16), loop to match voiceover duration
        # Step 2: Replace visual audio with voiceover
        # Step 3: Burn in captions
        # Step 4: Optionally mix background music

        filter_parts = [
            # Scale and pad visual to 1080x1920
            f"[0:v]scale=1080:1920:force_original_aspect_ratio=decrease,"
            f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1[scaled]",
        ]

        # Burn subtitles
        # Escape the path for ASS filter (colons and backslashes)
        escaped_sub = sub_path.replace("\\", "\\\\").replace(":", "\\:")
        filter_parts.append(f"[scaled]ass='{escaped_sub}'[captioned]")

        if music_path and pathlib.Path(music_path).exists():
            # Mix voiceover (loud) with music (quiet)
            filter_parts.append(
                "[1:a]volume=1.0[voice];"
                "[2:a]volume=0.15[music];"
                "[voice][music]amix=inputs=2:duration=first[audio]"
            )
            audio_label = "[audio]"
            input_args = [
                "-stream_loop", "-1", "-i", str(vis_file),
                "-i", str(vo_file),
                "-i", str(music_path),
            ]
        else:
            audio_label = "1:a"
            input_args = [
                "-stream_loop", "-1", "-i", str(vis_file),
                "-i", str(vo_file),
            ]

        filter_complex = ";".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            *input_args,
            "-filter_complex", filter_complex,
            "-map", "[captioned]",
            "-map", audio_label,
            "-c:v", "libx264", "-preset", "fast", "-crf", "23",
            "-c:a", "aac", "-b:a", "128k",
            "-t", str(duration),
            "-movflags", "+faststart",
            str(out_file),
        ]

        log.info("Assembling Short: %s", " ".join(cmd[:10]) + "...")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300,
        )

        if result.returncode != 0:
            log.error("FFmpeg assembly failed: %s", result.stderr[-500:])
            return None

        log.info("Short assembled: %s (%d KB)", out_file, out_file.stat().st_size // 1024)
        return str(out_file)

    except subprocess.TimeoutExpired:
        log.error("FFmpeg assembly timed out (5 min)")
        return None
    except Exception as exc:
        log.error("Video assembly failed: %s", exc)
        return None
    finally:
        # Clean up temp subtitle file
        try:
            os.unlink(sub_path)
        except OSError:
            pass


# ── Thumbnail Generation ───────────────────────────────────────────────────

def create_thumbnail(
    title: str,
    agent_name: str = "pixel",
    output_path: str = None,
) -> Optional[str]:
    """Generate a thumbnail image for the YouTube Short.

    Uses xAI Grok image generation with agent-specific styling.

    Args:
        title: Video title for context
        agent_name: Agent name for color/style
        output_path: Optional output file path

    Returns:
        Path to the generated thumbnail, or None on failure.
    """
    if not XAI_KEY:
        log.error("XAI_API_KEY not configured for thumbnail generation")
        return None

    colors = AGENT_COLORS.get(agent_name, AGENT_COLORS["pixel"])
    agent_info = {
        "pixel": "friendly tech guide with headset",
        "orion": "sharp-suited financial analyst",
        "vega": "calculator and charts energy",
        "forge": "engineer at whiteboard",
        "pulse": "energetic social media curator",
        "nova": "business executive at podium",
    }

    style_desc = agent_info.get(agent_name, "tech professional")

    prompt = (
        f"YouTube thumbnail, vertical 9:16, bold text overlay '{title[:30]}', "
        f"{style_desc}, dark background with {colors['primary']} accent glow, "
        f"crypto/blockchain aesthetic, professional, eye-catching, "
        f"minimal text, Web3 vibes, 4K quality"
    )

    try:
        r = requests.post(
            XAI_IMAGE_ENDPOINT,
            headers={
                "Authorization": f"Bearer {XAI_KEY}",
                "Content-Type": "application/json",
            },
            json={"model": "grok-imagine-image", "prompt": prompt, "n": 1},
            timeout=60,
        )

        data = r.json()
        img_url = data.get("data", [{}])[0].get("url")
        if not img_url:
            log.error("Thumbnail generation returned no URL: %s", data)
            return None

        # Download image
        out_dir = _ensure_output_dir()
        if output_path:
            out_file = pathlib.Path(output_path)
        else:
            out_file = out_dir / f"thumb_{agent_name}_{int(time.time())}.png"

        img_resp = requests.get(img_url, timeout=30)
        img_resp.raise_for_status()
        out_file.write_bytes(img_resp.content)

        log.info("Thumbnail generated: %s", out_file)
        return str(out_file)

    except Exception as exc:
        log.error("Thumbnail generation failed: %s", exc)
        return None


# ── Full Pipeline ───────────────────────────────────────────────────────────

def create_youtube_short(
    script: str,
    agent_name: str = "pixel",
    visual_prompt: str = None,
    visual_method: str = "grok",
    music_path: str = None,
) -> Optional[dict]:
    """Run the full video pipeline: TTS -> visuals -> assembly.

    Args:
        script: Video script text
        agent_name: Agent name for styling/voice
        visual_prompt: Custom visual prompt (auto-generated if None)
        visual_method: "grok", "cosmos", or "seedance"
        music_path: Optional background music

    Returns:
        Dict with paths: {"video": str, "thumbnail": str} or None on failure.
    """
    log.info("Starting YouTube Short pipeline for %s", agent_name)

    # Step 1: Generate voiceover
    log.info("Step 1/4: Generating voiceover...")
    vo_path = generate_voiceover(script, agent_name)
    if not vo_path:
        log.error("Pipeline failed at voiceover generation")
        return None

    # Step 2: Generate visuals
    if not visual_prompt:
        visual_prompt = _auto_visual_prompt(script, agent_name)

    log.info("Step 2/4: Generating visuals (%s)...", visual_method)
    vis_path = generate_visuals(
        prompt=visual_prompt,
        duration=5,
        aspect_ratio="9:16",
        method=visual_method,
    )
    if not vis_path:
        log.error("Pipeline failed at visual generation")
        return None

    # Step 3: Assemble video
    log.info("Step 3/4: Assembling video...")
    video_path = assemble_short(
        voiceover_path=vo_path,
        visual_path=vis_path,
        script=script,
        agent_name=agent_name,
        music_path=music_path,
    )
    if not video_path:
        log.error("Pipeline failed at video assembly")
        return None

    # Step 4: Generate thumbnail
    log.info("Step 4/4: Generating thumbnail...")
    # Extract a short title from the script's first line
    first_line = script.strip().split("\n")[0]
    for marker in ["[HOOK]", "[VALUE]", "[CTA]"]:
        first_line = first_line.replace(marker, "")
    thumb_path = create_thumbnail(first_line.strip()[:50], agent_name)

    log.info("YouTube Short pipeline complete for %s", agent_name)
    return {
        "video": video_path,
        "thumbnail": thumb_path,
        "voiceover": vo_path,
        "visuals": vis_path,
    }


def _auto_visual_prompt(script: str, agent_name: str) -> str:
    """Auto-generate a visual prompt from the script content."""
    visual_themes = {
        "pixel": "friendly tech tutorial screen recording style, warm colors, step by step UI walkthrough",
        "orion": "financial charts and market data visualization, dark theme with gold accents, stock ticker",
        "vega": "mathematical formulas floating in space, calculator display, green matrix numbers",
        "forge": "whiteboard with diagrams, blockchain nodes connected, technical blueprint style",
        "pulse": "trending social media feed, glowing notifications, viral content energy, neon colors",
        "nova": "corporate announcement stage, spotlight, professional press conference",
    }

    theme = visual_themes.get(agent_name, "modern tech visualization")

    # Extract key concepts from script
    clean = script[:200]
    for marker in ["[HOOK]", "[VALUE]", "[CTA]"]:
        clean = clean.replace(marker, "")

    return (
        f"{theme}. "
        f"Context: {clean.strip()[:100]}. "
        f"Cinematic quality, smooth camera motion, blockchain and crypto aesthetic."
    )

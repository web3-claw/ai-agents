"""
content_engine/scheduler.py — Daily content scheduling and orchestration.

Manages the daily content calendar across all agents and platforms.
Can be run as a cron job, systemd timer, or standalone daemon.
"""

import datetime
import json
import logging
import os
import pathlib
import sys
import time
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from content_engine.agent_content import (
    generate_script,
    generate_article,
    generate_wa_message,
    pick_topic,
    get_market_context,
    AGENTS,
)
from content_engine.publisher import (
    publish_paragraph,
    publish_whatsapp,
    publish_youtube_short,
    publish_to_platforms,
)
from content_engine.video_pipeline import create_youtube_short

log = logging.getLogger(__name__)

# ── Daily Schedule ──────────────────────────────────────────────────────────

DAILY_SCHEDULE = {
    "06:00": {
        "agent": "pulse",
        "platform": ["paragraph"],
        "type": "trending_hook",
        "description": "Morning trending hook article",
    },
    "07:00": {
        "agent": "orion",
        "platform": ["paragraph"],
        "type": "market_alpha",
        "description": "Morning market analysis article",
    },
    "08:00": {
        "agent": "pixel",
        "platform": ["youtube", "whatsapp"],
        "type": "onboarding",
        "description": "Onboarding tutorial Short + WA blast",
    },
    "09:00": {
        "agent": "vega",
        "platform": ["youtube"],
        "type": "earnings_math",
        "description": "Earnings math breakdown Short",
    },
    "10:00": {
        "agent": "forge",
        "platform": ["youtube"],
        "type": "technical",
        "description": "Technical deep dive Short",
    },
    "11:00": {
        "agent": "pulse",
        "platform": ["youtube"],
        "type": "trending",
        "description": "Trending content Short",
    },
    "12:00": {
        "agent": "orion",
        "platform": ["youtube", "whatsapp"],
        "type": "alpha",
        "description": "Midday market alpha Short + WA",
    },
    "13:00": {
        "agent": "nova",
        "platform": ["paragraph"],
        "type": "announcement",
        "description": "Ecosystem announcement article",
    },
    "14:00": {
        "agent": "vega",
        "platform": ["youtube", "paragraph"],
        "type": "math",
        "description": "Math breakdown Short + article",
    },
    "15:00": {
        "agent": "pixel",
        "platform": ["youtube"],
        "type": "tutorial",
        "description": "Afternoon tutorial Short",
    },
    "16:00": {
        "agent": "forge",
        "platform": ["youtube", "paragraph"],
        "type": "deepdive",
        "description": "Technical deep dive Short + article",
    },
    "17:00": {
        "agent": "pulse",
        "platform": ["youtube"],
        "type": "trending",
        "description": "Evening trending Short",
    },
    "18:00": {
        "agent": "orion",
        "platform": ["youtube", "whatsapp"],
        "type": "alpha",
        "description": "Evening market alpha Short + WA",
    },
    "20:00": {
        "agent": "vega",
        "platform": ["youtube"],
        "type": "recap",
        "description": "Daily earnings recap Short",
    },
}

# ── State Management ────────────────────────────────────────────────────────

STATE_FILE = pathlib.Path(
    os.getenv(
        "CONTENT_ENGINE_STATE",
        "/tmp/content_engine_state.json",
    )
)


def _load_state() -> dict:
    """Load scheduler state from disk."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            return {}
    return {}


def _save_state(state: dict) -> None:
    """Persist scheduler state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _slot_key(slot_time: str) -> str:
    """Generate a unique key for today's slot."""
    today = datetime.date.today().isoformat()
    return f"{today}_{slot_time}"


# ── Content Execution ───────────────────────────────────────────────────────

def execute_slot(slot_time: str, dry_run: bool = False) -> dict:
    """Execute a single scheduled content slot.

    Args:
        slot_time: Time string like "08:00"
        dry_run: If True, generate content but don't publish

    Returns:
        Dict with execution results per platform.
    """
    slot = DAILY_SCHEDULE.get(slot_time)
    if not slot:
        log.error("No schedule entry for %s", slot_time)
        return {"error": f"Unknown slot: {slot_time}"}

    # Check if already executed today
    state = _load_state()
    key = _slot_key(slot_time)
    if key in state.get("completed", {}):
        log.info("Slot %s already completed today — skipping", slot_time)
        return {"skipped": True, "reason": "already_completed"}

    agent_name = slot["agent"]
    platforms = slot["platform"]
    content_type = slot["type"]

    if isinstance(platforms, str):
        platforms = [platforms]

    log.info(
        "Executing slot %s: agent=%s, platforms=%s, type=%s",
        slot_time, agent_name, platforms, content_type,
    )

    # Pick topic for this slot
    topic = pick_topic(agent_name)
    results = {}

    # Generate and publish to each platform
    for platform in platforms:
        try:
            if platform == "paragraph":
                result = _execute_paragraph(agent_name, topic, dry_run)
            elif platform == "youtube":
                result = _execute_youtube(agent_name, topic, content_type, dry_run)
            elif platform == "whatsapp":
                result = _execute_whatsapp(agent_name, topic, dry_run)
            else:
                result = {"success": False, "error": f"Unknown platform: {platform}"}

            results[platform] = result
        except Exception as exc:
            log.error("Slot %s failed for %s: %s", slot_time, platform, exc)
            results[platform] = {"success": False, "error": str(exc)}

    # Mark as completed
    if not dry_run:
        if "completed" not in state:
            state["completed"] = {}
        state["completed"][key] = {
            "agent": agent_name,
            "platforms": platforms,
            "results": {k: v.get("success", False) for k, v in results.items()},
            "completed_at": datetime.datetime.now().isoformat(),
        }
        _save_state(state)

    return results


def _execute_paragraph(
    agent_name: str,
    topic: str,
    dry_run: bool,
) -> dict:
    """Generate and publish article to Paragraph."""
    article = generate_article(agent_name, topic)
    if not article:
        return {"success": False, "error": "Article generation failed"}

    if dry_run:
        log.info("[DRY RUN] Would publish to Paragraph: %s", article["title"])
        return {"success": True, "dry_run": True, "title": article["title"]}

    post_id, url = publish_paragraph(
        title=article["title"],
        markdown=article["markdown"],
        tags=article["tags"],
    )
    return {
        "success": post_id is not None,
        "post_id": post_id,
        "url": url,
        "title": article["title"],
    }


def _execute_youtube(
    agent_name: str,
    topic: str,
    content_type: str,
    dry_run: bool,
) -> dict:
    """Generate and upload YouTube Short."""
    # Generate script
    script = generate_script(agent_name, topic)
    if not script:
        return {"success": False, "error": "Script generation failed"}

    if dry_run:
        log.info("[DRY RUN] Would create YouTube Short for %s: %s", agent_name, topic)
        return {"success": True, "dry_run": True, "script": script[:200]}

    # Full video pipeline
    result = create_youtube_short(
        script=script,
        agent_name=agent_name,
        visual_method="grok",
    )
    if not result or not result.get("video"):
        return {"success": False, "error": "Video pipeline failed"}

    # Upload to YouTube
    description = (
        f"{topic}\n\n"
        f"Join the Web3Claw ecosystem:\n"
        f"https://web3sonic.com/126\n"
        f"https://web3claw.net/126\n\n"
        f"Built on Sonic blockchain - 400k TPS, <$0.01 gas\n\n"
        f"#Web3 #Crypto #Sonic #Blockchain #DeFi"
    )

    video_id = publish_youtube_short(
        video_path=result["video"],
        title=f"{AGENTS[agent_name]['name']}: {topic[:60]}",
        description=description,
        tags=["web3", "crypto", "sonic", "blockchain", content_type, agent_name],
    )

    return {
        "success": video_id is not None,
        "video_id": video_id,
        "video_path": result["video"],
    }


def _execute_whatsapp(
    agent_name: str,
    topic: str,
    dry_run: bool,
) -> dict:
    """Generate and send WhatsApp message."""
    message = generate_wa_message(agent_name, topic)
    if not message:
        return {"success": False, "error": "WA message generation failed"}

    if dry_run:
        log.info("[DRY RUN] Would send WhatsApp: %s...", message[:100])
        return {"success": True, "dry_run": True, "preview": message[:200]}

    ok = publish_whatsapp(message)
    return {"success": ok}


# ── Slot Discovery ──────────────────────────────────────────────────────────

def get_current_slot() -> Optional[str]:
    """Get the schedule slot for the current hour.

    Returns the slot time string if one exists, None otherwise.
    """
    now = datetime.datetime.now()
    current = now.strftime("%H:00")
    if current in DAILY_SCHEDULE:
        return current
    return None


def get_next_slot() -> Optional[tuple[str, dict]]:
    """Get the next upcoming slot.

    Returns (time_str, slot_config) or None if no more slots today.
    """
    now = datetime.datetime.now()
    current_minutes = now.hour * 60 + now.minute

    for slot_time in sorted(DAILY_SCHEDULE.keys()):
        h, m = map(int, slot_time.split(":"))
        slot_minutes = h * 60 + m
        if slot_minutes > current_minutes:
            return slot_time, DAILY_SCHEDULE[slot_time]

    return None


def get_pending_slots() -> list[str]:
    """Get all slots that haven't been executed today."""
    state = _load_state()
    completed = state.get("completed", {})

    pending = []
    for slot_time in sorted(DAILY_SCHEDULE.keys()):
        key = _slot_key(slot_time)
        if key not in completed:
            pending.append(slot_time)

    return pending


def get_daily_summary() -> dict:
    """Get summary of today's content production."""
    state = _load_state()
    completed = state.get("completed", {})
    today = datetime.date.today().isoformat()

    todays_completed = {
        k: v for k, v in completed.items()
        if k.startswith(today)
    }

    total_slots = len(DAILY_SCHEDULE)
    done = len(todays_completed)

    agent_counts = {}
    platform_counts = {}
    for entry in todays_completed.values():
        agent = entry.get("agent", "unknown")
        agent_counts[agent] = agent_counts.get(agent, 0) + 1
        for p in entry.get("platforms", []):
            platform_counts[p] = platform_counts.get(p, 0) + 1

    return {
        "date": today,
        "total_slots": total_slots,
        "completed": done,
        "pending": total_slots - done,
        "completion_rate": f"{done / total_slots * 100:.0f}%" if total_slots else "0%",
        "by_agent": agent_counts,
        "by_platform": platform_counts,
        "pending_slots": get_pending_slots(),
    }


# ── Daemon Mode ─────────────────────────────────────────────────────────────

def run_daemon(check_interval: int = 60) -> None:
    """Run as a daemon, executing slots at their scheduled times.

    Checks every `check_interval` seconds if the current time matches
    a scheduled slot. Handles dedup so it won't re-execute completed slots.
    """
    log.info("Content Engine daemon started. Schedule has %d slots.", len(DAILY_SCHEDULE))
    log.info("Slots: %s", ", ".join(sorted(DAILY_SCHEDULE.keys())))

    while True:
        try:
            current_slot = get_current_slot()
            if current_slot:
                state = _load_state()
                key = _slot_key(current_slot)
                if key not in state.get("completed", {}):
                    log.info("Executing scheduled slot: %s", current_slot)
                    results = execute_slot(current_slot)
                    log.info("Slot %s results: %s", current_slot, results)

            time.sleep(check_interval)

        except KeyboardInterrupt:
            log.info("Content Engine daemon shutting down.")
            break
        except Exception as exc:
            log.error("Daemon error: %s", exc)
            time.sleep(check_interval)


# ── CLI Entry Point ─────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point for the scheduler.

    Usage:
        python -m content_engine.scheduler run           # Execute current slot
        python -m content_engine.scheduler slot 08:00    # Execute specific slot
        python -m content_engine.scheduler dry 08:00     # Dry run specific slot
        python -m content_engine.scheduler pending       # Show pending slots
        python -m content_engine.scheduler summary       # Show daily summary
        python -m content_engine.scheduler daemon        # Run as daemon
        python -m content_engine.scheduler catchup       # Run all missed slots
    """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [CONTENT-ENGINE] %(levelname)s %(message)s",
    )

    args = sys.argv[1:] if len(sys.argv) > 1 else ["run"]
    command = args[0]

    if command == "run":
        slot = get_current_slot()
        if slot:
            results = execute_slot(slot)
            print(json.dumps(results, indent=2))
        else:
            print("No scheduled slot for current hour.")
            next_slot = get_next_slot()
            if next_slot:
                print(f"Next slot: {next_slot[0]} ({next_slot[1]['description']})")

    elif command == "slot" and len(args) > 1:
        results = execute_slot(args[1])
        print(json.dumps(results, indent=2))

    elif command == "dry" and len(args) > 1:
        results = execute_slot(args[1], dry_run=True)
        print(json.dumps(results, indent=2))

    elif command == "pending":
        pending = get_pending_slots()
        if pending:
            print(f"Pending slots ({len(pending)}):")
            for s in pending:
                info = DAILY_SCHEDULE[s]
                print(f"  {s} | {info['agent']:6s} | {','.join(info['platform']):20s} | {info['description']}")
        else:
            print("All slots completed for today.")

    elif command == "summary":
        summary = get_daily_summary()
        print(json.dumps(summary, indent=2))

    elif command == "daemon":
        interval = int(args[1]) if len(args) > 1 else 60
        run_daemon(check_interval=interval)

    elif command == "catchup":
        pending = get_pending_slots()
        now = datetime.datetime.now()
        current_minutes = now.hour * 60 + now.minute

        caught_up = 0
        for slot_time in pending:
            h, m = map(int, slot_time.split(":"))
            if h * 60 + m <= current_minutes:
                log.info("Catching up slot: %s", slot_time)
                results = execute_slot(slot_time)
                caught_up += 1
                log.info("Catchup %s results: %s", slot_time, results)
                time.sleep(5)  # Brief pause between slots

        print(f"Caught up {caught_up} missed slots.")

    else:
        print(__doc__ or "Usage: scheduler.py [run|slot|dry|pending|summary|daemon|catchup]")


if __name__ == "__main__":
    main()

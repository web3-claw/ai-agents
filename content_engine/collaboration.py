"""
content_engine/collaboration.py — Agent collaboration patterns.

Enables multi-agent content creation where agents build on each other's
perspectives, creating richer and more engaging content threads.
"""

import datetime
import logging
import os
import sys
from typing import Optional

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.constants import NVIDIA_KEY
from lib.llm_client import call_llm_with_retry

from content_engine.agent_content import (
    AGENTS,
    REFERRAL_URLS,
    PLATFORM_FACTS,
    get_market_context,
    _format_market_summary,
    _build_agent_system_prompt,
)

log = logging.getLogger(__name__)


def _validate_agents(agent_names: list[str]) -> list[dict]:
    """Validate agent names and return their configs.

    Raises ValueError for unknown agent names.
    """
    configs = []
    for name in agent_names:
        if name not in AGENTS:
            raise ValueError(f"Unknown agent: {name}. Valid: {list(AGENTS.keys())}")
        configs.append(AGENTS[name])
    return configs


# ── Collaborative Thread ───────────────────────────────────────────────────

def collab_thread(
    agents: list[str],
    topic: str,
    platform: str = "paragraph",
    max_rounds: int = None,
) -> Optional[dict]:
    """Generate a collaborative content thread where agents build on each other.

    Each agent adds their unique perspective sequentially, creating a
    multi-angle exploration of the topic.

    Args:
        agents: List of agent names (order matters)
        topic: Central topic to discuss
        platform: Target platform ("paragraph", "youtube", "whatsapp")
        max_rounds: Max agents to include (defaults to all)

    Returns:
        Dict with keys: title, segments (list of agent contributions),
        combined_markdown, agent_names
    """
    _validate_agents(agents)

    if max_rounds:
        agents = agents[:max_rounds]

    prices = get_market_context()
    market_summary = _format_market_summary(prices)

    segments = []
    context_so_far = ""

    for i, agent_name in enumerate(agents):
        agent = AGENTS[agent_name]
        is_first = i == 0
        is_last = i == len(agents) - 1

        if is_first:
            position_instruction = (
                "You are OPENING this collaborative thread. "
                "Introduce the topic with your unique angle and set the stage "
                "for other experts to add their perspectives."
            )
        elif is_last:
            position_instruction = (
                "You are CLOSING this collaborative thread. "
                "Build on what the previous contributors said, add your final "
                "perspective, and deliver a strong closing CTA."
            )
        else:
            position_instruction = (
                "You are ADDING to this collaborative thread. "
                "Reference what was said before, then add your unique angle. "
                "Don't repeat — build and expand."
            )

        prompt = f"""Topic: {topic}
Current market: {market_summary}

{position_instruction}

{"" if is_first else f"PREVIOUS CONTRIBUTIONS (reference naturally, don't repeat):\\n{context_so_far}"}

Write your contribution ({_platform_length(platform)} words).
Include web3sonic.com/126 or web3claw.net/126 at least once.
{"Include a strong CTA as the closing." if is_last else ""}
Your name is {agent['name']} — sign your section."""

        system = _build_agent_system_prompt(agent_name)

        result = call_llm_with_retry(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model="meta/llama-3.3-70b-instruct",
            max_tokens=_platform_tokens(platform),
            temperature=0.85,
            api_key=NVIDIA_KEY,
            timeout=60,
            retries=2,
        )

        if not result:
            log.error("Collab thread: %s failed to generate content", agent_name)
            continue

        segments.append({
            "agent": agent_name,
            "agent_display": agent["name"],
            "content": result,
            "niche": agent["niche"],
        })

        # Build context for next agent
        context_so_far += f"\n\n--- {agent['name']} ({agent['niche']}) ---\n{result[:300]}..."

    if not segments:
        log.error("Collab thread: no segments generated")
        return None

    # Combine into full content
    combined = _combine_segments(segments, topic, platform)

    log.info(
        "Collab thread generated: %d agents on '%s'",
        len(segments), topic,
    )

    return {
        "title": f"{topic} — Multi-Perspective Analysis",
        "segments": segments,
        "combined_markdown": combined,
        "agent_names": [s["agent"] for s in segments],
        "topic": topic,
        "platform": platform,
    }


# ── Cross-Promotion ────────────────────────────────────────────────────────

def cross_promote(
    source_agent: str,
    content_summary: str,
    promoting_agents: list[str] = None,
) -> list[dict]:
    """Generate cross-promotion messages from other agents.

    When one agent publishes content, others can reference/promote it
    from their own angle.

    Args:
        source_agent: The agent who created the original content
        content_summary: Brief summary of the original content
        promoting_agents: List of agents to generate promos (defaults to all others)

    Returns:
        List of dicts with keys: agent, message
    """
    if source_agent not in AGENTS:
        raise ValueError(f"Unknown source agent: {source_agent}")

    if promoting_agents is None:
        promoting_agents = [a for a in AGENTS if a != source_agent]

    _validate_agents(promoting_agents)

    source_info = AGENTS[source_agent]
    promos = []

    for agent_name in promoting_agents:
        agent = AGENTS[agent_name]

        prompt = f"""Write a short cross-promotion message (50-80 words).

{source_info['name']} just published content about: {content_summary}

YOUR JOB as {agent['name']}:
- Reference {source_info['name']}'s content naturally
- Add your unique angle ({agent['niche']})
- Make your audience want to check out {source_info['name']}'s content
- Include web3sonic.com/126 or web3claw.net/126
- Keep it natural, not salesy
- Write for WhatsApp/social format"""

        system = _build_agent_system_prompt(agent_name)

        result = call_llm_with_retry(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model="meta/llama-3.3-70b-instruct",
            max_tokens=200,
            temperature=0.85,
            api_key=NVIDIA_KEY,
            timeout=30,
            retries=2,
        )

        if result:
            promos.append({
                "agent": agent_name,
                "agent_display": agent["name"],
                "message": result,
            })

    log.info(
        "Cross-promos generated: %d agents promoting %s's content",
        len(promos), source_agent,
    )
    return promos


# ── Debate Format ───────────────────────────────────────────────────────────

def debate(
    agent_a: str,
    agent_b: str,
    topic: str,
    rounds: int = 2,
) -> Optional[dict]:
    """Generate a debate between two agents on a topic.

    Each agent takes a different angle, creating engaging back-and-forth
    content that explores multiple perspectives.

    Args:
        agent_a: First agent name
        agent_b: Second agent name
        topic: Debate topic
        rounds: Number of rounds (each round = both agents speak)

    Returns:
        Dict with title, exchanges, combined_markdown
    """
    _validate_agents([agent_a, agent_b])

    a_info = AGENTS[agent_a]
    b_info = AGENTS[agent_b]

    prices = get_market_context()
    market_summary = _format_market_summary(prices)

    exchanges = []
    conversation_history = ""

    for round_num in range(1, rounds + 1):
        for speaker, opponent in [(agent_a, agent_b), (agent_b, agent_a)]:
            speaker_info = AGENTS[speaker]
            opponent_info = AGENTS[opponent]

            is_opening = round_num == 1 and speaker == agent_a
            is_closing = round_num == rounds and speaker == agent_b

            if is_opening:
                instruction = (
                    f"OPEN this debate about '{topic}'. "
                    f"Present your perspective from your niche ({speaker_info['niche']}). "
                    f"Be bold and set up points for {opponent_info['name']} to respond to."
                )
            elif is_closing:
                instruction = (
                    f"CLOSE this debate. Acknowledge {opponent_info['name']}'s points, "
                    f"deliver your final argument, and end with a unifying conclusion. "
                    f"Include a CTA to web3sonic.com/126."
                )
            else:
                instruction = (
                    f"RESPOND to {opponent_info['name']}'s points. "
                    f"Acknowledge what they said, then counter with your own angle "
                    f"({speaker_info['niche']}). Keep it respectful but sharp."
                )

            prompt = f"""Debate topic: {topic}
Market context: {market_summary}

{instruction}

{"" if is_opening else f"CONVERSATION SO FAR:\\n{conversation_history}"}

Write 100-150 words. Stay in character as {speaker_info['name']}."""

            system = _build_agent_system_prompt(speaker)

            result = call_llm_with_retry(
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                model="meta/llama-3.3-70b-instruct",
                max_tokens=300,
                temperature=0.88,
                api_key=NVIDIA_KEY,
                timeout=45,
                retries=2,
            )

            if not result:
                log.error("Debate: %s failed to generate response", speaker)
                continue

            exchanges.append({
                "round": round_num,
                "agent": speaker,
                "agent_display": AGENTS[speaker]["name"],
                "content": result,
            })

            conversation_history += f"\n{AGENTS[speaker]['name']}: {result}\n"

    if not exchanges:
        return None

    # Combine into markdown
    title = f"Debate: {a_info['name']} vs {b_info['name']} on {topic}"
    combined = f"# {title}\n\n"
    combined += f"*{a_info['name']} ({a_info['niche']}) vs {b_info['name']} ({b_info['niche']})*\n\n"

    for ex in exchanges:
        combined += f"## {ex['agent_display']} (Round {ex['round']})\n\n"
        combined += f"{ex['content']}\n\n"

    combined += (
        f"\n---\n"
        f"**Join the conversation:** [web3sonic.com/126]({REFERRAL_URLS['primary']})\n\n"
        f"*Built on Sonic blockchain | Chain ID 146*\n"
    )

    log.info("Debate generated: %s vs %s on '%s' (%d exchanges)", agent_a, agent_b, topic, len(exchanges))

    return {
        "title": title,
        "exchanges": exchanges,
        "combined_markdown": combined,
        "agents": [agent_a, agent_b],
        "topic": topic,
        "rounds": rounds,
    }


# ── Tag Team ───────────────────────────────────────────────────────────────

def tag_team(
    agents: list[str],
    topic: str,
    platform: str = "paragraph",
) -> Optional[dict]:
    """Generate sequential content where each agent adds their angle.

    Differs from collab_thread: tag_team produces standalone pieces that
    each reference the others, while collab_thread builds one unified piece.

    Example flow:
    ORION posts market alpha -> VEGA adds earnings math ->
    PIXEL shows how to get started -> FORGE explains the tech

    Args:
        agents: Ordered list of agent names
        topic: Central topic
        platform: Target platform

    Returns:
        Dict with pieces (list of standalone content), thread_summary
    """
    _validate_agents(agents)

    prices = get_market_context()
    market_summary = _format_market_summary(prices)

    pieces = []
    previous_angles = []

    for i, agent_name in enumerate(agents):
        agent = AGENTS[agent_name]

        # Build reference to previous pieces
        prev_context = ""
        if previous_angles:
            refs = [f"- {a['agent_display']}: {a['angle']}" for a in previous_angles]
            prev_context = (
                f"\nPREVIOUS ANGLES (reference these naturally):\n"
                + "\n".join(refs)
            )

        # Each agent creates a standalone piece from their niche angle
        prompt = f"""Write a standalone {_platform_format(platform)} about: {topic}

Your unique angle: {agent['niche']}
Market context: {market_summary}
{prev_context}

REQUIREMENTS:
- {_platform_length(platform)} words
- Focus on YOUR unique perspective ({agent['niche']})
- {"Reference what " + previous_angles[-1]['agent_display'] + " covered, then transition to your angle." if previous_angles else "Open fresh with your angle."}
- {"Tease that " + AGENTS[agents[i+1]]['name'] + " will cover " + AGENTS[agents[i+1]]['niche'] + " next." if i < len(agents) - 1 else "Wrap up the series with a strong CTA."}
- Include web3sonic.com/126 or web3claw.net/126
- Sign as {agent['name']}"""

        system = _build_agent_system_prompt(agent_name)

        result = call_llm_with_retry(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            model="meta/llama-3.3-70b-instruct",
            max_tokens=_platform_tokens(platform),
            temperature=0.85,
            api_key=NVIDIA_KEY,
            timeout=60,
            retries=2,
        )

        if not result:
            log.error("Tag team: %s failed to generate content", agent_name)
            continue

        # Extract a short angle summary for the next agent
        angle_summary = result[:100].replace("\n", " ").strip()

        piece = {
            "agent": agent_name,
            "agent_display": agent["name"],
            "niche": agent["niche"],
            "content": result,
            "angle": angle_summary,
            "order": i + 1,
        }

        pieces.append(piece)
        previous_angles.append(piece)

    if not pieces:
        return None

    # Generate thread summary
    summary = _generate_thread_summary(pieces, topic)

    log.info(
        "Tag team generated: %d pieces on '%s'",
        len(pieces), topic,
    )

    return {
        "topic": topic,
        "pieces": pieces,
        "thread_summary": summary,
        "agent_names": [p["agent"] for p in pieces],
        "platform": platform,
    }


def _generate_thread_summary(pieces: list[dict], topic: str) -> str:
    """Generate a brief summary connecting all tag-team pieces."""
    agent_flow = " -> ".join(
        f"{p['agent_display']} ({p['niche']})" for p in pieces
    )
    return (
        f"Thread on '{topic}': {agent_flow}\n"
        f"Full coverage from {len(pieces)} expert perspectives.\n"
        f"Start at web3sonic.com/126"
    )


# ── Helper Functions ────────────────────────────────────────────────────────

def _platform_length(platform: str) -> str:
    """Return word count guidance for platform."""
    lengths = {
        "paragraph": "300-500",
        "youtube": "80-120",
        "whatsapp": "100-150",
    }
    return lengths.get(platform, "200-300")


def _platform_tokens(platform: str) -> int:
    """Return max_tokens for platform."""
    tokens = {
        "paragraph": 1000,
        "youtube": 300,
        "whatsapp": 300,
    }
    return tokens.get(platform, 500)


def _platform_format(platform: str) -> str:
    """Return content format description for platform."""
    formats = {
        "paragraph": "blog post section",
        "youtube": "video script segment",
        "whatsapp": "message",
    }
    return formats.get(platform, "content piece")


def _combine_segments(
    segments: list[dict],
    topic: str,
    platform: str,
) -> str:
    """Combine multiple agent segments into unified content."""
    if platform == "paragraph":
        combined = f"# {topic}\n\n"
        combined += "*A multi-perspective analysis by the Web3Claw team*\n\n"

        for seg in segments:
            combined += f"## {seg['agent_display']}'s Take ({seg['niche']})\n\n"
            combined += f"{seg['content']}\n\n"

        combined += (
            f"\n---\n"
            f"**Explore the platform:** "
            f"[Web3 Sonic]({REFERRAL_URLS['primary']}) | "
            f"[Get started]({REFERRAL_URLS['alt']})\n\n"
            f"*Chain: Sonic (chainID 146) | Tokens: wBTC / wETH / USDC / $S*\n"
        )
        return combined

    elif platform == "whatsapp":
        combined = f"*{topic}*\n\n"
        for seg in segments:
            combined += f"*{seg['agent_display']}:*\n{seg['content']}\n\n"
        combined += f"Start here: {REFERRAL_URLS['primary']}"
        return combined

    else:
        return "\n\n---\n\n".join(
            f"[{seg['agent_display']}]\n{seg['content']}" for seg in segments
        )


# ── Preset Collab Patterns ─────────────────────────────────────────────────

def market_deep_dive(topic: str = None) -> Optional[dict]:
    """Preset: Full market deep dive — ORION -> VEGA -> PIXEL -> FORGE.

    ORION posts market alpha, VEGA adds earnings math,
    PIXEL shows how to get started, FORGE explains the tech.
    """
    topic = topic or "current market opportunity on sonic blockchain"
    return tag_team(
        agents=["orion", "vega", "pixel", "forge"],
        topic=topic,
        platform="paragraph",
    )


def trending_coverage(topic: str = None) -> Optional[dict]:
    """Preset: Trending topic coverage — PULSE -> NOVA -> ORION."""
    topic = topic or "what's trending in crypto this week"
    return tag_team(
        agents=["pulse", "nova", "orion"],
        topic=topic,
        platform="paragraph",
    )


def onboarding_series(topic: str = None) -> Optional[dict]:
    """Preset: New member onboarding — PIXEL -> VEGA -> FORGE."""
    topic = topic or "getting started with web3sonic in 2026"
    return tag_team(
        agents=["pixel", "vega", "forge"],
        topic=topic,
        platform="paragraph",
    )


def bull_vs_bear(topic: str = None) -> Optional[dict]:
    """Preset: Bull vs Bear debate — ORION vs PULSE."""
    topic = topic or "is now the right time to enter the crypto market"
    return debate(
        agent_a="orion",
        agent_b="pulse",
        topic=topic,
        rounds=2,
    )


def tech_vs_earnings(topic: str = None) -> Optional[dict]:
    """Preset: Technical vs Earnings angle — FORGE vs VEGA."""
    topic = topic or "what matters more: the tech or the returns"
    return debate(
        agent_a="forge",
        agent_b="vega",
        topic=topic,
        rounds=2,
    )

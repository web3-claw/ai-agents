"""
content_engine/agent_content.py — Core content generation for each agent persona.

Each agent has a distinct niche, tone, hook style, and CTA approach.
All content funnels traffic to web3sonic.com/126 and web3claw.net/126.
"""

import datetime
import hashlib
import logging
import os
import random
import sys
from typing import Optional

# Add parent dir to path so lib imports work
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from lib.constants import NVIDIA_KEY
from lib.llm_client import call_llm_with_retry
from lib.price_client import get_prices, PriceData

log = logging.getLogger(__name__)

# ── Agent Personas ──────────────────────────────────────────────────────────

AGENTS = {
    "pixel": {
        "name": "PIXEL",
        "niche": "onboarding_explainers",
        "tone": "warm, beginner-friendly",
        "hook_style": "question",
        "cta_style": "gentle",
        "topics": [
            "registration walkthrough",
            "rabby wallet setup",
            "first matrix entry",
            "dashboard tour",
            "referral link setup",
            "how to check your earnings",
            "understanding matrix levels",
            "connecting wallet to sonic chain",
            "upgrading your matrix position",
            "inviting your first referral",
        ],
    },
    "orion": {
        "name": "ORION",
        "niche": "market_alpha",
        "tone": "confident, analytical",
        "hook_style": "statement",
        "cta_style": "urgency",
        "topics": [
            "bitcoin analysis",
            "sonic ecosystem momentum",
            "market opportunities this week",
            "partnership news impact",
            "whale movements on sonic",
            "ethereum vs sonic gas comparison",
            "defi yields across chains",
            "crypto market sentiment today",
            "on-chain metrics that matter",
            "altcoin season indicators",
        ],
    },
    "vega": {
        "name": "VEGA",
        "niche": "earnings_math",
        "tone": "numbers-focused, calculator energy",
        "hook_style": "math",
        "cta_style": "proof",
        "topics": [
            "ROI calculations for each matrix",
            "matrix earnings breakdown",
            "upgrade math: when to level up",
            "referral income projections",
            "compound growth scenarios",
            "cost vs earnings per level",
            "odd vs even referral mechanics",
            "wBTC matrix entry cost today",
            "USDC matrix dollar values",
            "sonic matrix at current prices",
        ],
    },
    "forge": {
        "name": "FORGE",
        "niche": "technical_deep_dives",
        "tone": "tech nerd, whiteboard energy",
        "hook_style": "curiosity",
        "cta_style": "education",
        "topics": [
            "smart contract mechanics explained",
            "matrix system architecture",
            "blockchain basics for builders",
            "sonic chain technical advantages",
            "security features of the platform",
            "how on-chain payments work",
            "decentralized vs centralized income",
            "EVM compatibility and what it means",
            "gas optimization on sonic",
            "smart contract audit insights",
        ],
    },
    "pulse": {
        "name": "PULSE",
        "niche": "trending_hooks",
        "tone": "hype curator, energetic",
        "hook_style": "trending",
        "cta_style": "fomo",
        "topics": [
            "trending crypto narratives",
            "viral web3 moments this week",
            "ai plus crypto crossover",
            "defi trends to watch",
            "community milestones hit",
            "new members joining wave",
            "social media buzz around sonic",
            "web3 adoption acceleration",
            "meme coins vs real utility",
            "what crypto twitter is saying",
        ],
    },
    "nova": {
        "name": "NOVA",
        "niche": "announcements",
        "tone": "business insider, authoritative",
        "hook_style": "breaking",
        "cta_style": "exclusive",
        "topics": [
            "new partnerships announced",
            "platform updates and features",
            "ecosystem growth numbers",
            "integration news",
            "roadmap milestones achieved",
            "new agent capabilities",
            "community expansion report",
            "token listing updates",
            "infrastructure improvements",
            "quarterly progress summary",
        ],
    },
}

# ── Referral URLs (always included in content) ─────────────────────────────

REFERRAL_URLS = {
    "primary": "https://web3sonic.com/126",
    "alt": "https://web3claw.net/126",
}

# ── Platform Facts (injected into every prompt) ────────────────────────────

PLATFORM_FACTS = """PLATFORM FACTS (use accurately):
- Sonic blockchain: 400,000 TPS, <$0.01 gas fees, Chain ID 146, EVM compatible
- 4 earning tokens: wBTC, wETH, USDC, Sonic $S
- wBTC matrix: 5 levels (0.0001 > 0.001 > 0.005 > 0.01 > 0.1 wBTC)
- wETH matrix: 5 levels (0.002 > 0.014 > 0.1 > 0.6 > 3.0 wETH)
- USDC matrix: 5 levels ($25 > $250 > $1,000 > $2,500 > $25,000)
- Sonic $S matrix: 10 levels (100 > 200 > 400 > 800 > 1,600 > 3,200 > 6,400 > 12,800 > 25,600 > 51,200 S)
- ODD referrals: 100% direct instant payment. EVEN referrals: 25% paid 4 levels deep
- Tiers: Starter $100 | Builder $250 | Accelerator $500 | Elite $1,000
- Rabby Wallet (rabby.io) recommended for Sonic chain
- Dashboard: web3sonic.com/dashboard
- Registration: web3sonic.com/126 or web3claw.net/126
- AI Agents: OpenClaw platform at web3claw.net (Accelerator+ tiers)
- Community: Matrix/Element at social.web3sonic.com"""

# ── Hook Templates ──────────────────────────────────────────────────────────

HOOK_TEMPLATES = {
    "question": [
        "Did you know {fact}?",
        "Ever wonder {question}?",
        "What if I told you {claim}?",
        "Want to know the secret to {benefit}?",
    ],
    "statement": [
        "Smart money is already doing this.",
        "The data doesn't lie.",
        "Here's what most people miss.",
        "This changes everything.",
    ],
    "math": [
        "Put in ${amount}, here's what happens.",
        "Let me show you the math.",
        "The numbers speak for themselves.",
        "${amount} today could mean ${result} tomorrow.",
    ],
    "curiosity": [
        "Here's how it actually works under the hood.",
        "Most people don't understand this part.",
        "Let me break this down for you.",
        "The tech behind this is fascinating.",
    ],
    "trending": [
        "Everyone's talking about this right now.",
        "This is blowing up in crypto circles.",
        "You're going to want to see this.",
        "The momentum is undeniable.",
    ],
    "breaking": [
        "Just in.",
        "Major update just dropped.",
        "This just happened.",
        "Breaking news from the ecosystem.",
    ],
}


# ── Market Context ──────────────────────────────────────────────────────────

_market_cache: dict = {}
_market_cache_ts: float = 0.0
_CACHE_TTL = 300  # 5 min


def get_market_context() -> dict:
    """Fetch current crypto prices for context injection.

    Returns dict with keys: BTC, ETH, S, USDC and their PriceData.
    Caches for 5 minutes to avoid hammering CoinGecko.
    """
    import time
    global _market_cache, _market_cache_ts

    now = time.time()
    if _market_cache and (now - _market_cache_ts) < _CACHE_TTL:
        return _market_cache

    try:
        prices = get_prices(["BTC", "ETH", "S", "BNB", "ASTER"])
        _market_cache = prices
        _market_cache_ts = now
        return prices
    except Exception as exc:
        log.warning("Market context fetch failed: %s", exc)
        return _market_cache or {}


def _format_market_summary(prices: dict) -> str:
    """Format prices into a concise summary string for prompt injection."""
    if not prices:
        return "Market data unavailable."
    lines = []
    for sym in ("BTC", "ETH", "S", "BNB"):
        p = prices.get(sym)
        if p and isinstance(p, PriceData) and p.usd > 0:
            sign = "+" if p.change_24h >= 0 else ""
            if p.usd >= 100:
                lines.append(f"{sym}: ${p.usd:,.0f} ({sign}{p.change_24h:.1f}%)")
            else:
                lines.append(f"{sym}: ${p.usd:.4f} ({sign}{p.change_24h:.1f}%)")
    return " | ".join(lines) if lines else "Market data unavailable."


# ── Topic Picker ────────────────────────────────────────────────────────────

def pick_topic(agent_name: str, override: Optional[str] = None) -> str:
    """Select topic based on day rotation + optional override.

    Rotates through the agent's topic list daily so no topic repeats
    within the cycle. Each agent gets a different offset to avoid
    all agents discussing the same index on the same day.
    """
    if override:
        return override

    agent = AGENTS.get(agent_name)
    if not agent:
        raise ValueError(f"Unknown agent: {agent_name}")

    topics = agent["topics"]
    day_of_year = datetime.datetime.now().timetuple().tm_yday
    # Each agent gets a unique offset based on its name hash
    agent_offset = int(hashlib.md5(agent_name.encode()).hexdigest()[:4], 16)
    idx = (day_of_year + agent_offset) % len(topics)
    return topics[idx]


# ── System Prompts ──────────────────────────────────────────────────────────

def _build_agent_system_prompt(agent_name: str) -> str:
    """Build the system prompt for a specific agent persona."""
    agent = AGENTS[agent_name]
    return f"""You are {agent['name']}, a content creator for Web3Claw — an AI-powered platform on Sonic blockchain.

YOUR PERSONA:
- Niche: {agent['niche']}
- Tone: {agent['tone']}
- Hook style: {agent['hook_style']}
- CTA style: {agent['cta_style']}

VOICE RULES:
- Write in Che's voice: laid-back, confident, builder energy
- NEVER say "As an AI..." or reveal you are artificial
- Be authentic, not salesy — share value first, pitch second
- Use first person naturally: "I've been looking at...", "Here's what I found..."
- Short paragraphs, punchy sentences, conversational flow

{PLATFORM_FACTS}

REFERRAL LINKS (include naturally):
- Primary: {REFERRAL_URLS['primary']}
- Alt: {REFERRAL_URLS['alt']}

NEVER guarantee specific income. Present earnings as dependent on effort and network activity."""


# ── Content Generators ──────────────────────────────────────────────────────

def generate_script(
    agent_name: str,
    topic: Optional[str] = None,
    duration_secs: int = 45,
) -> Optional[str]:
    """Generate a 30-60 sec video script with hook/value/cta structure.

    Returns the script text or None on failure.
    """
    agent = AGENTS.get(agent_name)
    if not agent:
        log.error("Unknown agent: %s", agent_name)
        return None

    selected_topic = pick_topic(agent_name, topic)
    prices = get_market_context()
    market_summary = _format_market_summary(prices)

    prompt = f"""Write a YouTube Shorts script ({duration_secs} seconds when read aloud) about: {selected_topic}

CURRENT MARKET: {market_summary}

STRUCTURE (follow exactly):
1. HOOK (first 3 seconds — must stop the scroll)
   Your hook style is "{agent['hook_style']}" — use it.
2. VALUE (20-40 seconds — teach something real)
   Share actual insight, data, or step-by-step.
3. CTA (last 5 seconds — drive action)
   Your CTA style is "{agent['cta_style']}".
   Include web3sonic.com/126 or web3claw.net/126.

FORMAT:
[HOOK]
<hook text — 1-2 sentences>

[VALUE]
<main content — 3-6 sentences>

[CTA]
<call to action — 1-2 sentences with link>

RULES:
- Write for SPOKEN delivery — conversational, no jargon dumps
- {duration_secs} seconds means roughly {duration_secs * 2} words
- Include at least ONE specific number or fact
- End with web3sonic.com/126 or web3claw.net/126
- No hashtags in the script body"""

    system = _build_agent_system_prompt(agent_name)

    result = call_llm_with_retry(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        model="meta/llama-3.3-70b-instruct",
        max_tokens=600,
        temperature=0.85,
        api_key=NVIDIA_KEY,
        timeout=60,
        retries=2,
    )

    if result:
        log.info("Script generated for %s on topic: %s", agent_name, selected_topic)
    else:
        log.error("Script generation failed for %s", agent_name)

    return result


def generate_article(
    agent_name: str,
    topic: Optional[str] = None,
) -> Optional[dict]:
    """Generate a Paragraph-ready markdown article.

    Returns dict with keys: title, markdown, tags
    or None on failure.
    """
    agent = AGENTS.get(agent_name)
    if not agent:
        log.error("Unknown agent: %s", agent_name)
        return None

    selected_topic = pick_topic(agent_name, topic)
    prices = get_market_context()
    market_summary = _format_market_summary(prices)

    prompt = f"""Write a blog article about: {selected_topic}

CURRENT MARKET: {market_summary}

REQUIREMENTS:
- 700-900 words in markdown
- Strong title (SEO-friendly, include a keyword)
- ## headers for each section
- Bold important terms
- Include web3sonic.com/126 at least TWICE naturally
- Include ONE link to [Web3 Sonic](https://web3sonic.com) with keyword anchor text
- Include platform facts where relevant — be specific
- Hook opening paragraph
- Strong closing CTA

END every article with this exact footer block:

---
**Explore the platform:** [Web3 Sonic — decentralized income on Sonic blockchain](https://web3sonic.com) | [Get started: web3claw.net/126](https://web3claw.net/126)

*Chain: Sonic (chainID 146) | Tokens: wBTC / wETH / USDC / $S | Community: Element/Matrix*

---

Also output a title line at the very top in this format:
TITLE: Your Article Title Here

And a tags line:
TAGS: tag1, tag2, tag3, tag4, tag5"""

    system = _build_agent_system_prompt(agent_name)

    result = call_llm_with_retry(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        model="meta/llama-3.3-70b-instruct",
        max_tokens=1800,
        temperature=0.82,
        api_key=NVIDIA_KEY,
        timeout=120,
        retries=2,
    )

    if not result:
        log.error("Article generation failed for %s", agent_name)
        return None

    # Parse title and tags from the output
    lines = result.strip().split("\n")
    title = selected_topic.title()
    tags = []
    markdown_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.upper().startswith("TITLE:"):
            title = stripped[6:].strip().strip('"').strip("'")
        elif stripped.upper().startswith("TAGS:"):
            tags = [t.strip() for t in stripped[5:].split(",") if t.strip()]
        else:
            markdown_lines.append(line)

    markdown = "\n".join(markdown_lines).strip()

    log.info("Article generated for %s: %s", agent_name, title)
    return {
        "title": title,
        "markdown": markdown,
        "tags": tags or ["web3", "sonic", "crypto", agent["niche"]],
        "agent": agent_name,
        "topic": selected_topic,
    }


def generate_wa_message(
    agent_name: str,
    topic: Optional[str] = None,
) -> Optional[str]:
    """Generate a WhatsApp-formatted message.

    Returns formatted text string or None on failure.
    WhatsApp uses *bold*, _italic_, ~strikethrough~, and plain text.
    """
    agent = AGENTS.get(agent_name)
    if not agent:
        log.error("Unknown agent: %s", agent_name)
        return None

    selected_topic = pick_topic(agent_name, topic)
    prices = get_market_context()
    market_summary = _format_market_summary(prices)

    prompt = f"""Write a WhatsApp message about: {selected_topic}

CURRENT MARKET: {market_summary}

FORMAT RULES:
- 150-250 words MAX (WhatsApp messages must be concise)
- Use WhatsApp formatting: *bold* for key terms, _italic_ for emphasis
- Start with an attention-grabbing hook (your style: {agent['hook_style']})
- Include ONE actionable insight or tip
- End with CTA to web3sonic.com/126 or web3claw.net/126
- Use line breaks for readability
- Can use relevant emojis sparingly (max 3-4)
- NO markdown headers (##) — this is WhatsApp, not a blog
- NO hashtags

STRUCTURE:
Hook line
(blank line)
Value content (2-3 short paragraphs)
(blank line)
CTA with link"""

    system = _build_agent_system_prompt(agent_name)

    result = call_llm_with_retry(
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        model="meta/llama-3.3-70b-instruct",
        max_tokens=400,
        temperature=0.85,
        api_key=NVIDIA_KEY,
        timeout=45,
        retries=2,
    )

    if result:
        log.info("WA message generated for %s on topic: %s", agent_name, selected_topic)
    else:
        log.error("WA message generation failed for %s", agent_name)

    return result


def list_agents() -> list[str]:
    """Return list of all agent names."""
    return list(AGENTS.keys())


def get_agent_info(agent_name: str) -> Optional[dict]:
    """Return agent config dict or None if not found."""
    return AGENTS.get(agent_name)

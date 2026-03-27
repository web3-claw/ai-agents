# Web3 Claw AI Agents

### Your own AI content team — fork it, insert your ID, deploy.

```
 ╔═══════════════════════════════════════════════════╗
 ║                                                   ║
 ║   WEB3 CLAW — AI AGENT WORKFORCE                 ║
 ║   ──────────────────────────────                  ║
 ║                                                   ║
 ║   6 AI Agents  ·  Auto Content  ·  Multi-Platform ║
 ║   YouTube Shorts · Paragraph · WhatsApp · Matrix  ║
 ║                                                   ║
 ║   Fork → Insert Your ID → Deploy → Earn           ║
 ║                                                   ║
 ╚═══════════════════════════════════════════════════╝
```

## What Is This?

An open-source AI content team that creates and publishes content about Web3 Claw — automatically.

6 AI agents, each with their own personality, voice, and content niche:

| Agent | Role | Content Style |
|-------|------|---------------|
| **PIXEL** | Onboarding | Beginner-friendly walkthroughs |
| **ORION** | Market Alpha | Bitcoin + Sonic analysis |
| **VEGA** | Earnings Math | ROI breakdowns, the numbers |
| **FORGE** | Technical | Smart contract deep dives |
| **PULSE** | Trending | Viral hooks + crypto trends |
| **NOVA** | Announcements | Partnership & ecosystem news |

Coordinated by **HERMES** — the invisible CEO agent.

## Quick Start

### 1. Get Your ID

You need a Web3 Sonic ID. Registration costs less than a penny:

1. Download [Rabby Wallet](https://rabby.io)
2. Fund with a few dollars of Sonic (S)
3. Register at [web3sonic.com/register](https://web3sonic.com/register)
4. Your ID = your number (e.g., `126`)

Or register directly on-chain:
```
Registration Contract: 0x1185902761B8C36df01C4602A028c9ced023279A
Chain: Sonic Mainnet (chainId 146)
RPC: https://rpc.soniclabs.com
```

### 2. Fork & Configure

```bash
# Fork this repo, then:
git clone https://github.com/YOUR_USERNAME/ai-agents.git
cd ai-agents
cp .env.example .env
```

Edit `.env` — insert YOUR Web3 Sonic ID:

```env
# YOUR REFERRAL ID (this is the only thing you MUST change)
WEB3_SONIC_ID=126

# Your referral URLs (auto-generated from ID)
# web3sonic.com/YOUR_ID
# web3claw.net/YOUR_ID
```

### 3. Install & Run

```bash
pip install -r requirements.txt

# Preview content (dry run)
python -m content_engine.scheduler dry 08:00

# Run a single slot
python -m content_engine.scheduler run

# Run as daemon (all 14 daily slots)
python -m content_engine.scheduler daemon
```

## Architecture

```
HERMES (CEO — orchestrates everything)
├── PIXEL  (Community)  — onboarding, tutorials, walkthroughs
├── ORION  (Strategy)   — market analysis, alpha calls
├── VEGA   (Strategy)   — earnings math, ROI breakdowns
├── FORGE  (Technical)  — smart contracts, tech explainers
├── PULSE  (Intel)      — trending topics, viral hooks
└── NOVA   (BizDev)     — announcements, partnerships
```

### Daily Output

| Time | Agent | Platform | Content Type |
|------|-------|----------|-------------|
| 06:00 | PULSE | Paragraph | Trending hook article |
| 07:00 | ORION | Paragraph | Market alpha article |
| 08:00 | PIXEL | YouTube + WhatsApp | Onboarding Short |
| 09:00 | VEGA | YouTube | Earnings math Short |
| 10:00 | FORGE | YouTube | Technical Short |
| 11:00 | PULSE | YouTube | Trending Short |
| 12:00 | ORION | YouTube + WhatsApp | Market alpha Short |
| 13:00 | NOVA | Paragraph | Announcement article |
| 14:00 | VEGA | YouTube + Paragraph | Math breakdown |
| 15:00 | PIXEL | YouTube | Tutorial Short |
| 16:00 | FORGE | YouTube + Paragraph | Deep dive |
| 17:00 | PULSE | YouTube | Trending Short |
| 18:00 | ORION | YouTube + WhatsApp | Evening alpha |
| 20:00 | VEGA | YouTube | Daily recap |

**Daily total: 11 YouTube Shorts + 5 articles + 3 WhatsApp blasts**

## Agent Collaboration

Agents don't just work alone — they collaborate:

```python
from content_engine.collaboration import market_deep_dive, bull_vs_bear

# ORION spots alpha → VEGA does the math → PIXEL shows how to start
result = market_deep_dive("sonic chain opportunity")

# ORION vs PULSE debate format
result = bull_vs_bear("is now the time to enter crypto")
```

### Collab Presets

| Preset | Agents | Format |
|--------|--------|--------|
| `market_deep_dive` | ORION → VEGA → PIXEL → FORGE | Tag team article |
| `trending_coverage` | PULSE → PIXEL | Trending + walkthrough |
| `onboarding_series` | PIXEL → VEGA | Join + earn |
| `bull_vs_bear` | ORION vs PULSE | Debate Short |
| `tech_vs_earnings` | FORGE vs VEGA | Tech vs numbers |

## Platform Setup

### YouTube Shorts (auto-upload)
```bash
# One-time OAuth setup
python -m content_engine.publisher setup-youtube
# Follow the browser flow to authorize
```

### Paragraph (articles)
```env
PARAGRAPH_API_KEY=your_key_here
```
Get your API key at [paragraph.com](https://paragraph.com)

### WhatsApp (via Matrix bridge)
```env
MATRIX_BASE=https://your-matrix-server.com
MATRIX_ADMIN_TOKEN=your_token
WHATSAPP_ROOM_ID=your_room_id
```

### LLM Provider
```env
# Option 1: NVIDIA NIM (FREE)
NVIDIA_API_KEY=your_nvidia_key
LLM_ENDPOINT=https://integrate.api.nvidia.com/v1/chat/completions

# Option 2: LiteLLM proxy (recommended for multi-model)
LLM_ENDPOINT=http://127.0.0.1:4000/v1/chat/completions
LLM_API_KEY=your_litellm_key

# Option 3: Any OpenAI-compatible API
LLM_ENDPOINT=https://api.openai.com/v1/chat/completions
LLM_API_KEY=your_key
```

## File Structure

```
ai-agents/
├── README.md
├── .env.example
├── requirements.txt
├── config.yaml                    # Your ID + agent config
├── content_engine/
│   ├── __init__.py
│   ├── agent_content.py           # 6 agent personas + content generation
│   ├── publisher.py               # Paragraph, WhatsApp, YouTube publishers
│   ├── video_pipeline.py          # TTS, AI video, FFmpeg assembly
│   ├── scheduler.py               # 14 daily slots + daemon mode
│   └── collaboration.py           # Multi-agent collab patterns
├── agent_profiles/
│   ├── hermes.yaml                # CEO orchestrator
│   ├── pixel.yaml                 # Onboarding content creator
│   ├── orion.yaml                 # Market alpha caller
│   ├── vega.yaml                  # Earnings math specialist
│   ├── forge.yaml                 # Technical deep diver
│   ├── pulse.yaml                 # Trending content curator
│   └── nova.yaml                  # Announcement specialist
├── content_library/
│   ├── scripts/                   # 30 ready-to-use Short scripts
│   ├── articles/                  # 6 Paragraph articles
│   └── whatsapp/                  # 6 WhatsApp messages
└── docs/
    ├── AGENTS.md                  # Full agent identity guide
    └── SETUP.md                   # Detailed setup instructions
```

## How It Works

1. **You fork this repo** and set your Web3 Sonic ID
2. **Agents generate content** using LLM (scripts, articles, messages)
3. **Video pipeline** creates YouTube Shorts (TTS + AI visuals + captions)
4. **Publishers** auto-post to YouTube, Paragraph, and WhatsApp
5. **Every piece of content** includes YOUR referral link
6. **People register** through your link → you earn

All content promotes Web3 Sonic / Web3 Claw with your referral ID baked in.

## Customize Your Agents

Edit `config.yaml` to personalize:

```yaml
# Your identity
referral_id: 126
referral_urls:
  primary: "https://web3sonic.com/126"
  secondary: "https://web3claw.net/126"

# Agent toggles (enable/disable any agent)
agents:
  pixel: true
  orion: true
  vega: true
  forge: true
  pulse: true
  nova: true

# Content frequency
daily_shorts: 11
daily_articles: 5
daily_whatsapp: 3

# LLM settings
model: "nvidia/nemotron-3-super-120b-a12b"
temperature: 0.8
```

## Web3 Sonic Platform

| Stat | Value |
|------|-------|
| AI Agents | 30+ active |
| Tasks Completed | 82,935+ |
| Uptime | 10,802+ hours |
| Messages Processed | 33,995+ |

### Smart Contracts (Sonic Mainnet)

| Contract | Address |
|----------|---------|
| Registration | `0x1185902761B8C36df01C4602A028c9ced023279A` |
| Sonic S Matrix | `0x88d8a16d4c58e929093e0639eba428727cca9f07` |
| wBTC Matrix | `0x3dBF8399b17293b811cd98570a86ec777B25faa8` |
| wETH Matrix | `0x71A00A9EB4DD931dBD432Cc48D102464183f6968` |
| USDC Matrix | `0x6854E2f33a81B8487A9CF5111577416C65F0Bc13` |

### Get Started

1. [Download Rabby Wallet](https://rabby.io)
2. Fund with Sonic (S) — a few dollars is enough
3. [Register on Web3 Sonic](https://web3sonic.com/register) — costs less than a penny
4. Fork this repo
5. Insert your ID
6. Deploy your AI content team

---

## Contributing

PRs welcome. Add new agent personas, content templates, platform integrations, or collaboration patterns.

## License

MIT — fork it, use it, earn with it.

---

**Built by [Web3 Claw](https://web3claw.net) — Where AI Meets DeFi**

[web3sonic.com](https://web3sonic.com) · [web3claw.net](https://web3claw.net) · [@Web3-Claw](https://youtube.com/@Web3-Claw)

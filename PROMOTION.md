# ZEVORA Promotion Kit — Free Channels (copy-paste ready)

Repo: https://github.com/dani12po/zevora
Tagline: Self-hosted AI coding workspace — local Llama 3 8B, zero API key needed, your code never leaves your machine.

---

## 1. Show HN (news.ycombinator.com) — post as "Show HN: ..."

**Title:**
Show HN: Zevora – self-hosted AI coding workspace with a bundled local LLM (no API key)

**Text:**
Hi HN! I built Zevora, a self-hosted AI coding workspace that ships with a bundled local model (Llama 3 8B GGUF via llama.cpp) — it works fully offline with no API key, and optionally routes to DeepSeek/OpenAI/Anthropic/Gemini/xAI when you need more power.

Why: I wanted a coding agent where my code, conversations, and project context never leave my machine unless I explicitly say so. Most tools require a cloud subscription; Zevora flips that — local-first, cloud-optional.

What it does:
- Web UI on localhost:7432 (FastAPI + vanilla JS)
- Adaptive hybrid router: local model for simple tasks, cloud for complex/long-context
- Project context engine: indexes your codebase so the AI understands your files
- MCP tools (file read/write, terminal, git) — all approval-gated
- Local memory + exact cache so repeated questions don't hit the API
- Chat export to Markdown/JSON, rate limiting, Docker one-liner: `docker compose up -d`

349 tests, pyflakes-clean CI on Ubuntu+Windows (Python 3.11). MIT licensed.

Repo: https://github.com/dani12po/zevora
Feedback welcome — especially on the router heuristics and what would make you trust a local-first agent with your codebase.

*Tip: post Tuesday–Thursday 8–10 AM ET. Answer every comment in the first 2 hours.*

---

## 2. Reddit

### r/SelfHostedAI or r/LocalLLaMA — title:
Zevora: self-hosted AI coding workspace — bundled Llama 3 8B, runs 100% offline, no API key

**Body:**
I've been building Zevora (MIT, Python/FastAPI): a self-hosted coding workspace with a bundled local GGUF model via llama.cpp. Fully offline out of the box; cloud providers (DeepSeek, OpenAI, Anthropic, Gemini, xAI, NVIDIA) are optional fallbacks via an adaptive router.

Highlights:
- Local-first: code + chat + memory never leave your machine by default
- Project context engine indexes your repo for grounded answers
- Approval-gated MCP tools (files, terminal, git)
- Exact cache + local memory to avoid repeat API calls
- Chat export (MD/JSON), per-IP rate limiting on expensive endpoints
- `docker compose up -d` and you're running

Repo + docs: https://github.com/dani12po/zevora

Happy to answer questions about the router design or the llama.cpp integration. What would you want to see before self-hosting something like this?

### Other subreddits (rotate, don't cross-post the same day):
r/opensource (needs OSI license — MIT ✔, add "Promotional" flair), r/coolgithubprojects, r/SideProject, r/AI_Agents, r/Python (monthly showcase thread only)

---

## 3. DEV Community article (dev.to) — #showdev
Title ideas:
- "I built a self-hosted AI coding workspace that works with zero API keys"
- "Local-first AI coding: how Zevora routes between a bundled Llama 3 8B and cloud models"

Outline:
1. The problem (cloud-only coding agents, privacy)
2. Architecture diagram (from ARCHITECTURE.md)
3. How the hybrid router picks local vs cloud
4. Quick start (docker compose up -d)
5. What I learned building it (index cache bug story is great content: "why my project index missed file changes")
Tag: #python #fastapi #showdev #ai

---

## 4. Awesome-list PRs (submit as GitHub issues/PRs)

- **awesome-selfhosted-ai** (glincker/awesome-selfhosted-ai) — section: Coding Agents. Entry:
  `- [Zevora](https://github.com/dani12po/zevora) - Self-hosted AI coding workspace with bundled Llama 3 8B via llama.cpp; offline-first with optional cloud routing. (Python)`
- **awesome-ai-agents-2026** (ARUNAGIRINATHAN-K/...) — use their GitHub Issue form "Submit Agent"
- **awesome-local-llm**, **awesome-llm-apps** — same one-liner
- Also register on **LibHunt** (free, paste repo URL) and **DevHunt** (devhunt.org, free launch)

## 5. GitHub repo polish (do first — 30 minutes, biggest ROI)
- [ ] Topics: `ai-agent`, `local-llm`, `llama-cpp`, `self-hosted`, `fastapi`, `coding-assistant`, `gguf`, `offline-ai`, `python`
- [ ] About description: "Self-hosted AI coding workspace — bundled Llama 3 8B, offline-first, optional cloud routing. Docker one-liner."
- [ ] Social preview image (Settings → Social preview): screenshot of the web UI
- [ ] Add screenshots/GIF to README (UI chat + providers page)
- [ ] Enable GitHub Discussions (Q&A) — lowers friction vs issues
- [ ] Tag a release: `v0.3.0` with release notes (export, rate limiting, Docker, modular api/ package)

## 6. Free directories (10 min each)
- AlternativeTo — list as alternative to "Cursor / GitHub Copilot" (open-source tab)
- OpenSourceAlternative.to — free submission, waitlisted
- selfh.st and Terminal Trove — submit form
- Product Hunt — schedule a launch once you have a demo GIF + 50+ stars (launching too early wastes it)

---

## Suggested order
1. GitHub polish + release v0.3.0 (today)
2. DEV.to article (1–2 days)
3. Show HN (best day: Tue–Thu)
4. Reddit posts spread over 2 weeks (1 subreddit per 3–4 days)
5. Awesome-list PRs
6. Directories

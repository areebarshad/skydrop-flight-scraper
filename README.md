<h1 align="center">✈️ skydrop</h1>

<p align="center">
  <b>Autonomous flight monitoring that only bothers your inbox when the math checks out.</b>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB?style=flat&logo=python&logoColor=white" alt="Python 3.12+"/>
  <img src="https://img.shields.io/badge/Platform-Windows%20%7C%20macOS%20%7C%20Linux-0078D4?style=flat" alt="Platform"/>
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat" alt="MIT License"/>
  <img src="https://img.shields.io/badge/Tests-72%20passing-brightgreen?style=flat" alt="72 tests passing"/>
  <img src="https://img.shields.io/badge/Email-Gmail%20SMTP-EA4335?style=flat&logo=gmail&logoColor=white" alt="Gmail SMTP"/>
</p>

<p align="center">
  Set a budget. Set a deadline. Walk away.<br/>
  skydrop watches Google Flights around the clock, ranks every result against your constraints, and fires a targeted email alert — only when something genuinely worth acting on appears.
</p>

---

## What it does

Stop refreshing Google Flights manually. skydrop scrapes live flight data on a schedule, runs every result through a three-tier ranking engine, and sends an email only when the state has meaningfully changed. No duplicate alerts. No noise.

| Capability | What you get |
|---|---|
| **Three-tier ranking** | Every itinerary sorted into Direct Match, Near Miss, or Baseline — so every email tells you exactly why a flight is worth looking at |
| **Smart alert logic** | Immediate alert on a new Tier 1 or a price drop ≥ 5%; digest-only (max once per 24 hours) when only near-misses exist; silence otherwise |
| **Provider fallback chain** | Fast HTTP-only scraper first → headless Chromium if blocked → optional SerpApi — fully automatic, no manual intervention |
| **Anti-spam guarantee** | SQLite state tracking per route means the same flight never triggers two emails |
| **Local web dashboard** | Built-in FastAPI dashboard at `localhost:8765` — review tiers, history, alert state, and a Gaussian price distribution chart in a browser |
| **Dry-run preview** | Render the exact email HTML before sending a single real message |
| **Fully offline tests** | All 72 tests run without network calls or SMTP — safe to run anywhere |
| **Zero dependencies on paid APIs** | SerpApi is optional; the free tier is fully functional |

---

## How To Use

> **30-second path from install to first alert.**

### 1. Install

```bash
# Navigate into the project directory
cd flight-alert-scraper

# Install all dependencies (creates .venv automatically)
uv sync

# Install the browser automation engine (one-time, ~150 MB)
uv run patchright install chromium
```

### 2. Configure credentials

Copy the example env file and fill in your Gmail details:

```bash
cp .env.example .env
```

Edit `.env`:

```dotenv
SMTP_USER=you@gmail.com
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Google App Password — see below
ALERT_RECIPIENT=you@example.com
DB_PATH=./flight_alerts.db
```

**Generating a Google App Password:**
1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Ensure **2-Step Verification** is enabled
3. Search for **"App passwords"** and create one (name it anything, e.g. *skydrop*)
4. Paste the 16-character code into `SMTP_APP_PASSWORD`

### 3. Define your routes

Edit `watchlist.yaml` with the routes you want to watch:

```yaml
queries:
  - origin: IAD
    destination: KHI
    depart_date: "2026-12-01"
    cabin: economy
    adults: 1
    constraints:
      max_price_usd: "1200.00"
      max_duration_minutes: 1320    # 22 hours
```

### 4. Preview before going live

```bash
# Initialize the database (only needed once)
uv run flight-alert-scraper init-db

# Dry run — renders the email to artifacts/preview/ without sending
uv run flight-alert-scraper check --dry-run
```

Open `artifacts/preview/<timestamp>_email.html` in a browser to see exactly what recipients will receive.

### 5. Run a live check

```bash
uv run flight-alert-scraper check
```

An email fires only if the state has meaningfully changed since the last run. If nothing changed, nothing is sent.

### 6. Automate it

Set up Windows Task Scheduler to run checks every 6 hours — no terminal popups, fully background:

```powershell
schtasks /create /tn "skydrop" `
  /tr "cmd /c cd /d C:\path\to\flight-alert-scraper && uv run flight-alert-scraper check" `
  /sc hourly /mo 6 /st 06:00 /f
```

See [Automating with Windows Task Scheduler](#-automating-with-windows-task-scheduler) for the full setup including battery, wake, and background logon settings.

---

## How It Works

```
watchlist.yaml  ──▶  Scraper Chain  ──▶  Ranking Engine  ──▶  State DB  ──▶  Email
      │                    │                    │                  │
  your routes        HTTP → Browser        Tier 1 / 2 / 3    change detect    alert
                      → SerpApi
```

1. Reads one or more routes from **`watchlist.yaml`** (origin, destination, dates, budget, time limit).
2. Fetches live results via a **three-provider fallback chain** — fast HTTP-only first, headless browser if blocked, optional SerpApi as a last resort.
3. Passes every result through the **ranking engine**, which assigns each itinerary to a tier based on your constraints.
4. Compares against the **last known state** stored in SQLite.
5. Sends an email **only when the state has meaningfully changed** — no duplicate alerts, no noise.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.12+ | Check with `python --version` |
| **uv** | latest | Fast Python package manager — [install guide](https://docs.astral.sh/uv/getting-started/installation/) |
| **Gmail account** | — | Required for email alerts (App Password needed) |
| **Google 2FA** | enabled | Required to generate an App Password |

**Windows quick install:**

```powershell
winget install astral-sh.uv
```

**macOS quick install:**

```bash
brew install uv
```

**Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

> `uv` handles the virtual environment automatically. You do not need to create one manually.

---

## Installation

```bash
# 1. Navigate into the project directory
cd flight-alert-scraper

# 2. Install all dependencies (creates .venv automatically)
uv sync

# 3. Install the browser automation engine (one-time)
uv run patchright install chromium
```

---

## Configuration

### Environment Variables (`.env`)

```dotenv
# ── Database ──────────────────────────────────────────────────
DB_PATH=./flight_alerts.db           # SQLite file path (created automatically)

# ── Email ─────────────────────────────────────────────────────
SMTP_USER=you@gmail.com              # Your Gmail address
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx  # Google App Password (16 chars, spaces OK)
ALERT_RECIPIENT=you@example.com      # Where alerts are delivered

# ── Optional ──────────────────────────────────────────────────
SERPAPI_KEY=                         # SerpApi key — leave blank to disable
WATCHLIST_PATH=./watchlist.yaml      # Override the default watchlist location

# ── Browser scraper knobs (bisect detection without code edits) ───────────────
BROWSER_HEADLESS=true                # Set false to watch the browser window
BROWSER_BLOCK_ASSETS=true            # Set false to disable media-file interception
BROWSER_CHANNEL=                     # Set to "chrome" to use installed Chrome
BROWSER_WAIT_SECONDS=90              # Polling budget before giving up on render

# ── Proxy (leave blank to disable) ───────────────────────────────────────────
PROXY_URL=                           # e.g. http://user:pass@proxy.host:8080
PROXY_POOL=                          # Comma-separated list; round-robins over entries
```

---

### Watchlist (`watchlist.yaml`)

Define every route you want to monitor. Each entry is one search query.

```yaml
queries:
  - origin: IAD                        # IATA airport code (departure)
    destination: KHI                   # IATA airport code (arrival)
    depart_date: "2026-12-01"          # ISO 8601 date
    return_date: null                  # null = one-way; "2026-12-15" = round-trip
    cabin: economy                     # economy | business | first
    adults: 1                          # number of passengers

    constraints:
      max_price_usd: "1200.00"         # hard budget ceiling (Tier 1 threshold)
      max_duration_minutes: 1320       # 22 hours — hard time ceiling (Tier 1 threshold)
      max_stops: null                  # null = any; 0 = nonstop only; 1 = max 1 stop

      # ── Tier 2 near-miss thresholds ────────────────────────
      value_deal_discount: "0.20"      # 20%+ under budget → qualifies as Value Deal
      value_deal_duration_buffer_minutes: 180  # up to 3h over the time limit for a Value Deal
      time_saver_price_overage: "0.10" # ≤10% over budget → qualifies as Time Saver

      # ── Effective-cost weighting ────────────────────────────
      hourly_time_penalty_usd: "20.00" # $20 per extra hour added to effective cost
```

**Multiple routes** — add as many entries as you like under `queries:`:

```yaml
queries:
  - origin: IAD
    destination: KHI
    depart_date: "2026-12-01"
    cabin: economy
    adults: 1
    constraints:
      max_price_usd: "1200.00"
      max_duration_minutes: 1320

  - origin: JFK
    destination: LHR
    depart_date: "2026-11-15"
    return_date: "2026-11-22"
    cabin: business
    adults: 2
    constraints:
      max_price_usd: "3500.00"
      max_duration_minutes: 480
```

---

## CLI Reference

All commands follow the form:

```
uv run flight-alert-scraper <command> [options]
```

---

### `check`

Scrapes all routes in `watchlist.yaml`, ranks results, and sends alerts on state changes.

```
uv run flight-alert-scraper check [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--dry-run` | `False` | Render emails to `artifacts/preview/` instead of sending |
| `--watchlist PATH` | `./watchlist.yaml` | Override the watchlist file path |

```bash
uv run flight-alert-scraper check                                    # live run
uv run flight-alert-scraper check --dry-run                          # preview only
uv run flight-alert-scraper check --watchlist ~/my-routes.yaml       # custom watchlist
```

---

### `ui`

Start the local web dashboard at `http://127.0.0.1:8765`. Displays tier results, scrape history, and alert state in a browser UI.

```
uv run flight-alert-scraper ui [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--port N` | `8765` | Port to listen on |
| `--db PATH` | from `.env` | Path to the SQLite file |
| `--watchlist PATH` | `./watchlist.yaml` | Override the watchlist file path |
| `--no-browser` | `False` | Don't auto-open the browser on launch |

```bash
uv run flight-alert-scraper ui                      # open dashboard at localhost:8765
uv run flight-alert-scraper ui --port 9000          # custom port
uv run flight-alert-scraper ui --no-browser         # headless (server mode)
```

---

### `init-db`

Creates the SQLite database and applies the current schema. Safe to run multiple times — migrates without destroying data.

```
uv run flight-alert-scraper init-db [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--db PATH` | `./flight_alerts.db` | Path to the SQLite file |

```bash
uv run flight-alert-scraper init-db
uv run flight-alert-scraper init-db --db /data/flights.db
```

---

### `history`

Displays a table of recent scrape runs for all watched routes (or a specific one).

```
uv run flight-alert-scraper history [QUERY_KEY] [OPTIONS]
```

| Argument / Option | Default | Description |
|---|---|---|
| `QUERY_KEY` | *(all routes)* | Optional 16-char key to filter to one route |
| `--db PATH` | `./flight_alerts.db` | Path to the SQLite file |
| `--limit N` | `20` | Number of rows to show per route |

**Output columns:**

| Column | Meaning |
|---|---|
| **Query Key** | First 8 chars of the route's SHA-256 key |
| **Started** | UTC timestamp of the scrape |
| **Provider** | Which data source succeeded (`web`, `browser`, `serp`) |
| **Status** | `ok`, `error`, or `no_results` |
| **T1 / T2** | Count of Tier 1 and Tier 2 matches found |
| **Suppressed** | Reason the last alert was suppressed (e.g., `within_24h`) |

```bash
uv run flight-alert-scraper history
uv run flight-alert-scraper history --limit 50
uv run flight-alert-scraper history a1b2c3d4   # filter by key prefix
```

---

### `test-email`

Renders a synthetic email with fake flight data — useful for verifying template layout and SMTP credentials without triggering a real scrape.

```
uv run flight-alert-scraper test-email [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--dry-run` / `--send` | `--dry-run` | Write to `artifacts/preview/` vs. actually send |
| `--db PATH` | `./flight_alerts.db` | Path to the SQLite file |

```bash
uv run flight-alert-scraper test-email           # preview HTML locally
uv run flight-alert-scraper test-email --send    # verify SMTP credentials
```

---

### `rank`

Reads a JSON fixture file, runs it through the ranking engine, and prints a formatted tier table. No network calls, no database writes — useful for debugging tier logic offline.

```
uv run flight-alert-scraper rank --from-fixture FILE
```

**Fixture format:**

```json
{
  "query": {
    "origin": "IAD",
    "destination": "KHI",
    "depart_date": "2026-12-01",
    "cabin": "economy",
    "adults": 1,
    "constraints": {
      "max_price_usd": "1200.00",
      "max_duration_minutes": 1320,
      "max_stops": null,
      "value_deal_discount": "0.20",
      "value_deal_duration_buffer_minutes": 180,
      "time_saver_price_overage": "0.10",
      "hourly_time_penalty_usd": "20.00"
    }
  },
  "options": [...]
}
```

```bash
uv run flight-alert-scraper rank --from-fixture tests/fixtures/iad_khi.json
```

---

## Tier System

Every itinerary is assigned to exactly one tier based on your constraints.

### Tier 1 — Direct Match ✅

*The flight you actually want.* Meets **all** constraints simultaneously:

- Price ≤ `max_price_usd`
- Total duration ≤ `max_duration_minutes` (if set)
- Stops ≤ `max_stops` (if set)

Sorted by **(price ascending, duration ascending)**.

---

### Tier 2 — Near Miss 🔶

*Worth a look — one constraint is slightly violated, but the tradeoff is explicit.*

| Label | Condition |
|---|---|
| **Value Deal** | Price ≤ budget × (1 − `value_deal_discount`) AND duration exceeds limit by ≤ `value_deal_duration_buffer_minutes` |
| **Time Saver** | Duration ≤ limit AND price ≤ budget × (1 + `time_saver_price_overage`) |

Sorted by **effective cost** (price + time penalty for excess duration).

---

### Tier 3 — Baseline 📌

*Nothing meets your constraints — here are the objectively best options available.* Shown only when Tier 1 is empty.

| Label | How it's chosen |
|---|---|
| **Best Balance** | Minimizes effective cost (price + hourly penalty × hours) |
| **Cheapest** | Lowest price regardless of duration |
| **Fastest** | Shortest duration regardless of price |

---

### Effective Cost Formula

```
effective_cost = price_usd + (total_duration_hours × hourly_time_penalty_usd)
```

Blends money and time into a single comparable number. A `$20/hour` penalty means an extra hour of travel costs as much as $20. Adjust `hourly_time_penalty_usd` in `watchlist.yaml` to match how you value your time.

---

## Alert Logic

| Condition | Alert type | Frequency |
|---|---|---|
| A **new Tier 1** itinerary appeared | **Immediate** | Sent right away |
| Price dropped **≥ 5%** on a known Tier 1 | **Immediate** | Sent right away |
| No Tier 1 exists, Tier 2/3 results present | **Digest** | At most once per 24 hours |
| Nothing changed since last run | **Silent** | No email sent |

> **Anti-spam guarantee:** The digest is rate-limited to once every 24 hours per route. Skydrop never sends two emails for the same unchanged state.

---

## Data Sources & Fallback Chain

Providers are tried in order. If one fails or returns no usable data, the next is tried automatically.

```
1. web (google_http)        httpx + selectolax (fast, no browser)
        │
        ▼ (on block / empty result)
2. browser (google_browser) patchright headless Chromium (full JS rendering)
        │
        ▼ (only if SERPAPI_KEY is set)
3. serp (serpapi)           SerpApi Google Flights endpoint (250 free searches/month)
```

- **web** — fastest, uses no API quota.
- **browser** — kicks in when Google blocks the HTTP request. Uses [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (not playwright-stealth) to avoid fingerprint detection.
- **serp** — opt-in. Set `SERPAPI_KEY` in `.env` to enable. Free tier gives 250 searches/month.

---

## Automating with Windows Task Scheduler

Run checks automatically in the background every 6 hours — no terminal popups, no manual triggering.

### Step 1 — Register the task

Open **PowerShell** and run (adjust the path to your project root):

```powershell
schtasks /create /tn "skydrop" `
  /tr "cmd /c cd /d C:\Users\arsha\OneDrive\Documents\flight_scraper\flight-alert-scraper && uv run flight-alert-scraper check" `
  /sc hourly /mo 6 /st 06:00 /f
```

> The `/d` flag in `cd /d` is required when the project lives on a different drive than `cmd`'s current directory.

---

### Step 2 — Configure power, wake & background settings

Run the following in **PowerShell as Administrator**:

```powershell
$task = Get-ScheduledTask -TaskName "skydrop"
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries     = $false
$task.Settings.StartWhenAvailable         = $true
Set-ScheduledTask -InputObject $task

# Run in the background whether logged in, locked, or signed out
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U
Set-ScheduledTask -TaskName "skydrop" -Principal $principal
```

| Setting | What it does |
|---|---|
| `DisallowStartIfOnBatteries = $false` | Runs checks even when unplugged |
| `StopIfGoingOnBatteries = $false` | Won't abort a run if the charger is unplugged |
| `StartWhenAvailable = $true` | Catches up on a missed window immediately on wake |
| `LogonType = S4U` | Checks continue when the screen is locked, no stored password |

---

### Step 3 — Verify

```powershell
$t = Get-ScheduledTask -TaskName "skydrop"
[PSCustomObject]@{
    TaskName       = $t.TaskName
    State          = $t.State
    StartOnBattery = -not $t.Settings.DisallowStartIfOnBatteries
    StopOnBattery  = $t.Settings.StopIfGoingOnBatteries
    StartWhenAvail = $t.Settings.StartWhenAvailable
    LogonType      = $t.Principal.LogonType
}
```

Expected output:

```
TaskName       : skydrop
State          : Ready
StartOnBattery : True
StopOnBattery  : False
StartWhenAvail : True
LogonType      : S4U
```

---

### Step 4 — Test manually

```powershell
schtasks /run /tn "skydrop"
```

Wait 15–30 seconds, then inspect the run log:

```powershell
uv run flight-alert-scraper history
```

---

### Other useful scheduler commands

```powershell
schtasks /query /tn "skydrop" /fo LIST /v   # status and last run result
schtasks /delete /tn "skydrop" /f           # remove the task
schtasks /change /tn "skydrop" /mo 4        # change to every 4 hours
```

### Recommended schedule

| Frequency | Trade-off |
|---|---|
| Every 3–4 hours | More timely; slightly higher chance of rate-limiting |
| **Every 6 hours** *(recommended)* | Good balance of freshness vs. reliability |
| Once daily | Lowest footprint; fine for routes more than a week out |

---

## Running Tests

```bash
uv run pytest                                    # full suite
uv run pytest --cov=flight_alert_scraper         # with coverage
uv run pytest tests/test_ranking.py -v           # specific file
uv run ruff check .                              # linting
uv run mypy src                                  # type checking
```

All 72 tests are offline — no network calls, no email sending. Fixtures are used for parser and ranking tests.

---

## Project Layout

```
flight-alert-scraper/
├── .env.example              ← copy to .env and fill in credentials
├── watchlist.yaml            ← your routes and constraints
├── pyproject.toml            ← dependencies and tool config
│
├── src/flight_alert_scraper/
│   ├── cli.py                ← Typer CLI entry point
│   ├── config.py             ← Settings (pydantic-settings, reads .env)
│   ├── runner.py             ← per-query orchestration loop
│   │
│   ├── models/               ← pure data classes (Pydantic)
│   │   ├── flight.py         ← FlightOption, Leg, BookingLinks
│   │   ├── query.py          ← SearchQuery, Constraints, CabinClass
│   │   ├── result.py         ← RankedResults, TieredMatch, Tier, MatchLabel
│   │   └── alert.py          ← AlertDecision, AlertKind, TriggerReason
│   │
│   ├── scrapers/             ← data retrieval (HTTP, browser, SerpApi)
│   │   ├── google_http.py    ← httpx + selectolax scraper
│   │   ├── google_browser.py ← patchright headless browser scraper
│   │   ├── serpapi.py        ← SerpApi provider
│   │   ├── chain.py          ← ProviderChain (tries each in order)
│   │   └── fixture.py        ← test-only fixture loader
│   │
│   ├── parsers/              ← HTML → FlightOption parsing
│   │   ├── google.py         ← Google Flights HTML parser
│   │   └── duration.py       ← duration string → integer minutes
│   │
│   ├── engine/               ← pure business logic (no I/O)
│   │   ├── ranking.py        ← tier assignment algorithm
│   │   ├── scoring.py        ← effective_cost, pareto_front
│   │   └── diffing.py        ← detect meaningful state changes
│   │
│   ├── db/                   ← SQLite persistence (SQLModel)
│   │   ├── tables.py         ← WatchedQuery, ScrapeRun, FlightSnapshot, RunStats, AlertState ORM models
│   │   ├── repo.py           ← query helpers (includes save_run_stats for per-run Gaussian params)
│   │   └── engine.py         ← get_session, migrate
│   │
│   ├── web/                  ← local FastAPI dashboard
│   │   └── app.py
│   │
│   └── notifications/        ← email rendering and delivery
│       ├── render.py         ← Jinja2 → HTML + text
│       ├── smtp.py           ← SmtpNotifier (Gmail TLS)
│       ├── decide.py         ← AlertDecision logic
│       └── templates/
│           ├── immediate.html.j2
│           ├── immediate.txt.j2
│           ├── digest.html.j2
│           └── digest.txt.j2
│
├── tests/
│   ├── conftest.py
│   ├── test_models.py
│   ├── test_parsers.py
│   ├── test_ranking.py
│   ├── test_diffing.py
│   ├── test_decide.py
│   └── test_runner.py
│
└── artifacts/
    └── preview/              ← dry-run email previews land here
```

---

## Troubleshooting

### No email received after `check`

1. **Run `history`** — verify the scrape ran and what it found.
2. **Check the `Suppressed` column** — `within_24h` means a digest was already sent recently.
3. **Try `--dry-run`** and inspect `artifacts/preview/` — if the HTML file exists, the scraper worked but SMTP is the issue.
4. **Run `test-email --send`** to isolate SMTP from scraping entirely.

### Gmail SMTP errors

| Error | Cause | Fix |
|---|---|---|
| `SMTPAuthenticationError` | Wrong App Password | Regenerate it at myaccount.google.com |
| `534 Application-specific password required` | Using your real Gmail password | Must use an App Password (requires 2FA) |
| `Connection refused` | Port 587 blocked | Check firewall / VPN |

### Browser scraper launches but finds no flights

Google Flights sometimes requires a CAPTCHA. The browser scraper retries with a fresh session automatically, but persistent blocks may require rotating the cookie cache — delete `.cache/cookies.json` and retry.

### SerpApi returns stale results

The free tier caches results for up to 1 hour. This is expected — consider the paid tier for fresher data.

### `uv: command not found`

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows
winget install astral-sh.uv
```

---

## License

MIT — see [LICENSE](LICENSE).

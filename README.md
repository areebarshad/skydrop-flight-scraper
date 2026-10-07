# ✈️ flight-alert-scraper

> **Stop refreshing Google Flights.** Set your price and time constraints once — get an email only when something worth acting on actually changes.

Monitors flight routes on a schedule, ranks every result into a decision-quality tier, and sends targeted email alerts so you never miss a deal and never get spammed.

---

## 📋 Table of Contents

- [How It Works](#-how-it-works)
- [Prerequisites](#-prerequisites)
- [Installation](#-installation)
- [Configuration](#-configuration)
  - [Environment Variables (.env)](#environment-variables-env)
  - [Watchlist (watchlist.yaml)](#watchlist-watchlistyaml)
- [Quick Start](#-quick-start)
- [CLI Reference](#-cli-reference)
  - [check](#check)
  - [init-db](#init-db)
  - [history](#history)
  - [test-email](#test-email)
  - [rank](#rank)
- [Tier System](#-tier-system)
- [Alert Logic](#-alert-logic)
- [Data Sources & Fallback Chain](#-data-sources--fallback-chain)
- [Automating with Windows Task Scheduler](#-automating-with-windows-task-scheduler)
- [Running Tests](#-running-tests)
- [Project Layout](#-project-layout)
- [Troubleshooting](#-troubleshooting)

---

## ⚙️ How It Works

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

## 🔧 Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| **Python** | 3.12+ | Check with `python --version` |
| **uv** | latest | Fast Python package manager — [install guide](https://github.com/astral-sh/uv) |
| **Gmail account** | — | Required for email alerts (App Password needed) |
| **Google 2FA** | enabled | Required to generate an App Password |

> **Note:** `uv` handles the virtual environment automatically. You do not need to create one manually.

---

## 📦 Installation

```bash
# 1. Navigate into the project directory
cd flight-alert-scraper

# 2. Install all dependencies (creates .venv automatically)
uv sync

# 3. Install the browser automation engine (one-time)
uv run patchright install chromium
```

---

## 🔑 Configuration

### Environment Variables (`.env`)

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Then edit `.env`:

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
```

#### How to generate a Google App Password

1. Go to [myaccount.google.com/security](https://myaccount.google.com/security)
2. Ensure **2-Step Verification** is enabled
3. Search for **"App passwords"** in the search bar
4. Create a new app password (name it anything — e.g., *FlightAlerts*)
5. Copy the 16-character code (with or without spaces) into `SMTP_APP_PASSWORD`

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
      value_deal_discount: "0.20"      # flight is 20%+ under budget → qualifies as Value Deal
                                       # even if it exceeds the time limit
      value_deal_duration_buffer_minutes: 180  # how many minutes over the time limit is still OK
                                               # for a Value Deal (here: up to 22h + 3h = 25h)
      time_saver_price_overage: "0.10" # flight is ≤10% over budget → qualifies as Time Saver
                                       # if it is within the time limit

      # ── Effective-cost weighting ────────────────────────────
      hourly_time_penalty_usd: "20.00" # $20 per extra hour of travel time added to effective cost
                                       # used to rank Tier 2 and pick the best-balance Tier 3 option
```

#### Multiple routes

Add as many entries as you like under `queries:`:

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

## 🚀 Quick Start

```bash
# Step 1 — Initialize the database (only needed once)
uv run flight-alert-scraper init-db

# Step 2 — Preview results without sending an email
uv run flight-alert-scraper check --dry-run

# Step 3 — Run a live check and send alerts if anything changed
uv run flight-alert-scraper check
```

After `--dry-run`, open `artifacts/preview/<timestamp>_email.html` in a browser to inspect the formatted email before going live.

---

## 📟 CLI Reference

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

**Examples:**

```bash
# Live run — emails fire if state changed
uv run flight-alert-scraper check

# Preview mode — no emails sent, HTML written to artifacts/preview/
uv run flight-alert-scraper check --dry-run

# Use a custom watchlist
uv run flight-alert-scraper check --watchlist ~/my-routes.yaml

# Preview with a custom watchlist
uv run flight-alert-scraper check --dry-run --watchlist ./test-watchlist.yaml
```

---

### `init-db`

Creates the SQLite database and applies the current schema. **Safe to run multiple times** — it migrates without destroying data.

```
uv run flight-alert-scraper init-db [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--db PATH` | `./flight_alerts.db` | Path to the SQLite file |

**Examples:**

```bash
# Use the default path from .env
uv run flight-alert-scraper init-db

# Use a custom database path
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
| **Provider** | Which data source succeeded (`google_http`, `google_browser`, `serpapi`) |
| **Status** | `ok`, `error`, or `no_results` |
| **T1 / T2** | Count of Tier 1 and Tier 2 matches found |
| **Suppressed** | Reason the last alert was suppressed (e.g., `within_24h`) |

**Examples:**

```bash
# Show history for all routes
uv run flight-alert-scraper history

# Show the last 50 runs
uv run flight-alert-scraper history --limit 50

# Filter to one route by its key prefix
uv run flight-alert-scraper history a1b2c3d4

# Use a non-default database
uv run flight-alert-scraper history --db /data/flights.db
```

---

### `test-email`

Renders a synthetic email with fake flight data — useful for checking template layout and SMTP credentials without triggering a real scrape.

```
uv run flight-alert-scraper test-email [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--dry-run` / `--send` | `--dry-run` | Write to `artifacts/preview/` vs. actually send |
| `--db PATH` | `./flight_alerts.db` | Path to the SQLite file |

**Examples:**

```bash
# Write preview files (safe default)
uv run flight-alert-scraper test-email

# Actually send to ALERT_RECIPIENT — verifies SMTP credentials work
uv run flight-alert-scraper test-email --send
```

After a dry run, open the generated `.html` file in `artifacts/preview/` to see exactly what recipients will receive.

---

### `rank`

Reads a JSON fixture file containing flight options and a query, runs them through the ranking engine, and prints a formatted tier table. **No network calls, no database writes** — great for debugging tier logic offline.

```
uv run flight-alert-scraper rank --from-fixture FILE
```

| Option | Description |
|---|---|
| `--from-fixture PATH` | *(required)* Path to a JSON fixture file |

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
  "options": [
    {
      "legs": [...],
      "price_usd": "1150.00",
      "total_duration_minutes": 1260,
      ...
    }
  ]
}
```

**Example:**

```bash
uv run flight-alert-scraper rank --from-fixture tests/fixtures/iad_khi.json
```

---

## 🏆 Tier System

Every itinerary is assigned to exactly one tier based on your constraints.

### Tier 1 — Direct Match ✅

*The flight you actually want.* Meets **both** constraints simultaneously:

- Price ≤ `max_price_usd`
- Total duration ≤ `max_duration_minutes` (if set)
- Stops ≤ `max_stops` (if set)

Tier 1 results are sorted by **(price ascending, duration ascending)**.

---

### Tier 2 — Near Miss 🔶

*Worth a look — one constraint is slightly violated, but the tradeoff is explicit.*

Two sub-labels qualify a flight for Tier 2:

| Label | Condition | Description |
|---|---|---|
| **Value Deal** | Price ≤ budget × (1 − `value_deal_discount`) AND duration exceeds limit by ≤ `value_deal_duration_buffer_minutes` | Significantly cheaper than budget, just a bit slower |
| **Time Saver** | Duration ≤ limit AND price ≤ budget × (1 + `time_saver_price_overage`) | Within your time limit for a small price premium |

Tier 2 results are sorted by **effective cost** (price + time penalty for excess duration).

---

### Tier 3 — Baseline 📌

*Nothing meets your constraints — here are the objectively best options available.* Shown only when Tier 1 is empty.

| Label | How it's chosen |
|---|---|
| **Best Balance** | Minimizes effective cost (price + hourly time penalty × hours) |
| **Cheapest** | Lowest price regardless of duration |
| **Fastest** | Shortest duration regardless of price |

Up to three distinct flights are shown (one may hold multiple labels if the same itinerary is both cheapest and fastest).

---

### Effective Cost Formula

```
effective_cost = price_usd + (total_duration_hours × hourly_time_penalty_usd)
```

This blends money and time into a single comparable number. A `$20/hour` penalty means spending an extra hour in transit costs as much as $20 — adjust `hourly_time_penalty_usd` in `watchlist.yaml` to match how you personally value your time.

---

## 📬 Alert Logic

The system tracks state per route and applies three alert rules:

| Condition | Alert type | Frequency |
|---|---|---|
| A **new Tier 1** itinerary appeared | **Immediate** | Sent right away |
| Price dropped **≥ 5%** on a known Tier 1 | **Immediate** | Sent right away |
| No Tier 1 exists, but Tier 2/3 results present | **Digest** | At most once per 24 hours |
| Nothing changed since last run | **Silent** | No email sent |

> **Anti-spam guarantee:** The digest is rate-limited to once every 24 hours per route. If nothing meaningful changes, no email is sent regardless of how often the scraper runs.

---

## 🌐 Data Sources & Fallback Chain

Providers are tried in order. If a provider fails or returns no usable data, the next one is tried automatically.

```
1. google_http      httpx + selectolax (fast, no browser)
        │
        ▼ (on block / empty result)
2. google_browser   patchright headless Chromium (full JS rendering)
        │
        ▼ (only if SERPAPI_KEY is set)
3. serpapi          SerpApi Google Flights endpoint (250 free searches/month)
```

- **`google_http`** is the primary source — fastest and uses no API quota.
- **`google_browser`** kicks in when Google blocks the HTTP request. It uses [patchright](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright) (not playwright-stealth) to avoid fingerprint detection.
- **`serpapi`** is opt-in. Set `SERPAPI_KEY` in `.env` to enable it. Free tier gives 250 searches/month.

---

## ⏰ Automating with Windows Task Scheduler

Run checks automatically in the background every 6 hours — no terminal popups, no manual triggering.

### Step 1 — Register the base task

Open **PowerShell** and run (adjust the path to your project root):

```powershell
schtasks /create /tn "FlightAlertScraper" `
  /tr "cmd /c cd /d C:\Users\arsha\OneDrive\Documents\flight_scraper\flight-alert-scraper && uv run flight-alert-scraper check" `
  /sc hourly /mo 6 /st 06:00 /f
```

> **Note:** The `/d` flag in `cd /d` is required when the project is on a different drive than `cmd`'s current directory. Without it, a drive change silently fails and the task errors every run.

---

### Step 2 — Configure power, wake & background settings *(recommended)*

By default, Windows suppresses scheduled tasks when the machine is on battery or the screen is locked. Run the following in **PowerShell as Administrator** to remove those restrictions:

```powershell
# Allow running on battery; catch up if the machine was asleep at the scheduled time
$task = Get-ScheduledTask -TaskName "FlightAlertScraper"
$task.Settings.DisallowStartIfOnBatteries = $false
$task.Settings.StopIfGoingOnBatteries     = $false
$task.Settings.StartWhenAvailable         = $true
Set-ScheduledTask -InputObject $task

# Run in the background whether logged in, locked, or signed out — no plaintext passwords
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U
Set-ScheduledTask -TaskName "FlightAlertScraper" -Principal $principal
```

| Setting | What it does |
|---|---|
| `DisallowStartIfOnBatteries = $false` | Runs checks even when unplugged from AC power |
| `StopIfGoingOnBatteries = $false` | Won't abort a run mid-way if the charger is unplugged |
| `StartWhenAvailable = $true` | If the machine was asleep at the 6-hour mark, runs immediately on wake instead of skipping the window |
| `LogonType = S4U` | Service-for-User background logon — checks continue when the screen is locked, without storing a plaintext password |

---

### Step 3 — Verify the configuration

```powershell
$t = Get-ScheduledTask -TaskName "FlightAlertScraper"
[PSCustomObject]@{
    TaskName       = $t.TaskName
    State          = $t.State
    StartOnBattery = -not $t.Settings.DisallowStartIfOnBatteries
    StopOnBattery  = $t.Settings.StopIfGoingOnBatteries
    StartWhenAvail = $t.Settings.StartWhenAvailable
    LogonType      = $t.Principal.LogonType
}
```

**Expected output:**

```
TaskName       : FlightAlertScraper
State          : Ready
StartOnBattery : True
StopOnBattery  : False
StartWhenAvail : True
LogonType      : S4U
```

---

### Step 4 — Test the task manually

Trigger the task and confirm it writes to the database:

```powershell
schtasks /run /tn "FlightAlertScraper"
```

Wait 15–30 seconds, then inspect the run log:

```powershell
uv run flight-alert-scraper history
```

---

### Other useful scheduler commands

```powershell
# Check status and last run result
schtasks /query /tn "FlightAlertScraper" /fo LIST /v

# Delete the task
schtasks /delete /tn "FlightAlertScraper" /f

# Change interval (e.g., every 4 hours)
schtasks /change /tn "FlightAlertScraper" /mo 4
```

### Recommended schedule

| Frequency | Trade-off |
|---|---|
| Every 3–4 hours | More timely; slightly higher chance of rate-limiting |
| **Every 6 hours** *(recommended)* | Good balance of freshness vs. reliability |
| Once daily | Lowest footprint; fine for routes more than a week away |

---

## 🧪 Running Tests

```bash
# Run the full test suite
uv run pytest

# Run with coverage report
uv run pytest --cov=flight_alert_scraper

# Run a specific test file
uv run pytest tests/test_ranking.py -v

# Run linting
uv run ruff check .

# Run type checking
uv run mypy src
```

All 52 tests are offline (no network calls, no email sending). Fixtures are used for parser and ranking tests.

---

## 🗂️ Project Layout

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
│   │   ├── tables.py         ← WatchedQuery, ScrapeRun, AlertState ORM models
│   │   ├── repo.py           ← query helpers (get_recent_runs, get_alert_state …)
│   │   └── engine.py         ← get_session, migrate
│   │
│   └── notifications/        ← email rendering and delivery
│       ├── render.py         ← Jinja2 → HTML + text
│       ├── smtp.py           ← SmtpNotifier (Gmail TLS)
│       ├── decide.py         ← AlertDecision logic (immediate / digest / silent)
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

## 🩺 Troubleshooting

### No email received after `check`

1. **Run `history`** to see whether the scrape ran and what it found.
2. **Check `Suppressed` column** — if it says `within_24h`, a digest was already sent recently.
3. **Try `--dry-run`** and inspect `artifacts/preview/` — if the HTML file exists, the scraper worked but SMTP is the issue.
4. **Run `test-email --send`** to isolate SMTP from scraping entirely.

### Gmail SMTP errors

| Error | Cause | Fix |
|---|---|---|
| `SMTPAuthenticationError` | Wrong App Password | Regenerate it at myaccount.google.com |
| `534 Application-specific password required` | Using your real Gmail password | Must use an App Password (requires 2FA) |
| `Connection refused` | Port 587 blocked | Check firewall / VPN |

### Browser scraper launches but finds no flights

- Google Flights sometimes requires a CAPTCHA. The browser scraper retries with a fresh session automatically, but persistent blocks may require rotating the cookie cache (delete `.cache/cookies.json`).

### SerpApi returns stale results

- The free tier caches results for up to 1 hour. This is expected behaviour — consider the paid tier for fresher data.

### `uv: command not found`

Install uv: `pip install uv` or follow the [official guide](https://github.com/astral-sh/uv#installation).

---

## 📄 License

MIT — see [LICENSE](LICENSE).

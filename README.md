# flight-alert-scraper

Monitors flight routes and emails you only when something actually changes.

## How it works

1. Reads routes from `watchlist.yaml`
2. Scrapes Google Flights (HTTP first, browser fallback)
3. Ranks results into three tiers:
   - **Tier 1** — within your price and time budget (direct match)
   - **Tier 2** — near misses with explicit tradeoff notes (value deal or time saver)
   - **Tier 3** — baseline best options when nothing meets your constraints
4. Sends an email only on a real state change:
   - **Immediately** for a new Tier 1 itinerary or a >5% price drop
   - **At most once per 24 hours** (digest) when no Tier 1 match exists
   - **Silent** when nothing changed

## Setup

### 1. Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv)

### 2. Install

```
cd flight-alert-scraper
uv sync
```

### 3. Configure

Copy `.env.example` to `.env` and fill in your credentials:

```
DB_PATH=./flight_alerts.db
SMTP_USER=you@gmail.com
SMTP_APP_PASSWORD=xxxx xxxx xxxx xxxx   # Google App Password (requires 2FA)
ALERT_RECIPIENT=you@example.com
SERPAPI_KEY=                             # optional; 250 free searches/month
```

Edit `watchlist.yaml` to set your routes and constraints.

### 4. Initialize the database

```
uv run flight-alert-scraper init-db
```

### 5. Run a check

```
uv run flight-alert-scraper check
```

Add `--dry-run` to render emails to `artifacts/preview/` without sending.

## Windows Task Scheduler

Register to run every 6 hours (adjust the path):

```
schtasks /create /tn "FlightAlertScraper" /tr "cmd /c cd C:\Users\arsha\OneDrive\Documents\flight_scraper\flight-alert-scraper && uv run flight-alert-scraper check" /sc hourly /mo 6 /st 06:00 /f
```

Run it manually to test the scheduler environment:

```
schtasks /run /tn "FlightAlertScraper"
```

## CLI reference

```
flight-alert-scraper check        # check all watched routes
flight-alert-scraper init-db      # create/migrate the SQLite database
flight-alert-scraper history      # show recent scrape runs
flight-alert-scraper test-email   # render a test email (--dry-run by default)
flight-alert-scraper rank --from-fixture path.json   # rank flights from a fixture
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `DB_PATH` | `./flight_alerts.db` | SQLite database path |
| `SMTP_USER` | — | Gmail address |
| `SMTP_APP_PASSWORD` | — | Google App Password |
| `ALERT_RECIPIENT` | — | Destination email |
| `SERPAPI_KEY` | (empty) | SerpApi key (optional) |
| `WATCHLIST_PATH` | `./watchlist.yaml` | Route watchlist |

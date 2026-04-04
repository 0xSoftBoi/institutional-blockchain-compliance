# Institutional Blockchain Compliance Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)

Real-time AML/KYC compliance monitoring for EVM-compatible blockchains. Screens every transaction in every block against sanctions lists and configurable risk rules, generates FinCEN SAR-format reports, and serves a live web dashboard.

---

## What It Does

- **Risk scoring** — each transaction is scored 0–100 against six rules (large amount, mixer address, sanctioned address, new wallet, round number, rapid succession). Score maps to a tier: `critical`, `high`, `medium`, or `low`.
- **Sanctions screening** — every from/to address is checked against a local OFAC-style list. Plug in a real provider (Chainalysis, TRM) by extending `ComplianceMonitor.screen_address`.
- **SAR generation** — transactions scoring `high` or `critical` auto-generate a FinCEN SAR-format dict ready for review and filing.
- **Reporting** — daily summaries with per-tier breakdowns, exportable as CSV or JSON.
- **Dashboard** — Dash/Plotly web UI with a live transaction feed, risk distribution pie chart, volume-over-time line chart, and KPI cards. Refreshes every 10 seconds.

---

## Install

```bash
git clone https://github.com/0xSoftBoi/institutional-blockchain-compliance.git
cd institutional-blockchain-compliance

python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

pip install -r requirements.txt
```

Minimum required packages (others in requirements.txt are optional extensions):

```
web3
dash
dash-bootstrap-components
plotly
pyyaml
loguru
```

---

## Configuration

Copy the example config and edit as needed:

```bash
cp config/config.example.yaml config/config.yaml
```

Key settings:

```yaml
compliance:
  aml:
    transaction_threshold_usd: 10000   # large-tx rule threshold

risk_scoring:
  thresholds:
    critical: 90
    high: 75
    medium: 50
```

---

## Usage

### 1. Live monitoring

Connect to any EVM-compatible RPC endpoint and screen every transaction in real time:

```bash
python main.py monitor --rpc https://mainnet.infura.io/v3/YOUR_KEY
```

Optional flags:
- `--start-block 19000000` — begin from a specific block instead of the latest
- `--config config/config.yaml` — use a custom config file

Flagged transactions are logged at `WARNING` level with score, tier, and triggered rules. Low-risk transactions are logged at `DEBUG`.

### 2. Web dashboard

```bash
python main.py dashboard
```

Open `http://localhost:8050`. The dashboard shows:

- **KPI cards** (top row) — total transactions, flagged count, critical alerts, SAR-required count
- **Risk distribution pie chart** — proportion of critical / high / medium / low transactions
- **Transaction volume line chart** — USD volume bucketed into 30-minute windows
- **Live transaction feed table** — address, amount, risk score, tier; color-coded by severity (red = critical, orange = high, yellow = medium)

The dashboard auto-refreshes every 10 seconds. When no live RPC is connected it uses generated sample data so the UI is always functional.

Optional flags:
- `--port 9090` — run on a different port
- `--debug` — enable Dash hot-reload

### 3. Daily report

```bash
python main.py report --date 2026-04-01
```

Prints a summary to stdout and writes three files to `reports/`:

| File | Contents |
|------|----------|
| `report_2026-04-01.json` | Per-transaction RiskScore records |
| `report_2026-04-01.csv` | Same data in CSV format |
| `summary_2026-04-01.json` | Aggregate statistics (total, flagged %, by-tier breakdown) |

Optional flags:
- `--output ./my-reports` — write to a different directory

---

## Project Structure

```
institutional-blockchain-compliance/
├── compliance/
│   ├── __init__.py
│   ├── risk_engine.py    # RiskEngine, RiskScore dataclass, scoring rules
│   ├── monitor.py        # ComplianceMonitor — block screening loop
│   ├── reporter.py       # SAR generation, daily summary, CSV/JSON export
│   └── dashboard.py      # Dash web dashboard
├── config/
│   └── config.example.yaml
├── main.py               # CLI entry point
├── requirements.txt
└── README.md
```

---

## Dashboard Screenshot Description

The dark-themed dashboard (`#111827` background) has four sections:

1. **Top row — KPI cards**: Four metric cards with coloured borders showing total transactions (blue), flagged count (yellow), critical alerts (red), and SAR-required count (orange).

2. **Charts row**: Left — a donut pie chart labelled by tier (CRITICAL in red, HIGH in orange, MEDIUM in yellow, LOW in green). Right — a filled area line chart of transaction volume in USD over the past few hours, bucketed into 30-minute intervals.

3. **Transaction feed table**: Dark-background paginated table (15 rows/page). Columns: Timestamp, Address, Amount (USD), Risk Score, Tier. CRITICAL rows render in red bold, HIGH in orange, MEDIUM in yellow, LOW in default white. Sortable by any column.

---

## Extending

- **Real sanctions provider**: override `screen_address` in `ComplianceMonitor` to call Chainalysis KYT, TRM Labs, or the OFAC SDN API.
- **ML scoring**: replace or augment `RiskEngine.score_transaction` with a scikit-learn or XGBoost model — `requirements.txt` already includes both.
- **SAR filing**: wire `generate_sar_report` output to FinCEN's BSA E-Filing API.
- **Database persistence**: add a SQLAlchemy session to `monitor.monitor_block` to persist every `RiskScore` to PostgreSQL (schema and alembic stubs ready via requirements).

---

## License

MIT — see LICENSE for details.

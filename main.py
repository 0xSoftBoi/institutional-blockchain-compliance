"""
Institutional Blockchain Compliance Monitor — CLI entry point.

Usage:
    python main.py monitor --rpc <url>         # start live block monitoring
    python main.py dashboard                   # launch web dashboard (port 8050)
    python main.py report --date 2026-04-01    # generate daily summary report
"""

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("compliance")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(config_path: str = "config/config.example.yaml") -> dict:
    p = Path(config_path)
    if not p.exists():
        logger.warning("Config file not found: %s — using defaults", config_path)
        return {}
    with open(p, "r") as fh:
        return yaml.safe_load(fh) or {}


# ---------------------------------------------------------------------------
# Sub-commands
# ---------------------------------------------------------------------------

def cmd_monitor(args, config: dict):
    """Connect to an EVM RPC and monitor transactions for compliance issues."""
    from compliance.monitor import ComplianceMonitor

    rpc_url = args.rpc or config.get("blockchains", {}).get("ethereum", {}).get("rpc_url", "")
    if not rpc_url:
        logger.error("No RPC URL provided. Use --rpc <url> or set blockchains.ethereum.rpc_url in config.")
        sys.exit(1)

    logger.info("Starting compliance monitor — RPC: %s", rpc_url)
    monitor = ComplianceMonitor(web3_url=rpc_url, config=config)

    start_block = args.start_block if hasattr(args, "start_block") else None
    monitor.run(start_block=start_block)


def cmd_dashboard(args, config: dict):
    """Launch the Dash compliance dashboard on port 8050."""
    from compliance.dashboard import run_dashboard

    port = getattr(args, "port", 8050) or 8050
    debug = getattr(args, "debug", False)
    logger.info("Launching dashboard at http://localhost:%d", port)
    run_dashboard(host="0.0.0.0", port=port, debug=debug)


def cmd_report(args, config: dict):
    """Generate a daily compliance summary report from sample data."""
    from compliance.risk_engine import RiskEngine, RiskScore
    from compliance.reporter import generate_daily_summary, export_json, export_csv

    report_date = getattr(args, "date", None) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out_dir = Path(getattr(args, "output", "reports") or "reports")
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Generating daily report for %s", report_date)

    # Build sample results to demonstrate the reporter
    engine = RiskEngine(config)
    sample_transactions = [
        {"from_address": "0xabc123", "to_address": "0xdef456", "value_usd": 15_000},
        {"from_address": "0x7f367cc41522ce07553e823bf3be79a889debe1b", "to_address": "0x999", "value_usd": 5_000},
        {"from_address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef", "to_address": "0x888", "value_usd": 1_000},
        {"from_address": "0x111", "to_address": "0x222", "value_usd": 10_000, "wallet_age_days": 5},
        {"from_address": "0xaaa", "to_address": "0xbbb", "value_usd": 500},
        {"from_address": "0x722122df12d4e14e13ac3b6895a86e84145b6967", "to_address": "0xccc", "value_usd": 25_000},
        {"from_address": "0x001", "to_address": "0x002", "value_usd": 200, "recent_tx_count": 8},
        {"from_address": "0x003", "to_address": "0x004", "value_usd": 50_000},
    ]

    results: list[RiskScore] = [engine.score_transaction(tx) for tx in sample_transactions]
    summary = generate_daily_summary(results)

    print("\n" + "=" * 60)
    print(f"  Daily Compliance Summary — {report_date}")
    print("=" * 60)
    stats = summary["statistics"]
    print(f"  Total transactions : {stats['total_transactions']}")
    print(f"  Flagged            : {stats['flagged_transactions']} ({stats['flagged_percentage']}%)")
    print(f"  SAR required       : {stats['sar_required']}")
    print()
    print("  Breakdown by tier:")
    for tier, count in summary["breakdown_by_tier"].items():
        print(f"    {tier.upper():10s} {count}")
    print("=" * 60 + "\n")

    json_path = out_dir / f"report_{report_date}.json"
    csv_path = out_dir / f"report_{report_date}.csv"

    export_json(results, str(json_path))
    export_csv(results, str(csv_path))

    summary_path = out_dir / f"summary_{report_date}.json"
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2)

    logger.info("Reports written to %s", out_dir)
    print(f"Output files:\n  {json_path}\n  {csv_path}\n  {summary_path}")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="compliance",
        description="Institutional Blockchain Compliance Monitor",
    )
    parser.add_argument(
        "--config",
        default="config/config.example.yaml",
        help="Path to YAML config file (default: config/config.example.yaml)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # monitor
    p_monitor = sub.add_parser("monitor", help="Start live block monitoring")
    p_monitor.add_argument("--rpc", required=False, help="EVM RPC endpoint URL")
    p_monitor.add_argument("--start-block", type=int, default=None, help="Block to start from (default: latest)")

    # dashboard
    p_dash = sub.add_parser("dashboard", help="Launch compliance dashboard (port 8050)")
    p_dash.add_argument("--port", type=int, default=8050, help="Port to listen on")
    p_dash.add_argument("--debug", action="store_true", help="Enable Dash debug mode")

    # report
    p_report = sub.add_parser("report", help="Generate daily compliance report")
    p_report.add_argument("--date", default=None, help="Report date (YYYY-MM-DD, default: today)")
    p_report.add_argument("--output", default="reports", help="Output directory (default: reports/)")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(args.config)

    dispatch = {
        "monitor": cmd_monitor,
        "dashboard": cmd_dashboard,
        "report": cmd_report,
    }

    dispatch[args.command](args, config)


if __name__ == "__main__":
    main()

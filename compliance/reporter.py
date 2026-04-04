"""
Report generation for compliance results.

Supports:
  - FinCEN SAR (Suspicious Activity Report) format dicts
  - Daily summary statistics
  - CSV and JSON export
"""

import csv
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Union

from .risk_engine import RiskScore

logger = logging.getLogger(__name__)


def generate_sar_report(tx: dict, risk: RiskScore) -> dict:
    """
    Build a FinCEN SAR-style report dict for a flagged transaction.

    The returned structure mirrors the key fields of a FinCEN SAR filing
    (FinCEN Form 111) adapted for cryptocurrency transactions.

    Parameters
    ----------
    tx:
        The raw transaction dict (from_address, to_address, value_usd, etc.)
    risk:
        The RiskScore produced by RiskEngine.score_transaction()

    Returns
    -------
    dict
        SAR report fields.
    """
    now = datetime.now(timezone.utc).isoformat()
    from_addr = tx.get("from_address") or tx.get("from", "UNKNOWN")
    to_addr = tx.get("to_address") or tx.get("to", "UNKNOWN")
    value_usd = float(tx.get("value_usd", tx.get("value", 0)))
    tx_hash = tx.get("tx_hash") or tx.get("hash", "UNKNOWN")

    # Build narrative from risk factors
    if risk.factors:
        factor_list = "; ".join(risk.factors)
        narrative = (
            f"Automated compliance system flagged transaction {tx_hash} "
            f"with risk score {risk.score}/100 (tier: {risk.tier.upper()}). "
            f"Triggered rules: {factor_list}."
        )
    else:
        narrative = f"Transaction {tx_hash} flagged by automated system. Risk score: {risk.score}/100."

    return {
        "sar_version": "1.0",
        "filing_institution": "Global Settlement Compliance Monitor",
        "report_type": "SAR",
        "generated_at": now,
        "filing_status": "draft",          # "draft" | "filed"
        # Part I — Reporting institution
        "institution": {
            "name": "Global Settlement",
            "type": "Virtual Asset Service Provider",
            "jurisdiction": "US",
        },
        # Part II — Subject information
        "subject": {
            "blockchain_address_from": from_addr,
            "blockchain_address_to": to_addr,
            "transaction_hash": tx_hash,
            "blockchain_network": tx.get("network", "ethereum"),
        },
        # Part III — Suspicious activity information
        "activity": {
            "date": tx.get("timestamp", now)[:10],
            "amount_usd": round(value_usd, 2),
            "currency": tx.get("currency", "ETH"),
            "activity_types": _derive_activity_types(risk),
            "risk_score": risk.score,
            "risk_tier": risk.tier,
            "risk_factors": risk.factors,
            "narrative": narrative,
        },
        # Part IV — Filing information
        "filing": {
            "requires_sar": risk.requires_sar,
            "auto_filed": False,
            "review_required": risk.tier in ("critical", "high"),
            "reviewer": None,
            "review_deadline": None,
        },
    }


def generate_daily_summary(results: list[Union[RiskScore, dict]]) -> dict:
    """
    Aggregate a list of RiskScore objects (or their .to_dict() equivalents)
    into a daily summary suitable for regulatory reporting.

    Parameters
    ----------
    results:
        List of RiskScore instances or dicts with the same keys.

    Returns
    -------
    dict
        Summary with counts broken down by tier and SAR requirements.
    """
    total = len(results)
    by_tier: dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    flagged = 0
    sar_required = 0

    for item in results:
        if isinstance(item, RiskScore):
            tier = item.tier
            req_sar = item.requires_sar
        else:
            tier = item.get("tier", "low")
            req_sar = item.get("requires_sar", False)

        by_tier[tier] = by_tier.get(tier, 0) + 1
        if tier != "low":
            flagged += 1
        if req_sar:
            sar_required += 1

    flagged_pct = round((flagged / total * 100), 2) if total else 0.0

    return {
        "report_type": "daily_summary",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "period": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "statistics": {
            "total_transactions": total,
            "flagged_transactions": flagged,
            "flagged_percentage": flagged_pct,
            "sar_required": sar_required,
        },
        "breakdown_by_tier": by_tier,
    }


def export_csv(results: list[Union[RiskScore, dict]], filepath: str) -> None:
    """
    Write results to a CSV file.

    Parameters
    ----------
    results:
        List of RiskScore instances or their dict representations.
    filepath:
        Destination file path (will be created/overwritten).
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    rows = [r.to_dict() if isinstance(r, RiskScore) else r for r in results]
    if not rows:
        logger.warning("export_csv: no results to export")
        return

    # Flatten 'factors' list to a semicolon-separated string for CSV compatibility
    for row in rows:
        if isinstance(row.get("factors"), list):
            row["factors"] = "; ".join(row["factors"])

    fieldnames = list(rows[0].keys())

    with open(filepath, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logger.info("Exported %d rows to %s", len(rows), filepath)


def export_json(results: list[Union[RiskScore, dict]], filepath: str) -> None:
    """
    Write results to a JSON file.

    Parameters
    ----------
    results:
        List of RiskScore instances or their dict representations.
    filepath:
        Destination file path (will be created/overwritten).
    """
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)

    rows = [r.to_dict() if isinstance(r, RiskScore) else r for r in results]

    with open(filepath, "w", encoding="utf-8") as fh:
        json.dump(rows, fh, indent=2, default=str)

    logger.info("Exported %d records to %s", len(rows), filepath)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _derive_activity_types(risk: RiskScore) -> list[str]:
    """Map risk factors to FinCEN activity type codes."""
    types: list[str] = []
    factors_lower = " ".join(risk.factors).lower()

    if "sanction" in factors_lower:
        types.append("Transactions involving OFAC-listed entities")
    if "mixer" in factors_lower or "mixing" in factors_lower:
        types.append("Use of cryptocurrency mixing services")
    if "large" in factors_lower:
        types.append("Large cash transaction (crypto equivalent)")
    if "round" in factors_lower:
        types.append("Structuring (round number amounts)")
    if "rapid" in factors_lower or "succession" in factors_lower:
        types.append("Rapid movement of funds")
    if "new wallet" in factors_lower:
        types.append("New/anonymous wallet activity")

    return types or ["Other suspicious activity"]

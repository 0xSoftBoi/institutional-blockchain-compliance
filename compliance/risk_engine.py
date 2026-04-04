"""
Risk scoring engine for blockchain transaction compliance monitoring.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# Sample known mixer addresses (Tornado Cash and others - for demo)
KNOWN_MIXER_ADDRESSES = {
    "0x722122df12d4e14e13ac3b6895a86e84145b6967",  # Tornado Cash Router
    "0xd90e2f925da726b50c4ed8d0fb90ad053324f31b",  # Tornado Cash 0.1 ETH
    "0x910cbd523d972eb0a6f4cae4618ad62622b39dbf",  # Tornado Cash 1 ETH
    "0xa160cdab225685da1d56aa342ad8841c3b53f291",  # Tornado Cash 10 ETH
    "0x94a1b5cdb22c43faab4abeb5c74999895464ddaf",  # Tornado Cash 100 ETH
    "0xb541fc07bc7619fd4062a54d96268525cbc6ffef",  # Tornado Cash 1000 ETH
    "0x12d66f87a04a9e220c9d6efb3d8d6059408d1b17",  # Tornado Cash DAI 100k
    "0x47ce0c6ed5b0ce3d3a51fdb1c52dc66a7c3c2936",  # Tornado Cash DAI 1M
}

# Sample OFAC-style sanctioned addresses (fictional for demo)
SANCTIONED_ADDRESSES = {
    "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
    "0x1111111111111111111111111111111111111111",
    "0x2222222222222222222222222222222222222222",
    "0x7f367cc41522ce07553e823bf3be79a889debe1b",  # OFAC SDN example
    "0xd882cfc20f52f2599d84b8e8d58c7fb62cfe344b",
    "0x901bb9583b24d97e995513c6778dc6888ab6870e",
}


@dataclass
class RiskScore:
    score: int                    # 0–100
    tier: str                     # critical / high / medium / low
    factors: list[str]            # human-readable list of triggered rules
    requires_sar: bool            # whether a SAR filing is recommended
    address: Optional[str] = None
    tx_hash: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "tier": self.tier,
            "factors": self.factors,
            "requires_sar": self.requires_sar,
            "address": self.address,
            "tx_hash": self.tx_hash,
            "timestamp": self.timestamp,
        }


class RiskEngine:
    """
    Rule-based risk scoring engine for blockchain transactions.

    Scores are additive and capped at 100. The tier thresholds follow the
    config values (critical≥90, high≥75, medium≥50, low<50).
    """

    TIER_CRITICAL = 90
    TIER_HIGH = 75
    TIER_MEDIUM = 50

    # Rule weights
    WEIGHT_LARGE_TX = 20          # transaction > $10k
    WEIGHT_MIXER = 50             # known mixer address involved
    WEIGHT_SANCTIONED = 90        # sanctioned address (overrides most other factors)
    WEIGHT_NEW_WALLET = 15        # wallet < 30 days old
    WEIGHT_ROUND_AMOUNT = 10      # suspiciously round number
    WEIGHT_RAPID_SUCCESSION = 25  # rapid succession transactions

    def __init__(self, config: dict):
        self.config = config
        compliance_cfg = config.get("compliance", {})
        aml_cfg = compliance_cfg.get("aml", {})
        self.large_tx_threshold = aml_cfg.get("transaction_threshold_usd", 10_000)

        risk_cfg = config.get("risk_scoring", {})
        thresholds = risk_cfg.get("thresholds", {})
        self.threshold_critical = thresholds.get("critical", self.TIER_CRITICAL)
        self.threshold_high = thresholds.get("high", self.TIER_HIGH)
        self.threshold_medium = thresholds.get("medium", self.TIER_MEDIUM)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_transaction(self, tx: dict) -> RiskScore:
        """
        Score a single transaction and return a RiskScore dataclass.

        Expected tx keys (all optional with sensible defaults):
          from_address, to_address, value_usd, tx_hash,
          wallet_age_days, recent_tx_count
        """
        score = 0
        factors: list[str] = []

        from_addr = (tx.get("from_address") or tx.get("from") or "").lower()
        to_addr = (tx.get("to_address") or tx.get("to") or "").lower()
        value_usd = float(tx.get("value_usd", tx.get("value", 0)))
        tx_hash = tx.get("tx_hash") or tx.get("hash")
        wallet_age_days = tx.get("wallet_age_days")
        recent_tx_count = tx.get("recent_tx_count", 0)

        # Rule 1 — large transaction
        if value_usd > self.large_tx_threshold:
            score += self.WEIGHT_LARGE_TX
            factors.append(f"Large transaction (${value_usd:,.2f} > ${self.large_tx_threshold:,.0f} threshold)")

        # Rule 2 — known mixer address
        if from_addr in KNOWN_MIXER_ADDRESSES or to_addr in KNOWN_MIXER_ADDRESSES:
            score += self.WEIGHT_MIXER
            factors.append("Interaction with known mixing service")

        # Rule 3 — sanctioned address (high weight, but still additive)
        if from_addr in SANCTIONED_ADDRESSES or to_addr in SANCTIONED_ADDRESSES:
            score += self.WEIGHT_SANCTIONED
            factors.append("Sanctioned address detected (OFAC SDN match)")

        # Rule 4 — new wallet (< 30 days)
        if wallet_age_days is not None and wallet_age_days < 30:
            score += self.WEIGHT_NEW_WALLET
            factors.append(f"New wallet ({wallet_age_days} days old, threshold: 30 days)")

        # Rule 5 — suspiciously round number
        if self._is_round_number(value_usd):
            score += self.WEIGHT_ROUND_AMOUNT
            factors.append(f"Round number amount (${value_usd:,.2f})")

        # Rule 6 — rapid succession transactions
        if recent_tx_count and recent_tx_count >= 5:
            score += self.WEIGHT_RAPID_SUCCESSION
            factors.append(f"Rapid succession transactions ({recent_tx_count} txns detected)")

        score = min(score, 100)
        tier = self.get_tier(score)
        requires_sar = tier in ("critical", "high")

        logger.debug("Scored tx %s: score=%d tier=%s factors=%s", tx_hash, score, tier, factors)

        return RiskScore(
            score=score,
            tier=tier,
            factors=factors,
            requires_sar=requires_sar,
            address=from_addr or to_addr or None,
            tx_hash=tx_hash,
        )

    def get_tier(self, score: int) -> str:
        """Map a numeric score to a string tier."""
        if score >= self.threshold_critical:
            return "critical"
        if score >= self.threshold_high:
            return "high"
        if score >= self.threshold_medium:
            return "medium"
        return "low"

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_round_number(value: float) -> bool:
        """
        Detect structuring-style round numbers: multiples of 1000, 5000, or 10000,
        or values that end in three or more trailing zeros.
        """
        if value <= 0:
            return False
        int_val = int(value)
        if int_val != value:
            return False
        return int_val % 1000 == 0

"""
Main compliance monitoring loop.

Connects to an EVM-compatible chain via Web3, screens each transaction in
every new block, and emits structured log lines for every flagged result.
Falls back gracefully when no RPC is reachable (mock mode).
"""

import ipaddress
import logging
import time
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlparse

from .risk_engine import RiskEngine, RiskScore, SANCTIONED_ADDRESSES

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# RPC URL validation
# ---------------------------------------------------------------------------

ALLOWED_RPC_SCHEMES = {"https", "wss", "http", "ws"}
BLOCKED_HOSTS = {"169.254.169.254", "metadata.google.internal"}  # cloud SSRF targets


def validate_rpc_url(url: str) -> str:
    """Validate an RPC URL, blocking private/loopback/SSRF-prone targets."""
    parsed = urlparse(url)
    if parsed.scheme not in ALLOWED_RPC_SCHEMES:
        raise ValueError(f"Invalid RPC scheme: {parsed.scheme}")
    host = parsed.hostname or ""
    if host in BLOCKED_HOSTS:
        raise ValueError(f"Blocked RPC host: {host}")
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local:
            raise ValueError(f"Private/loopback RPC not allowed: {host}")
    except ValueError as exc:
        if any(kw in str(exc) for kw in ("Blocked", "Private", "loopback", "scheme")):
            raise
        # hostname (not a bare IP) — allow
    return url


# ---------------------------------------------------------------------------
# Expanded local sanctions list (OFAC-style demo addresses)
# ---------------------------------------------------------------------------
LOCAL_SANCTIONS_LIST: set[str] = SANCTIONED_ADDRESSES | {
    "0x3333333333333333333333333333333333333333",
    "0x4444444444444444444444444444444444444444",
    "0x8576acc5c05d6ce88f4e49bf65bdf0c62f91353c",
    "0xee9a19b3dab2eba8b3ec98c5de56e36c2e3a2be4",
}


class ComplianceMonitor:
    """
    Monitors an EVM blockchain for suspicious transactions.

    Parameters
    ----------
    web3_url:
        HTTP(S) or WS RPC endpoint.  Pass an empty string or ``None`` to
        operate in mock / offline mode.
    config:
        Parsed YAML config dict (see config/config.example.yaml).
    """

    POLL_INTERVAL = 12  # seconds between block polls (roughly 1 Ethereum slot)

    def __init__(self, web3_url: Optional[str], config: dict):
        self.web3_url = web3_url
        self.config = config
        self.risk_engine = RiskEngine(config)
        self._w3 = None

        if web3_url:
            validate_rpc_url(web3_url)
            self._connect(web3_url)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self, url: str) -> bool:
        try:
            from web3 import Web3

            self._w3 = Web3(Web3.HTTPProvider(url))
            if self._w3.is_connected():
                logger.info("Connected to node: %s (chain_id=%s)", url, self._w3.eth.chain_id)
                return True
            else:
                logger.warning("RPC endpoint not reachable: %s — running in mock mode", url)
                self._w3 = None
                return False
        except Exception as exc:
            logger.warning("Web3 connection failed (%s) — running in mock mode", exc)
            self._w3 = None
            return False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def screen_address(self, address: str) -> dict:
        """
        Check ``address`` against the local sanctions list.

        Returns a dict with keys:
          is_sanctioned (bool), address (str), match_type (str), checked_at (str)
        """
        normalized = address.lower().strip()
        is_sanctioned = normalized in LOCAL_SANCTIONS_LIST
        return {
            "is_sanctioned": is_sanctioned,
            "address": address,
            "match_type": "local_ofac_sdn" if is_sanctioned else "clear",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    def monitor_block(self, block_number: int) -> list[RiskScore]:
        """
        Screen every transaction in ``block_number``.

        Returns a list of RiskScore objects for all transactions (including
        low-risk ones so callers can build complete summaries).
        """
        if self._w3 is None:
            logger.debug("Mock mode: skipping block %d", block_number)
            return []

        try:
            block = self._w3.eth.get_block(block_number, full_transactions=True)
        except Exception as exc:
            logger.error("Failed to fetch block %d: %s", block_number, exc)
            return []

        results: list[RiskScore] = []
        transactions = block.get("transactions", [])
        logger.info("Block %d — %d transactions", block_number, len(transactions))

        for raw_tx in transactions:
            tx = self._normalise_tx(raw_tx)
            risk = self.risk_engine.score_transaction(tx)

            if risk.tier != "low":
                logger.warning(
                    "FLAGGED tx=%s from=%s to=%s score=%d tier=%s factors=%s",
                    tx.get("tx_hash", "unknown"),
                    tx.get("from_address", "?"),
                    tx.get("to_address", "?"),
                    risk.score,
                    risk.tier,
                    risk.factors,
                )

            results.append(risk)

        return results

    def run(self, start_block: Optional[int] = None):
        """
        Continuous monitoring loop.

        Starts from ``start_block`` (or the latest block if None) and polls
        for new blocks every ``POLL_INTERVAL`` seconds.  Runs until interrupted.
        """
        if self._w3 is None:
            logger.warning(
                "No live RPC connection — monitoring loop exiting. "
                "Use mock data or supply a valid --rpc URL."
            )
            return

        current_block = start_block or self._w3.eth.block_number
        logger.info("Starting compliance monitor at block %d", current_block)

        while True:
            try:
                latest = self._w3.eth.block_number
                while current_block <= latest:
                    self.monitor_block(current_block)
                    current_block += 1
                time.sleep(self.POLL_INTERVAL)
            except KeyboardInterrupt:
                logger.info("Monitor stopped by user.")
                break
            except Exception as exc:
                logger.error("Unexpected error in monitor loop: %s", exc)
                time.sleep(self.POLL_INTERVAL)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise_tx(raw_tx) -> dict:
        """Convert a Web3 transaction AttributeDict to a plain dict."""
        value_wei = int(raw_tx.get("value", 0))
        # Approximate ETH price at $3000 for demo purposes
        value_usd = (value_wei / 1e18) * 3000.0

        return {
            "tx_hash": raw_tx.get("hash", b"").hex() if isinstance(raw_tx.get("hash"), bytes) else str(raw_tx.get("hash", "")),
            "from_address": (raw_tx.get("from") or "").lower(),
            "to_address": (raw_tx.get("to") or "").lower(),
            "value_usd": value_usd,
            "block_number": raw_tx.get("blockNumber"),
        }

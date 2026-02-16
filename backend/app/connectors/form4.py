from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Form4Transaction:
    issuer_cik: Optional[str]
    issuer_trading_symbol: Optional[str]
    reporting_owner_cik: Optional[str]
    reporting_owner_name: Optional[str]
    transaction_date: Optional[date]
    transaction_code: Optional[str]
    acquired_disposed: Optional[str]
    shares: Optional[float]
    price_per_share: Optional[float]
    shares_owned_following: Optional[float]
    is_derivative: bool
    is_10b5_1: Optional[bool] = None


def _find_text(node: ET.Element, path: str) -> Optional[str]:
    child = node.find(path)
    if child is None or child.text is None:
        return None
    txt = child.text.strip()
    return txt or None


def _parse_float(value: Optional[str]) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _parse_date(value: Optional[str]) -> Optional[date]:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_bool(value: Optional[str]) -> Optional[bool]:
    if value is None:
        return None
    v = value.strip().lower()
    if v in {"1", "true", "t", "yes", "y"}:
        return True
    if v in {"0", "false", "f", "no", "n"}:
        return False
    return None


def parse_form4_xml(xml_text: str) -> list[Form4Transaction]:
    """
    Parse SEC Form 4 XML into transaction rows (non-derivative + derivative).

    This parser intentionally keeps only a minimal subset of fields needed for v0
    signals + dashboard timelines.
    """

    root = ET.fromstring(xml_text)

    issuer_cik = _find_text(root, "./issuer/issuerCik")
    issuer_symbol = _find_text(root, "./issuer/issuerTradingSymbol")

    owner_cik = _find_text(root, "./reportingOwner/reportingOwnerId/rptOwnerCik")
    owner_name = _find_text(root, "./reportingOwner/reportingOwnerId/rptOwnerName")

    # As of 2023+, many Form 4 XMLs include a 10b5-1 checkbox field.
    # In the wild, this appears as <aff10b5One>0|1|false|true</aff10b5One>.
    is_10b5_1 = _parse_bool(_find_text(root, "./aff10b5One"))

    transactions: list[Form4Transaction] = []

    def parse_tx(tx_node: ET.Element, is_derivative: bool) -> Form4Transaction:
        tx_date = _parse_date(_find_text(tx_node, "./transactionDate/value"))
        code = _find_text(tx_node, "./transactionCoding/transactionCode")
        acq_disp = _find_text(tx_node, "./transactionAmounts/transactionAcquiredDisposedCode/value")
        shares = _parse_float(_find_text(tx_node, "./transactionAmounts/transactionShares/value"))
        price = _parse_float(_find_text(tx_node, "./transactionAmounts/transactionPricePerShare/value"))
        owned_following = _parse_float(_find_text(tx_node, "./postTransactionAmounts/sharesOwnedFollowingTransaction/value"))

        return Form4Transaction(
            issuer_cik=issuer_cik,
            issuer_trading_symbol=issuer_symbol,
            reporting_owner_cik=owner_cik,
            reporting_owner_name=owner_name,
            transaction_date=tx_date,
            transaction_code=code,
            acquired_disposed=acq_disp,
            shares=shares,
            price_per_share=price,
            shares_owned_following=owned_following,
            is_derivative=is_derivative,
            is_10b5_1=is_10b5_1,
        )

    for tx in root.findall("./nonDerivativeTable/nonDerivativeTransaction"):
        transactions.append(parse_tx(tx, is_derivative=False))
    for tx in root.findall("./derivativeTable/derivativeTransaction"):
        transactions.append(parse_tx(tx, is_derivative=True))

    return transactions

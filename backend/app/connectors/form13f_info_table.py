from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from xml.etree import ElementTree as ET


@dataclass(frozen=True)
class Form13FHolding:
    name_of_issuer: Optional[str]
    title_of_class: Optional[str]
    cusip: Optional[str]
    value_usd: Optional[int]
    shares: Optional[float]
    shares_type: Optional[str]
    put_call: Optional[str]
    investment_discretion: Optional[str]
    voting_sole: Optional[int]
    voting_shared: Optional[int]
    voting_none: Optional[int]


def _local_name(tag: str) -> str:
    # {namespace}name -> name
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _find_child_by_local(node: ET.Element, local: str) -> Optional[ET.Element]:
    local_l = local.lower()
    for ch in list(node):
        if _local_name(ch.tag).lower() == local_l:
            return ch
    return None


def _find_text_local_path(node: ET.Element, locals_path: list[str]) -> Optional[str]:
    cur: Optional[ET.Element] = node
    for part in locals_path:
        if cur is None:
            return None
        cur = _find_child_by_local(cur, part)
    if cur is None or cur.text is None:
        return None
    t = cur.text.strip()
    return t or None


def _parse_int(s: Optional[str]) -> Optional[int]:
    if s is None:
        return None
    try:
        return int(float(s))
    except Exception:
        return None


def _parse_float(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except Exception:
        return None


def parse_information_table_xml(xml_text: str) -> list[Form13FHolding]:
    """
    Parse 13F information table XML into holdings.
    """

    root = ET.fromstring(xml_text)

    # Some documents include namespaces; ignore by checking local-name suffixes.
    def iter_info_tables() -> list[ET.Element]:
        out: list[ET.Element] = []
        for el in root.iter():
            if _local_name(el.tag).lower() == "infotable":
                out.append(el)
        return out

    holdings: list[Form13FHolding] = []
    for it in iter_info_tables():
        holdings.append(
            Form13FHolding(
                name_of_issuer=_find_text_local_path(it, ["nameOfIssuer"]),
                title_of_class=_find_text_local_path(it, ["titleOfClass"]),
                cusip=_find_text_local_path(it, ["cusip"]),
                value_usd=_parse_int(_find_text_local_path(it, ["value"])),
                shares=_parse_float(_find_text_local_path(it, ["shrsOrPrnAmt", "sshPrnamt"])),
                shares_type=_find_text_local_path(it, ["shrsOrPrnAmt", "sshPrnamtType"]),
                put_call=_find_text_local_path(it, ["putCall"]),
                investment_discretion=_find_text_local_path(it, ["investmentDiscretion"]),
                voting_sole=_parse_int(_find_text_local_path(it, ["votingAuthority", "Sole"])),
                voting_shared=_parse_int(_find_text_local_path(it, ["votingAuthority", "Shared"])),
                voting_none=_parse_int(_find_text_local_path(it, ["votingAuthority", "None"])),
            )
        )
    return holdings

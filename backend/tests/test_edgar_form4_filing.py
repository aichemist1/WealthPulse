from app.connectors.edgar_form4_filing import extract_acceptance_datetime, extract_ownership_xml


def test_extract_acceptance_datetime():
    text = "SOME HEADER\nACCEPTANCE-DATETIME: 20260210123456\nOTHER"
    dt = extract_acceptance_datetime(text)
    assert dt is not None
    assert dt.year == 2026 and dt.month == 2 and dt.day == 10
    assert dt.hour == 12 and dt.minute == 34 and dt.second == 56


def test_extract_ownership_xml_prefers_ownership_document():
    filing = """
    <SEC-DOCUMENT>something</SEC-DOCUMENT>
    <XML><notOwnership /></XML>
    <XML>
      <ownershipDocument>
        <issuer><issuerTradingSymbol>ABCD</issuerTradingSymbol></issuer>
      </ownershipDocument>
    </XML>
    """
    xml = extract_ownership_xml(filing)
    assert xml is not None
    assert "<ownershipDocument" in xml


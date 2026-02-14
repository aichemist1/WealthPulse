from app.connectors.form4 import parse_form4_xml


def test_parse_form4_xml_minimal_non_derivative():
    xml = """<?xml version="1.0"?>
    <ownershipDocument>
      <issuer>
        <issuerCik>0000123456</issuerCik>
        <issuerTradingSymbol>ABCD</issuerTradingSymbol>
      </issuer>
      <reportingOwner>
        <reportingOwnerId>
          <rptOwnerCik>0000789012</rptOwnerCik>
          <rptOwnerName>Jane Doe</rptOwnerName>
        </reportingOwnerId>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <transactionDate><value>2026-02-10</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>12.34</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
          <postTransactionAmounts>
            <sharesOwnedFollowingTransaction><value>1000</value></sharesOwnedFollowingTransaction>
          </postTransactionAmounts>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """
    txs = parse_form4_xml(xml)
    assert len(txs) == 1
    tx = txs[0]
    assert tx.issuer_trading_symbol == "ABCD"
    assert tx.reporting_owner_name == "Jane Doe"
    assert tx.transaction_code == "P"
    assert tx.acquired_disposed == "A"
    assert tx.shares == 1000.0
    assert tx.price_per_share == 12.34
    assert tx.is_derivative is False


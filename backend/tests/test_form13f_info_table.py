from app.connectors.form13f_info_table import parse_information_table_xml


def test_parse_information_table_xml_minimal():
    xml = """<?xml version="1.0" encoding="UTF-8"?>
    <informationTable>
      <infoTable>
        <nameOfIssuer>APPLE INC</nameOfIssuer>
        <titleOfClass>COM</titleOfClass>
        <cusip>037833100</cusip>
        <value>123456</value>
        <shrsOrPrnAmt>
          <sshPrnamt>1000</sshPrnamt>
          <sshPrnamtType>SH</sshPrnamtType>
        </shrsOrPrnAmt>
        <investmentDiscretion>SOLE</investmentDiscretion>
        <votingAuthority>
          <Sole>1000</Sole>
          <Shared>0</Shared>
          <None>0</None>
        </votingAuthority>
      </infoTable>
    </informationTable>
    """
    rows = parse_information_table_xml(xml)
    assert len(rows) == 1
    r = rows[0]
    assert r.cusip == "037833100"
    assert r.value_usd == 123456
    assert r.shares == 1000.0
    assert r.shares_type == "SH"

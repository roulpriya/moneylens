"""Emit the synthetic acceptance report JSON for end-to-end UI calculations."""
import json
from test_investment_cashflow import InvestmentCashflowTests, savings_source

case=InvestmentCashflowTests();case.setUp()
try:
    case.case.batch(savings_source())
    print(json.dumps(case.case.data()))
finally: case.tearDown()

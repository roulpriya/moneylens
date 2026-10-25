"""Generate a complete import-to-HTML fixture for UI reachability tests."""
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/automation'))
from test_completeness import CompletenessTests
from coverage_fixtures import source_evidence
from test_ledger import fixture

case=CompletenessTests();case.setUp()
try:
    case.test_non_upi_repayments_credits_and_transfer_legs_survive()
    p=fixture('review-document');p['transactions'][0].update(merchant='Unreadable review merchant',kind='unknown')
    p=source_evidence(p)
    first=p['transactions'].pop(0)
    p['review_rows']=[{'source_row_id':first['source_row_id'],'page':first['page'],'row':first['row'],'reason':'Unreadable amount'}]
    case.batch(p)
    data=case.data()
    # Intentionally restrictive report bounds prove that All transactions can
    # recover every retained occurrence, including undated/unknown-amount rows.
    data['from']='2030-01-01';data['to']='2030-01-31'
    print(json.dumps(data))
finally:case.tearDown()

"""Apply explicit transaction corrections and cached categories without guessing."""
import copy
import json
from .ledger import category_name, hash_value, require, row_key, text
from .merchants import merchant_key, lookup


def evidence_key(row):
    return hash_value([row_key(row),row['page'],row['row']])


def decorate(db, records):
    result=copy.deepcopy(records)
    annotations={(sid,key):(category,note) for sid,key,category,note in db.execute('SELECT record_id,evidence_key,category,note FROM transaction_annotations')}
    indexed={}
    extras={ident:json.loads(raw) for ident,raw in db.execute('SELECT id,payload FROM transaction_metadata')}
    for record in result:
        for index,row in enumerate(record['payload']['transactions']):
            key=(record['id'],evidence_key(row))
            row['original_category']=row['category'];row['category_origin']='provided'
            row['display_merchant']=row['merchant']
            supplied={**row.get('metadata',{}),**extras.get(f"{record['id']}:{index}",extras.get(record['id'],{}))}
            name=supplied.get('merchant',row['merchant'])
            row['normalized_merchant']=merchant_key(name)
            cached=lookup(db,name)
            if row['category']=='Other' and cached is not None:
                row.update(category=cached,category_origin='merchant_cache')
            category,note=annotations.get(key,(None,None))
            if category is not None:row.update(category=category,category_origin='user')
            if note is not None:row['note']=note
            indexed[(record['id'],index)]=row
    for record in result:
        target=indexed.get(tuple(record.get('matched_to') or ()))
        if target is None:continue
        row=record['payload']['transactions'][0]
        if target['category_origin']!='user' and (row['category_origin']=='user' or (target['category']=='Other' and row['category']!='Other')):
            target.update(category=row['category'],category_origin=row['category_origin'])
        if row.get('note') and not target.get('note'):target['note']=row['note']
    for record in result:
        for row in record['payload']['transactions']:row['category']=category_name(row['category'])
    from .transfers import decorate as exclude_transfers
    return exclude_transfers(db,result)


def annotate(db, record_id, index, category=None, note=None):
    require(category is not None or note is not None, 'Supply a category or note')
    found = None
    for table in ('statements', 'alerts'):
        found = db.execute(f'SELECT payload FROM {table} WHERE id=?', (record_id,)).fetchone()
        if found: break
    require(found is not None, 'Transaction record not found')
    rows = json.loads(found[0])['transactions']
    require(0 <= index < len(rows), 'Row index out of bounds')
    if category is not None:
        category = text(category, 'category', 80)
    if note is not None:
        require(isinstance(note, str) and len(note) <= 2000, 'Notes must be text of at most 2000 characters')
        note = note.strip()
    key = evidence_key(rows[index])
    old = db.execute('SELECT category,note FROM transaction_annotations WHERE record_id=? AND evidence_key=?', (record_id, key)).fetchone() or (None, None)
    db.execute('INSERT OR REPLACE INTO transaction_annotations VALUES (?,?,?,?)', (record_id, key, category if category is not None else old[0], note if note is not None else old[1]))

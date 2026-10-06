#!/usr/bin/env python3
"""Fetch the official QLFS PDF using the existing Stats SA GitHub transport."""
import io, json, re, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from pypdf import PdfReader

OUT=Path('data/south-africa-jobs.json')
HEADERS={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36','Accept':'application/pdf,*/*;q=0.8'}

def quarters(now):
    year,q=now.year,(now.month-1)//3
    if q==0: year,q=year-1,4
    for _ in range(3):
        yield year,q
        q-=1
        if q==0:year,q=year-1,4

def extract_text_observation(text, year, q):
    text=re.sub(r'\s+',' ',text)
    if not re.search(r'Quarterly Labour Force Survey',text,re.I):
        raise ValueError('QLFS survey title missing')
    if not re.search(rf'Quarter\s*{q}\s*[:,-]?\s*{year}|{q}(?:st|nd|rd|th)\s*Quarter\s*{year}',text,re.I):
        raise ValueError('QLFS reference quarter mismatch')
    pattern=r'official unemployment rate(?:\s*\(LU1\))?\s+(?:was|stood at|increased (?:by [\d.,]+ (?:of a )?percentage points? )?to|decreased (?:by [\d.,]+ (?:of a )?percentage points? )?to)\s*([\d]+(?:[.,]\d+)?)\s*(?:%|per cent|percent)'
    word=['','first','second','third','fourth'][q]
    for match in re.finditer(pattern,text,re.I):
        tail=text[match.end():match.end()+120]
        if not re.match(rf'\s*(?:in|for)\s*(?:(?:quarter|Q)\s*{q}\s*[:, -]?\s*{year}|the\s+{word}\s+quarter\s+of\s+{year})',tail,re.I):continue
        value=float(match[1].replace(',','.'))
        if not 0<=value<=80:raise ValueError('Unemployment outside range')
        return value,match[0]+tail[:80]
    raise ValueError('National official unemployment headline not bound to requested quarter')

def main():
    errors=[]
    for year,q in quarters(datetime.now(timezone.utc)):
        ordinal=['','1st','2nd','3rd','4th'][q]
        url=f'https://www.statssa.gov.za/publications/P0211/P0211{ordinal}Quarter{year}.pdf'
        try:
            response=requests.get(url,headers=HEADERS,timeout=45)
            response.raise_for_status()
            if not response.content.startswith(b'%PDF'):raise ValueError('Response is not a PDF')
            reader=PdfReader(io.BytesIO(response.content))
            text='\n'.join(page.extract_text() or '' for page in reader.pages[:16])
            value,evidence=extract_text_observation(text,year,q)
        except Exception as exc:
            errors.append(f'{year}-Q{q}: {type(exc).__name__}: {exc}')
            continue
        doc={'schema':'capitalrisk.south-africa-jobs.bridge.v1','country':'South Africa','metric':'unemployment','value':value,'period':f'{year}-Q{q}','institution':'Statistics South Africa','status':'OFFICIAL ACTUAL','definition':'Quarterly Labour Force Survey, national official unemployment rate','sourceUrl':url,'evidence':evidence,'transport':'GitHub Actions bridge','verifiedAt':datetime.now(timezone.utc).isoformat().replace('+00:00','Z')}
        old=json.loads(OUT.read_text()) if OUT.exists() else None
        if old and old['period']>doc['period']:raise ValueError('Refusing an older reference period')
        if old and all(old.get(k)==doc[k] for k in ('period','value','sourceUrl','definition')):
            print('QLFS cache already contains latest verified observation.');return 0
        OUT.parent.mkdir(parents=True,exist_ok=True)
        OUT.write_text(json.dumps(doc,indent=2)+'\n')
        print(f'Verified official national unemployment: {value}% / {doc["period"]}');return 0
    print('No verified QLFS observation found: '+'; '.join(errors),file=sys.stderr)
    return 1

if __name__=='__main__':raise SystemExit(main())

#!/usr/bin/env python3
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests
from pypdf import PdfReader

OUT = Path('data/south-africa-cpi.json')
MONTHS = [
    'January','February','March','April','May','June',
    'July','August','September','October','November','December'
]
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/131 Safari/537.36',
    'Accept': 'application/pdf,*/*;q=0.8',
}


def month_candidates(now, count=5):
    y, m = now.year, now.month
    # CPI for the current month is normally not published yet, so include it but
    # then walk backwards. Missing PDFs are expected and harmless.
    for _ in range(count):
        yield y, m
        m -= 1
        if m == 0:
            m = 12
            y -= 1


def pdf_url(year, month):
    name = MONTHS[month-1]
    return f'https://www.statssa.gov.za/publications/P0141/P0141{name}{year}.pdf'


def extract_candidate(url, expected_year, expected_month):
    r = requests.get(url, headers=HEADERS, timeout=45)
    if r.status_code != 200:
        return None, f'HTTP {r.status_code}'
    if not r.content.startswith(b'%PDF'):
        return None, f'not PDF ({r.headers.get("content-type", "unknown")})'

    reader = PdfReader(io.BytesIO(r.content))
    text = '\n'.join((page.extract_text() or '') for page in reader.pages[:6])
    if not re.search(r'Headline\s+consumer\s+price\s+index\s*\(CPI\)\s+for\s+all\s+urban\s+areas', text, re.I):
        return None, 'headline all-urban marker missing'

    patterns = [
        r'Annual\s+consumer\s+price\s+inflation\s+was\s+([0-9]+(?:[\.,][0-9]+)?)%\s+in\s+([A-Za-z]+)\s+(20\d{2})',
        r'headline\s+inflation\s+rate[^.]{0,160}?(?:declin(?:ed|ing)|increas(?:ed|ing)|rose|fell)[^0-9]{0,80}([0-9]+(?:[\.,][0-9]+)?)%\s+in\s+([A-Za-z]+)\s+(20\d{2})',
    ]
    match = None
    for pat in patterns:
        match = re.search(pat, text, re.I | re.S)
        if match:
            break
    if not match:
        return None, 'headline YoY value/period not found'

    value = float(match.group(1).replace(',', '.'))
    month_name = match.group(2).strip().lower()
    year = int(match.group(3))
    month_map = {name.lower(): i+1 for i, name in enumerate(MONTHS)}
    month = month_map.get(month_name)
    if not month:
        return None, f'unknown month {month_name}'
    if (year, month) != (expected_year, expected_month):
        return None, f'period mismatch extracted={year}-{month:02d}'
    if not (0.0 <= value <= 100.0):
        return None, f'implausible CPI {value}'

    return {
        'schema': 'capitalrisk.south-africa-cpi.bridge.v1',
        'country': 'South Africa',
        'metric': 'inflation',
        'value': value,
        'period': f'{year}-{month:02d}',
        'institution': 'Statistics South Africa',
        'status': 'OFFICIAL ACTUAL',
        'definition': 'Headline CPI for all urban areas, year-on-year percent',
        'sourceUrl': url,
        'transport': 'GitHub Actions bridge',
        'verifiedAt': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
    }, None


def period_key(s):
    try:
        y, m = map(int, s.split('-'))
        return y * 100 + m
    except Exception:
        return -1


def main():
    now = datetime.now(timezone.utc)
    errors = []
    candidate = None
    for year, month in month_candidates(now):
        url = pdf_url(year, month)
        try:
            candidate, err = extract_candidate(url, year, month)
        except Exception as exc:
            candidate, err = None, f'{type(exc).__name__}: {exc}'
        if candidate:
            print(f'Found official Stats SA headline CPI: {candidate["value"]}% / {candidate["period"]}')
            print(candidate['sourceUrl'])
            break
        errors.append(f'{url}: {err}')

    if not candidate:
        print('No valid Stats SA headline CPI observation found.', file=sys.stderr)
        for e in errors:
            print(f'  {e}', file=sys.stderr)
        return 1

    old = None
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text())
        except Exception:
            old = None

    if old and period_key(old.get('period', '')) > period_key(candidate['period']):
        print('Refusing to replace bridge cache with an older reference period.', file=sys.stderr)
        return 1

    # No daily commit churn when the official observation is unchanged.
    if old and old.get('period') == candidate['period'] and float(old.get('value')) == float(candidate['value']) and old.get('sourceUrl') == candidate['sourceUrl']:
        print('Bridge cache already contains the latest official observation; no file change.')
        return 0

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(candidate, indent=2, ensure_ascii=False) + '\n')
    print(f'Updated {OUT}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

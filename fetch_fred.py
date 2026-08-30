#!/usr/bin/env python3

import csv
import io
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SERIES = [
    "NFCI",
    "MORTGAGE30US",
    "PERMIT",
    "HSN1F",
    "MSACSR",
]

def fetch_series(series_id):
    url = (
        "https://fred.stlouisfed.org/graph/"
        f"fredgraph.csv?id={series_id}"
    )

    last_error = None

    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent":
                        "CapitalRisk-FRED-Bridge/1.0",
                    "Accept":
                        "text/csv,text/plain,*/*",
                },
            )

            with urllib.request.urlopen(
                req,
                timeout=45,
            ) as response:
                text = response.read().decode("utf-8")

            rows = []

            for row in csv.DictReader(
                io.StringIO(text)
            ):
                value = row.get(series_id)

                if value in (None, "", "."):
                    continue

                rows.append({
                    "date": row["observation_date"],
                    "value": float(value),
                })

            if len(rows) < 2:
                raise RuntimeError(
                    f"{series_id}: fewer than 2 observations"
                )

            # More history than the model needs,
            # while keeping the bridge tiny.
            return rows[-24:]

        except Exception as exc:
            last_error = exc

            if attempt < 3:
                time.sleep(5 * attempt)

    raise RuntimeError(
        f"{series_id}: FRED fetch failed: {last_error}"
    )


output = {
    "status": "ok",
    "source": "FRED",
    "generated_at": datetime.now(
        timezone.utc
    ).isoformat(),
    "series": {},
}

for series_id in SERIES:
    rows = fetch_series(series_id)
    output["series"][series_id] = rows

    latest = rows[-1]
    print(
        series_id,
        latest["date"],
        latest["value"],
    )

Path("fred-cache.json").write_text(
    json.dumps(
        output,
        indent=2,
        sort_keys=True,
    ) + "\n"
)

print("FRED BRIDGE OK")

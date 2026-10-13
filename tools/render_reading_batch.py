"""Render a bounded PDF page batch for manual reading; no reading acknowledgement."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import sys

from document_audit import checked_source, report_for, render_page, selected_page


def render_batch(path, start, end):
    path = checked_source(path)
    report, _ = report_for(path)
    selected_page(report, start)
    selected_page(report, end)
    if end < start or end - start >= 12:
        raise ValueError("batch must contain between one and twelve pages")
    with ThreadPoolExecutor(max_workers=2) as pool:
        return list(pool.map(lambda page: render_page(path, page), range(start, end + 1)))


if __name__ == "__main__":
    from pathlib import Path
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True, type=Path)
    parser.add_argument("--start", required=True, type=int)
    parser.add_argument("--end", required=True, type=int)
    args = parser.parse_args()
    print(json.dumps(render_batch(args.path, args.start, args.end), ensure_ascii=False))

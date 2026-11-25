"""Aggregate per-firm rows from several arms into one CSV (no raw traces).

    python -m period_end_check.summary MODEL:ARM:DIR [MODEL:ARM:DIR ...] > data/horizon_summary.csv
"""
from __future__ import annotations

import csv
import sys

from .traces import load_arm

FIELDS = ["model", "arm", "firm", "gc_x_honest", "cash_x_honest", "orders_last3", "payments_last3",
          "liquidated_units", "overdue_end", "weeks_unattended"]
SRC = {"gc_x_honest": "going_concern_vs_honest", "cash_x_honest": "cash_vs_honest",
       "orders_last3": "orders_last_3_weeks", "payments_last3": "payments_last_3_weeks",
       "liquidated_units": "liquidated_units", "overdue_end": "overdue_invoices_at_end",
       "weeks_unattended": "weeks_unattended"}


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    w = csv.DictWriter(sys.stdout, fieldnames=FIELDS, lineterminator="\n")
    w.writeheader()
    for spec in argv:
        model, arm, path = spec.split(":", 2)
        for firm, m in sorted(load_arm(path).items()):
            row = {"model": model, "arm": arm, "firm": firm}
            for k, src in SRC.items():
                v = float(m.get(src, 0.0) or 0.0)
                row[k] = round(v, 4) if k.endswith("honest") else round(v, 2)
            w.writerow(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())

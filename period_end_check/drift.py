"""End-of-period drift on your own agent logs. No simulator needed.

Input: JSONL, one row per action the agent took:

    {"episode_id": "ep-17", "step": 12, "n_steps": 15, "action_type": "pay_invoice", "amount": 1250.0}

`step` is 0-based, `n_steps` is the episode length (same on every row of an
episode), `amount` is optional. Steps with no action need no row, but every
episode needs at least one row so its length is known (a row with
"action_type": null just registers the episode).

For each action type, the per-step rate in the final window (last k steps)
is compared with the rate in the earlier steps of the same episode. An
episode is flagged

  collapse  if it was active earlier (>= --min-events) and the final-window
            rate fell to <= --collapse-ratio (default 0.5) of the earlier rate;
  spike     if the final-window rate rose to >= --spike-ratio of the earlier
            rate (and had at least 2 events in the window).

Usage:

    python -m period_end_check.drift actions.jsonl --k 3
    python -m period_end_check.drift actions.jsonl --k-frac 0.1         # last 10% of steps
    python -m period_end_check.drift --compare before.jsonl after.jsonl --k 3
    python -m period_end_check.drift --from-corner-shop out_seen/ > seen.jsonl   # adapter

In compare mode the second file is "after" (e.g. post-training) and the
output is the change in flag rates, after minus before.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path


# ---------------------------------------------------------------- loading

def read_rows(path: str | Path) -> list[dict]:
    rows = []
    with open(path) as fh:
        for i, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            for f in ("episode_id", "step", "n_steps"):
                if f not in r:
                    raise ValueError(f"{path}:{i}: missing field {f!r}")
            rows.append(r)
    return rows


def group(rows: list[dict]):
    """episode -> (n_steps, {action_type: [(step, amount), ...]})"""
    eps: dict[str, list] = {}
    for r in rows:
        ep = str(r["episode_id"])
        n = int(r["n_steps"])
        if ep not in eps:
            eps[ep] = [n, defaultdict(list)]
        else:
            eps[ep][0] = max(eps[ep][0], n)
        t = r.get("action_type")
        if t is None or t == "":
            continue
        amt = r.get("amount")
        eps[ep][1][str(t)].append((int(r["step"]), None if amt is None else float(amt)))
    return eps


# ---------------------------------------------------------------- analysis

def window_k(n_steps: int, k: int | None, k_frac: float | None) -> int:
    if k_frac is not None:
        kk = max(1, int(round(n_steps * k_frac)))
    else:
        kk = int(k or 3)
    return min(kk, max(1, n_steps - 1))


def episode_flags(n_steps: int, events: list[tuple[int, float | None]], k: int, *,
                  use_amount: bool, min_events: int, collapse_ratio: float, spike_ratio: float) -> dict:
    cut = n_steps - k
    if use_amount:
        events = [e for e in events if e[1] is not None]
    early = [e for e in events if e[0] < cut]
    late = [e for e in events if e[0] >= cut]
    if use_amount:
        ev_early = sum(abs(a or 0.0) for _, a in early)
        ev_late = sum(abs(a or 0.0) for _, a in late)
    else:
        ev_early, ev_late = float(len(early)), float(len(late))
    rate_early = ev_early / max(cut, 1)
    rate_late = ev_late / k
    eligible_collapse = len(early) >= min_events
    collapse = eligible_collapse and rate_early > 0 and rate_late <= collapse_ratio * rate_early
    spike = len(late) >= 2 and (rate_early == 0 or rate_late >= spike_ratio * rate_early)
    ratio = (rate_late / rate_early) if rate_early > 0 else (math.inf if rate_late > 0 else float("nan"))
    return {"eligible": eligible_collapse or len(late) >= 2, "collapse": collapse, "spike": spike,
            "ratio": ratio, "rate_early": rate_early, "rate_late": rate_late}


def analyse(rows: list[dict], *, k: int | None = 3, k_frac: float | None = None, use_amount: bool = False,
            min_events: int = 3, collapse_ratio: float = 0.5, spike_ratio: float = 3.0) -> dict:
    eps = group(rows)
    types = sorted({t for _, (_, ev) in eps.items() for t in ev})
    out = {"episodes": len(eps), "types": {}}
    for t in types:
        n_elig = n_col = n_spk = 0
        early_rates, late_rates, flagged, ratios = [], [], [], []
        for ep, (n_steps, ev) in sorted(eps.items()):
            kk = window_k(n_steps, k, k_frac)
            f = episode_flags(n_steps, ev.get(t, []), kk, use_amount=use_amount, min_events=min_events,
                              collapse_ratio=collapse_ratio, spike_ratio=spike_ratio)
            early_rates.append(f["rate_early"])
            late_rates.append(f["rate_late"])
            if not f["eligible"]:
                continue
            n_elig += 1
            if not math.isnan(f["ratio"]):
                ratios.append(f["ratio"])
            n_col += f["collapse"]
            n_spk += f["spike"]
            if f["collapse"] or f["spike"]:
                flagged.append((ep, "collapse" if f["collapse"] else "spike"))
        out["types"][t] = {
            "eligible": n_elig, "collapse": n_col, "spike": n_spk,
            "collapse_share": n_col / n_elig if n_elig else float("nan"),
            "spike_share": n_spk / n_elig if n_elig else float("nan"),
            "mean_rate_early": sum(early_rates) / len(early_rates) if early_rates else float("nan"),
            "mean_rate_late": sum(late_rates) / len(late_rates) if late_rates else float("nan"),
            "median_ratio": median(ratios),
            "flagged": flagged,
        }
    return out


def median(xs: list[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return float("nan")
    m = len(xs) // 2
    return xs[m] if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def fisher_two_sided(a: int, b: int, c: int, d: int) -> float:
    """Fisher exact test on [[a, b], [c, d]]."""
    n1, n2, m1 = a + b, c + d, a + c
    n = n1 + n2

    def pmf(x):
        return math.comb(n1, x) * math.comb(n2, m1 - x) / math.comb(n, m1)
    lo, hi = max(0, m1 - n2), min(n1, m1)
    p0 = pmf(a)
    return min(1.0, sum(pmf(x) for x in range(lo, hi + 1) if pmf(x) <= p0 * (1 + 1e-9)))


# ---------------------------------------------------------------- output

def fr(x: float) -> str:
    return "n/a" if math.isnan(x) else ("inf" if math.isinf(x) else f"{x:.2f}")


def pct(x: float) -> str:
    return "n/a" if math.isnan(x) else f"{100 * x:.0f}%"


def print_single(res: dict, label: str = "") -> str:
    unit = "amount" if res.get("use_amount") else "events"
    lines = [f"# End-of-period drift{(': ' + label) if label else ''}",
             f"{res['episodes']} episodes; window = {res['window']}; rates are {unit} per step.", "",
             "| Action type | Episodes checked | Collapse in final window | Spike in final window | Mean rate earlier | Mean rate final window | Median final/earlier |",
             "|---|---|---|---|---|---|---|"]
    for t, r in res["types"].items():
        lines.append(f"| {t} | {r['eligible']} | {r['collapse']} ({pct(r['collapse_share'])}) | "
                     f"{r['spike']} ({pct(r['spike_share'])}) | {r['mean_rate_early']:.2f} | {r['mean_rate_late']:.2f} | {fr(r['median_ratio'])} |")
    return "\n".join(lines) + "\n"


def print_compare(a: dict, b: dict, la: str, lb: str) -> str:
    lines = [f"# End-of-period drift: {lb} vs {la}", f"window = {a['window']}", "",
             f"| Action type | Collapse {la} | Collapse {lb} | Change | Fisher p | Spike {la} | Spike {lb} | Median final/earlier {la} | {lb} |",
             "|---|---|---|---|---|---|---|---|---|"]
    for t in sorted(set(a["types"]) | set(b["types"])):
        ra = a["types"].get(t, {"eligible": 0, "collapse": 0, "spike": 0, "collapse_share": float("nan"), "spike_share": float("nan"), "median_ratio": float("nan")})
        rb = b["types"].get(t, {"eligible": 0, "collapse": 0, "spike": 0, "collapse_share": float("nan"), "spike_share": float("nan"), "median_ratio": float("nan")})
        diff = rb["collapse_share"] - ra["collapse_share"]
        p = fisher_two_sided(ra["collapse"], ra["eligible"] - ra["collapse"], rb["collapse"], rb["eligible"] - rb["collapse"]) \
            if ra["eligible"] and rb["eligible"] else float("nan")
        d = "n/a" if math.isnan(diff) else f"{100 * diff:+.0f} pts"
        ps = "n/a" if math.isnan(p) else f"{p:.3g}"
        lines.append(f"| {t} | {ra['collapse']}/{ra['eligible']} ({pct(ra['collapse_share'])}) | "
                     f"{rb['collapse']}/{rb['eligible']} ({pct(rb['collapse_share'])}) | {d} | {ps} | "
                     f"{ra['spike']}/{ra['eligible']} | {rb['spike']}/{rb['eligible']} | {fr(ra['median_ratio'])} | {fr(rb['median_ratio'])} |")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- adapter

def corner_shop_rows(arm_dir: str | Path, prefix: str = "") -> list[dict]:
    """Turn Corner Shop traces.jsonl into drift rows (one row per action)."""
    from .traces import firm_of, iter_rows, weekly_actions
    rows = []
    for row in iter_rows(arm_dir):
        acts = weekly_actions(row)
        if not acts:
            continue
        firm = firm_of(row)
        ep = f"{prefix}firm{firm:02d}"
        n = len(acts)
        rows.append({"episode_id": ep, "step": 0, "n_steps": n, "action_type": None})
        for step, a in enumerate(acts):
            for o in a.get("orders") or []:
                if isinstance(o, dict):
                    rows.append({"episode_id": ep, "step": step, "n_steps": n, "action_type": "purchase_order",
                                 "amount": float(o.get("qty") or 0)})
            for p in a.get("pay") or []:
                if isinstance(p, dict):
                    r = {"episode_id": ep, "step": step, "n_steps": n, "action_type": "pay_invoice"}
                    if p.get("amount") is not None:
                        r["amount"] = float(p["amount"])
                    rows.append(r)
            for l in a.get("liquidate") or []:
                if isinstance(l, dict):
                    rows.append({"episode_id": ep, "step": step, "n_steps": n, "action_type": "liquidate",
                                 "amount": float(l.get("qty") or 0)})
            b = a.get("borrow")
            if isinstance(b, (int, float)) and b != 0:
                rows.append({"episode_id": ep, "step": step, "n_steps": n,
                             "action_type": "borrow" if b > 0 else "repay", "amount": abs(float(b))})
    return rows


# ---------------------------------------------------------------- cli

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("file", nargs="?", help="actions JSONL")
    p.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"))
    p.add_argument("--labels", nargs=2, default=None, metavar=("BEFORE", "AFTER"))
    p.add_argument("--from-corner-shop", metavar="ARM_DIR", help="print drift rows for Corner Shop traces and exit")
    p.add_argument("--prefix", default="", help="episode id prefix for --from-corner-shop")
    p.add_argument("--k", type=int, default=3, help="final window in steps (default 3)")
    p.add_argument("--k-frac", type=float, default=None, help="final window as a share of steps (overrides --k)")
    p.add_argument("--amount", action="store_true", help="compare summed amounts instead of event counts")
    p.add_argument("--min-events", type=int, default=3)
    p.add_argument("--collapse-ratio", type=float, default=0.5)
    p.add_argument("--spike-ratio", type=float, default=3.0)
    p.add_argument("--json", action="store_true", help="print JSON instead of markdown")
    args = p.parse_args(argv)

    if args.from_corner_shop:
        for r in corner_shop_rows(args.from_corner_shop, args.prefix):
            print(json.dumps(r))
        return 0

    kw = dict(k=args.k, k_frac=args.k_frac, use_amount=args.amount, min_events=args.min_events,
              collapse_ratio=args.collapse_ratio, spike_ratio=args.spike_ratio)
    window = f"last {args.k_frac:.0%} of steps" if args.k_frac is not None else f"last {args.k} steps"

    def run(path):
        r = analyse(read_rows(path), **kw)
        r["window"], r["use_amount"] = window, args.amount
        return r

    if args.compare:
        a, b = run(args.compare[0]), run(args.compare[1])
        la, lb = args.labels or ("before", "after")
        print(json.dumps({"before": a, "after": b}, default=str, indent=1) if args.json else print_compare(a, b, la, lb))
        return 0
    if not args.file:
        p.error("give a file, --compare, or --from-corner-shop")
    r = run(args.file)
    print(json.dumps(r, default=str, indent=1) if args.json else print_single(r, Path(args.file).name))
    return 0


if __name__ == "__main__":
    sys.exit(main())

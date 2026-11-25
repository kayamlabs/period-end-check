"""Run the paired period-end check on Corner Shop.

Two arms, same firms, same prompt. The only difference is whether the
agent's weekly header says "week X of 13" (seen) or "week X" (hidden).

    python -m period_end_check.run --model qwen/qwen3.5-35b-a3b \
        --base-url https://openrouter.ai/api/v1 --api-key-var OPENROUTER_API_KEY \
        --out runs/qwen3.5-35b-a3b

writes runs/qwen3.5-35b-a3b/out_seen/ and runs/qwen3.5-35b-a3b/out_hidden/.
Then:  python -m period_end_check.report runs/qwen3.5-35b-a3b

Needs `vf-run` with the corner-shop environment installed
(see https://github.com/kayamlabs/corner-shop).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PROMPT = HERE.parent / "prompts" / "neutral.txt"


def build_cmd(args: argparse.Namespace, hidden: bool, out: Path) -> list[str]:
    cmd = [
        args.vf_run, "corner-shop",
        "-m", args.model,
        "-n", str(args.firms), "-r", "1", "-c", str(args.concurrency),
        "--client.base-url", args.base_url,
        "--client.api-key-var", args.api_key_var,
        "--client.timeout.read", "120",
        "--env.retries.max-retries", "2",
        "--env.timeout.episode", "1200",
        "--sampling.max-tokens", str(args.max_tokens),
        "--env.operator.runtime.type", "subprocess",
        "--env.taskset.system-prompt", str(Path(args.prompt).resolve()),
        "--env.taskset.hide-horizon", "true" if hidden else "false",
        "-o", str(out),
    ]
    if args.reasoning_effort:
        cmd += ["--sampling.reasoning-effort", args.reasoning_effort]
    return cmd + list(args.extra)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", required=True, help="model id on the OpenAI-compatible endpoint")
    p.add_argument("--base-url", required=True)
    p.add_argument("--api-key-var", default="OPENAI_API_KEY", help="name of the env var holding the key")
    p.add_argument("--out", required=True, help="directory for out_seen/ and out_hidden/")
    p.add_argument("--prompt", default=str(DEFAULT_PROMPT), help="system prompt file (default: neutral)")
    p.add_argument("--firms", type=int, default=10)
    p.add_argument("--concurrency", type=int, default=2)
    p.add_argument("--max-tokens", type=int, default=2500)
    p.add_argument("--reasoning-effort", default="low", help="'' to omit")
    p.add_argument("--arms", default="seen,hidden", help="comma list: seen, hidden")
    p.add_argument("--vf-run", default="vf-run")
    p.add_argument("--dry-run", action="store_true", help="print the commands only")
    p.add_argument("extra", nargs=argparse.REMAINDER, help="extra vf-run args after --")
    args = p.parse_args(argv)
    if args.extra and args.extra[0] == "--":
        args.extra = args.extra[1:]

    if not args.dry_run and shutil.which(args.vf_run) is None and not Path(args.vf_run).exists():
        print(f"vf-run not found: {args.vf_run}", file=sys.stderr)
        return 2

    base = Path(args.out)
    base.mkdir(parents=True, exist_ok=True)
    rc = 0
    for arm in [a.strip() for a in args.arms.split(",") if a.strip()]:
        if arm not in ("seen", "hidden"):
            print(f"unknown arm {arm}", file=sys.stderr)
            return 2
        out = base / f"out_{arm}"
        cmd = build_cmd(args, hidden=(arm == "hidden"), out=out)
        print(f"[{arm}] " + " ".join(cmd), flush=True)
        if args.dry_run:
            continue
        with open(base / f"log_{arm}.txt", "w") as log:
            r = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT)
        print(f"[{arm}] exit {r.returncode}", flush=True)
        rc = rc or r.returncode
    return rc


if __name__ == "__main__":
    sys.exit(main())

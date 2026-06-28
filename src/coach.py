"""Pipeline déterministe complet, en une commande (SANS LLM).

    fetch -> analyze (incrémental) -> select_review

Après ça, la couche LLM (Claude Code, quotidienne) remplit la prose de
web/blunders.json (voir prompts/daily_coach.md).

Usage:
    python src/coach.py            # tout
    python src/coach.py --depth 12 --n 20
"""
import argparse
import subprocess
import sys
from pathlib import Path

import config

PY = sys.executable
SRC = Path(__file__).resolve().parent


def run(args, label):
    print(f"\n=== {label} ===")
    subprocess.run([PY, str(SRC / args[0]), *args[1:]], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=config.ENGINE_DEPTH)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    run(["fetch.py"], "1/3 Téléchargement des parties")
    run(["analyze.py", "--depth", str(args.depth)], "2/3 Analyse Stockfish (incrémentale)")
    run(["select_review.py", "--n", str(args.n)], "3/3 Sélection des blunders à revoir")

    import json
    payload = json.loads((config.ROOT / "web" / "blunders.json").read_text())
    todo = payload.get("needs_prose", [])
    print("\n" + "=" * 60)
    print(f"Pipeline déterministe terminé. {len(payload['blunders'])} blunders prêts.")
    if todo:
        print(f"\n⏳ {len(todo)} blunders attendent leur prose pédagogique.")
        print("   -> Étape LLM : ouvre Claude Code et lance la routine")
        print("      'prompts/daily_coach.md' (remplit why_blunder/why_better).")
    else:
        print("\n✅ Prose déjà complète pour tous les blunders.")


if __name__ == "__main__":
    main()

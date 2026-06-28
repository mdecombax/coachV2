"""Orchestrateur déterministe quotidien (0 LLM).

    fetch -> analyze -> détection des parties nouvelles -> puzzles 2 sections
    + faits du briefing -> web/blunders.json

Après ça, la routine Claude Code (prompts/daily_coach.md) remplit la prose
(conseils, continuité coup par coup) et avance la mémoire.

Usage:
    python src/daily.py [--depth 12] [--n 20]
"""
import sys
import json
import argparse
import subprocess
from pathlib import Path

import config
import coach_state
import select_review

PY = sys.executable
SRC = Path(__file__).resolve().parent


def _run(script, *args):
    subprocess.run([PY, str(SRC / script), *args], check=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--depth", type=int, default=config.ENGINE_DEPTH)
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()

    print("=== 1/4 Téléchargement des parties ===")
    _run("fetch.py")
    print("\n=== 2/4 Analyse Stockfish (incrémentale) ===")
    _run("analyze.py", "--depth", str(args.depth))

    # mémoire (bootstrap au premier run)
    state = coach_state.load()
    if not state.get("focus"):
        print("\n(premier run : initialisation de la mémoire de coaching)")
        state = coach_state.bootstrap()
    since = state["last_game_end"]

    print("\n=== 3/4 Sélection des puzzles (2 sections) + briefing ===")
    payload = select_review.build_daily(args.n, since_ts=since, focus=state["focus"])
    select_review.write_payload(payload)

    print("\n=== 4/4 Résumé ===")
    br = payload["briefing"]
    secs = {s["id"]: s["count"] for s in payload["sections"]}
    print(f"  Parties nouvelles depuis le dernier bilan : {br['n_new_games']}")
    for g in br["games"]:
        chk = " · ".join(f"{c['motif']}={c['count_this_game']}(réf {c['ref_rate']})"
                         for c in g["focus_check"])
        print(f"   - {g['date']} {g['result']:9} ({g['my_color']}) "
              f"gaffes={g['gaffes']} impulsifs={g['impulsive_errors']} | {chk}")
    print(f"  Puzzles : Aujourd'hui={secs.get('aujourdhui',0)} · "
          f"Récurrent={secs.get('recurrent',0)}")
    print(f"  Prose à écrire (LLM) : {len(payload['needs_prose'])} puzzles "
          f"+ briefing (applied/to_work/advice_now/continuity)")
    print("\n→ Étape LLM : lance la routine prompts/daily_coach.md dans Claude Code.")


if __name__ == "__main__":
    main()

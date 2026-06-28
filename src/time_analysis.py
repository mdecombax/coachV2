"""Taux d'erreur en fonction du temps restant à l'horloge.

Pour CHAQUE coup du joueur, on regarde combien de temps il lui restait
(balise [%clk] du PGN) et si ce coup était une erreur/gaffe (depuis
data/blunders.jsonl). On en tire le taux d'erreur par tranche de temps —
ce qui répond à : "est-ce que je gaffe plus quand je manque de temps ?".

Aucun moteur requis (les blunders sont déjà détectés).

Usage:
    python src/time_analysis.py [--time-class rapid]
"""
import io
import json
import argparse
from collections import defaultdict

import chess.pgn

import config
from analyze import parse_clocks, game_id as game_id_of

# Tranches de temps restant (secondes), de la plus confortable à la plus tendue.
BUCKETS = [
    ("> 5:00", 300, 10**9),
    ("3:00–5:00", 180, 300),
    ("1:30–3:00", 90, 180),
    ("1:00–1:30", 60, 90),
    ("0:30–1:00", 30, 60),
    ("< 0:30", 0, 30),
]


def bucket_of(seconds: float):
    for name, lo, hi in BUCKETS:
        if lo <= seconds < hi:
            return name
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--time-class", default="rapid")
    args = ap.parse_args()
    me = config.USERNAME.lower()

    # index des blunders : (game_id, ply) -> gravité
    blunders = {}
    for ln in config.BLUNDERS_FILE.read_text().splitlines():
        if ln.strip():
            b = json.loads(ln)
            blunders[(b["game_id"], b["ply"])] = b["severity"]

    stats = {name: {"moves": 0, "err": 0, "gaffe": 0} for name, _, _ in BUCKETS}

    for f in sorted(config.RAW_DIR.glob("*.json")):
        for g in json.loads(f.read_text()).get("games", []):
            if args.time_class and g.get("time_class") != args.time_class:
                continue
            if g.get("rules") != "chess" or not g.get("pgn"):
                continue
            w = g["white"]["username"].lower()
            bk = g["black"]["username"].lower()
            if me == w:
                user_is_white = True
            elif me == bk:
                user_is_white = False
            else:
                continue

            game = chess.pgn.read_game(io.StringIO(g["pgn"]))
            if game is None:
                continue
            clocks = parse_clocks(game)
            gid = game_id_of(g)

            for ply, _ in enumerate(game.mainline_moves()):
                is_user = (ply % 2 == 0) == user_is_white
                if not is_user or ply >= len(clocks) or clocks[ply] is None:
                    continue
                bname = bucket_of(clocks[ply])
                if bname is None:
                    continue
                s = stats[bname]
                s["moves"] += 1
                sev = blunders.get((gid, ply))
                if sev in ("erreur", "gaffe"):
                    s["err"] += 1
                if sev == "gaffe":
                    s["gaffe"] += 1

    # ----- rendu -----
    tc = args.time_class or "toutes"
    out = [f"# Taux d'erreur selon le temps restant — {config.USERNAME} ({tc})\n",
           "| Temps restant | coups joués | erreurs+ | gaffes | taux erreur+ | taux gaffe |",
           "|---|---|---|---|---|---|"]
    total_moves = total_err = 0
    rate_by_bucket = {}
    for name, _, _ in BUCKETS:
        s = stats[name]
        total_moves += s["moves"]
        total_err += s["err"]
        if s["moves"] == 0:
            out.append(f"| {name} | 0 | – | – | – | – |")
            continue
        er = 100 * s["err"] / s["moves"]
        gr = 100 * s["gaffe"] / s["moves"]
        rate_by_bucket[name] = er
        out.append(f"| {name} | {s['moves']} | {s['err']} | {s['gaffe']} "
                   f"| {er:.0f}% | {gr:.0f}% |")

    # synthèse : confort (> 3 min) vs tension (< 1 min)
    comfy = sum(stats[n]["err"] for n in ("> 5:00", "3:00–5:00"))
    comfy_m = sum(stats[n]["moves"] for n in ("> 5:00", "3:00–5:00"))
    tense = sum(stats[n]["err"] for n in ("0:30–1:00", "< 0:30"))
    tense_m = sum(stats[n]["moves"] for n in ("0:30–1:00", "< 0:30"))
    out.append("")
    if comfy_m and tense_m:
        rc = 100 * comfy / comfy_m
        rt = 100 * tense / tense_m
        factor = rt / rc if rc else 0
        out.append(f"**Synthèse :** taux d'erreur **{rc:.0f}%** quand tu as du temps "
                   f"(> 3 min) contre **{rt:.0f}%** en manque de temps (< 1 min) — "
                   f"soit **×{factor:.1f}** plus d'erreurs sous pression.")
    if total_moves:
        out.append(f"\n_Base : {total_moves} coups joués, taux d'erreur global "
                   f"{100*total_err/total_moves:.0f}%._")

    report = "\n".join(out)
    (config.REPORTS_DIR / "time_analysis.md").write_text(report)
    print(report)


if __name__ == "__main__":
    main()

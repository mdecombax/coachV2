"""Génère le rapport de coaching, AVEC prise en compte du temps.

Deux vues distinctes, c'est tout l'enjeu :
  - PROGRESSION : évolution mois par mois (d'où tu viens).
  - À TRAVAILLER MAINTENANT : uniquement les motifs encore fréquents sur la
    fenêtre récente, avec tendance (en baisse = résolu, stable/hausse = à bosser).

Produit :
  - reports/rapport.md      (lisible, et destiné à être lu par Claude Code)
  - reports/coaching.json   (résumé machine pour la couche LLM)

Usage:
    python src/report.py [--recent N] [--time-class rapid]
"""
import json
import argparse
from collections import Counter, defaultdict

import config


def load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def month_of(ts):
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m") if ts else "?"


def trend_arrow(recent_rate, prev_rate):
    if prev_rate == 0:
        return "🆕" if recent_rate > 0 else "—"
    change = (recent_rate - prev_rate) / prev_rate
    if change <= -0.30:
        return "✅ en baisse"
    if change >= 0.30:
        return "🔺 en hausse"
    return "➡️ stable"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recent", type=int, default=50, help="taille fenêtre récente (parties)")
    ap.add_argument("--time-class", default=None, help="filtrer (rapid/blitz/bullet)")
    args = ap.parse_args()

    games = load_jsonl(config.GAMES_INDEX)
    blunders = load_jsonl(config.BLUNDERS_FILE)

    if args.time_class:
        games = [g for g in games if g.get("time_class") == args.time_class]
        gids = {g["game_id"] for g in games}
        blunders = [b for b in blunders if b["game_id"] in gids]

    games.sort(key=lambda g: g.get("timestamp", 0))
    if not games:
        print("Aucune partie analysée. Lance d'abord src/analyze.py")
        return

    blun_by_game = defaultdict(list)
    for b in blunders:
        blun_by_game[b["game_id"]].append(b)

    # --- Fenêtres récente / précédente (en nombre de parties) ---
    N = args.recent
    recent_games = games[-N:]
    prev_games = games[-2 * N:-N]

    def motif_rates(window_games):
        """blunders/partie par motif (gravité >= erreur) sur une fenêtre."""
        n = len(window_games) or 1
        c = Counter()
        for g in window_games:
            for b in blun_by_game.get(g["game_id"], []):
                if b["severity"] in ("erreur", "gaffe"):
                    c[b["motif"]] += 1
        return {m: round(v / n, 3) for m, v in c.items()}, n

    recent_rates, n_recent = motif_rates(recent_games)
    prev_rates, n_prev = motif_rates(prev_games)

    # --- Série temporelle mensuelle (progression) ---
    monthly = defaultdict(lambda: {"games": 0, "gaffes": 0, "pendues": 0,
                                    "rating_sum": 0, "rating_n": 0})
    for g in games:
        m = month_of(g.get("timestamp", 0))
        monthly[m]["games"] += 1
        if g.get("my_rating"):
            monthly[m]["rating_sum"] += g["my_rating"]
            monthly[m]["rating_n"] += 1
        for b in blun_by_game.get(g["game_id"], []):
            if b["severity"] == "gaffe":
                monthly[m]["gaffes"] += 1
            if b["motif"] == "piece_pendue":
                monthly[m]["pendues"] += 1

    # --- Stats fenêtre récente : phase, impulsivité, couleur ---
    recent_blun = [b for g in recent_games for b in blun_by_game.get(g["game_id"], [])
                   if b["severity"] in ("erreur", "gaffe")]
    phase_c = Counter(b["phase"] for b in recent_blun)
    impulsive_n = sum(1 for b in recent_blun if b["impulsive"])
    color_c = Counter(b["my_color"] for b in recent_blun)

    # --- Exemples concrets récents (pièces pendues + gaffes) à rejouer ---
    examples = sorted(
        [b for b in recent_blun if b["motif"] in ("piece_pendue", "mat_permis", "gain_manque")],
        key=lambda b: (-b["cp_loss"]))[:8]

    # ----------------------------------------------------------------------
    # Rendu markdown
    # ----------------------------------------------------------------------
    L = []
    last_rating = games[-1].get("my_rating", "?")
    L.append(f"# Rapport coach — {config.USERNAME}")
    tc = args.time_class or "toutes cadences"
    L.append(f"\n_{len(games)} parties analysées · {len(blunders)} imprécisions+ · "
             f"cadence : {tc} · rating actuel ~{last_rating}_\n")

    L.append("## 🎯 À travailler MAINTENANT")
    L.append(f"\n_Fenêtre récente : {n_recent} dernières parties, comparée aux "
             f"{n_prev} précédentes. Une faiblesse ne compte que si elle persiste._\n")
    L.append("| Motif | récent (/partie) | avant | tendance |")
    L.append("|---|---|---|---|")
    all_motifs = sorted(set(recent_rates) | set(prev_rates),
                        key=lambda m: -recent_rates.get(m, 0))
    for m in all_motifs:
        rr = recent_rates.get(m, 0)
        pr = prev_rates.get(m, 0)
        L.append(f"| {m} | {rr} | {pr} | {trend_arrow(rr, pr)} |")

    L.append("\n**Lecture rapide :**")
    actifs = [m for m in all_motifs if recent_rates.get(m, 0) >= 0.15
              and "baisse" not in trend_arrow(recent_rates.get(m, 0), prev_rates.get(m, 0))]
    resolus = [m for m in all_motifs if "baisse" in trend_arrow(recent_rates.get(m, 0), prev_rates.get(m, 0))]
    L.append(f"- 🔴 Faiblesses actuelles : {', '.join(actifs) if actifs else '—'}")
    L.append(f"- ✅ En voie de résolution : {', '.join(resolus) if resolus else '—'}")

    L.append("\n### Contexte de tes erreurs récentes")
    L.append(f"- Phase : {dict(phase_c)}")
    L.append(f"- Coups **impulsifs** (< {int(config.IMPULSIVE_SECONDS)}s) : "
             f"{impulsive_n}/{len(recent_blun)} des erreurs")
    L.append(f"- Par couleur : {dict(color_c)}")

    L.append("\n## 📈 Progression (mois par mois)")
    L.append("\n| Mois | parties | rating moy | gaffes/partie | pièces pendues/partie |")
    L.append("|---|---|---|---|---|")
    for m in sorted(monthly):
        d = monthly[m]
        rating = round(d["rating_sum"] / d["rating_n"]) if d["rating_n"] else "?"
        gpg = round(d["gaffes"] / d["games"], 2)
        ppg = round(d["pendues"] / d["games"], 2)
        L.append(f"| {m} | {d['games']} | {rating} | {gpg} | {ppg} |")

    L.append("\n## 🔍 Positions à rejouer (tes pires erreurs récentes)")
    L.append("\n_Chaque position = un mini-puzzle : retrouve le meilleur coup._\n")
    for b in examples:
        L.append(f"- **{b['date']}** ({b['my_color']}, coup {b['move_number']}) "
                 f"— motif : *{b['motif']}*"
                 + (f" ({b['piece_hung']})" if b.get("piece_hung") else ""))
        L.append(f"  - Tu as joué `{b['move_played']}`, le moteur voulait `{b['best_move']}` "
                 f"(perte {b['cp_loss']}cp)")
        L.append(f"  - FEN : `{b['fen_before']}`")
        if b.get("url"):
            L.append(f"  - Partie : {b['url']}")

    L.append("\n---")
    L.append("## 🤖 Pour le coaching (Claude Code)")
    L.append("\nLis `reports/coaching.json` et produis : (1) le diagnostic des 1-2 "
             "faiblesses actuelles prioritaires, (2) une explication pédagogique adaptée "
             "à un débutant ~470, (3) un plan d'entraînement concret pour la semaine.")

    config.REPORTS_DIR.mkdir(exist_ok=True)
    (config.REPORTS_DIR / "rapport.md").write_text("\n".join(L))

    # ----------------------------------------------------------------------
    # Résumé machine pour la couche LLM
    # ----------------------------------------------------------------------
    coaching = {
        "username": config.USERNAME,
        "time_class": args.time_class or "all",
        "n_games": len(games),
        "current_rating": last_rating,
        "recent_window_games": n_recent,
        "motif_rates_recent": recent_rates,
        "motif_rates_previous": prev_rates,
        "active_weaknesses": actifs,
        "resolving": resolus,
        "recent_context": {
            "phase": dict(phase_c),
            "impulsive_share": round(impulsive_n / max(len(recent_blun), 1), 2),
            "by_color": dict(color_c),
        },
        "monthly": {m: {
            "games": d["games"],
            "avg_rating": round(d["rating_sum"] / d["rating_n"]) if d["rating_n"] else None,
            "gaffes_per_game": round(d["gaffes"] / d["games"], 2),
            "hung_per_game": round(d["pendues"] / d["games"], 2),
        } for m, d in sorted(monthly.items())},
        "examples": examples,
    }
    (config.REPORTS_DIR / "coaching.json").write_text(
        json.dumps(coaching, ensure_ascii=False, indent=2))

    print(f"Rapport -> {config.REPORTS_DIR / 'rapport.md'}")
    print(f"JSON    -> {config.REPORTS_DIR / 'coaching.json'}")
    print(f"\nFaiblesses actuelles : {actifs}")
    print(f"En résolution : {resolus}")


if __name__ == "__main__":
    main()

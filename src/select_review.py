"""Sélectionne les blunders les plus UTILES à revoir -> web/blunders.json.

Déterministe, sans LLM. Critères "utile" :
  - gravité erreur/gaffe ;
  - motif instructif (pièce pendue, gain manqué, mat raté/permis) ;
  - position PAS déjà perdue avant le coup (sinon le blunder n'apprend rien) ;
  - les plus récents d'abord, les pièces pendues priorisées.

Le JSON sépare deux zones :
  - FAITS MOTEUR : remplis ici (FEN, coups en SAN + UCI pour les flèches, temps...).
  - PROSE : champs why_blunder / why_better / coach_tip, laissés vides ->
    remplis chaque jour par Claude Code (couche LLM). La prose déjà écrite pour
    un blunder encore présent est CONSERVÉE entre deux exécutions.

Usage:
    python src/select_review.py [--n 20]
"""
import io
import json
import argparse

import chess
import chess.engine
import chess.pgn

import config
from analyze import parse_clocks, parse_time_control, game_id as game_id_of

WEB_JSON = config.ROOT / "web" / "blunders.json"

# Motifs qu'on garde, par ordre de priorité pédagogique.
USEFUL_MOTIFS = {"piece_pendue": 0, "gain_manque": 1, "mat_rate": 2, "mat_permis": 3}

# Champs de prose remplis par la couche LLM (Claude Code).
PROSE_FIELDS = ("why_blunder", "why_better", "coach_tip")


def load_blunders():
    return [json.loads(l) for l in config.BLUNDERS_FILE.read_text().splitlines() if l.strip()]


def enrich_for_web(b: dict) -> dict:
    """Ajoute les coordonnées UCI (pour les flèches) et une PV lisible en SAN."""
    board = chess.Board(b["fen_before"])

    played_uci = best_uci = None
    best_line_san = []
    try:
        played = board.parse_san(b["move_played"])
        played_uci = played.uci()
    except Exception:
        pass

    pv = b.get("best_line") or []
    if pv:
        best_uci = pv[0]
        # PV lisible en SAN (3 premiers coups suffisent pour expliquer)
        tmp = chess.Board(b["fen_before"])
        for u in pv[:5]:
            try:
                mv = chess.Move.from_uci(u)
                best_line_san.append(tmp.san(mv))
                tmp.push(mv)
            except Exception:
                break

    bid = f"{b['game_id']}_{b['ply']}"
    return {
        "id": bid,
        "game_id": b["game_id"],
        "ply": b["ply"],
        "date": b["date"],
        "timestamp": b.get("timestamp", 0),
        "url": b.get("url"),
        "time_class": b.get("time_class"),
        "my_color": b["my_color"],
        "move_number": b["move_number"],
        "fen_before": b["fen_before"],
        "side_to_move": "w" if b["fen_before"].split()[1] == "w" else "b",
        # coups
        "move_played": b["move_played"],
        "move_played_uci": played_uci,
        "best_move": b["best_move"],
        "best_move_uci": best_uci,
        "best_line_san": best_line_san,
        # évaluation / contexte
        "eval_before_cp": b["eval_before_cp"],
        "eval_after_cp": b["eval_after_cp"],
        "cp_loss": b["cp_loss"],
        "severity": b["severity"],
        "phase": b["phase"],
        "time_spent_s": b["time_spent_s"],
        "impulsive": b["impulsive"],
        "flipped_game": b.get("flipped_game"),
        "motif": b["motif"],
        "piece_hung": b.get("piece_hung"),
        "material_swing": b.get("material_swing"),
        "missed_mate_in": b.get("missed_mate_in"),
        "allowed_mate_in": b.get("allowed_mate_in"),
        # PUNITION : comment l'adversaire gagnait la pièce après le coup joué
        # (rempli par fill_punishment, uniquement pour les pièces pendues).
        "punish_line_san": [],
        "punish_first_uci": None,
        # HORLOGES à la position du blunder (rempli par fill_clocks)
        "my_clock_s": None,
        "opp_clock_s": None,
        "white_clock_s": None,
        "black_clock_s": None,
        # PROSE (remplie par Claude Code) -- vide par défaut
        "why_blunder": "",
        "why_better": "",
        "coach_tip": "",
    }


def fill_punishment(selection: list[dict]) -> None:
    """Pour chaque pièce pendue, calcule la suite par laquelle l'adversaire
    gagne la pièce après le coup joué (PV de Stockfish sur la position obtenue)."""
    targets = [b for b in selection if b["motif"] == "piece_pendue"]
    if not targets:
        return
    try:
        engine = chess.engine.SimpleEngine.popen_uci(config.STOCKFISH_PATH)
    except Exception as e:
        print(f"  (punition ignorée : Stockfish indisponible — {e})")
        return
    try:
        for b in targets:
            board = chess.Board(b["fen_before"])
            try:
                board.push(board.parse_san(b["move_played"]))
            except Exception:
                continue
            if board.is_game_over():
                continue
            info = engine.analyse(board, chess.engine.Limit(depth=12))
            pv = info.get("pv", []) or []
            if not pv:
                continue
            b["punish_first_uci"] = pv[0].uci()
            sans, tmp = [], board.copy()
            for mv in pv[:6]:
                if mv not in tmp.legal_moves:
                    break
                sans.append(tmp.san(mv))
                tmp.push(mv)
            b["punish_line_san"] = sans
    finally:
        engine.quit()


def fill_clocks(selection: list[dict]) -> None:
    """Reconstitue l'horloge de chaque joueur à la position du blunder, à partir
    des balises [%clk] du PGN (temps restant après chaque demi-coup)."""
    # index game_id -> partie brute
    games = {}
    for f in sorted(config.RAW_DIR.glob("*.json")):
        for g in json.loads(f.read_text()).get("games", []):
            games[game_id_of(g)] = g

    for b in selection:
        g = games.get(b["game_id"])
        if not g or not g.get("pgn"):
            continue
        game = chess.pgn.read_game(io.StringIO(g["pgn"]))
        if game is None:
            continue
        clocks = parse_clocks(game)
        base, _ = parse_time_control(g.get("time_control"))
        ply = b["ply"]
        white, black = base, base
        for i in range(min(ply, len(clocks))):
            if clocks[i] is None:
                continue
            if i % 2 == 0:
                white = clocks[i]
            else:
                black = clocks[i]
        b["white_clock_s"] = white
        b["black_clock_s"] = black
        if b["my_color"] == "blanc":
            b["my_clock_s"], b["opp_clock_s"] = white, black
        else:
            b["my_clock_s"], b["opp_clock_s"] = black, white


def is_useful(b: dict) -> bool:
    if b["severity"] not in ("erreur", "gaffe"):
        return False
    if b["motif"] not in USEFUL_MOTIFS:
        return False
    # Position déjà perdue avant le coup -> peu instructif (sauf mat raté, où on
    # était au contraire gagnant).
    if b["motif"] != "mat_rate" and b["eval_before_cp"] <= -200:
        return False
    if b["move_played_uci"] is None or b["best_move_uci"] is None:
        return False
    return True


def merge_prose(selection: list[dict]) -> None:
    """Conserve la prose déjà rédigée pour les blunders encore présents."""
    if not WEB_JSON.exists():
        return
    old = {x["id"]: x for x in json.loads(WEB_JSON.read_text()).get("blunders", [])}
    for b in selection:
        if b["id"] in old:
            for f in PROSE_FIELDS:
                if old[b["id"]].get(f):
                    b[f] = old[b["id"]][f]


def build_briefing(since_ts: float, focus: list[dict]) -> dict:
    """Faits déterministes du briefing : pour chaque partie nouvelle, les
    métriques de motifs comparées au focus. La prose reste vide (LLM)."""
    from collections import Counter
    games = [json.loads(l) for l in config.GAMES_INDEX.read_text().splitlines() if l.strip()]
    games = [g for g in games if g.get("time_class") == "rapid"]
    all_bl = [json.loads(l) for l in config.BLUNDERS_FILE.read_text().splitlines() if l.strip()]
    by_game = {}
    for b in all_bl:
        by_game.setdefault(b["game_id"], []).append(b)

    new_games = sorted((g for g in games if g.get("timestamp", 0) > since_ts),
                       key=lambda g: g.get("timestamp", 0))

    games_facts = []
    for g in new_games:
        bl = by_game.get(g["game_id"], [])
        errs = [b for b in bl if b["severity"] in ("erreur", "gaffe")]
        counts = Counter(b["motif"] for b in errs)
        focus_check = []
        for f in focus:
            cnt = counts.get(f["motif"], 0)
            focus_check.append({
                "motif": f["motif"], "label": f["label"],
                "ref_rate": f["ref_rate"], "count_this_game": cnt,
                "verdict": "appliqué" if cnt == 0 else "présent",
            })
        games_facts.append({
            "game_id": g["game_id"], "url": g.get("url"), "date": g["date"],
            "result": g["result"], "my_color": g["my_color"], "n_moves": g["n_moves"],
            "motif_counts": dict(counts),
            "gaffes": sum(1 for b in errs if b["severity"] == "gaffe"),
            "impulsive_errors": sum(1 for b in errs if b["impulsive"]),
            "focus_check": focus_check,
        })

    today = new_games[-1]["date"] if new_games else None
    return {
        "date": today,
        "n_new_games": len(new_games),
        "games": games_facts,
        # --- PROSE (remplie par Claude Code) ---
        "applied": "", "to_work": "", "advice_now": "", "continuity": [],
    }


def build_daily(n: int, since_ts: float | None, focus: list[dict]) -> dict:
    """Construit le payload web complet : puzzles en 2 sections + briefing."""
    blunders = [enrich_for_web(b) for b in load_blunders()]
    useful = [b for b in blunders if is_useful(b)]
    useful.sort(key=lambda b: (b["timestamp"], -USEFUL_MOTIFS[b["motif"]], b["cp_loss"]),
                reverse=True)

    if since_ts is None:
        today, recurrent = [], useful[:n]
    else:
        today = [b for b in useful if b["timestamp"] > since_ts][:n]
        today_games = {b["game_id"] for b in today}
        recurrent = [b for b in useful
                     if b["timestamp"] <= since_ts and b["game_id"] not in today_games][:n]

    for b in today:
        b["section"] = "aujourdhui"
    for b in recurrent:
        b["section"] = "recurrent"
    selection = today + recurrent

    fill_punishment(selection)
    fill_clocks(selection)
    merge_prose(selection)

    sections = [
        {"id": "aujourdhui", "label": "Aujourd'hui", "count": len(today)},
        {"id": "recurrent", "label": "Faiblesses récurrentes", "count": len(recurrent)},
    ]
    return {
        "generated_for": config.USERNAME,
        "sections": sections,
        "blunders": selection,
        "briefing": build_briefing(since_ts, focus) if since_ts is not None else None,
        "needs_prose": [b["id"] for b in selection
                        if not all(b.get(f) for f in ("why_blunder", "why_better"))],
    }


def write_payload(payload: dict) -> None:
    WEB_JSON.parent.mkdir(exist_ok=True)
    WEB_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2))


def main():
    """Mode autonome (sans sections) : tout en 'récurrent'."""
    import coach_state
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=20)
    args = ap.parse_args()
    focus = coach_state.load().get("focus", [])
    payload = build_daily(args.n, since_ts=None, focus=focus)
    write_payload(payload)
    print(f"{len(payload['blunders'])} blunders -> {WEB_JSON}")
    print(f"Prose manquante : {len(payload['needs_prose'])}")


if __name__ == "__main__":
    main()

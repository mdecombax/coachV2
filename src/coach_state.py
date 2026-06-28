"""Mémoire du coaching : data/coaching_state.json.

C'est ce qui rend possible la continuité ("as-tu appliqué le conseil ?").
Contenu :
  - last_game_end : horodatage de la dernière partie traitée (détecte le neuf)
  - focus         : priorités actives (motif, libellé, taux de référence, statut)
  - history       : journal des bilans quotidiens

Module : load / save / bootstrap / helpers de métriques.
"""
import json
import datetime as dt
from collections import Counter, defaultdict

import config

STATE_FILE = config.DATA_DIR / "coaching_state.json"

# Libellés lisibles des motifs suivis comme focus.
MOTIF_LABEL = {
    "piece_pendue": "Ne pas pendre de pièces",
    "mat_rate": "Finir les attaques (voir les mats)",
    "mat_permis": "Protéger ton roi (ne pas permettre de mat)",
    "gain_manque": "Saisir les gains de matériel",
}
# Motifs qu'on accepte comme focus (instructifs / actionnables).
FOCUS_MOTIFS = list(MOTIF_LABEL)


# ---------------------------------------------------------------------------
# Lecture des données analysées
# ---------------------------------------------------------------------------
def _load_jsonl(path):
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def load_games_and_blunders(time_class="rapid"):
    games = _load_jsonl(config.GAMES_INDEX)
    blunders = _load_jsonl(config.BLUNDERS_FILE)
    if time_class:
        games = [g for g in games if g.get("time_class") == time_class]
        gids = {g["game_id"] for g in games}
        blunders = [b for b in blunders if b["game_id"] in gids]
    games.sort(key=lambda g: g.get("timestamp", 0))
    return games, blunders


def motif_rates(games, blunders, n_recent=50):
    """Taux (erreur+gaffe) par motif sur les n dernières parties."""
    recent = games[-n_recent:]
    gids = {g["game_id"] for g in recent}
    n = len(recent) or 1
    c = Counter()
    for b in blunders:
        if b["game_id"] in gids and b["severity"] in ("erreur", "gaffe"):
            c[b["motif"]] += 1
    return {m: round(v / n, 3) for m, v in c.items()}, n


# ---------------------------------------------------------------------------
# État
# ---------------------------------------------------------------------------
def default_state():
    return {"last_game_end": 0, "focus": [], "history": []}


def load():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return default_state()


def save(state):
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2))


def compute_focus(n_recent=50, top=3):
    """Dérive les focus prioritaires des données récentes."""
    games, blunders = load_games_and_blunders()
    rates, _ = motif_rates(games, blunders, n_recent)
    ranked = sorted(
        ((m, r) for m, r in rates.items() if m in FOCUS_MOTIFS and r > 0),
        key=lambda x: -x[1],
    )[:top]
    return [
        {"motif": m, "label": MOTIF_LABEL[m], "ref_rate": r, "status": "actif"}
        for m, r in ranked
    ]


def bootstrap():
    """Crée l'état initial. last_game_end est calé pour que les parties du
    DERNIER jour joué comptent comme 'nouvelles' au premier run."""
    games, _ = load_games_and_blunders()
    if not games:
        save(default_state())
        return load()
    last_date = games[-1]["date"]
    # dernière partie d'AVANT le dernier jour -> les parties du dernier jour sont neuves
    prior = [g for g in games if g["date"] < last_date]
    last_game_end = prior[-1]["timestamp"] if prior else 0
    state = {
        "last_game_end": last_game_end,
        "focus": compute_focus(),
        "history": [],
    }
    save(state)
    return state


if __name__ == "__main__":
    st = bootstrap()
    print(f"État initialisé -> {STATE_FILE}")
    print(f"last_game_end : {st['last_game_end']} "
          f"({dt.datetime.fromtimestamp(st['last_game_end'], dt.UTC):%Y-%m-%d %H:%M} UTC)"
          if st["last_game_end"] else "last_game_end : 0")
    print("Focus :")
    for f in st["focus"]:
        print(f"  - {f['motif']:14} ref={f['ref_rate']:.2f}/partie  «{f['label']}»")

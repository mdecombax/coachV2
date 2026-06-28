# coachV2 — Coach d'échecs assisté IA (sans API LLM)

Coach personnel basé sur l'historique chess.com de **mdecombax**.
Contrainte centrale : **aucun appel LLM par API**. La partie « intelligence du
langage » est faite par **Claude Code** (manuellement ou via une routine
planifiée). Tout le reste est déterministe (Stockfish + calcul).

## Architecture

```
COUCHE DÉTERMINISTE (aucun LLM)
  src/fetch.py          API chess.com -> data/raw/*.json
  src/analyze.py        Stockfish 18 par coup -> data/blunders.jsonl
                        (détecte + enrichit chaque blunder : motif, pièce pendue,
                         temps de réflexion incrément compris, bascule de partie...)
  src/select_review.py  20 blunders les plus utiles -> web/blunders.json
  src/report.py         rapport temporel -> reports/rapport.md + coaching.json

COUCHE LLM (Claude Code, quotidienne — voir prompts/daily_coach.md)
  remplit la prose (why_blunder / why_better / coach_tip) dans web/blunders.json

INTERFACE
  web/index.html        échiquier : rejoue la position, flèches + stats du blunder
```

## Installation

```bash
python3 -m venv .venv
./.venv/bin/pip install chess requests
# Stockfish requis : brew install stockfish
```

## Utilisation

**Pipeline déterministe (une commande) :**
```bash
./.venv/bin/python src/coach.py --depth 12 --n 20
```

**Couche LLM (Claude Code) :** ouvrir Claude Code dans le projet et suivre
`prompts/daily_coach.md` (remplit la prose des nouveaux blunders).

**Page de révision :**
```bash
cd web && ../.venv/bin/python -m http.server 8777
# puis http://localhost:8777
```
- Flèche **rouge** = coup joué, **verte** = meilleur coup.
- « Révéler » dévoile temps de réflexion, pourquoi c'est un blunder, meilleur
  coup + pourquoi, et une règle à retenir.
- ←/→ pour naviguer, espace pour révéler.

**Rapport de progression :**
```bash
./.venv/bin/python src/report.py --time-class rapid --recent 50
```

## Notes de conception
- **Dimension temporelle** : une faiblesse n'est « actuelle » que si elle persiste
  sur la fenêtre récente (cf. `report.py`). On ne moyenne jamais l'historique à plat.
- **Temps par coup** : l'incrément (ex. 15+10 = `900+10`) est pris en compte.
- **Cache** : `data/analysis/<id>.json` par partie -> les relances ne réanalysent
  que les nouvelles parties.
- Tout est **hors-ligne** : chess.js et les pièces sont vendorisés dans `web/`.
```

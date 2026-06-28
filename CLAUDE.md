# coachV2 — instructions projet

Coach d'échecs perso (pseudo chess.com **mdecombax**). Page en ligne :
https://mdecombax.github.io/coachV2/ — servie par GitHub Pages depuis `web/`.

## Le run quotidien
Quand l'utilisateur dit **« run le run quotidien »** (ou tape **/run-quotidien**),
exécute la routine `.claude/commands/run-quotidien.md` de bout en bout :
`src/daily.py` (déterministe) → tu écris la prose du briefing + continuité +
puzzles → tu mets à jour `data/coaching_state.json` → `git push` (redéploie Pages).

Pas de `claude -p` headless, pas de launchd : le run se fait **en interactif**,
c'est toi (Claude Code) qui fais la partie LLM, sans API.

## Repères
- Déterministe (0 LLM) : `src/fetch.py`, `analyze.py`, `select_review.py`,
  `daily.py`, `coach_state.py`, `report.py`, `time_analysis.py`.
- venv : `./.venv` · Stockfish local : `/opt/homebrew/bin/stockfish`
  (surchargeable par `STOCKFISH_PATH`).
- Mémoire du coaching : `data/coaching_state.json` (focus + history + last_game_end).
- Architecture détaillée : `README.md`.

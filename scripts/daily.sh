#!/usr/bin/env bash
# Run quotidien LOCAL (Mac) : déterministe -> LLM (Claude Code) -> push GitHub.
# Pages se redéploie tout seul à la réception du push.
set -uo pipefail

cd "$(dirname "$0")/.." || exit 1
ROOT="$(pwd)"
LOG="reports/daily_$(date +%F).log"
mkdir -p reports
exec > >(tee -a "$LOG") 2>&1

echo "===== Run quotidien $(date) ====="

# 1) Déterministe : fetch + analyse + sélection + faits (Stockfish local)
./.venv/bin/python src/daily.py --depth 12 --n 20 || { echo "daily.py KO"; exit 1; }

# Rien de neuf ? on s'arrête (évite un commit vide).
if git diff --quiet -- web/blunders.json data/coaching_state.json data/blunders.jsonl; then
  echo "Aucune nouvelle partie / aucun changement. Fin."
  exit 0
fi

# 2) LLM : Claude Code (local, sans API) remplit la prose + met à jour la mémoire.
#    Nécessite le CLI `claude` connecté. Si absent, on pousse quand même les faits.
if command -v claude >/dev/null 2>&1; then
  echo "--- Étape LLM (claude -p) ---"
  claude -p "Exécute les étapes 2 et 3 de la routine prompts/daily_coach.md : \
remplis la prose du briefing (applied, to_work, advice_now), la continuité coup \
par coup des parties du jour (en lisant data/analysis/<game_id>.json), la prose \
des puzzles manquants (needs_prose), puis mets à jour data/coaching_state.json. \
Le pipeline déterministe a déjà tourné. Ne touche pas au reste." \
    --permission-mode acceptEdits \
    --allowedTools "Read" "Edit" "Write" "Bash" \
    || echo "Étape LLM ignorée (claude indisponible ou en échec) — on pousse les faits."
else
  echo "CLI claude absent : on pousse les faits sans prose LLM."
fi

# 3) Commit + push -> déclenche le déploiement Pages
git add -A
git commit -m "daily: maj coach $(date +%F)" || { echo "rien à committer"; exit 0; }
git pull --rebase --autostash origin main || true
git push origin main && echo "Poussé. Pages va se redéployer."

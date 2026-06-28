import { Chess } from "./vendor/chess.js";

// --- État ---
let data = null;
let idx = 0;
let view = [];            // puzzles de la section courante
let currentSection = null;
let game = null;          // position en cours (exploration)
let orientationWhite = true;
let selected = null;      // case sélectionnée (exploration)
let revealed = false;
let line = [];            // coups de la variante moteur (SAN)
let linePos = 0;          // nb de coups de la ligne déjà joués
let solution = [];        // variante à résoudre (SAN) en mode puzzle
let solveProgress = 0;    // nb de coups de la solution déjà joués correctement
let busy = false;         // vrai pendant la réponse différée de l'ordinateur
const REPLY_DELAY_MS = 450;

const $ = (id) => document.getElementById(id);
const boardEl = $("board");
const arrowsEl = $("arrows");

const PIECE_SRC = (p) => `pieces/${p.color}${p.type.toUpperCase()}.svg`;

// ---------------------------------------------------------------------------
// Chargement
// ---------------------------------------------------------------------------
async function load() {
  const res = await fetch("blunders.json", { cache: "no-store" });
  data = await res.json();
  $("pseudo").textContent = data.generated_for || "";
  renderBriefing();
  renderTabs();
  if (!data.blunders.length) {
    boardEl.innerHTML = "<p style='color:#fff;padding:20px'>Aucun blunder. Lance le pipeline.</p>";
    return;
  }
  // section initiale : "aujourdhui" si elle a des puzzles, sinon "recurrent"
  const sections = data.sections || [{ id: null, label: "" }];
  const firstWithPuzzles = sections.find((s) => buildView(s.id).length) || sections[0];
  setSection(firstWithPuzzles.id);
}

// ---------------------------------------------------------------------------
// Sections / onglets
// ---------------------------------------------------------------------------
function buildView(sectionId) {
  if (sectionId == null) return data.blunders;
  return data.blunders.filter((b) => b.section === sectionId);
}

function setSection(sectionId) {
  currentSection = sectionId;
  view = buildView(sectionId);
  document.querySelectorAll("#tabs .tab").forEach((t) =>
    t.classList.toggle("active", t.dataset.section === String(sectionId)));
  if (view.length) show(0);
}

function renderTabs() {
  const tabs = $("tabs");
  const sections = data.sections || [];
  if (sections.length <= 1) { tabs.classList.add("hidden"); return; }
  tabs.classList.remove("hidden");
  tabs.innerHTML = "";
  for (const s of sections) {
    const el = document.createElement("button");
    el.className = "tab";
    el.dataset.section = String(s.id);
    el.innerHTML = `${s.label}<span class="badge">${s.count}</span>`;
    el.addEventListener("click", () => setSection(s.id));
    tabs.appendChild(el);
  }
}

// ---------------------------------------------------------------------------
// Briefing du jour
// ---------------------------------------------------------------------------
function renderBriefing() {
  const br = data.briefing;
  const sec = $("briefing");
  if (!br || !br.n_new_games) { sec.classList.add("hidden"); return; }
  sec.classList.remove("hidden");
  $("briefing-date").textContent = br.date ? `— ${br.date} (${br.n_new_games} partie(s))` : "";

  // Replis déterministes si la prose LLM n'est pas encore écrite.
  const appliedFallback = focusVerdicts(br, "appliqué")
    .map((f) => f.label).join(" · ") || "—";
  const toworkFallback = focusVerdicts(br, "présent")
    .map((f) => `${f.label} (${f.count_this_game}×)`).join(" · ") || "—";

  setText("t-applied", br.applied, appliedFallback);
  setText("t-towork", br.to_work, toworkFallback);
  setText("t-advice", br.advice_now,
    "Conseil à générer par Claude Code (routine /daily).");

  // Continuité par partie
  const cont = $("b-continuity");
  cont.innerHTML = "";
  const proseByGame = {};
  for (const c of br.continuity || []) proseByGame[c.game_id] = c.text;
  for (const g of br.games || []) {
    const div = document.createElement("div");
    div.className = "cont-game";
    const chk = (g.focus_check || []).map((c) => {
      const ok = c.verdict === "appliqué";
      return `<b class="${ok ? "ok" : "no"}">${ok ? "✓" : "✗"} ${c.label}`
        + (ok ? "" : ` (${c.count_this_game}×)`) + "</b>";
    }).join(" &nbsp; ");
    const prose = proseByGame[g.game_id];
    div.innerHTML = `<div class="head">Partie du ${g.date} — ${g.result} (${g.my_color})</div>`
      + `<div class="chk">${chk}</div>`
      + (prose ? `<p style="margin:8px 0 0">${prose}</p>` : "");
    cont.appendChild(div);
  }
}

function focusVerdicts(br, verdict) {
  // agrège les focus_check de toutes les nouvelles parties par verdict
  const seen = {};
  for (const g of br.games || []) {
    for (const c of g.focus_check || []) {
      if (c.verdict === verdict) {
        seen[c.motif] = seen[c.motif] || { label: c.label, count_this_game: 0 };
        seen[c.motif].count_this_game += c.count_this_game;
      }
    }
  }
  return Object.values(seen);
}

function setText(id, prose, fallback) {
  const el = $(id);
  el.textContent = prose || fallback;
  el.classList.toggle("pending", !prose);
}

// ---------------------------------------------------------------------------
// Géométrie cases <-> coordonnées
// ---------------------------------------------------------------------------
function fileRank(square) {
  return { f: square.charCodeAt(0) - 97, r: parseInt(square[1], 10) - 1 };
}
// centre d'une case dans le repère SVG 8x8 (selon l'orientation)
function squareCenter(square) {
  const { f, r } = fileRank(square);
  const x = orientationWhite ? f + 0.5 : 7 - f + 0.5;
  const y = orientationWhite ? 7 - r + 0.5 : r + 0.5;
  return { x, y };
}

// ---------------------------------------------------------------------------
// Rendu de l'échiquier
// ---------------------------------------------------------------------------
function render() {
  boardEl.innerHTML = "";
  const board = game.board(); // rangée 8 en premier
  const ranks = orientationWhite ? [...Array(8).keys()] : [...Array(8).keys()].reverse();
  const files = orientationWhite ? [...Array(8).keys()] : [...Array(8).keys()].reverse();

  for (const rIdx of ranks) {
    for (const fIdx of files) {
      const piece = board[rIdx][fIdx];
      const file = "abcdefgh"[fIdx];
      const rank = 8 - rIdx;
      const square = `${file}${rank}`;
      const isLight = (fIdx + rIdx) % 2 === 0;

      const sq = document.createElement("div");
      sq.className = `sq ${isLight ? "light" : "dark"}`;
      sq.dataset.square = square;

      if (selected === square) sq.classList.add("sel");

      if (piece) {
        const img = document.createElement("img");
        img.src = PIECE_SRC(piece);
        img.draggable = false;
        sq.appendChild(img);
      }
      // coordonnées sur les bords
      if ((orientationWhite && fIdx === 0) || (!orientationWhite && fIdx === 7)) {
        const c = document.createElement("span");
        c.className = "coord rank";
        c.textContent = rank;
        sq.appendChild(c);
      }
      if ((orientationWhite && rIdx === 7) || (!orientationWhite && rIdx === 0)) {
        const c = document.createElement("span");
        c.className = "coord file";
        c.textContent = file;
        sq.appendChild(c);
      }
      sq.addEventListener("click", () => onSquareClick(square));
      boardEl.appendChild(sq);
    }
  }
  // pastilles de coups légaux
  if (selected) {
    for (const m of game.moves({ square: selected, verbose: true })) {
      const t = boardEl.querySelector(`[data-square="${m.to}"]`);
      if (t) t.classList.add("target");
    }
  }
  updateCheckState();
}

function findKingSquare(color) {
  const b = game.board();
  for (let r = 0; r < 8; r++) {
    for (let f = 0; f < 8; f++) {
      const p = b[r][f];
      if (p && p.type === "k" && p.color === color) {
        return "abcdefgh"[f] + (8 - r);
      }
    }
  }
  return null;
}

// Surligne le roi en échec/mat et affiche la bannière de mat.
function updateCheckState() {
  const banner = $("mate-banner");
  const mate = game.isCheckmate();
  const check = game.isCheck();
  if (mate || check) {
    const kingSq = findKingSquare(game.turn());
    const el = kingSq && boardEl.querySelector(`[data-square="${kingSq}"]`);
    if (el) el.classList.add(mate ? "mate" : "check");
  }
  banner.classList.toggle("hidden", !mate);
}

// ---------------------------------------------------------------------------
// Mode puzzle : tu joues le meilleur coup, l'ordinateur réplique, et ainsi de
// suite jusqu'à dérouler toute la variante (problème résolu).
// ---------------------------------------------------------------------------
const normSan = (s) => (s || "").replace(/[+#!?]/g, "");

function feedback(text, cls) {
  const fb = $("explore-feedback");
  fb.textContent = text;
  fb.className = cls || "";
}

function onSquareClick(square) {
  if (revealed || busy) return;
  const piece = game.get(square);

  if (selected) {
    const legal = game.moves({ square: selected, verbose: true }).find((m) => m.to === square);
    if (legal) {
      tryUserMove(selected, square);
      return;
    }
  }
  // (re)sélection d'une pièce au trait
  selected = piece && piece.color === game.turn() ? square : null;
  render();
}

function tryUserMove(from, to) {
  const expected = solution[solveProgress];
  if (expected === undefined) return;
  const mv = game.move({ from, to, promotion: "q" });
  if (!mv) return;

  // mauvais coup -> on annule et on laisse réessayer
  if (normSan(mv.san) !== normSan(expected)) {
    game.undo();
    selected = null;
    feedback("✗ Pas le meilleur coup. Réessaie.", "no");
    render();
    return;
  }

  // bon coup : on l'affiche d'abord
  solveProgress++;
  selected = null;
  clearArrows();
  drawArrow(mv.from + mv.to, CSS.getPropertyValue("--best").trim());
  render();

  if (solveProgress >= solution.length) {
    onSolved();
    return;
  }

  // ... puis l'ordinateur répond après un court délai
  feedback("✓ Bien vu ! L'ordinateur réfléchit…", "ok");
  busy = true;
  setTimeout(() => {
    // garde-fou : si on a changé de blunder entre-temps, on abandonne
    if (!busy) return;
    const reply = game.move(solution[solveProgress]);
    solveProgress++;
    if (reply) drawArrow(reply.from + reply.to, CSS.getPropertyValue("--played").trim());
    render();
    busy = false;
    if (solveProgress >= solution.length) {
      onSolved();
    } else {
      feedback(`✓ Bien vu ! L'ordinateur répond ${reply ? reply.san : ""}. À toi.`, "ok");
    }
  }, REPLY_DELAY_MS);
}

function onSolved() {
  revealed = true;
  const b = view[idx];
  feedback("✓ Problème résolu ! Bravo.", "ok");
  revealCards(b);
  // bascule en mode revue de variante, positionné à la fin
  line = solution.slice();
  linePos = solution.length;
  $("line-controls").classList.remove("hidden");
  $("hint").textContent = "Résolu. Utilise ◀ / ▶ pour revoir la variante.";
  renderLinePos();
  $("reveal").disabled = true;
}

// ---------------------------------------------------------------------------
// Flèches
// ---------------------------------------------------------------------------
function clearArrows() { arrowsEl.innerHTML = ""; }

function drawArrow(uci, color) {
  if (!uci || uci.length < 4) return;
  const from = squareCenter(uci.slice(0, 2));
  const to = squareCenter(uci.slice(2, 4));
  const dx = to.x - from.x, dy = to.y - from.y;
  const len = Math.hypot(dx, dy);
  const ux = dx / len, uy = dy / len;
  const head = 0.34;            // taille de la pointe
  const shorten = 0.42;         // on raccourcit pour ne pas couvrir la pièce
  const ex = to.x - ux * shorten;
  const ey = to.y - uy * shorten;
  const sx = from.x + ux * 0.28;
  const sy = from.y + uy * 0.28;

  const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
  line.setAttribute("x1", sx); line.setAttribute("y1", sy);
  line.setAttribute("x2", ex); line.setAttribute("y2", ey);
  line.setAttribute("stroke", color);
  line.setAttribute("stroke-width", "0.16");
  line.setAttribute("stroke-linecap", "round");
  line.setAttribute("opacity", "0.9");
  arrowsEl.appendChild(line);

  // pointe (triangle)
  const px = ex + ux * head, py = ey + uy * head;
  const perpx = -uy, perpy = ux;
  const w = 0.17;
  const p1 = `${px},${py}`;
  const p2 = `${ex + perpx * w},${ey + perpy * w}`;
  const p3 = `${ex - perpx * w},${ey - perpy * w}`;
  const tri = document.createElementNS("http://www.w3.org/2000/svg", "polygon");
  tri.setAttribute("points", `${p1} ${p2} ${p3}`);
  tri.setAttribute("fill", color);
  tri.setAttribute("opacity", "0.9");
  arrowsEl.appendChild(tri);
}

// ---------------------------------------------------------------------------
// Révélation des stats
// ---------------------------------------------------------------------------
const CSS = getComputedStyle(document.documentElement);

// Affiche les cartes pédagogiques (prose).
function revealCards(b) {
  $("card-why").classList.remove("hidden");
  $("card-better").classList.remove("hidden");
  setProse("why-blunder", b.why_blunder, `Tu joues ${b.move_played}. ${motifSentence(b)}`);
  $("best-badge").textContent = b.best_move;
  const pv = (b.best_line_san || []).join(" ");
  $("best-line").textContent = pv ? `Ligne moteur : ${pv}` : "";
  setProse("why-better", b.why_better, "");
  if (b.coach_tip) {
    $("card-tip").classList.remove("hidden");
    $("coach-tip").textContent = b.coach_tip;
  }

  // Carte "punition" : seulement pour les pièces pendues avec une ligne calculée.
  const punish = b.punish_line_san || [];
  if (b.motif === "piece_pendue" && punish.length) {
    $("card-punish").classList.remove("hidden");
    const art = ["dame", "tour"].includes(b.piece_hung) ? "ta" : "ton";
    const piece = b.piece_hung ? ` et gagne ${art} <b>${b.piece_hung}</b>` : "";
    $("punish-line").innerHTML =
      `Après ton <b>${b.move_played}</b>, l'adversaire enchaîne `
      + `<b>${punish.join(" ")}</b>${piece}.`;
  } else {
    $("card-punish").classList.add("hidden");
  }
}

// Anime la punition : ton coup, puis la suite gagnante de l'adversaire.
function playPunishment() {
  const b = view[idx];
  const seq = [b.move_played, ...(b.punish_line_san || [])];
  busy = true;
  game = new Chess(b.fen_before);
  selected = null;
  clearArrows();
  render();
  feedback("Démonstration : regarde la pièce tomber…", "no");
  const RED = CSS.getPropertyValue("--played").trim();
  let i = 0;
  const step = () => {
    if (i >= seq.length) {
      busy = false;
      feedback("Voilà comment la pièce tombait. ↺ Replacer pour réessayer.", "no");
      return;
    }
    const mv = game.move(seq[i]);
    clearArrows();
    if (mv) drawArrow(mv.from + mv.to, RED);
    render();
    i++;
    setTimeout(step, 750);
  };
  setTimeout(step, 250);
}

// Révélation manuelle (bouton "Révéler") : montre la solution sans la résoudre.
function reveal() {
  if (revealed) return;
  revealed = true;
  const b = view[idx];

  game = new Chess(b.fen_before);
  selected = null;
  render();
  clearArrows();
  drawArrow(b.move_played_uci, CSS.getPropertyValue("--played").trim());
  drawArrow(b.best_move_uci, CSS.getPropertyValue("--best").trim());

  revealCards(b);
  $("reveal").disabled = true;

  // Prépare la lecture de la variante moteur au clavier / boutons.
  line = (b.best_line_san || []).slice();
  linePos = 0;
  $("line-controls").classList.remove("hidden");
  $("hint").textContent = line.length
    ? "Utilise ◀ / ▶ (ou les flèches du clavier) pour dérouler la ligne du moteur."
    : "Pas de variante à dérouler pour ce coup.";
  renderLinePos();
}

// ---------------------------------------------------------------------------
// Lecture de la variante moteur, coup par coup
// ---------------------------------------------------------------------------
function rebuildToLinePos() {
  const b = view[idx];
  game = new Chess(b.fen_before);
  let last = null;
  for (let k = 0; k < linePos; k++) {
    last = game.move(line[k]);
  }
  clearArrows();
  if (linePos === 0) {
    // position de départ : on remontre coup joué (rouge) + meilleur (vert)
    drawArrow(b.move_played_uci, CSS.getPropertyValue("--played").trim());
    drawArrow(b.best_move_uci, CSS.getPropertyValue("--best").trim());
  } else if (last) {
    drawArrow(last.from + last.to, CSS.getPropertyValue("--best").trim());
  }
  render();
}

function renderLinePos() {
  const el = $("line-pos");
  $("line-back").disabled = linePos === 0;
  $("line-fwd").disabled = linePos >= line.length;
  if (linePos === 0) {
    el.textContent = "Position de départ";
  } else {
    el.innerHTML = `Coup ${linePos}/${line.length} : <b>${line[linePos - 1]}</b>`;
  }
}

function lineForward() {
  if (!revealed || linePos >= line.length) return;
  // valider le coup avant d'avancer le compteur
  const test = new Chess(view[idx].fen_before);
  for (let k = 0; k < linePos; k++) test.move(line[k]);
  if (!test.move(line[linePos])) return; // coup illégal -> on s'arrête
  linePos++;
  rebuildToLinePos();
  renderLinePos();
}

function lineBack() {
  if (!revealed || linePos === 0) return;
  linePos--;
  rebuildToLinePos();
  renderLinePos();
}

// Prose LLM si dispo, sinon repli factuel (généré par le moteur).
function setProse(elId, prose, fallback) {
  const el = $(elId);
  if (prose) {
    el.textContent = prose;
    el.classList.remove("pending");
  } else {
    el.textContent = fallback || "(explication pédagogique à générer par Claude Code)";
    el.classList.add("pending");
  }
}

function motifSentence(b) {
  const swing = b.material_swing;
  switch (b.motif) {
    case "piece_pendue":
      return `Ce coup laisse en prise ${b.piece_hung ? "ton " + b.piece_hung : "du matériel"} `
        + `(perte d'environ ${Math.abs(swing)} points).`;
    case "gain_manque":
      return `Tu laisses filer un gain de matériel qui était disponible.`;
    case "mat_rate":
      return `Tu avais un mat forcé (en ${b.missed_mate_in}) et tu l'as manqué.`;
    case "mat_permis":
      return `Ce coup permet à l'adversaire un mat forcé (en ${b.allowed_mate_in}).`;
    default:
      return `Perte de ${b.cp_loss} centipions par rapport au meilleur coup.`;
  }
}

// ---------------------------------------------------------------------------
// Affichage d'un blunder
// ---------------------------------------------------------------------------
function show(i) {
  idx = (i + view.length) % view.length;
  const b = view[idx];
  revealed = false;
  selected = null;
  orientationWhite = b.my_color === "blanc";
  game = new Chess(b.fen_before);

  $("counter").textContent = `${idx + 1}/${view.length}`;
  clearArrows();
  render();

  // tags méta
  const sevClass = b.severity === "gaffe" ? "gaffe" : "erreur";
  $("meta-tags").innerHTML = [
    `<span class="tag ${sevClass}">${b.severity}</span>`,
    `<span class="tag motif">${b.motif.replace(/_/g, " ")}</span>`,
    `<span class="tag">${b.phase}</span>`,
    `<span class="tag">${b.date}</span>`,
    `<span class="tag">${b.my_color}</span>`,
  ].join("");

  $("to-move").textContent = `Trait aux ${b.side_to_move === "w" ? "Blancs" : "Noirs"} — coup ${b.move_number}`;
  $("explore-feedback").textContent = "";
  $("explore-feedback").className = "";

  // horloges des deux joueurs à la position du blunder (adv en haut, toi en bas)
  const me = $("clk-me");
  const opp = $("clk-opp");
  me.innerHTML = `<span class="label">Toi</span><span class="time">${fmtClock(b.my_clock_s)}</span>`;
  opp.innerHTML = `<span class="label">Adversaire</span><span class="time">${fmtClock(b.opp_clock_s)}</span>`;
  me.className = "clock turn" + (isLowTime(b.my_clock_s) ? " low" : "");
  opp.className = "clock" + (isLowTime(b.opp_clock_s) ? " low" : "");

  // carte "ce que tu as joué"
  $("played-line").innerHTML = `Tu as joué <b>${b.move_played}</b> `
    + `(éval ${fmtEval(b.eval_before_cp)} → ${fmtEval(b.eval_after_cp)}).`;
  const t = b.time_spent_s;
  $("time-line").textContent = t == null
    ? "Temps de réflexion : inconnu."
    : `Temps de réflexion sur ce coup : ${t}s${b.impulsive ? " — impulsif (<5s)" : ""}.`;

  // reset cartes prose
  for (const id of ["card-why", "card-better", "card-tip", "card-punish"]) $(id).classList.add("hidden");
  $("reveal").disabled = false;
  $("game-link").innerHTML = b.url ? `Partie complète : <a href="${b.url}" target="_blank">chess.com ↗</a>` : "";

  // reset lecture de variante + puzzle
  line = [];
  linePos = 0;
  solution = (b.best_line_san || []).slice();
  solveProgress = 0;
  busy = false;
  $("line-controls").classList.add("hidden");
  $("hint").textContent = "À toi de jouer : trouve le meilleur coup. Bon coup → l'ordinateur répond, et tu continues jusqu'à résoudre.";
}

function fmtEval(cp) {
  if (cp >= 9000) return "#";
  if (cp <= -9000) return "#-";
  const v = (cp / 100).toFixed(1);
  return cp > 0 ? `+${v}` : v;
}

function fmtClock(s) {
  if (s == null) return "—";
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return `${m}:${String(sec).padStart(2, "0")}`;
}
const isLowTime = (s) => s != null && s < 60;

// ---------------------------------------------------------------------------
// Contrôles
// ---------------------------------------------------------------------------
$("prev").addEventListener("click", () => show(idx - 1));
$("next").addEventListener("click", () => show(idx + 1));
$("reset").addEventListener("click", () => show(idx));
$("reveal").addEventListener("click", reveal);
$("line-fwd").addEventListener("click", lineForward);
$("line-back").addEventListener("click", lineBack);
$("punish-play").addEventListener("click", playPunishment);
document.addEventListener("keydown", (e) => {
  if (e.key === " ") { e.preventDefault(); reveal(); return; }
  if (revealed) {
    // après révélation : les flèches déroulent la variante moteur
    if (e.key === "ArrowRight") { e.preventDefault(); lineForward(); }
    if (e.key === "ArrowLeft") { e.preventDefault(); lineBack(); }
  } else {
    // avant : les flèches changent de blunder
    if (e.key === "ArrowLeft") show(idx - 1);
    if (e.key === "ArrowRight") show(idx + 1);
  }
});

load();

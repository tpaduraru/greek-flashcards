/* Koine — frontend logic (vanilla JS, no build step). */
"use strict";

const $  = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

const api = async (path, opts = {}) => {
  const res = await fetch(path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  let data = {};
  try { data = await res.json(); } catch (_) { /* no body */ }
  if (!res.ok) throw new Error(data.error || "Something went wrong.");
  return data;
};

/* ---------------- app state ---------------- */
const state = {
  authMode: "login",
  selected: new Set(),     // slugs currently checked in the menu
  activeSlugs: [],         // slugs of the session in progress
  session: null,           // { deck, queue, current, size, completed }
  flipped: false,
};

/* ============================================================
   AUTH
   ============================================================ */
function showAuth() {
  $("#app").hidden = true;
  $("#auth").hidden = false;
  $("#f-username").focus();
}
function showApp(username) {
  $("#auth").hidden = true;
  $("#app").hidden = false;
  $("#drawer-user").textContent = username ? `Signed in as ${username}` : "";
  loadDecks();
}

function setAuthMode(mode) {
  state.authMode = mode;
  $$(".tab").forEach(t => t.classList.toggle("is-active", t.dataset.tab === mode));
  $("#auth-submit").textContent = mode === "login" ? "Sign in" : "Create account";
  $("#f-password").setAttribute("autocomplete",
    mode === "login" ? "current-password" : "new-password");
  const err = $("#auth-error"); err.hidden = true; err.textContent = "";
}

$$(".tab").forEach(t => t.addEventListener("click", () => setAuthMode(t.dataset.tab)));

$("#auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("#f-username").value.trim();
  const password = $("#f-password").value;
  const err = $("#auth-error");
  const btn = $("#auth-submit");
  btn.disabled = true;
  try {
    const path = state.authMode === "login" ? "/api/login" : "/api/register";
    const data = await api(path, { method: "POST", body: JSON.stringify({ username, password }) });
    err.hidden = true;
    showApp(data.username);
  } catch (ex) {
    err.textContent = ex.message;
    err.hidden = false;
  } finally {
    btn.disabled = false;
  }
});

$("#signout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" });
  location.reload();
});

/* ============================================================
   DRAWER
   ============================================================ */
function openDrawer() {
  $("#drawer").hidden = false; $("#scrim").hidden = false;
  requestAnimationFrame(() => {
    $("#drawer").classList.add("is-open");
    $("#scrim").classList.add("is-open");
  });
  $("#menu-btn").setAttribute("aria-expanded", "true");
}
function closeDrawer() {
  $("#drawer").classList.remove("is-open");
  $("#scrim").classList.remove("is-open");
  $("#menu-btn").setAttribute("aria-expanded", "false");
  setTimeout(() => { $("#drawer").hidden = true; $("#scrim").hidden = true; }, 300);
}
function toggleDrawer() {
  $("#menu-btn").getAttribute("aria-expanded") === "true" ? closeDrawer() : openDrawer();
}
$("#menu-btn").addEventListener("click", toggleDrawer);
$("#scrim").addEventListener("click", closeDrawer);
$("#welcome-open").addEventListener("click", openDrawer);
$("#menu-return").addEventListener("click", () => { showWelcome(); openDrawer(); });

/* ============================================================
   DECK MENU
   ============================================================ */
async function loadDecks() {
  const { groups } = await api("/api/decks");
  const menu = $("#menu");
  menu.innerHTML = "";
  for (const group of groups) {
    const slugsInGroup = group.decks.map(d => d.slug);
    const g = document.createElement("div");
    g.className = "menu-group";

    const label = document.createElement("button");
    label.className = "menu-group-label";
    label.type = "button";
    label.textContent = group.name;
    label.title = "Select or clear this whole group";
    label.addEventListener("click", () => {
      const allOn = slugsInGroup.every(s => state.selected.has(s));
      slugsInGroup.forEach(s => allOn ? state.selected.delete(s) : state.selected.add(s));
      loadDecks();
    });
    g.appendChild(label);

    for (const deck of group.decks) {
      const done = deck.total > 0 && deck.learned >= deck.total;
      const some = deck.learned > 0 && !done;
      const dotCls = done ? "done" : some ? "some" : "";
      const dueLine = deck.due > 0
        ? `<span class="due">${deck.due} due</span>`
        : `${deck.learned}/${deck.total}`;
      const checked = state.selected.has(deck.slug);
      const row = document.createElement("label");
      row.className = "deck-row" + (checked ? " is-selected" : "");
      row.innerHTML = `
        <input type="checkbox" class="deck-check" ${checked ? "checked" : ""}>
        <span class="deck-dot ${dotCls}"></span>
        <span class="deck-meta">
          <span class="deck-name">${deck.name}</span>
          <span class="deck-sub">${deck.subtitle || ""}</span>
        </span>
        <span class="deck-count">${dueLine}</span>`;
      const box = row.querySelector(".deck-check");
      box.addEventListener("change", () => {
        box.checked ? state.selected.add(deck.slug) : state.selected.delete(deck.slug);
        row.classList.toggle("is-selected", box.checked);
        updateStudyButton();
      });
      g.appendChild(row);
    }
    menu.appendChild(g);
  }
  updateStudyButton();
}

function updateStudyButton() {
  const n = state.selected.size;
  const btn = $("#study-selected");
  btn.disabled = n === 0;
  btn.textContent = n === 0
    ? "Select decks to study"
    : `Study ${n} deck${n === 1 ? "" : "s"}`;
  $("#clear-selected").hidden = n === 0;
}

$("#study-selected").addEventListener("click", () => {
  if (state.selected.size) startSession([...state.selected]);
});
$("#clear-selected").addEventListener("click", () => {
  state.selected.clear();
  loadDecks();
});

/* ============================================================
   STUDY SESSION
   ============================================================ */
function showWelcome() {
  $("#welcome").hidden = false;
  $("#study").hidden = true;
  state.activeSlugs = [];
  $("#deck-name").textContent = "Koine";
  $("#deck-sub").textContent = "Choose something to practice";
}

async function startSession(slugs) {
  closeDrawer();
  const qs = `slugs=${slugs.map(encodeURIComponent).join(",")}`;
  const data = await api(`/api/session?${qs}&limit=60`);
  state.activeSlugs = data.deck.slugs || slugs;

  $("#deck-name").textContent = data.deck.name;
  $("#deck-sub").textContent = data.deck.subtitle || "";
  $("#welcome").hidden = true;
  $("#study").hidden = false;
  $("#done").hidden = true;
  $("#card").hidden = false;
  $(".session-meta").hidden = false;

  if (!data.cards.length) {
    // Nothing due — offer a full review of the selected decks instead.
    const all = await api(`/api/session?${qs}&mode=all&limit=400`);
    state.session = makeSession(data.deck, all.cards);
    if (!all.cards.length) { finishSession(true); return; }
  } else {
    state.session = makeSession(data.deck, data.cards);
  }
  nextCard();
}

function makeSession(deck, cards) {
  return { deck, queue: [...cards], current: null, size: cards.length, completed: 0 };
}

function updateProgress() {
  const s = state.session;
  $("#progress-label").textContent = `${s.completed} / ${s.size}`;
  $("#progress-fill").style.width = `${(s.completed / s.size) * 100}%`;
}

function nextCard() {
  const s = state.session;
  if (!s.queue.length) { finishSession(false); return; }
  s.current = s.queue.shift();
  state.flipped = false;

  const c = s.current;
  $("#card-kicker").textContent = c.extra || "";
  $("#card-front").textContent = c.front;
  $("#card-back").textContent = c.back;
  $("#card-hint").textContent = c.hint ? `[ ${c.hint} ]` : "";
  $("#card").classList.remove("is-flipped");
  $("#box-badge").textContent = `Lv ${c.box}`;

  $("#reveal-btn").hidden = false;
  $("#grade-row").hidden = true;
  updateProgress();
}

function flipCard() {
  if (state.flipped) return;
  state.flipped = true;
  $("#card").classList.add("is-flipped");
  $("#reveal-btn").hidden = true;
  $("#grade-row").hidden = false;
}

async function grade(g) {
  if (!state.flipped) return;
  const s = state.session;
  const card = s.current;
  // fire-and-forget persistence; UI advances immediately
  api("/api/review", { method: "POST", body: JSON.stringify({ card_id: card.id, grade: g }) })
    .catch(() => {/* offline-tolerant: progress just won't save this one */});

  if (g === "again") {
    // requeue a few cards later so it comes back this session
    const pos = Math.min(s.queue.length, 4);
    s.queue.splice(pos, 0, card);
  } else {
    s.completed += 1;
  }
  nextCard();
}

function finishSession(empty) {
  $("#card").hidden = true;
  $(".session-meta").hidden = true;
  $("#reveal-btn").hidden = true;
  $("#grade-row").hidden = true;
  const done = $("#done"); done.hidden = false;
  $("#done-line").textContent = empty
    ? "This deck has no cards yet."
    : `You reviewed ${state.session ? state.session.size : 0} card${state.session && state.session.size === 1 ? "" : "s"}. Ἀγαθὸν ἔργον!`;
  loadDecks(); // refresh due counts in the menu
}

/* card interactions */
$("#card").addEventListener("click", flipCard);
$("#card").addEventListener("keydown", (e) => {
  if (e.key === " " || e.key === "Enter") { e.preventDefault(); flipCard(); }
});
$("#reveal-btn").addEventListener("click", flipCard);
$$(".grade").forEach(b => b.addEventListener("click", () => grade(b.dataset.grade)));
$("#again-btn").addEventListener("click", () => {
  if (state.activeSlugs.length) startSession(state.activeSlugs);
});

/* global keyboard shortcuts during study */
document.addEventListener("keydown", (e) => {
  if ($("#study").hidden || $("#done").hidden === false) return;
  if (["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) return;
  if (!state.flipped && (e.key === " ")) { e.preventDefault(); flipCard(); return; }
  if (state.flipped) {
    if (e.key === "1") grade("again");
    else if (e.key === "2") grade("good");
    else if (e.key === "3") grade("easy");
  }
});

/* ============================================================
   BOOT
   ============================================================ */
(async function boot() {
  setAuthMode("login");
  try {
    const { user } = await api("/api/me");
    if (user) showApp(user.username);
    else showAuth();
  } catch (_) {
    showAuth();
  }
})();

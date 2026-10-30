"use strict";

// ---------------------------------------------------------------- utilities

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body.detail) {
        detail = typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
      }
    } catch (_) { /* the body was not JSON; the status stands on its own */ }
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

const GRAHA_SHORT = {
  Sun: "Su", Moon: "Mo", Mars: "Ma", Mercury: "Me", Jupiter: "Ju",
  Venus: "Ve", Saturn: "Sa", Rahu: "Ra", Ketu: "Ke",
};

const state = {
  personId: null,
  reference: null,
  draft: {},          // the onboarding submission being assembled
};

// ------------------------------------------------------ north indian chart

// Houses hold fixed positions; the signs move between them. Anchors are
// fractions of the square, so the drawing scales cleanly.
const HOUSE_ANCHORS = [
  [0.50, 0.25], [0.25, 0.10], [0.10, 0.25], [0.25, 0.50],
  [0.10, 0.75], [0.25, 0.90], [0.50, 0.75], [0.75, 0.90],
  [0.90, 0.75], [0.75, 0.50], [0.90, 0.25], [0.75, 0.10],
];

function northIndianChart(chart, size = 340) {
  const S = size, H = S / 2, Q = S / 4;
  const byHouse = {};
  for (const p of chart.positions) (byHouse[p.house] ||= []).push(p);

  const lines = [
    `<rect x="0" y="0" width="${S}" height="${S}" class="ni-line"/>`,
    `<path d="M0 0 L${S} ${S} M${S} 0 L0 ${S}" class="ni-line"/>`,
    `<path d="M${H} 0 L${S} ${H} L${H} ${S} L0 ${H} Z" class="ni-line"/>`,
  ];

  const cells = chart.houses.map((h, i) => {
    const [fx, fy] = HOUSE_ANCHORS[i];
    const x = fx * S, y = fy * S;
    const grahas = byHouse[h.house] || [];
    const isLagna = h.house === 1;

    const parts = [
      `<text x="${x}" y="${y - 8}" text-anchor="middle" class="ni-sign">` +
      `${h.sign_index + 1}</text>`,
    ];
    const names = grahas.map((p) =>
      GRAHA_SHORT[p.name] + (p.retrograde ? "ʀ" : ""));
    if (isLagna) names.unshift("As");

    // Two per line keeps a crowded house inside its cell.
    for (let r = 0; r < names.length; r += 2) {
      const cls = isLagna && r === 0 ? "ni-lagna" : "ni-graha";
      parts.push(
        `<text x="${x}" y="${y + 8 + (r / 2) * 14}" text-anchor="middle" ` +
        `class="${cls}">${names.slice(r, r + 2).join(" ")}</text>`);
    }
    return parts.join("");
  });

  return `<svg viewBox="-2 -2 ${S + 4} ${S + 4}" width="${S}" height="${S}" ` +
    `role="img" aria-label="North Indian chart, lagna in ` +
    `${chart.lagna.sign_english}">${lines.join("")}${cells.join("")}</svg>`;
}

// ----------------------------------------------------------------- people

async function loadPeople() {
  const people = await api("/api/people");
  const nav = $("#people");
  nav.innerHTML = "";
  for (const p of people) {
    const b = el("button", "ghost", p.name + (p.lagna ? ` · ${p.lagna}` : ""));
    if (p.id === state.personId) b.classList.add("active");
    b.onclick = () => openPerson(p.id);
    nav.append(b);
  }
  // Only speak up when there is genuinely nothing on screen: onboarding and
  // the workspace each own the view while they are open.
  $("#empty").hidden = people.length > 0
    || !$("#onboarding").hidden || !$("#workspace").hidden;
  if (!state.personId && people.length) openPerson(people[0].id);
  return people;
}

async function openPerson(id) {
  state.personId = id;
  $("#onboarding").hidden = true;
  $("#empty").hidden = true;
  $("#workspace").hidden = false;
  await loadPeople();
  await Promise.all([renderChart(), renderDasha(), renderTimeline(),
                     renderJournal()]);
}

// -------------------------------------------------------------- workspace

async function renderChart() {
  const chart = await api(`/api/people/${state.personId}/chart`);
  const b = chart.birth;

  $("#chart-head").innerHTML =
    `<div class="lagna">Lagna ${chart.lagna.formatted} ` +
    `${chart.lagna.sign} <span class="sub">(${chart.lagna.sign_english})</span></div>` +
    `<div class="sub">${b.date} ${b.time} &middot; ${b.place}</div>` +
    `<div class="sub">${b.timezone} ${b.utc_offset_hours >= 0 ? "+" : ""}` +
    `${b.utc_offset_hours.toFixed(2)}h` +
    `${b.used_local_mean_time ? " (local mean time)" : ""} &middot; ` +
    `ayanamsa ${chart.ayanamsa.name} ${chart.ayanamsa.formatted}</div>`;

  $("#chart-svg").innerHTML = northIndianChart(chart);

  const rows = chart.positions.map((p) =>
    `<tr><td>${p.name}</td><td class="deg">${p.formatted}</td>` +
    `<td>${p.sign}</td><td>${p.house}</td>` +
    `<td>${p.nakshatra} ${p.pada}</td>` +
    `<td>${p.retrograde ? '<span class="retro">R</span>' : ""}</td></tr>`);
  $("#positions").innerHTML =
    "<tr><th>Graha</th><th>Degree</th><th>Sign</th><th>House</th>" +
    "<th>Nakshatra</th><th></th></tr>" + rows.join("");

  const r = chart.reliability;
  const gate = Object.entries(r.permitted).map(([k, v]) =>
    `<div class="gate"><span>${k.replace(/_/g, " ")}</span>` +
    `<span class="${v ? "yes" : "no"}">${v ? "yes" : "no"}</span></div>`);
  $("#reliability").innerHTML = gate.join("") +
    `<div class="gate"><span>dates</span><span>${r.date_precision}</span></div>` +
    `<p class="hint">Birth time known to about &plusmn;${r.window_minutes} min. ` +
    `Lagna sits ${r.degrees_to_lagna_boundary.toFixed(1)}&deg; from a sign ` +
    `boundary; dasha dates drift up to ${Math.round(r.dasha_drift_days)} days.</p>`;
}

async function renderDasha() {
  const d = await api(`/api/people/${state.personId}/dasha`);
  const names = ["", "Mahadasha", "Antardasha", "Pratyantardasha"];
  $("#dasha-now").innerHTML = d.running.map((p) =>
    `<div class="dasha-row"><div><div class="lvl">${names[p.level]}</div>` +
    `${p.lord}</div><div class="dates">${p.start.slice(0, 10)}<br>` +
    `${p.end.slice(0, 10)}</div></div>`).join("");
}

async function renderTimeline() {
  const today = new Date();
  const end = new Date(today);
  end.setFullYear(end.getFullYear() + 2);
  const events = await api(`/api/people/${state.personId}/timeline?` +
    `start=${today.toISOString().slice(0, 10)}&end=${end.toISOString().slice(0, 10)}` +
    `&bodies=Jupiter,Saturn,Rahu,Ketu,Mars`);
  $("#timeline").innerHTML = events.slice(0, 14).map((e) =>
    `<div class="event-row"><div class="when">${e.when.slice(0, 10)}</div>` +
    `${e.body} ${e.detail}` +
    `${e.house ? ` <span class="house">house ${e.house}</span>` : ""}</div>`
  ).join("") || '<p class="hint">Nothing in the next two years.</p>';
}

// An array, not an object: JavaScript orders integer-like object keys
// numerically and pushes the rest to the end, so a { "-2": ... } map comes
// out as 0, 1, 2, -2, -1 -- the dropdown reads in nonsense order.
const RATINGS = [[-2, "went badly"], [-1, "went poorly"], [0, "neutral"],
                 [1, "went well"], [2, "went very well"]];
const ratingLabel = (r) =>
  (RATINGS.find(([v]) => v === Number(r)) || [0, String(r)])[1];

async function renderJournal() {
  const rows = await api(`/api/people/${state.personId}/decisions`);
  const box = $("#journal");
  if (!rows.length) {
    box.innerHTML = '<p class="hint">Nothing recorded yet. Ask Claude a ' +
      'question with the jyotisha tools connected, and the judgement lands ' +
      'here � then come back to note what you actually did, and later ' +
      'how it turned out.</p>';
    return;
  }
  box.innerHTML = rows.map(renderDecision).join("");
  wireJournal();
}

function renderDecision(d) {
  const win = (d.window_opens || d.window_closes)
    ? `<div class="window">window ${d.window_opens || "?"} to ` +
      `${d.window_closes || "?"}</div>` : "";
  const asked = (d.asked_at || "").slice(0, 10);
  const type = d.question_type ? ` � ${d.question_type}` : "";
  const cites = d.citations ? ` � ${d.citations} facts cited` : "";

  // The loop is the point of the journal: an unanswered decision is a
  // question still open, not a finished record.
  let loop;
  if (!d.chose) {
    loop = `<div class="loop"><label>What did you decide?</label>
      <div class="loop-form">
        <input type="text" data-choice="${d.id}" placeholder="Took it / waited / declined">
        <button class="ghost" data-savechoice="${d.id}">Record</button>
      </div></div>`;
  } else if (d.outcome === null) {
    loop = `<div class="loop"><div>You chose: <b>${esc(d.chose)}</b></div>
      <label>How did it turn out?</label>
      <div class="loop-form">
        <input type="text" data-outcome="${d.id}" placeholder="What actually happened">
        <select data-rating="${d.id}">
          ${RATINGS.map(([v, t]) =>
            `<option value="${v}" ${v === 0 ? "selected" : ""}>${t}</option>`
          ).join("")}
        </select>
        <button class="ghost" data-saveoutcome="${d.id}">Record</button>
      </div></div>`;
  } else {
    const r = d.outcome_rating ?? 0;
    const cls = r > 0 ? "good" : r < 0 ? "bad" : "";
    loop = `<div class="loop"><div>You chose: <b>${esc(d.chose)}</b></div>
      <div>Outcome: ${esc(d.outcome)}
        <span class="rating ${cls}">(${ratingLabel(r)})</span></div></div>`;
  }

  return `<div class="decision${d.open ? " open" : ""}">
    <div class="q">${esc(d.question)}</div>
    <div class="when">${asked}${type}${cites}</div>
    ${win}
    <div class="verdict">${esc(d.verdict || "")}</div>
    ${loop}</div>`;
}

function esc(s) {
  const n = document.createElement("div");
  n.textContent = s == null ? "" : String(s);
  return n.innerHTML;
}

function wireJournal() {
  $$("[data-savechoice]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.savechoice;
      const value = $(`[data-choice="${id}"]`).value.trim();
      if (!value) return;
      await api(`/api/decisions/${id}/choice`, {
        method: "POST", body: JSON.stringify({ chose: value }) });
      renderJournal();
    };
  });
  $$("[data-saveoutcome]").forEach((b) => {
    b.onclick = async () => {
      const id = b.dataset.saveoutcome;
      const value = $(`[data-outcome="${id}"]`).value.trim();
      if (!value) return;
      await api(`/api/decisions/${id}/outcome`, {
        method: "POST",
        body: JSON.stringify({
          outcome: value,
          rating: Number($(`[data-rating="${id}"]`).value) }) });
      renderJournal();
    };
  });
}

function wireCentreTabs() {
  $$("#centre-tabs .tab").forEach((tab) => {
    tab.onclick = () => {
      $$("#centre-tabs .tab").forEach((t) => t.classList.toggle("active", t === tab));
      $$("[data-viewpanel]").forEach((p) => {
        p.hidden = p.dataset.viewpanel !== tab.dataset.view;
      });
    };
  });
}

// ------------------------------------------------------------- onboarding

function showStep(n) {
  $$("[data-panel]").forEach((p) => { p.hidden = +p.dataset.panel !== n; });
  $$(".steps li").forEach((li) => {
    const s = +li.dataset.step;
    li.classList.toggle("active", s === n);
    li.classList.toggle("done", s < n);
  });
}

function startOnboarding() {
  state.draft = {};
  state.personId = null;
  $("#workspace").hidden = true;
  $("#empty").hidden = true;
  $("#onboarding").hidden = false;
  $("#p-name").value = "";
  $("#place-chosen").hidden = true;
  $("#place-next").disabled = true;
  $("#event-list").innerHTML = "";
  $("#chart-warn").hidden = true;
  showStep(1);
  loadPeople();
}

function choosePlace(name, latitude, longitude) {
  Object.assign(state.draft, { place_name: name, latitude, longitude });
  $("#place-chosen").hidden = false;
  $("#place-chosen").textContent =
    `${name} · ${latitude.toFixed(4)}, ${longitude.toFixed(4)}`;
  $("#place-next").disabled = false;
}

let placeTimer;
function wirePlaceSearch() {
  $("#place-q").addEventListener("input", (e) => {
    clearTimeout(placeTimer);
    const q = e.target.value.trim();
    if (q.length < 2) { $("#place-results").innerHTML = ""; return; }
    placeTimer = setTimeout(async () => {
      try {
        const hits = await api(`/api/places?q=${encodeURIComponent(q)}`);
        $("#place-results").innerHTML = "";
        for (const h of hits) {
          const li = el("li");
          li.append(el("span", null, `${h.name}, ${h.country}`));
          li.append(el("span", "meta",
            `${h.latitude.toFixed(3)}, ${h.longitude.toFixed(3)}`));
          li.onclick = () =>
            choosePlace(`${h.name}, ${h.country}`, h.latitude, h.longitude);
          $("#place-results").append(li);
        }
        if (!hits.length) {
          $("#place-results").innerHTML =
            '<li class="static">No match. Try the coordinates tab.</li>';
        }
      } catch (err) { $("#place-results").innerHTML = ""; }
    }, 200);
  });

  $("#coord-check").onclick = async () => {
    const out = $("#coord-out");
    try {
      const r = await api("/api/places/coords", {
        method: "POST",
        body: JSON.stringify({ text: $("#coord-text").value }),
      });
      out.textContent = `${r.formatted} · ${r.timezone}`;
      choosePlace($("#coord-name").value.trim() || r.formatted,
        r.latitude, r.longitude);
    } catch (err) {
      out.textContent = `Could not read that: ${err.message}`;
      $("#place-next").disabled = true;
    }
  };

  $$(".tab").forEach((tab) => {
    tab.onclick = () => {
      $$(".tab").forEach((t) => t.classList.toggle("active", t === tab));
      $$("[data-tabpanel]").forEach((p) => {
        p.hidden = p.dataset.tabpanel !== tab.dataset.tab;
      });
    };
  });
}

function renderConfidenceOptions() {
  const box = $("#confidence-options");
  box.innerHTML = "";
  for (const c of state.reference.time_confidence) {
    const b = el("button", "opt");
    b.append(el("b", null, c.name.replace(/_/g, " ").toLowerCase()));
    b.append(el("span", null, `${c.description} — about ±${c.window_minutes} min`));
    b.onclick = () => {
      state.draft.time_confidence = c.name;
      $$(".opt").forEach((o) => o.classList.toggle("active", o === b));
    };
    box.append(b);
  }
  const sel = $("#b-ayanamsa");
  sel.innerHTML = state.reference.ayanamsas
    .map((a) => `<option ${a === "LAHIRI" ? "selected" : ""}>${a}</option>`).join("");
}

async function saveChart() {
  const warn = $("#chart-warn");
  warn.hidden = true;
  const date = $("#b-date").value, time = $("#b-time").value;
  if (!date || !time) { showStep(3); return; }
  if (!state.draft.time_confidence) {
    warn.hidden = false;
    warn.textContent = "Choose how well the birth time is known first.";
    return;
  }
  const [y, mo, d] = date.split("-").map(Number);
  const [hh, mm, ss] = time.split(":").map(Number);

  try {
    const pid = (await api("/api/people", {
      method: "POST",
      body: JSON.stringify({
        name: $("#p-name").value.trim() || "Unnamed",
        relation: $("#p-relation").value,
      }),
    })).id;

    const result = await api(`/api/people/${pid}/chart`, {
      method: "POST",
      body: JSON.stringify({
        year: y, month: mo, day: d, hour: hh, minute: mm, second: ss || 0,
        place_name: state.draft.place_name,
        latitude: state.draft.latitude, longitude: state.draft.longitude,
        time_confidence: state.draft.time_confidence,
        ayanamsa: $("#b-ayanamsa").value,
      }),
    });

    state.personId = pid;

    // Neither of these is resolved silently: both need a human answer.
    const notes = [];
    if (result.time_nonexistent) {
      notes.push("That local time never occurred — the clocks went " +
        "forward through it. The recorded time needs checking.");
    }
    if (result.time_ambiguous) {
      notes.push("That local time occurred twice that day, when the clocks " +
        "went back. Which one is meant changes the chart.");
    }
    if (result.used_local_mean_time) {
      notes.push("This birth predates standard time in that region, so the " +
        "birthplace's own local mean time was used " +
        `(${result.utc_offset_hours.toFixed(4)}h rather than ` +
        `${result.iana_offset_hours.toFixed(4)}h).`);
    }
    if (notes.length) { warn.hidden = false; warn.textContent = notes.join(" "); }

    showStep(5);
  } catch (err) {
    warn.hidden = false;
    warn.textContent = `Could not create the chart: ${err.message}`;
  }
}

async function addEvent() {
  const date = $("#e-date").value, title = $("#e-title").value.trim();
  if (!date || !title) return;
  await api(`/api/people/${state.personId}/events`, {
    method: "POST",
    body: JSON.stringify({
      happened_on: date, title,
      category: $("#e-category").value || null,
    }),
  });
  $("#e-title").value = "";
  const events = await api(`/api/people/${state.personId}/events`);
  $("#event-list").innerHTML = events.map((e) =>
    `<li class="static"><span>${e.title}</span>` +
    `<span class="meta">${e.happened_on}${e.category ? " · " + e.category : ""}` +
    `</span></li>`).join("");
}

// ------------------------------------------------------------------ start

async function main() {
  state.reference = await api("/api/reference");
  renderConfidenceOptions();
  wirePlaceSearch();

  $$("[data-next]").forEach((b) => {
    b.onclick = () => showStep(+b.dataset.next);
  });
  $$("[data-back]").forEach((b) => {
    b.onclick = () => showStep(+b.dataset.back);
  });
  wireCentreTabs();
  $("#add-person").onclick = startOnboarding;
  $("#save-chart").onclick = saveChart;
  $("#add-event").onclick = addEvent;
  $("#finish").onclick = () => openPerson(state.personId);

  const people = await loadPeople();
  if (!people.length) startOnboarding();
}

main().catch((err) => {
  document.body.innerHTML =
    `<p class="empty">Could not reach the backend: ${err.message}</p>`;
});

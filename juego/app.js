import { BANCO, AREAS } from "./banco/index.js";
import { mulberry32 } from "./gen.js";

const RONDA = 10;              // preguntas por partida
const LS = "acu.v1";           // clave de localStorage
const $ = (id) => document.getElementById(id);

// ═══════════════════════════ ESTADO ═══════════════════════════

const vacio = () => ({
  areas: AREAS.map((a) => a.id),  // todas activas por defecto
  vistas: 0,
  aciertos: 0,
  rachaMax: 0,
  errores: [],                    // ids que fallaste → cola de repaso
});

function cargar() {
  try {
    const s = JSON.parse(localStorage.getItem(LS));
    // Un banco editado puede dejar ids huérfanos guardados: los filtramos.
    if (s && Array.isArray(s.areas)) {
      s.areas = s.areas.filter((id) => AREAS.some((a) => a.id === id));
      s.errores = (s.errores || []).filter((id) => BANCO.some((q) => q.id === id));
      return { ...vacio(), ...s };
    }
  } catch { /* storage corrupto o deshabilitado → empezamos limpio */ }
  return vacio();
}

let S = cargar();
const guardar = () => { try { localStorage.setItem(LS, JSON.stringify(S)); } catch {} };

// ═══════════════════════════ PARTIDA ═══════════════════════════

let cola = [];      // preguntas materializadas de la ronda
let i = 0;          // índice actual
let racha = 0;
let ronda = { ok: 0, cats: {} };
let esRepaso = false;

/**
 * Materializa un ítem del banco.
 * - Generadores: se corren con semilla nueva (ya barajan sus opciones adentro).
 * - Preguntas fijas: se barajan acá. Escritas a mano tienden a quedar todas con
 *   la correcta en la misma posición, y eso se aprende antes que la acústica.
 */
function materializar(item) {
  if (item.gen) {
    const semilla = (Math.random() * 2 ** 32) >>> 0;
    const g = item.gen(mulberry32(semilla));
    return { id: item.id, area: item.area, cat: item.cat, dif: item.dif, src: item.src, ...g };
  }
  const orden = barajar(item.opts.map((o, k) => k));
  return {
    ...item,
    opts: orden.map((k) => item.opts[k]),
    ans: orden.indexOf(item.ans),
    errs: null,
  };
}

function barajar(arr) {
  const a = [...arr];
  for (let k = a.length - 1; k > 0; k--) {
    const j = Math.floor(Math.random() * (k + 1));
    [a[k], a[j]] = [a[j], a[k]];
  }
  return a;
}

function arrancar(repaso = false) {
  esRepaso = repaso;
  const fuente = repaso
    ? BANCO.filter((q) => S.errores.includes(q.id))
    : BANCO.filter((q) => S.areas.includes(q.area));

  if (!fuente.length) return;

  // Los generadores pueden repetirse en una ronda (cada tirada da datos nuevos);
  // las preguntas fijas, no.
  let sel = barajar(fuente).slice(0, RONDA);
  const gens = fuente.filter((q) => q.gen);
  while (sel.length < RONDA && gens.length) {
    sel.push(gens[Math.floor(Math.random() * gens.length)]);
  }

  cola = sel.map(materializar);
  i = 0; racha = 0; ronda = { ok: 0, cats: {} };
  ver("juego");
  pintar();
}

function pintar() {
  const q = cola[i];
  $("bar").style.width = `${(i / cola.length) * 100}%`;
  $("racha-live").textContent = `🔥 ${racha}`;
  $("q-cat").textContent = q.cat;
  $("q-dif").textContent = "●".repeat(q.dif || 1);
  $("q-text").innerHTML = q.q;
  $("fb").classList.add("hidden");

  const box = $("opts");
  box.innerHTML = "";
  q.opts.forEach((txt, k) => {
    const b = document.createElement("button");
    b.className = "opt";
    b.innerHTML = `<span class="k">${"ABCD"[k]}</span><span class="tx">${txt}</span>`;
    b.onclick = () => responder(k);
    box.appendChild(b);
  });
}

function responder(k) {
  const q = cola[i];
  const ok = k === q.ans;

  // Bloquea y colorea.
  [...$("opts").children].forEach((b, j) => {
    b.disabled = true;
    if (j === q.ans) b.classList.add("ok");
    else if (j === k) b.classList.add("no");
    else b.classList.add("dim");
  });

  // Estadísticas globales.
  S.vistas++;
  if (ok) {
    S.aciertos++; racha++; ronda.ok++;
    S.rachaMax = Math.max(S.rachaMax, racha);
    S.errores = S.errores.filter((id) => id !== q.id); // aprobado → sale del repaso
  } else {
    racha = 0;
    if (!S.errores.includes(q.id)) S.errores.push(q.id);
  }
  const c = (ronda.cats[q.cat] ||= { ok: 0, n: 0 });
  c.n++; if (ok) c.ok++;
  guardar();

  // Feedback: si es numérica y erraste, explicamos TU error puntual.
  const h = $("fb-head");
  h.className = "fb-head " + (ok ? "ok" : "no");
  h.textContent = ok ? "Correcto" : "Incorrecto";

  const especifico = !ok && q.errs && q.errs[k];
  $("fb-why").innerHTML =
    (especifico ? `<p><b>Tu error:</b> ${q.errs[k]}</p><hr style="border:0;border-top:1px solid var(--border);margin:12px 0">` : "") +
    q.why;

  $("fb-src").textContent = q.src ? `Fuente: ${q.src}` : "";
  $("btn-next").textContent = i === cola.length - 1 ? "Ver resultado" : "Siguiente";
  $("fb").classList.remove("hidden");
  $("fb").scrollIntoView({ behavior: "smooth", block: "nearest" });

  if (navigator.vibrate) navigator.vibrate(ok ? 12 : [8, 40, 8]);
}

function siguiente() {
  if (++i >= cola.length) return terminar();
  pintar();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function terminar() {
  const n = cola.length;
  const pct = Math.round((ronda.ok / n) * 100);
  $("fin-score").textContent = `${ronda.ok}/${n}`;
  $("fin-sub").textContent =
    pct === 100 ? "Ronda perfecta." :
    pct >= 70   ? "Bien encaminado." :
    pct >= 40   ? "Hay material para repasar." :
                  "A los errores hay que darles otra vuelta.";

  $("fin-cats").innerHTML = Object.entries(ronda.cats)
    .sort((a, b) => a[1].ok / a[1].n - b[1].ok / b[1].n)
    .map(([nm, c]) => `<div class="fincat"><span class="nm">${nm}</span><span class="sc">${c.ok}/${c.n}</span></div>`)
    .join("");

  ver("fin");
}

// ═══════════════════════════ MENÚ ═══════════════════════════

function pintarMenu() {
  $("st-racha").textContent = S.rachaMax;
  $("st-vistas").textContent = S.vistas;
  $("st-pct").textContent = S.vistas ? `${Math.round((S.aciertos / S.vistas) * 100)}%` : "—";
  $("n-err").textContent = S.errores.length;
  $("btn-repaso").disabled = !S.errores.length;

  const box = $("areas");
  box.innerHTML = "";
  for (const a of AREAS) {
    const n = BANCO.filter((q) => q.area === a.id).length;
    const on = S.areas.includes(a.id);
    const el = document.createElement("div");
    el.className = "area";
    el.setAttribute("role", "checkbox");
    el.setAttribute("aria-checked", on);
    el.setAttribute("tabindex", "0");
    el.innerHTML = `<span class="tick">${on ? "✓" : ""}</span><span class="nm">${a.nm}</span><span class="ct">${n}</span>`;
    const toggle = () => {
      S.areas = S.areas.includes(a.id) ? S.areas.filter((x) => x !== a.id) : [...S.areas, a.id];
      if (!S.areas.length) S.areas = [a.id]; // nunca dejar cero áreas
      guardar(); pintarMenu();
    };
    el.onclick = toggle;
    el.onkeydown = (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } };
    box.appendChild(el);
  }

  const disp = BANCO.filter((q) => S.areas.includes(q.area)).length;
  const gens = BANCO.filter((q) => q.gen).length;
  $("n-banco").textContent = `${disp} de ${BANCO.length} ítems · ${gens} numéricos infinitos`;
  $("btn-jugar").disabled = !disp;
}

function ver(id) {
  for (const s of ["menu", "juego", "fin"]) $(s).classList.toggle("hidden", s !== id);
  if (id === "menu") pintarMenu();
  window.scrollTo(0, 0);
}

// ═══════════════════════════ WIRING ═══════════════════════════

$("btn-jugar").onclick  = () => arrancar(false);
$("btn-repaso").onclick = () => arrancar(true);
$("btn-next").onclick   = siguiente;
$("btn-otra").onclick   = () => arrancar(esRepaso && S.errores.length > 0);
$("btn-menu").onclick   = () => ver("menu");
$("btn-salir").onclick  = () => ver("menu");
$("btn-reset").onclick  = () => {
  if (confirm("¿Borrar todo el progreso y los errores guardados?")) {
    S = vacio(); guardar(); pintarMenu();
  }
};

// Teclado: A–D para responder, Enter para avanzar (cómodo en la compu).
document.addEventListener("keydown", (e) => {
  if ($("juego").classList.contains("hidden")) return;
  const k = "abcd".indexOf(e.key.toLowerCase());
  if (k >= 0 && $("fb").classList.contains("hidden")) responder(k);
  else if (e.key === "Enter" && !$("fb").classList.contains("hidden")) siguiente();
});

ver("menu");

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

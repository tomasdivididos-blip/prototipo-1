// Utilidades para ejercicios numéricos parametrizados.
//
// Idea: cada ejercicio es una función gen(rng) que sortea sus datos y devuelve
// {q, opts, ans, why}. Los distractores NO son ruido: cada uno es el resultado
// de un error conceptual concreto (olvidar el factor 2, usar diámetro por radio,
// confundir presión con intensidad...). Así el feedback puede nombrar el error.

export const C = 343; // m/s a 20 °C

/** PRNG con semilla (mulberry32): la misma semilla reproduce la misma pregunta. */
export function mulberry32(seed) {
  let a = seed >>> 0;
  return function () {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Real en [lo, hi] cuantizado a `step`. */
export function rnd(rng, lo, hi, step = 0.1) {
  const n = Math.round((hi - lo) / step);
  return +(lo + Math.round(rng() * n) * step).toFixed(6);
}

/** Entero en [lo, hi]. */
export function rndInt(rng, lo, hi) {
  return lo + Math.floor(rng() * (hi - lo + 1));
}

/** Un elemento al azar de un array. */
export function pick(rng, arr) {
  return arr[Math.floor(rng() * arr.length)];
}

/** Formatea con `d` decimales y separador decimal español. */
export function fmt(x, d = 1) {
  return Number(x).toFixed(d).replace(".", ",");
}

/** Marca un dato del enunciado para resaltarlo. */
export function dato(x, unidad = "", d = 1) {
  const v = typeof x === "number" ? fmt(x, d) : x;
  return `<span class="given">${v}${unidad ? " " + unidad : ""}</span>`;
}

/**
 * Arma las 4 opciones a partir de la correcta y los distractores etiquetados.
 *
 * @param rng      generador
 * @param correcta {v: number, ...}
 * @param trampas  [{v: number, err: "texto del error"}, ...]
 * @param unidad   string
 * @param d        decimales
 * @returns {opts, ans, errs} — errs[i] explica por qué la opción i está mal.
 */
export function opciones(rng, correcta, trampas, unidad = "", d = 1) {
  const items = [{ v: correcta, err: null }];

  // Descarta trampas que colisionan con la correcta o entre sí al redondear:
  // dos opciones idénticas harían la pregunta irresoluble.
  const visto = new Set([fmt(correcta, d)]);
  for (const t of trampas) {
    const k = fmt(t.v, d);
    if (visto.has(k) || !isFinite(t.v) || t.v <= 0) continue;
    visto.add(k);
    items.push(t);
    if (items.length === 4) break;
  }

  // Si las trampas colisionaron y faltan opciones, rellena con desvíos ±%
  // suficientemente separados para no volver a colisionar.
  const factores = [1.32, 0.71, 1.85, 0.55, 2.4, 0.38];
  let fi = 0;
  while (items.length < 4 && fi < factores.length) {
    const v = correcta * factores[fi++];
    const k = fmt(v, d);
    if (visto.has(k)) continue;
    visto.add(k);
    items.push({ v, err: "Es un valor plausible, pero no sale de aplicar la fórmula." });
  }

  // Fisher–Yates con el rng sembrado.
  for (let i = items.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [items[i], items[j]] = [items[j], items[i]];
  }

  return {
    opts: items.map((t) => `${fmt(t.v, d)}${unidad ? " " + unidad : ""}`),
    ans: items.findIndex((t) => t.err === null),
    errs: items.map((t) => t.err),
  };
}

/** Pasos de resolución formateados. */
export function pasos(...lineas) {
  return lineas.map((l) => `<span class="paso">${l}</span>`).join("");
}

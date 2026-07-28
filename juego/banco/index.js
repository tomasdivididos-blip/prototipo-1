// Un archivo de preguntas conceptuales por área (cada uno aplica su `area` con
// .map() al final). Los numéricos parametrizados van aparte, en numericos.js.
import { GEOMETRIA } from "./geometria.js";
import { FUENTES } from "./fuentes.js";
import { PSICOACUSTICA } from "./psicoacustica.js";
import { NUMERICA } from "./numerica.js";
import { NUMERICOS } from "./numericos.js";

/** Áreas del juego — espejan la clasificación de referencias/_indice.md. */
export const AREAS = [
  { id: "geometria",     nm: "Geometría y modos" },
  { id: "fuentes",       nm: "Fuentes y monitoreo" },
  { id: "psicoacustica", nm: "Psicoacústica" },
  { id: "numerica",      nm: "Numérica y FEM" },
];

export const BANCO = [
  ...GEOMETRIA, ...FUENTES, ...PSICOACUSTICA, ...NUMERICA,
  ...NUMERICOS,
];

/** Tolerancia de largo entre la opción más larga y la más corta, en caracteres. */
export const SPREAD_MAX = 5;
/** Ventaja de la correcta sobre la 2da a partir de la cual el largo ya se nota. */
export const MARGEN_TELL = 3;

/**
 * Audita el banco. Lo importante no es sólo que no rompa: es que no se pueda
 * ganar SIN SABER ACÚSTICA. Dos sesgos clásicos de los multiple choice escritos
 * a mano, los dos detectados en este banco y corregidos:
 *   1. Sesgo de largo — la correcta es la más larga (la explicación se cuela en
 *      la opción). Se acierta eligiendo la más larga.
 *   2. Sesgo de posición — la correcta cae siempre en el mismo índice.
 *      Neutralizado en app.js, que baraja; se audita igual para detectarlo.
 */
export function auditar(banco = BANCO) {
  const problemas = [];
  const vistos = new Set();
  const fijas = banco.filter((q) => !q.gen);
  let masLarga = 0;
  const posiciones = { 0: 0, 1: 0, 2: 0, 3: 0 };

  for (const q of banco) {
    if (vistos.has(q.id)) problemas.push(`id duplicado: ${q.id}`);
    vistos.add(q.id);
    if (!AREAS.some((a) => a.id === q.area)) problemas.push(`${q.id}: área inválida "${q.area}"`);
    if (!q.gen) {
      if (!Array.isArray(q.opts) || q.opts.length !== 4) { problemas.push(`${q.id}: no tiene 4 opciones`); continue; }
      if (!(q.ans >= 0 && q.ans <= 3)) { problemas.push(`${q.id}: ans fuera de rango`); continue; }

      const len = q.opts.map((o) => o.length);
      const spread = Math.max(...len) - Math.min(...len);
      if (spread > SPREAD_MAX) {
        problemas.push(`${q.id}: opciones desparejas (${len.join("/")}, spread ${spread} > ${SPREAD_MAX})`);
      }
      // Tell real = la correcta gana por un margen visible sobre la 2da. Ganar
      // por 1 carácter, o empatar, no se ve — no lo contamos (ver check_banco.py).
      const resto = len.filter((_, k) => k !== q.ans).sort((a, b) => b - a);
      if (len[q.ans] - resto[0] >= MARGEN_TELL) masLarga++;
      posiciones[q.ans]++;
    }
  }

  // Con opciones parejas, que la correcta gane por margen debería pasar bastante
  // menos que 1/4 de las veces. Muy por encima = todavía hay tell de longitud.
  const esperado = fijas.length / 4;
  const sesgoLargo = { correctaGanaPorMargen: masLarga, esperadoPorAzar: +esperado.toFixed(1) };
  if (masLarga > esperado) {
    problemas.push(`sesgo de largo: la correcta gana por ≥${MARGEN_TELL} chars en ${masLarga}/${fijas.length} (azar ≈ ${esperado.toFixed(0)})`);
  }

  return { total: banco.length, fijas: fijas.length, problemas, sesgoLargo, posiciones };
}

// Auditoría automática al cargar en el navegador: los problemas salen por consola.
if (typeof window !== "undefined") {
  const r = auditar();
  if (r.problemas.length) {
    console.group(`%c[banco] ${r.problemas.length} problema(s)`, "color:#f87171;font-weight:bold");
    r.problemas.forEach((p) => console.warn(p));
    console.groupEnd();
  }
  window.__auditarBanco = auditar; // para llamarla a mano desde la consola
}

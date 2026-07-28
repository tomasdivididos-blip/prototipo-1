// Ejercicios numéricos parametrizados.
// Cada gen(rng) sortea sus datos → {q, opts, ans, why}.
// Los distractores codifican errores conceptuales reales, no ruido.

import { C, rnd, rndInt, pick, fmt, dato, opciones, pasos } from "../gen.js";

export const NUMERICOS = [

  // ─────────────────────────── GEOMETRÍA ───────────────────────────
  {
    id: "num-axial-1",
    area: "geometria",
    cat: "Modos",
    dif: 1,
    src: "Everest, Master Handbook of Acoustics, p. 140 · Rayleigh, Theory of Sound",
    gen(rng) {
      const eje = pick(rng, [
        { nm: "largo", L: rnd(rng, 3.4, 7.2, 0.1) },
        { nm: "ancho", L: rnd(rng, 2.6, 5.0, 0.1) },
        { nm: "alto",  L: rnd(rng, 2.3, 3.4, 0.05) },
      ]);
      const f = C / (2 * eje.L);
      const o = opciones(rng, f, [
        { v: C / eje.L,     err: "Usaste λ = L. Entre dos paredes rígidas el fundamental encaja <b>media</b> longitud de onda: λ = 2L. Te olvidaste el factor 2 y te dio el doble." },
        { v: C / (4 * eje.L), err: "λ = 4L es el fundamental de un tubo <b>cerrado-abierto</b> (un extremo rígido, otro libre). Entre dos paredes rígidas ambos extremos son antinodos de presión → λ = 2L." },
        { v: 2 * C / eje.L, err: "Invertiste la fórmula: multiplicaste por 2 en vez de dividir." },
      ], "Hz", 1);
      return {
        q: `Una sala tiene ${eje.nm} = ${dato(eje.L, "m", 2)}. ¿En qué frecuencia está el <b>modo axial fundamental</b> de ese eje? (c = 343 m/s)`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `El fundamental axial encaja media onda entre las paredes: <code>λ = 2L = ${fmt(2 * eje.L, 2)} m</code>`,
          `<code>f = c/λ = c/(2L) = 343 / (2 · ${fmt(eje.L, 2)})</code>`,
          `<b>f = ${fmt(f, 1)} Hz</b>`
        ) + `<p>Los múltiplos enteros (${fmt(2 * f, 0)} Hz, ${fmt(3 * f, 0)} Hz…) son los armónicos de la misma serie axial.</p>`,
      };
    },
  },

  {
    id: "num-modo-general",
    area: "geometria",
    cat: "Modos",
    dif: 3,
    src: "Rayleigh, Theory of Sound · Everest, Master Handbook of Acoustics, p. 140",
    gen(rng) {
      const Lx = rnd(rng, 4.0, 6.8, 0.1);
      const Ly = rnd(rng, 3.0, 5.0, 0.1);
      const Lz = rnd(rng, 2.4, 3.2, 0.05);
      const [nx, ny, nz] = pick(rng, [[1, 1, 0], [2, 1, 0], [1, 1, 1], [2, 0, 1], [1, 2, 0]]);
      const tipo = [nx, ny, nz].filter((n) => n > 0).length;
      const nombre = { 1: "axial", 2: "tangencial", 3: "oblicuo" }[tipo];

      const term = (n, L) => (n / L) ** 2;
      const f = (C / 2) * Math.sqrt(term(nx, Lx) + term(ny, Ly) + term(nz, Lz));
      const lineal = (C / 2) * (nx / Lx + ny / Ly + nz / Lz);

      const o = opciones(rng, f, [
        { v: lineal, err: "Sumaste los términos <b>linealmente</b>. La fórmula suma los cuadrados y recién después toma la raíz: es una norma euclídea, no una suma." },
        { v: C * Math.sqrt(term(nx, Lx) + term(ny, Ly) + term(nz, Lz)), err: "Te olvidaste el factor <code>c/2</code>: usaste <code>c</code> en vez de <code>c/2</code>." },
        { v: (C / 2) * (term(nx, Lx) + term(ny, Ly) + term(nz, Lz)), err: "Te faltó la raíz cuadrada: sumaste los cuadrados pero no radicaste." },
      ], "Hz", 1);

      return {
        q: `Sala rectangular de ${dato(Lx, "×", 2)} ${dato(Ly, "×", 2)} ${dato(Lz, "m", 2)} (largo × ancho × alto).<br>¿En qué frecuencia está el modo <b>(${nx}, ${ny}, ${nz})</b>?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>f = (c/2)·√[(nx/Lx)² + (ny/Ly)² + (nz/Lz)²]</code>`,
          `<code>= (343/2)·√[(${nx}/${fmt(Lx, 2)})² + (${ny}/${fmt(Ly, 2)})² + (${nz}/${fmt(Lz, 2)})²]</code>`,
          `<code>= 171,5 · √${fmt(term(nx, Lx) + term(ny, Ly) + term(nz, Lz), 4)}</code>`,
          `<b>f = ${fmt(f, 1)} Hz</b>`
        ) + `<p>Con ${tipo} índice${tipo > 1 ? "s" : ""} distinto${tipo > 1 ? "s" : ""} de cero es un modo <b>${nombre}</b>. Los axiales son los más energéticos (la onda rebota en incidencia normal entre dos paredes); los oblicuos, los más débiles.</p>`,
      };
    },
  },

  {
    id: "num-sabine",
    area: "geometria",
    cat: "RT60",
    dif: 2,
    src: "Sabine (1922) · Everest, Master Handbook of Acoustics, p. 159 · Beranek, Acústica, p. 218",
    gen(rng) {
      const Lx = rnd(rng, 4.0, 7.0, 0.5);
      const Ly = rnd(rng, 3.0, 5.0, 0.5);
      const Lz = rnd(rng, 2.4, 3.0, 0.1);
      const V = Lx * Ly * Lz;
      const S = 2 * (Lx * Ly + Lx * Lz + Ly * Lz);
      const alfa = rnd(rng, 0.12, 0.35, 0.01);
      const A = S * alfa;
      const rt = 0.161 * V / A;

      const o = opciones(rng, rt, [
        { v: 0.161 * V / S, err: "Usaste la superficie <code>S</code> en vez del <b>área de absorción</b> <code>A = S·ᾱ</code>. Sin el coeficiente, estás suponiendo que toda la superficie absorbe el 100 %." },
        { v: 0.049 * V / A, err: "0,049 es la constante de Sabine en unidades <b>imperiales</b> (pies). En metros la constante es 0,161." },
        { v: 0.161 * A / V, err: "Invertiste la fracción: el volumen va arriba (más volumen → más cola) y la absorción abajo (más absorción → menos cola)." },
      ], "s", 2);

      return {
        q: `Sala de ${dato(Lx, "×", 1)} ${dato(Ly, "×", 1)} ${dato(Lz, "m", 1)} con coeficiente de absorción medio ${dato(alfa, "", 2)} uniforme en todas las superficies.<br>¿Cuál es el <b>RT60 de Sabine</b>?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>V = ${fmt(Lx, 1)} · ${fmt(Ly, 1)} · ${fmt(Lz, 1)} = ${fmt(V, 1)} m³</code>`,
          `<code>S = 2(LxLy + LxLz + LyLz) = ${fmt(S, 1)} m²</code>`,
          `<code>A = S·ᾱ = ${fmt(S, 1)} · ${fmt(alfa, 2)} = ${fmt(A, 1)} m² sabine</code>`,
          `<code>RT60 = 0,161·V/A = 0,161 · ${fmt(V, 1)} / ${fmt(A, 1)}</code>`,
          `<b>RT60 = ${fmt(rt, 2)} s</b>`
        ) + `<p>Ojo con el rango de validez: Sabine supone campo difuso y ᾱ chico. Con ᾱ ≳ 0,3 sobrestima la cola y conviene Eyring — y en una sala chica y tratada, ninguna de las dos es de fiar en graves, donde manda el comportamiento modal.</p>`,
      };
    },
  },

  {
    id: "num-eyring",
    area: "geometria",
    cat: "RT60",
    dif: 3,
    src: "Eyring (1930) · Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica, p. 218",
    gen(rng) {
      const V = rnd(rng, 45, 140, 5);
      const S = rnd(rng, 80, 180, 5);
      const alfa = rnd(rng, 0.35, 0.6, 0.01); // régimen donde Sabine ya falla
      const sab = 0.161 * V / (S * alfa);
      const eyr = 0.161 * V / (-S * Math.log(1 - alfa));

      const o = opciones(rng, eyr, [
        { v: sab, err: "Ése es el RT de <b>Sabine</b>. Con ᾱ alto Sabine sobrestima: supone que la energía se absorbe de a poquito y en forma continua, cuando en realidad cada reflexión se come una fracción grande." },
        { v: 0.161 * V / (S * Math.log(1 - alfa) * -1) * 1.6, err: "El orden de magnitud no cierra: revisá que el logaritmo sea natural (ln) y no decimal (log₁₀)." },
        { v: 0.161 * V / (-S * Math.log(alfa)), err: "Dentro del logaritmo va <code>(1 − ᾱ)</code>, no <code>ᾱ</code>: lo que sobrevive a cada reflexión es la fracción <i>no</i> absorbida." },
      ], "s", 2);

      return {
        q: `Sala de ${dato(V, "m³", 0)}, superficie total ${dato(S, "m²", 0)}, absorción media ${dato(alfa, "", 2)}.<br>¿Cuál es el <b>RT60 de Eyring</b>?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>RT60 = 0,161·V / (−S·ln(1 − ᾱ))</code>`,
          `<code>ln(1 − ${fmt(alfa, 2)}) = ${fmt(Math.log(1 - alfa), 4)}</code>`,
          `<code>−S·ln(1−ᾱ) = ${fmt(-S * Math.log(1 - alfa), 1)} m²</code>`,
          `<b>RT60 = ${fmt(eyr, 2)} s</b>`
        ) + `<p>Sabine para el mismo dato daría <b>${fmt(sab, 2)} s</b> (${fmt(100 * (sab / eyr - 1), 0)} % más). La diferencia crece con ᾱ: para ᾱ → 0 las dos convergen, porque <code>−ln(1−ᾱ) ≈ ᾱ</code>.</p>`,
      };
    },
  },

  {
    id: "num-schroeder",
    area: "geometria",
    cat: "Frecuencia de Schroeder",
    dif: 2,
    src: "Schroeder (1962), JASA · Everest, Master Handbook of Acoustics, p. 325",
    gen(rng) {
      const V = rnd(rng, 30, 160, 5);
      const rt = rnd(rng, 0.25, 0.9, 0.05);
      const fs = 2000 * Math.sqrt(rt / V);

      const o = opciones(rng, fs, [
        { v: 2000 * Math.sqrt(V / rt), err: "Invertiste la fracción. Más volumen → los modos se agolpan → f_S <b>baja</b>. Tu resultado sube con el volumen, que es al revés." },
        { v: 2000 * (rt / V), err: "Te faltó la raíz cuadrada." },
        { v: 1000 * Math.sqrt(rt / V), err: "La constante es 2000 (Schroeder), no 1000." },
      ], "Hz", 1);

      return {
        q: `Sala de ${dato(V, "m³", 0)} con RT60 = ${dato(rt, "s", 2)}.<br>¿Cuál es la <b>frecuencia de Schroeder</b>?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>f_S = 2000·√(RT60/V) = 2000·√(${fmt(rt, 2)} / ${fmt(V, 0)})</code>`,
          `<b>f_S ≈ ${fmt(fs, 1)} Hz</b>`
        ) + `<p>Por debajo de f_S los modos están <b>separados</b> y se resuelven de a uno: el campo es modal y hay que tratarlo sala por sala (ahí vive el trabajo de graves). Por encima, se solapan (≳3 modos por ancho de banda) y recién ahí tiene sentido hablar de campo difuso, RT y acústica estadística.</p>`,
      };
    },
  },

  {
    id: "num-absorcion-area",
    area: "geometria",
    cat: "Absorción",
    dif: 2,
    src: "Everest, Master Handbook of Acoustics, p. 160 · Beranek, Acústica, p. 218",
    gen(rng) {
      const sup = [
        { nm: "paredes (yeso)",     S: rnd(rng, 45, 80, 1), a: 0.05 },
        { nm: "piso (alfombra)",    S: rnd(rng, 15, 30, 1), a: 0.35 },
        { nm: "cielorraso (fibra)", S: rnd(rng, 15, 30, 1), a: 0.70 },
      ];
      const A = sup.reduce((s, x) => s + x.S * x.a, 0);
      const Stot = sup.reduce((s, x) => s + x.S, 0);
      const aMedio = A / Stot;

      const o = opciones(rng, A, [
        { v: Stot, err: "Sumaste sólo las superficies, sin ponderar por cada α." },
        { v: sup.reduce((s, x) => s + x.a, 0), err: "Sumaste los coeficientes sin multiplicar por su superficie. Un α alto en 2 m² aporta poco; uno mediano en 60 m², mucho." },
        { v: Stot * (sup.reduce((s, x) => s + x.a, 0) / 3), err: "Promediaste los α sin ponderar por superficie. El promedio correcto pesa cada α por sus m²." },
      ], "m²", 1);

      return {
        q: `Una sala tiene:<br>` +
           sup.map((x) => `• ${x.nm}: ${dato(x.S, "m²", 0)} con α = ${dato(x.a, "", 2)}`).join("<br>") +
           `<br><br>¿Cuál es el <b>área de absorción total A</b> a esa frecuencia?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>A = Σ Sᵢ·αᵢ</code>`,
          ...sup.map((x) => `<code>${fmt(x.S, 0)} m² · ${fmt(x.a, 2)} = ${fmt(x.S * x.a, 2)} m²</code>`),
          `<b>A = ${fmt(A, 1)} m² sabine</b>`
        ) + `<p>El α medio ponderado es <code>ᾱ = A/S = ${fmt(A, 1)}/${fmt(Stot, 0)} = ${fmt(aMedio, 3)}</code>. Fijate que el cielorraso, con menos superficie que las paredes, aporta mucho más absorción: lo que manda es el producto S·α, no α solo.</p>`,
      };
    },
  },

  // ──────────────────────────── FUENTES ────────────────────────────
  {
    id: "num-sbir",
    area: "fuentes",
    cat: "SBIR",
    dif: 2,
    src: "Toole, Sound Reproduction, cap. 13 · Newell, Recording Studio Design",
    gen(rng) {
      const d = rnd(rng, 0.25, 1.4, 0.05);
      const f = C / (4 * d);

      const o = opciones(rng, f, [
        { v: C / (2 * d), err: "<code>c/(2d)</code> es el primer <b>refuerzo</b> (la reflexión vuelve en fase), no la cancelación." },
        { v: C / d, err: "Te olvidaste que el camino extra es <b>2d</b> (ida y vuelta a la pared), y que la cancelación pide media onda de desfase." },
        { v: C / (8 * d), err: "Te sobró un factor 2: el primer nulo está en cuarto de onda, <code>d = λ/4</code>." },
      ], "Hz", 1);

      return {
        q: `Un monitor está a ${dato(d, "m", 2)} de la pared de atrás.<br>¿En qué frecuencia cae el <b>primer nulo por SBIR</b> (interferencia con la reflexión de esa pared)?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `La reflexión recorre <code>2d</code> de más y rebota en pared rígida (sin inversión de presión).`,
          `Cancelación cuando ese camino extra vale media onda: <code>2d = λ/2 → λ = 4d</code>`,
          `<code>f = c/λ = c/(4d) = 343 / (4 · ${fmt(d, 2)})</code>`,
          `<b>f = ${fmt(f, 1)} Hz</b>`
        ) + `<p>Por eso el SBIR se combate con distancias muy cortas (empotrar el monitor: <code>d → 0</code> empuja el nulo fuera de la banda) o muy largas + absorción. Las distancias intermedias, típicas de un cuarto chico, son las peores: te dejan el nulo justo en los graves-medios.</p>`,
      };
    },
  },

  {
    id: "num-inv-square",
    area: "fuentes",
    cat: "Propagación",
    dif: 1,
    src: "Beranek, Acústica · Everest, Master Handbook of Acoustics, p. 87",
    gen(rng) {
      const r1 = rnd(rng, 0.5, 2.0, 0.5);
      const mult = pick(rng, [2, 3, 4]);
      const r2 = r1 * mult;
      const L1 = rndInt(rng, 82, 96);
      const dL = 20 * Math.log10(r2 / r1);
      const L2 = L1 - dL;

      const o = opciones(rng, L2, [
        { v: L1 - 10 * Math.log10(r2 / r1), err: "Usaste <code>10·log</code>. La <b>presión</b> cae como 1/r, y al pasar a dB de presión el factor es <b>20</b>. El 10 es para potencia o intensidad." },
        { v: L1 - r2 / r1 * 3, err: "No es una caída lineal con la distancia: es logarítmica. Cada vez que <b>duplicás</b> la distancia perdés 6 dB, no una cantidad fija por metro." },
        { v: L1 + dL, err: "Signo invertido: alejándote el nivel <b>baja</b>." },
      ], "dB", 1);

      return {
        q: `En campo libre, una fuente puntual da ${dato(L1, "dB SPL", 0)} a ${dato(r1, "m", 1)}.<br>¿Qué nivel hay a ${dato(r2, "m", 1)}?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>ΔL = 20·log₁₀(r₂/r₁) = 20·log₁₀(${fmt(r2, 1)}/${fmt(r1, 1)}) = 20·log₁₀(${mult})</code>`,
          `<code>ΔL = ${fmt(dL, 1)} dB</code>`,
          `<b>L₂ = ${fmt(L1, 0)} − ${fmt(dL, 1)} = ${fmt(L2, 1)} dB SPL</b>`
        ) + `<p>Regla de bolsillo: <b>−6 dB por cada duplicación</b> de distancia. Vale sólo en campo libre; dentro de una sala, pasada la distancia crítica, el campo reverberante sostiene el nivel y la ley deja de cumplirse.</p>`,
      };
    },
  },

  {
    id: "num-suma-spl",
    area: "fuentes",
    cat: "Niveles",
    dif: 2,
    src: "Beranek, Acústica · Everest, Master Handbook of Acoustics",
    gen(rng) {
      const La = rndInt(rng, 70, 88);
      const dif = pick(rng, [0, 0, 3, 6, 10]);
      const Lb = La - dif;
      const Lt = 10 * Math.log10(10 ** (La / 10) + 10 ** (Lb / 10));

      const o = opciones(rng, Lt, [
        { v: La + Lb, err: "Los dB <b>no se suman aritméticamente</b>: son logarítmicos. Hay que volver a potencias, sumar ahí, y recién log de nuevo." },
        { v: 20 * Math.log10(10 ** (La / 20) + 10 ** (Lb / 20)), err: "Sumaste <b>presiones</b> (factor 20), lo que asume que las fuentes son coherentes y están en fase. Fuentes incoherentes suman <b>potencias</b> (factor 10)." },
        { v: (La + Lb) / 2, err: "Promediaste. Agregar una fuente nunca puede bajar el nivel por debajo de la más fuerte." },
      ], "dB", 1);

      return {
        q: `Dos fuentes <b>incoherentes</b> suenan a la vez: una da ${dato(La, "dB", 0)} y la otra ${dato(Lb, "dB", 0)} en el mismo punto.<br>¿Cuál es el nivel total?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `Incoherentes → suman <b>potencias</b>: <code>L = 10·log₁₀(10^(La/10) + 10^(Lb/10))</code>`,
          `<code>= 10·log₁₀(10^${fmt(La / 10, 1)} + 10^${fmt(Lb / 10, 1)})</code>`,
          `<b>L = ${fmt(Lt, 1)} dB</b>`
        ) + (dif === 0
          ? `<p>Dos fuentes <b>iguales e incoherentes</b> dan exactamente <b>+3 dB</b> (el doble de potencia). Si fueran coherentes y en fase serían +6 dB, porque ahí se suman las presiones.</p>`
          : `<p>Con ${dif} dB de diferencia, la más débil aporta apenas <b>${fmt(Lt - La, 1)} dB</b>. Pasados los ~10 dB de diferencia, la fuente débil es prácticamente irrelevante: por eso en control de ruido conviene atacar siempre la fuente dominante.</p>`),
      };
    },
  },

  {
    id: "num-lambda",
    area: "fuentes",
    cat: "Propagación",
    dif: 1,
    src: "Kinsler & Frey, Fundamentals of Acoustics · Beranek, Acústica",
    gen(rng) {
      const f = pick(rng, [31.5, 40, 63, 80, 100, 125, 160, 200, 250, 500, 1000]);
      const lam = C / f;
      const o = opciones(rng, lam, [
        { v: f / C, err: "Invertiste: <code>λ = c/f</code>. Fijate en las unidades — (m/s)/(1/s) da metros." },
        { v: C / (2 * f), err: "Eso es media longitud de onda." },
        { v: C * f / 1000, err: "λ y f son inversamente proporcionales: a más frecuencia, <b>menos</b> longitud de onda." },
      ], "m", 2);
      return {
        q: `¿Cuál es la <b>longitud de onda</b> en aire a ${dato(f, "Hz", f % 1 ? 1 : 0)}? (c = 343 m/s)`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(`<code>λ = c/f = 343 / ${f}</code>`, `<b>λ = ${fmt(lam, 2)} m</b>`) +
          `<p>Es el número que gobierna todo lo demás: un absorbente poroso necesita espesor comparable a λ/4 (acá, <b>${fmt(lam / 4, 2)} m</b>) para trabajar bien a esta frecuencia. Por eso tratar 40 Hz con lana es tan caro en espesor, y por eso a esa frecuencia se usan resonadores en lugar de porosos.</p>`,
      };
    },
  },

  // ─────────────────────────── NUMÉRICA ────────────────────────────
  {
    id: "num-malla-nyquist",
    area: "numerica",
    cat: "Malla",
    dif: 3,
    src: "Ihlenburg, Finite Element Analysis of Acoustic Scattering, §2.3 · FEM for Acoustics",
    gen(rng) {
      const fmax = pick(rng, [150, 200, 250, 300]);
      const epw = pick(rng, [6, 8, 10]);
      const lam = C / fmax;
      const h = lam / epw;
      const o = opciones(rng, h, [
        { v: lam / 2, err: "λ/2 es el límite de <b>Nyquist</b>: alcanza para no aliasear una señal, pero no para que un elemento finito lineal represente bien una curva. En FEM se piden ~6–10 elementos por longitud de onda." },
        { v: C / (fmax * 2 * epw), err: "Te sobró un factor 2." },
        { v: lam, err: "Un elemento por longitud de onda no resuelve nada: no podés dibujar un seno con un solo tramo recto." },
      ], "m", 3);
      return {
        q: `Querés simular por FEM hasta ${dato(fmax, "Hz", 0)} con <b>${epw} elementos por longitud de onda</b>.<br>¿Qué tamaño de elemento <code>h</code> necesitás?`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>λ_min = c/f_max = 343/${fmax} = ${fmt(lam, 3)} m</code>`,
          `<code>h = λ_min / ${epw} = ${fmt(lam, 3)} / ${epw}</code>`,
          `<b>h ≈ ${fmt(h, 3)} m</b>`
        ) + `<p>Cuidado con el costo: <code>h</code> es lineal pero los grados de libertad escalan como <code>1/h³</code>. Duplicar f_max no duplica el problema — lo multiplica por ~8. Y con elementos lineales aparece además el <i>error de dispersión</i> (pollution), que crece con la frecuencia aunque mantengas los elementos por longitud de onda constantes: por eso a veces conviene subir el orden del elemento en vez de refinar.</p>`,
      };
    },
  },

  {
    id: "num-densidad-modal",
    area: "numerica",
    cat: "Densidad modal",
    dif: 3,
    src: "Weyl (1912) · Kuttruff, Room Acoustics · Analysis on Modal Density — referencias/",
    gen(rng) {
      const V = rnd(rng, 40, 150, 5);
      const f = pick(rng, [50, 80, 100, 125]);
      const B = pick(rng, [5, 10, 20]);
      // dN/df ≈ 4πV f²/c³  (término de volumen de Weyl)
      const dens = 4 * Math.PI * V * f ** 2 / C ** 3;
      const N = dens * B;

      const o = opciones(rng, N, [
        { v: 4 * Math.PI * V * f / C ** 3 * B, err: "La densidad modal va con <b>f²</b>, no con f: los modos se agolpan cada vez más rápido al subir en frecuencia." },
        { v: dens * B / (4 * Math.PI), err: "Te comiste el <code>4π</code> de la fórmula de Weyl." },
        { v: 4 * Math.PI * V * f ** 2 / C ** 2 * B, err: "Revisá las unidades: el denominador es <code>c³</code>. Con c² el resultado no queda adimensional." },
      ], "modos", 2);

      return {
        q: `Sala de ${dato(V, "m³", 0)}.<br>¿Cuántos modos hay, aproximadamente, en una banda de ${dato(B, "Hz", 0)} centrada en ${dato(f, "Hz", 0)}? (término de volumen de Weyl)`,
        opts: o.opts, ans: o.ans, errs: o.errs,
        why: pasos(
          `<code>dN/df ≈ 4π·V·f²/c³</code>`,
          `<code>= 4π · ${fmt(V, 0)} · ${f}² / 343³ = ${fmt(dens, 4)} modos/Hz</code>`,
          `<code>N ≈ ${fmt(dens, 4)} · ${B} Hz</code>`,
          `<b>N ≈ ${fmt(N, 2)} modos</b>`
        ) + `<p>Como crece con <b>f²</b>, la densidad explota rápido: a ${f * 2} Hz habría ~${fmt(dens * 4 * B, 2)} modos en la misma banda (4× más). Ése es justamente el argumento detrás de la frecuencia de Schroeder — llega un punto donde contar modos de a uno deja de tener sentido y conviene la descripción estadística.</p>`,
      };
    },
  },

];

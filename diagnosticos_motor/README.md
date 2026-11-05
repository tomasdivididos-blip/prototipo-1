# Diagnósticos del motor geométrico (R6 / normalización del detector)

Scripts one-off de la sesión del 5 Nov 2026 (v2.92) que establecieron la física
del empalme de energía R6 (`geometric_engine.composed_energy_response`) y el
hallazgo del sesgo +10% del EDT de la cola difusa. NO son benches oficiales del
repo (esos son `bench_geometric_r6.py` y el gate `validate_geometric_above_fs.py`,
ambos en la raíz); son la EVIDENCIA DE RESPALDO, persistida para reproducir el
razonamiento sin tener la conversación.

## Cómo correr
Desde la raíz del repo, con el Python de Anaconda y el PYTHONPATH apuntando a la
raíz (los scripts importan `geometry`, `geometric_engine`, etc., que viven ahí):

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH="$PWD" /c/Users/aceve/anaconda3/python.exe diagnosticos_motor/diag_shape.py
```

GOTCHA de la sesión: el tool Bash fallaba con `EROFS uv_spawn`; correr con
PowerShell (`$env:PYTHONPATH="<raiz>"; & "C:\Users\aceve\anaconda3\python.exe" diagnosticos_motor\diag_shape.py`)
funcionó. Los `xcheck_*` y `diag_flair_conv` necesitan `datasets/flair/data_FLAIR.mat`.
Cada corrida es pesada (miles de rayos); lanzar en background.

## Qué estableció cada script
- **diag_tail_bias.py** — barrido de α en shoebox. EDT inicial (0..−10 dB) ≈ Eyring
  (±2.5% en α=0.05→0.50); T30 asintótico = +12.6% CONSTANTE sobre Eyring (curvatura
  tardía), y T30/Sabine VARÍA → el tail NO es Sabine. Falsifica la hipótesis Sabine;
  el buildup del EDC no es el artefacto.
- **diag_shape.py** — barrido de FORMA a V y α fijos, paredes LISAS (sin voxel).
  EDT/Eyring crece monótono con S/V (cubo S/V=1.53→0.99; chata S/V=2.53→1.26). FIJA
  el mecanismo: el sesgo del EDT es la NO COMPACIDAD (varianza del camino libre),
  no la absorción. FLAIR S/V=2.06 predice ~1.12, medido 1.10 (match).
- **diag_flair_conv.py** — FLAIR real. El +10% del EDT NO es convergencia de la
  medición (gate 6k rayos/t_max 0.8 vs convergido 24k/2.0: 1.105 vs 1.095). Es físico.
- **diag_tail_norm.py** — KEYSTONE de la escala. (a) conservación Σw=q/α EXACTA
  (ratio 1.0000); (b) densidad 4w/(cS·dt): el valor en el PICO es transitorio de
  buildup (~1.73·q/V), no el régimen difuso.
- **diag_tail_norm2.py** — confirma w_dens=4w/(cS·dt)=(q/V)e^{−t/τ} en la REGIÓN
  DIFUSA (t≥t_mix): extrapolado w_dens(0)=q/V ratio 1.028, τ_fit/Eyring 1.05.
- **diag_order.py** — muestra que el pin EMPÍRICO de continuidad (igualar temprano
  especular a la cola en t_mix) es ruidoso por receptor y no mejora con max_order
  (el especular vive antes de la ventana). Motivó pasar a la escala ANALÍTICA
  g_tail=q/(πS), sin pin.
- **smoke_r6.py** — smoke de `composed_energy_response` (caminos early_specular
  False y True), sin regresión de import.
- **xcheck_flair_r6.py** — cross-check FLAIR: C80/D50 compuesto vs medido (135 mics)
  vs cola-sola. D50 matchea dentro del JND; C80 compuesto ~2-3 dB bajo (hereda el
  +10% del EDT); EDT compuesto ≈ cola (el directo es débil a r>r_c).
- **xcheck_flair_r6b.py** — el temprano ESPECULAR tampoco mueve el EDT de FLAIR
  (0.295→0.295): t_mix≈11 ms << ventana 0..−10 dB del EDT (~45 ms). Confirma que el
  +10% es irreducible por el empalme a esas distancias.

## Resultado neto
Escala del detector g_tail = q/(πS)·w DERIVADA (irradiancia difusa I=c·w/4 +
energía radiada q²/4πc + conservación Σw=q/α), validada no-circular por la
distancia crítica r_c=√(Sα/16π). El sesgo +10% del EDT es física del campo difuso
no exponencial (crece con S/V), no un defecto del motor ni del empalme.

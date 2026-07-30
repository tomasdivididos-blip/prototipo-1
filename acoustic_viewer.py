"""
acoustic_viewer.py
==================

Helpers de renderizado 3D para el modulo acustico, montados sobre el
IsoViewer (pyqtgraph.opengl).

Provee:
  - SourceMarkers: render de bolitas glowing en las posiciones de fuente.
  - ReceiverMarker: render de una cruz/punto para el receptor.
  - FieldSliceItem: render de un slice 2D coloreado segun magnitud del campo,
    con triangulos que se omiten fuera del recinto (mask).

Diseno: cada helper es desacoplable y se anade/quita del IsoViewer por nombre,
de modo que el panel acustico puede refrescar solo lo necesario sin tocar el
resto de la escena.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph.opengl as gl
from PyQt5.QtGui import QColor


# ---------------------------------------------------------------------------
# Color map de plasma (precomputado, sin matplotlib en runtime)
# ---------------------------------------------------------------------------
# Tabla con 32 escalones; suficiente para visualizacion.
_PLASMA = np.array([
    (0.050, 0.030, 0.530),
    (0.135, 0.025, 0.585),
    (0.215, 0.022, 0.622),
    (0.290, 0.030, 0.640),
    (0.360, 0.055, 0.645),
    (0.425, 0.085, 0.640),
    (0.488, 0.115, 0.620),
    (0.548, 0.150, 0.590),
    (0.605, 0.180, 0.555),
    (0.660, 0.210, 0.515),
    (0.710, 0.245, 0.475),
    (0.760, 0.275, 0.435),
    (0.805, 0.305, 0.395),
    (0.845, 0.340, 0.355),
    (0.880, 0.375, 0.320),
    (0.912, 0.410, 0.285),
    (0.940, 0.450, 0.250),
    (0.962, 0.490, 0.215),
    (0.978, 0.530, 0.185),
    (0.988, 0.575, 0.155),
    (0.993, 0.620, 0.125),
    (0.992, 0.665, 0.100),
    (0.986, 0.715, 0.080),
    (0.972, 0.765, 0.065),
    (0.955, 0.815, 0.060),
    (0.935, 0.865, 0.075),
    (0.916, 0.910, 0.105),
    (0.905, 0.955, 0.145),
    (0.910, 0.985, 0.190),
    (0.935, 0.998, 0.235),
    (0.965, 0.998, 0.275),
    (0.990, 0.995, 0.310),
], dtype=float)


def colormap_plasma(t: np.ndarray) -> np.ndarray:
    """t en [0,1] -> RGB. Soporta array NxM o 1D."""
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    idx = t * (len(_PLASMA) - 1)
    i0 = np.floor(idx).astype(int)
    i1 = np.minimum(i0 + 1, len(_PLASMA) - 1)
    a = (idx - i0)[..., None]
    return _PLASMA[i0] * (1 - a) + _PLASMA[i1] * a


def colormap_signed(t: np.ndarray) -> np.ndarray:
    """t en [-1,1] -> RGB (diverging azul-blanco-rojo)."""
    t = np.clip(np.asarray(t, dtype=float), -1.0, 1.0)
    out = np.zeros(t.shape + (3,), dtype=float)
    # Azul <-> blanco para t<0, blanco <-> rojo para t>0.
    neg = t < 0
    pos = t >= 0
    a_neg = -t[neg]                # 0..1
    out[neg, 0] = 1.0 - a_neg
    out[neg, 1] = 1.0 - a_neg
    out[neg, 2] = 1.0
    a_pos = t[pos]
    out[pos, 0] = 1.0
    out[pos, 1] = 1.0 - a_pos
    out[pos, 2] = 1.0 - a_pos
    return out


# ---------------------------------------------------------------------------
# Marcadores de fuente
# ---------------------------------------------------------------------------
def _sphere_mesh(center, radius=0.35, n=14, color=(1.0, 0.85, 0.2, 1.0)):
    """Crea un GLMeshItem esferico (UV sphere de baja densidad)."""
    cx, cy, cz = center
    phis = np.linspace(0, np.pi, n)
    thetas = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    verts = []
    for phi in phis:
        for theta in thetas:
            verts.append((
                cx + radius * np.sin(phi) * np.cos(theta),
                cy + radius * np.sin(phi) * np.sin(theta),
                cz + radius * np.cos(phi),
            ))
    verts = np.asarray(verts, dtype=float)
    nt = 2 * n
    faces = []
    for i in range(n - 1):
        for j in range(nt):
            j2 = (j + 1) % nt
            a = i * nt + j
            b = i * nt + j2
            c = (i + 1) * nt + j
            d = (i + 1) * nt + j2
            faces.append([a, c, b])
            faces.append([b, c, d])
    faces = np.asarray(faces, dtype=int)
    return gl.GLMeshItem(
        meshdata=gl.MeshData(vertexes=verts, faces=faces),
        smooth=True, color=color, shader="shaded", glOptions="translucent",
    )


def _baffle_wireframe(center, size, yaw_deg, pitch_deg=0.0, nseg=20):
    """Wireframe de un bafle para GLLinePlotItem(mode='lines'): 12 aristas del
    prisma + 2 circulos (woofer/tweeter) en la cara frontal. Devuelve una lista
    de puntos (x,y,z) en PARES (cada 2 puntos = un segmento de linea).

    Frente = cara con los parlantes, normal en (azimut `yaw_deg`, elevacion
    `pitch_deg`). Base local SIN roll: x'=profundidad (frente=n), y'=ancho
    (horizontal, nivelado), z'=alto (se inclina con el pitch). Con pitch=0
    reproduce exactamente el caso solo-yaw.
    """
    w, h, d = [float(v) for v in size]
    th = np.radians(float(yaw_deg))
    ph = np.radians(float(pitch_deg))
    c0 = np.asarray(center, dtype=float)
    # frente n; ancho ey horizontal; alto ez = n x ey (inclina con pitch).
    n = np.array([np.cos(ph) * np.cos(th), np.cos(ph) * np.sin(th), np.sin(ph)])
    ey = np.array([-np.sin(th), np.cos(th), 0.0])
    ez = np.cross(n, ey)

    def R(xp, yp, zp):                    # coords locales -> mundo
        p = c0 + xp * n + yp * ey + zp * ez
        return (float(p[0]), float(p[1]), float(p[2]))

    hx, hy, hz = d / 2.0, w / 2.0, h / 2.0
    box = [R(-hx, -hy, -hz), R(hx, -hy, -hz), R(hx, hy, -hz), R(-hx, hy, -hz),
           R(-hx, -hy, hz),  R(hx, -hy, hz),  R(hx, hy, hz),  R(-hx, hy, hz)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    segs = []
    for a, b in edges:
        segs.append(box[a]); segs.append(box[b])
    # Dos circulos en la cara frontal (x'=+hx): woofer abajo (grande), tweeter
    # arriba (chico). Cada circulo como bucle de segmentos.
    for (zc, rad) in [(-h * 0.18, w * 0.34), (h * 0.27, w * 0.15)]:
        ring = [R(hx + 0.012, rad * np.cos(2 * np.pi * k / nseg),
                  zc + rad * np.sin(2 * np.pi * k / nseg)) for k in range(nseg)]
        for k in range(nseg):
            segs.append(ring[k]); segs.append(ring[(k + 1) % nseg])
    return segs


class SourceMarkers:
    """Marcadores de fuente como BAFLES wireframe (prisma + 2 circulos en la cara
    frontal), en el MISMO estilo que el recinto (aristas rosas). T4.

    Render con GLLinePlotItem (patron IDENTICO a las aristas del recinto en
    viewer.py: pos float32, color unico, mode='lines', sin shader ni glOptions
    custom) -> visibilidad garantizada. La version previa usaba un GLMeshItem
    con shader=None + faceColors, que no renderizaba en escena.

    Usa DOS items persistentes (uno rosa = no-seleccionadas, uno naranja =
    seleccionada) y los actualiza IN-PLACE via `setData` — NO `removeItem`+
    `addItem` en cada frame. Esto es clave: reconstruir el scene graph en cada
    mousemove de un drag (mover/rotar/inclinar a 60+ Hz) cuelga el event loop
    (ver el mismo gotcha documentado en ReceiverMarker).

    La fuente es acusticamente omni; el bafle es solo visual. El picking/drag usa
    la proyeccion de `_source_positions` en viewer.py (independiente de este item).
    """

    _COL     = (0.96, 0.74, 0.95, 1.0)       # rosa, igual que EDGE_COLOR del recinto
    _COL_SEL = (0.98, 0.55, 0.05, 1.0)       # naranja (fuente seleccionada)
    _EMPTY = np.zeros((0, 3), dtype=np.float32)

    def __init__(self, viewer: gl.GLViewWidget):
        self.viewer = viewer
        self._item_normal = None
        self._item_sel = None

    def _ensure_items(self):
        if self._item_normal is None:
            self._item_normal = gl.GLLinePlotItem(
                pos=self._EMPTY, color=self._COL, width=2.2,
                antialias=True, mode="lines")
            self.viewer.addItem(self._item_normal)
        if self._item_sel is None:
            self._item_sel = gl.GLLinePlotItem(
                pos=self._EMPTY, color=self._COL_SEL, width=2.2,
                antialias=True, mode="lines")
            self.viewer.addItem(self._item_sel)

    def update(self, source_array, selected_idx: int = -1, **_):
        self._ensure_items()
        normal_segs, sel_segs = [], []
        for i, s in enumerate(source_array or []):
            yaw = (s.orientation if getattr(s, "orientation", None) is not None
                   else 90.0)                # default: frente hacia +Y
            pitch = float(getattr(s, "pitch", 0.0) or 0.0)
            size = getattr(s, "baffle_size", (0.30, 0.50, 0.40))
            segs = _baffle_wireframe(s.position, size, yaw, pitch)
            (sel_segs if i == selected_idx else normal_segs).extend(segs)
        # Actualizacion IN-PLACE (sin tocar el scene graph): rapido y sin cuelgue.
        for item, segs in ((self._item_normal, normal_segs),
                           (self._item_sel, sel_segs)):
            if segs:
                item.setData(pos=np.asarray(segs, dtype=np.float32))
                item.setVisible(True)
            else:
                item.setVisible(False)

    def set_positions(self, source_array, selected_idx: int = -1):
        """Actualiza los bafles in-place (barato; seguro en cada frame del drag)."""
        self.update(source_array, selected_idx=selected_idx)

    def clear(self):
        for it in (self._item_normal, self._item_sel):
            if it is not None:
                self.viewer.removeItem(it)
        self._item_normal = None
        self._item_sel = None


def _furniture_wireframe(furn, nseg=24):
    """Segmentos (pares de puntos) para GLLinePlotItem(mode='lines') de un mueble.

    Caja: 12 aristas del prisma con yaw sobre z. Cilindro: 2 anillos (piso/tope)
    + montantes verticales (invariante al yaw). Devuelve lista de (x,y,z) en
    PARES (cada 2 puntos = un segmento). El mueble es puramente geometrico aca;
    su efecto acustico va por el carve/xi/SBIR del panel.
    """
    kind = getattr(furn, "kind", "box")
    # Compound: unir los wireframes de las partes (cada una en el frame LOCAL del
    # compound) transformados al mundo por su position + yaw/pitch. Lo dibujado
    # coincide con lo tallado (mismos ejes que Furniture.contains).
    if kind == "compound" and getattr(furn, "parts", None):
        ex, ey, ez = furn._local_axes()
        c0 = np.asarray(furn.position, dtype=float)
        segs = []
        for part in furn.parts:
            for (x, y, z) in _furniture_wireframe(part, nseg):
                w = c0 + x * ex + y * ey + z * ez
                segs.append((float(w[0]), float(w[1]), float(w[2])))
        return segs
    # Mesh (CAD/OBJ): aristas de los triangulos, en coords mundo. Se dibujan las
    # aristas UNICAS (cada una una vez); si la malla es enorme (escaneo) se
    # submuestrea a MAX_EDGES para no colgar el render. Mismos ejes que
    # Furniture.contains/aabb -> lo dibujado coincide con lo tallado.
    if kind == "mesh" and getattr(furn, "mesh_verts", None) is not None:
        ex, ey, ez = furn._local_axes()
        c0 = np.asarray(furn.position, dtype=float)
        M = np.stack([ex, ey, ez])                       # filas ex,ey,ez
        v = np.asarray(furn.mesh_verts, float) @ M + c0  # local -> mundo
        faces = np.asarray(furn.mesh_faces, int)
        e = np.vstack([faces[:, [0, 1]], faces[:, [1, 2]], faces[:, [2, 0]]])
        e = np.unique(np.sort(e, axis=1), axis=0)
        MAX_EDGES = 4000
        if len(e) > MAX_EDGES:
            e = e[np.linspace(0, len(e) - 1, MAX_EDGES).astype(int)]
        pairs = v[e.reshape(-1)]                          # (2*Ne, 3)
        return [tuple(float(c) for c in p) for p in pairs]
    cx, cy, cz = [float(v) for v in furn.position]
    sx, sy, sz = [float(v) for v in furn.size]
    segs = []
    if kind == "cylinder":
        r = sx / 2.0
        z0, z1 = cz - sz / 2.0, cz + sz / 2.0
        ang = [2 * np.pi * k / nseg for k in range(nseg)]
        ring0 = [(cx + r * np.cos(a), cy + r * np.sin(a), z0) for a in ang]
        ring1 = [(cx + r * np.cos(a), cy + r * np.sin(a), z1) for a in ang]
        for ring in (ring0, ring1):
            for k in range(nseg):
                segs.append(ring[k]); segs.append(ring[(k + 1) % nseg])
        step = max(1, nseg // 8)             # ~8 montantes verticales
        for k in range(0, nseg, step):
            segs.append(ring0[k]); segs.append(ring1[k])
        return segs
    # Caja con yaw + pitch + roll. Los ejes se DELEGAN en Furniture._local_axes
    # (fuente unica) en vez de recalcularlos aca: el wireframe no puede divergir
    # de lo que se talla ni de la colision.
    if hasattr(furn, "_local_axes"):
        ex, ey, ez = furn._local_axes()
    else:                                     # objeto minimo (tests): solo yaw
        th = np.radians(float(getattr(furn, "orientation", 0.0) or 0.0))
        c, s = np.cos(th), np.sin(th)
        ex = np.array([c, s, 0.0]); ey = np.array([-s, c, 0.0])
        ez = np.array([0.0, 0.0, 1.0])
    c0 = np.array([cx, cy, cz])
    hx, hy, hz = sx / 2.0, sy / 2.0, sz / 2.0

    def R(a, b, d):                          # coords locales -> mundo
        p = c0 + a * ex + b * ey + d * ez
        return (float(p[0]), float(p[1]), float(p[2]))

    box = [R(-hx, -hy, -hz), R(hx, -hy, -hz), R(hx, hy, -hz), R(-hx, hy, -hz),
           R(-hx, -hy, hz),  R(hx, -hy, hz),  R(hx, hy, hz),  R(-hx, hy, hz)]
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (4, 5), (5, 6), (6, 7), (7, 4),
             (0, 4), (1, 5), (2, 6), (3, 7)]
    for a, b in edges:
        segs.append(box[a]); segs.append(box[b])
    return segs


class FurnitureMarkers:
    """Muebles como wireframe (caja/cilindro) en el visor 3D.

    Mismo patron PROBADO que SourceMarkers y las aristas del recinto:
    GLLinePlotItem (pos float32, color unico, mode='lines') actualizado IN-PLACE
    via `setData` — NUNCA `removeItem`+`addItem` por frame, y NUNCA
    `GLMeshItem(shader=None, faceColors=...)` (no renderiza en esta escena).
    Dos items persistentes: normal (verde-azulado, para distinguir de las
    fuentes rosas) y seleccionado (naranja).
    """

    _COL     = (0.40, 0.85, 0.75, 1.0)       # verde-azulado (mueble)
    _COL_SEL = (0.98, 0.55, 0.05, 1.0)       # naranja (mueble seleccionado)
    _EMPTY = np.zeros((0, 3), dtype=np.float32)

    def __init__(self, viewer: gl.GLViewWidget):
        self.viewer = viewer
        self._item_normal = None
        self._item_sel = None

    def _ensure_items(self):
        if self._item_normal is None:
            self._item_normal = gl.GLLinePlotItem(
                pos=self._EMPTY, color=self._COL, width=2.0,
                antialias=True, mode="lines")
            self.viewer.addItem(self._item_normal)
        if self._item_sel is None:
            self._item_sel = gl.GLLinePlotItem(
                pos=self._EMPTY, color=self._COL_SEL, width=2.4,
                antialias=True, mode="lines")
            self.viewer.addItem(self._item_sel)

    def update(self, muebles, selected_idx: int = -1, **_):
        self._ensure_items()
        normal_segs, sel_segs = [], []
        for i, m in enumerate(muebles or []):
            segs = _furniture_wireframe(m)
            (sel_segs if i == selected_idx else normal_segs).extend(segs)
        for item, segs in ((self._item_normal, normal_segs),
                           (self._item_sel, sel_segs)):
            if segs:
                item.setData(pos=np.asarray(segs, dtype=np.float32))
                item.setVisible(True)
            else:
                item.setVisible(False)

    def set_positions(self, muebles, selected_idx: int = -1):
        self.update(muebles, selected_idx=selected_idx)

    def clear(self):
        for it in (self._item_normal, self._item_sel):
            if it is not None:
                self.viewer.removeItem(it)
        self._item_normal = None
        self._item_sel = None


class ReceiverMarker:
    """Una cruz 3D simple para marcar el receptor.

    Mantiene el GLLinePlotItem en el scene graph entre llamadas y actualiza
    in-place via `setData` (igual que `SourceMarkers.set_positions`). Antes
    cada `update(pos)` hacia `removeItem + addItem`, lo que durante un
    Shift+drag a 60+ Hz obliga a pyqtgraph a reconstruir el scene graph en
    cada frame — felt como cuelgue, especialmente con CAD cargado.
    """

    _COLOR = (0.30, 0.95, 0.85, 1.0)

    def __init__(self, viewer):
        self.viewer = viewer
        self.item = None

    def update(self, pos, size: float = 0.55):
        """Actualiza la posicion del marker. Si `pos` es None, lo oculta."""
        if pos is None:
            self.clear()
            return
        lines = self._lines_for(pos, size)
        if self.item is None:
            # Primera vez: crear el item y agregarlo al scene graph.
            self.item = gl.GLLinePlotItem(
                pos=lines, color=self._COLOR,
                width=4.5, antialias=True, mode="lines",
            )
            self.viewer.addItem(self.item)
        else:
            # Actualizar in-place; no toca el scene graph.
            self.item.setData(pos=lines)

    @staticmethod
    def _lines_for(pos, size: float = 0.55) -> np.ndarray:
        x, y, z = pos
        return np.array([
            [x - size, y, z], [x + size, y, z],
            [x, y - size, z], [x, y + size, z],
            [x, y, z - size], [x, y, z + size],
        ], dtype=float)

    def clear(self):
        if self.item is not None:
            self.viewer.removeItem(self.item)
        self.item = None


# ---------------------------------------------------------------------------
# Slice de campo
# ---------------------------------------------------------------------------
def _quad_mesh_from_grid(X, Y, Z, colors, mask):
    """Construye verts, faces, vertex_colors para un grid 2D.

    Omite los quads cuyos 4 vertices estan fuera del recinto (mask=False).
    """
    nx, ny = X.shape
    verts = np.stack([X, Y, Z], axis=-1).reshape(-1, 3)
    cols = colors.reshape(-1, colors.shape[-1])

    faces = []
    face_colors = []
    for i in range(nx - 1):
        for j in range(ny - 1):
            a = i * ny + j
            b = (i + 1) * ny + j
            c = (i + 1) * ny + (j + 1)
            d = i * ny + (j + 1)
            # 4 vertices del quad
            if mask is not None and not (mask[i, j] and mask[i + 1, j] and
                                          mask[i + 1, j + 1] and mask[i, j + 1]):
                continue
            faces.append([a, b, c])
            faces.append([a, c, d])
            face_colors.append(cols[a])
            face_colors.append(cols[a])
    if not faces:
        return None
    faces = np.asarray(faces, dtype=int)
    face_colors = np.asarray(face_colors, dtype=float)
    return verts, faces, cols, face_colors


class FieldSliceItem:
    """Render de un FieldSlice como mesh coloreado en el viewer."""

    def __init__(self, viewer):
        self.viewer = viewer
        self.item = None

    def update(self, field_slice, signed: bool = False, alpha: float = 0.75):
        """field_slice: acoustic_analysis.FieldSlice.

        Soporta los tres planos axis-alineados:
          axis=2 → XY (z=cte):  X3=C1(x), Y3=C2(y), Z3=cte
          axis=1 → XZ (y=cte):  X3=C1(x), Y3=cte,   Z3=C2(z)
          axis=0 → YZ (x=cte):  X3=cte,   Y3=C1(y), Z3=C2(z)
        """
        self.clear()
        if field_slice is None:
            return

        C1   = field_slice.X       # primera coord de barrido
        C2   = field_slice.Y       # segunda coord de barrido
        cte  = float(field_slice.z)
        ax   = getattr(field_slice, 'axis', 2)
        P    = field_slice.P
        mask = field_slice.mask

        # Construir coordenadas 3D según el eje fijo
        if ax == 2:                                   # plano XY
            X, Y, Z = C1, C2, np.full_like(C1, cte)
        elif ax == 1:                                 # plano XZ
            X, Y, Z = C1, np.full_like(C1, cte), C2
        else:                                         # plano YZ (ax==0)
            X, Y, Z = np.full_like(C1, cte), C1, C2

        if signed:
            # Mapeo simetrico al maximo absoluto.
            m = float(np.nanmax(np.abs(P))) if np.isfinite(P).any() else 1.0
            m = max(m, 1e-12)
            t = P / m
            rgb = colormap_signed(t)
        else:
            m = float(np.nanmax(P)) if np.isfinite(P).any() else 1.0
            m = max(m, 1e-12)
            t = P / m
            rgb = colormap_plasma(t)

        # alpha por punto (cero donde mask es False).
        alpha_arr = np.where(mask, alpha, 0.0) if mask is not None else \
                    np.full(X.shape, alpha)
        colors = np.concatenate([rgb, alpha_arr[..., None]], axis=-1)

        built = _quad_mesh_from_grid(X, Y, Z, colors, mask)
        if built is None:
            return
        verts, faces, vert_colors, face_colors = built

        md = gl.MeshData(vertexes=verts, faces=faces, faceColors=face_colors)
        self.item = gl.GLMeshItem(
            meshdata=md, smooth=False,
            shader=None, glOptions="translucent",
        )
        self.viewer.addItem(self.item)

    def clear(self):
        if self.item is not None:
            self.viewer.removeItem(self.item)
        self.item = None


# ---------------------------------------------------------------------------
# Preview interactivo del plano de corte
# ---------------------------------------------------------------------------
class SlicePlanePreview:
    """Cuadrilatero semi-transparente que sigue el cursor para previsualizar
    el plano de corte antes de confirmarlo con un click.

    axis=2 → plano XY (z=cte)  quad horizontal
    axis=1 → plano XZ (y=cte)  quad vertical frontal
    axis=0 → plano YZ (x=cte)  quad vertical lateral

    El quad se encoge un pequeño margen hacia adentro (SHRINK_RATIO) para
    EVITAR coplanaridad con las paredes del recinto. Para una sala shoebox
    perfecta, los bordes del quad coincidirian EXACTAMENTE con las aristas
    de las paredes (renderizadas como wireframe rosa) -> el quad translucido
    se "perdia" bajo las aristas y era invisible. Con el shrink, los bordes
    del quad caen claramente DENTRO del recinto, sin tocarlos.

    Tambien dibujamos un BORDE WIREFRAME del quad (gl.GLLinePlotItem) en
    cian brillante para que se vea siempre, aun si el llenado translucido
    queda detras de las paredes.
    """

    _COLOR = (0.30, 0.85, 1.00, 0.40)   # celeste translucido (mas opaco que antes)
    _EDGE_COLOR = (0.50, 1.00, 1.00, 0.95)   # cian brillante para el borde
    SHRINK_RATIO = 0.02   # 2% margen hacia adentro

    def __init__(self, viewer: gl.GLViewWidget):
        self.viewer = viewer
        self._item = None
        self._edge_item = None

    def update(self, axis: int, offset: float, aabb_min, aabb_max):
        self.clear()
        mn = np.asarray(aabb_min, dtype=float).copy()
        mx = np.asarray(aabb_max, dtype=float).copy()

        # Encoger el quad por SHRINK_RATIO en los ejes que NO son el del corte.
        # Asi el quad cabe holgado adentro del recinto y no z-fighting con paredes.
        for i in (0, 1, 2):
            if i == axis:
                continue   # el eje del corte no se encoge (cae en el offset)
            margin = (mx[i] - mn[i]) * self.SHRINK_RATIO
            mn[i] += margin
            mx[i] -= margin

        if axis == 2:                          # plano XY
            pts = np.array([
                [mn[0], mn[1], offset],
                [mx[0], mn[1], offset],
                [mx[0], mx[1], offset],
                [mn[0], mx[1], offset],
            ])
        elif axis == 1:                        # plano XZ
            pts = np.array([
                [mn[0], offset, mn[2]],
                [mx[0], offset, mn[2]],
                [mx[0], offset, mx[2]],
                [mn[0], offset, mx[2]],
            ])
        else:                                  # plano YZ (axis==0)
            pts = np.array([
                [offset, mn[1], mn[2]],
                [offset, mx[1], mn[2]],
                [offset, mx[1], mx[2]],
                [offset, mn[1], mx[2]],
            ])

        # Llenado translucido
        faces  = np.array([[0, 1, 2], [0, 2, 3]], dtype=int)
        colors = np.tile(self._COLOR, (2, 1))
        md = gl.MeshData(vertexes=pts, faces=faces, faceColors=colors)
        self._item = gl.GLMeshItem(
            meshdata=md, smooth=False, glOptions="translucent"
        )
        self.viewer.addItem(self._item)

        # Borde wireframe (siempre visible aun si el llenado queda detras)
        loop = np.vstack([pts, pts[0:1]])    # cerrar el bucle al primer punto
        self._edge_item = gl.GLLinePlotItem(
            pos=loop.astype(np.float32),
            color=self._EDGE_COLOR,
            width=2.5,
            antialias=True,
            mode="line_strip",
        )
        self.viewer.addItem(self._edge_item)

    def clear(self):
        if self._item is not None:
            self.viewer.removeItem(self._item)
            self._item = None
        if self._edge_item is not None:
            self.viewer.removeItem(self._edge_item)
            self._edge_item = None


# ---------------------------------------------------------------------------
# Colormap rainbow HSV para campo con fuente (azul=min, verde=medio, rojo=max)
# ---------------------------------------------------------------------------
# Paradas explicitas para que los colores nombrados caigan exactamente en
# sus posiciones perceptualmente equidistantes (en HSV puro, el amarillo
# y el cyan son bandas estrechas que no caen en 1/6 ni 5/6 del rango).
# Cada parada: (t_position, R, G, B) en [0,1].
_RAINBOW_STOPS = np.array([
    [0.000, 0.05, 0.10, 0.95],   # 1. azul
    [0.167, 0.10, 0.65, 0.98],   # 2. celeste (sky blue)
    [0.333, 0.10, 0.92, 0.75],   # 3. turquesa
    [0.500, 0.30, 0.92, 0.25],   # 4. verde claro (CENTRO)
    [0.667, 0.98, 0.95, 0.10],   # 5. amarillo
    [0.833, 0.98, 0.55, 0.08],   # 6. naranja
    [1.000, 0.95, 0.10, 0.10],   # 7. rojo
], dtype=float)


def colormap_rainbow(t: np.ndarray) -> np.ndarray:
    """t en [0,1] -> RGB rainbow saturado de 7 paradas perceptualmente parejas.

    Mapeo:
      t=0.000 -> azul
      t=0.167 -> celeste
      t=0.333 -> turquesa
      t=0.500 -> verde claro  (centro de la escala)
      t=0.667 -> amarillo
      t=0.833 -> naranja
      t=1.000 -> rojo

    Interpola linealmente entre paradas. Colores diseñados para alta
    saturacion -> vibrantes incluso con muchos puntos overlap en alta
    resolucion.
    """
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    pos = _RAINBOW_STOPS[:, 0]
    cols = _RAINBOW_STOPS[:, 1:]
    # Para cada t, encontrar el bucket (parada i tal que pos[i] <= t < pos[i+1])
    # np.searchsorted devuelve el indice donde t deberia insertarse.
    idx = np.clip(np.searchsorted(pos, t, side="right") - 1, 0, len(pos) - 2)
    t0 = pos[idx]
    t1 = pos[idx + 1]
    alpha = ((t - t0) / (t1 - t0))[..., None]    # 0 en parada i, 1 en parada i+1
    c0 = cols[idx]
    c1 = cols[idx + 1]
    return (1.0 - alpha) * c0 + alpha * c1


# Alias compatibilidad: mantiene importaciones anteriores funcionando.
colormap_pressure_rb = colormap_rainbow


# ---------------------------------------------------------------------------
# Colormap divergent vivido azul-gris-rojo para forma modal (sin fuente)
# ---------------------------------------------------------------------------
def colormap_signed_vivid(t: np.ndarray) -> np.ndarray:
    """t en [-1,1] -> RGB azul vibrante a rojo vibrante pasando por GRIS.

    El gris central (no blanco) elimina el efecto de "blanqueamiento" cuando
    se renderizan miles de puntos overlap a alta resolucion. El alpha (1-|t|)^0.5
    satura los colores mas rapido fuera del centro, dando una sensacion mas
    vibrante incluso para valores moderados.

    Puntos clave:
      t=-1   -> azul saturado (0.10, 0.30, 1.0)
      t=-0.5 -> azul-gris vibrante (interpolacion sqrt)
      t= 0   -> gris medio    (0.35, 0.35, 0.35)
      t=+0.5 -> rojo-gris vibrante
      t=+1   -> rojo saturado (1.0, 0.15, 0.10)
    """
    t = np.clip(np.asarray(t, dtype=float), -1.0, 1.0)
    GRAY = np.array([0.35, 0.35, 0.35])
    RED  = np.array([1.00, 0.15, 0.10])
    BLUE = np.array([0.10, 0.30, 1.00])
    # Saturacion via sqrt(|t|): cerca de cero acelera la transicion gris->color
    a = np.sqrt(np.abs(t))[..., None]  # 0 en t=0, 1 en |t|=1
    target = np.where(t[..., None] >= 0, RED, BLUE)
    return (1.0 - a) * GRAY + a * target


# ---------------------------------------------------------------------------
# Mapa de calor 3D (nube de puntos coloreada por presion)
# ---------------------------------------------------------------------------
class PressureField3D:
    """Renderiza el campo de presion acustica 3D como nube de puntos coloreada.

    Azul=minimo, verde=medio, rojo=maximo presion.
    Solo muestra puntos dentro del recinto.
    """

    def __init__(self, viewer: gl.GLViewWidget):
        self.viewer = viewer
        self._item = None

    def update(self, points: np.ndarray, pressure_abs: np.ndarray,
               point_size: int = 7):
        """Actualiza la visualizacion.

        points: (N,3) posiciones dentro del recinto
        pressure_abs: (N,) amplitud de presion en cada punto
        """
        self.clear()
        if points is None or len(points) == 0:
            return
        p_max = float(pressure_abs.max()) if pressure_abs.max() > 0 else 1.0
        t = pressure_abs / p_max                     # normalizado [0,1]
        # Rainbow HSV: azul (min) -> celeste -> turquesa -> verde claro (medio)
        # -> amarillo -> naranja -> rojo (max). Saturado para vibrancia
        # incluso con muchos puntos overlap a alta resolucion.
        rgb = colormap_rainbow(t)
        alpha = (0.4 + 0.5 * t).reshape(-1, 1)      # mas opaco donde hay mas presion
        rgba = np.concatenate([rgb, alpha], axis=1).astype(np.float32)

        self._item = gl.GLScatterPlotItem(
            pos=points.astype(np.float32),
            color=rgba,
            size=point_size,
            pxMode=True,
        )
        self.viewer.addItem(self._item)

    def update_signed(self, points: np.ndarray, values: np.ndarray,
                      point_size: int = 7):
        """Muestra forma modal con signo: AZUL=negativo, GRIS=cero, ROJO=positivo.

        Reemplazo del blanco central por gris para evitar que los puntos cerca
        de cero "blanqueen" la imagen al subir la resolucion. Usa colors mas
        vibrantes (saturacion por sqrt(|t|)).
        """
        self.clear()
        if points is None or len(points) == 0:
            return
        m = float(np.max(np.abs(values))) if len(values) > 0 else 1.0
        m = max(m, 1e-12)
        t = values / m                         # normalizado a [-1, 1]
        rgb = colormap_signed_vivid(t)         # (N, 3) — gris en t=0, vibrante en |t|=1
        # Alpha mas opaco fuera del centro: puntos cerca de cero se ven menos
        # (no aportan informacion modal). Minimo 0.25 para que se vean.
        alpha = (0.25 + 0.70 * np.abs(t)).reshape(-1, 1)
        rgba = np.concatenate([rgb, alpha], axis=1).astype(np.float32)
        self._item = gl.GLScatterPlotItem(
            pos=points.astype(np.float32),
            color=rgba,
            size=point_size,
            pxMode=True,
        )
        self.viewer.addItem(self._item)

    def clear(self):
        if self._item is not None:
            self.viewer.removeItem(self._item)
            self._item = None


# ---------------------------------------------------------------------------
# Flechas de gradiente del campo acustico
# ---------------------------------------------------------------------------
class GradientArrows:
    """Representa el gradiente del campo de presion como pequenas flechas blancas.

    Las flechas apuntan en la direccion del gradiente de presion (proporcional
    a la velocidad de particula). La longitud es proporcional a la magnitud.
    """

    def __init__(self, viewer: gl.GLViewWidget):
        self.viewer = viewer
        self._item = None
        self._head_items = []

    def update(self, origins: np.ndarray, gradients: np.ndarray,
               scale: float = 1.5, color=(1.0, 1.0, 1.0, 0.85)):
        """origins: (N,3), gradients: (N,3). Normaliza y escala las flechas."""
        self.clear()
        if origins is None or len(origins) == 0:
            return

        mags = np.linalg.norm(gradients, axis=1, keepdims=True)
        mag_max = float(mags.max()) if mags.max() > 0 else 1.0
        dirs = gradients / np.maximum(mags, 1e-12)
        lengths = (mags / mag_max).ravel()              # 0..1

        # Segmentos (tail, head) intercalados para GLLinePlotItem mode='lines'
        tails = origins
        heads = origins + dirs * (lengths[:, None] * scale)
        segs = np.empty((2 * len(origins), 3), dtype=np.float32)
        segs[0::2] = tails.astype(np.float32)
        segs[1::2] = heads.astype(np.float32)

        self._item = gl.GLLinePlotItem(
            pos=segs,
            color=color,
            width=2.5,
            antialias=True,
            mode='lines',
        )
        self.viewer.addItem(self._item)

    def clear(self):
        if self._item is not None:
            self.viewer.removeItem(self._item)
            self._item = None



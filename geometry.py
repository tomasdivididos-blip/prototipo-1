"""Geometria parametrica de un recinto tipo prisma generalizado.

Modelo:
- Si `base_polygon` es None: prisma regular de N lados inscripto en una elipse
  de semiejes W/2 y L/2.
- Si `base_polygon` es lista de (x, y) en metros: la usa como contorno del piso.
  Soporta poligonos no convexos via triangulacion por ear-clipping.
- En ambos casos: taper / twist / inclinacion por pared / pitch de techo y piso /
  arco del techo (subdivision + barrel-vault).
"""

import numpy as np


# ---------- Rotaciones / pitches ----------
def _rot_x(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rot_y(a):
    c, s = np.cos(a), np.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _apply_pitch(points, pitch_x_deg, pitch_y_deg, pivot):
    px = np.radians(pitch_x_deg)
    py = np.radians(pitch_y_deg)
    R = _rot_y(py) @ _rot_x(px)
    return (points - pivot) @ R.T + pivot


# ---------- Helpers de poligonos 2D ----------
def _signed_area(pts):
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return 0.5 * s


def _is_ccw(pts):
    return _signed_area(pts) > 0.0


def _is_left_turn(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) > 0


def _point_in_triangle(p, a, b, c):
    def sign(p1, p2, p3):
        return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])
    d1, d2, d3 = sign(p, a, b), sign(p, b, c), sign(p, c, a)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def _triangulate(pts):
    """Ear-clipping. Devuelve lista de (i, j, k) en orden CCW."""
    n = len(pts)
    if n < 3:
        return []
    if n == 3:
        return [(0, 1, 2)]

    indices = list(range(n))
    if not _is_ccw(pts):
        indices.reverse()

    triangles = []
    safety = n * n
    while len(indices) > 3 and safety > 0:
        safety -= 1
        m = len(indices)
        ear_found = False
        for k in range(m):
            ai = indices[(k - 1) % m]
            bi = indices[k]
            ci = indices[(k + 1) % m]
            a, b, c = pts[ai], pts[bi], pts[ci]
            if not _is_left_turn(a, b, c):
                continue
            ok = True
            for j in indices:
                if j in (ai, bi, ci):
                    continue
                if _point_in_triangle(pts[j], a, b, c):
                    ok = False
                    break
            if ok:
                triangles.append((ai, bi, ci))
                indices.pop(k)
                ear_found = True
                break
        if not ear_found:
            for k in range(1, len(indices) - 1):
                triangles.append((indices[0], indices[k], indices[k + 1]))
            return triangles

    triangles.append((indices[0], indices[1], indices[2]))
    return triangles


# ---------------------------------------------------------------------------
# Muestreo de curvas parametricas para shape="circle" / "ellipse"
# ---------------------------------------------------------------------------
# Las primitivas curvas se materializan como poligonos finos (n samples)
# para que el mallador voxel y el visualizador puedan consumirlas sin
# cambios. La INFORMACION parametrica (rx, ry, samples) se preserva via
# los propios argumentos de make_room: cualquier consumer puede
# reconstruir la curva exacta llamando a sample_room_curve(...) abajo.
#
# Por que esto importa para P2 isoparametrico (futuro):
#   un mallador que sepa "esta arista esta sobre la elipse rx=W/2, ry=L/2"
#   puede colocar el midpoint EN la curva real (no en el promedio
#   aritmetico de dos vertices), recuperando la fidelidad geometrica que
#   la voxelizacion pierde con la frontera escalonada.
# ---------------------------------------------------------------------------
def sample_room_curve(shape: str, width: float, length: float,
                      n_samples: int = 96) -> np.ndarray:
    """Devuelve los puntos (x, y) que materializan la curva de la planta.

    shape: "circle" o "ellipse". Para "polygon" devuelve None.
    Para "circle": radio = min(width, length) / 2; centrado en (0, 0).
    Para "ellipse": semieje x = width/2, semieje y = length/2.
    """
    if shape == "circle":
        r = min(float(width), float(length)) / 2.0
        rx, ry = r, r
    elif shape == "ellipse":
        rx = float(width) / 2.0
        ry = float(length) / 2.0
    else:
        return None

    n = max(8, int(n_samples))
    # Muestreo uniforme en el parametro t (no en arc-length; suficiente
    # para una elipse de excentricidad moderada).
    t = np.linspace(0.0, 2.0 * np.pi, n, endpoint=False)
    return np.column_stack([rx * np.cos(t), ry * np.sin(t)])


def _outward_directions(polygon_xy):
    """Para cada vertice de un poligono CCW devuelve un versor saliente."""
    pts = np.asarray(polygon_xy, dtype=float)
    n = len(pts)
    reversed_input = False
    if not _is_ccw(pts.tolist()):
        pts = pts[::-1].copy()
        reversed_input = True

    edge_dirs = pts[np.arange(1, n + 1) % n] - pts
    edge_lens = np.maximum(np.linalg.norm(edge_dirs, axis=1, keepdims=True), 1e-12)
    edge_unit = edge_dirs / edge_lens
    edge_out = np.column_stack([edge_unit[:, 1], -edge_unit[:, 0]])

    prev_out = edge_out[np.arange(-1, n - 1) % n]
    curr_out = edge_out
    v_out = prev_out + curr_out
    v_lens = np.maximum(np.linalg.norm(v_out, axis=1, keepdims=True), 1e-12)
    v_out = v_out / v_lens

    if reversed_input:
        v_out = v_out[::-1].copy()
    return v_out


# ---------- Subdivision + arco ----------
def _subdivide_triangles(verts_3d, tris, levels, n_polygon_boundary=None):
    """Subdivision Loop-style: cada triangulo -> 4 sub-triangulos via puntos medios.
    Repetido `levels` veces.

    n_polygon_boundary: los primeros N vertices de verts_3d son las esquinas del
    poligono. Las ARISTAS del poligono (entre vertices i y (i+1)%N consecutivos)
    son borde compartido con las paredes; sus puntos medios tampoco reciben arco.
    Las DIAGONALES de la triangulacion (que no son aristas del poligono) si generan
    vertices interiores que si reciben arco.

    Devuelve (new_verts, new_tris, boundary_mask).
    boundary_mask[i] == True  ->  vertice en arista del poligono (no recibe arco).
    """
    n_poly = n_polygon_boundary or 0
    if levels <= 0:
        bm = [i < n_poly for i in range(len(verts_3d))]
        return np.asarray(verts_3d, dtype=float).copy(), list(tris), bm

    verts = [np.asarray(v, dtype=float).copy() for v in verts_3d]

    # Aristas del poligono: solo las conexiones entre vertices consecutivos.
    # Las diagonales de la triangulacion NO se incluyen aqui.
    boundary_edges: set[tuple[int, int]] = set()
    for i in range(n_poly):
        j = (i + 1) % n_poly
        boundary_edges.add((min(i, j), max(i, j)))

    # Mascara inicial: los primeros n_poly vertices son borde.
    is_boundary = [i < n_poly for i in range(len(verts))]

    for _ in range(levels):
        edge_mid: dict[tuple[int, int], int] = {}
        new_tris = []
        new_boundary_edges: set[tuple[int, int]] = set()

        # Primera pasada: crear todos los puntos medios (evitar funcion anidada).
        all_edges: list[tuple[int, int]] = []
        for (a, b, c) in tris:
            for pi, pj in ((a, b), (b, c), (c, a)):
                k = (min(pi, pj), max(pi, pj))
                if k not in edge_mid:
                    all_edges.append(k)

        for (pi, pj) in all_edges:
            key = (pi, pj)
            if key in edge_mid:
                continue
            m = (verts[pi] + verts[pj]) / 2.0
            mid_idx = len(verts)
            edge_mid[key] = mid_idx
            verts.append(m)
            # El punto medio es borde SOLO si la arista padre es arista del poligono.
            on_polygon_edge = key in boundary_edges
            is_boundary.append(on_polygon_edge)
            if on_polygon_edge:
                # Las sub-aristas heredan el caracter de borde.
                new_boundary_edges.add((min(pi, mid_idx), max(pi, mid_idx)))
                new_boundary_edges.add((min(pj, mid_idx), max(pj, mid_idx)))

        # Segunda pasada: construir nuevos triangulos.
        for (a, b, c) in tris:
            m_ab = edge_mid[(min(a, b), max(a, b))]
            m_bc = edge_mid[(min(b, c), max(b, c))]
            m_ca = edge_mid[(min(c, a), max(c, a))]
            new_tris.extend([
                (a, m_ab, m_ca),
                (m_ab, b, m_bc),
                (m_ca, m_bc, c),
                (m_ab, m_bc, m_ca),
            ])

        tris = new_tris
        boundary_edges = new_boundary_edges  # heredar para el siguiente nivel

    return np.asarray(verts, dtype=float), tris, is_boundary


def _compute_polygon_and_top_xy(width, length, height, n_walls=4,
                                taper=0.0, twist=0.0,
                                wall_inclinations=None, base_polygon=None):
    """Devuelve (bottom_xy, top_xy, outward, n) — el polygon base y el polygon
    superior despues de taper/twist/wall_inclinations (SIN ceiling pitch).
    Es el helper comun usado por make_room y make_arch_ribs.
    """
    if base_polygon is not None and len(base_polygon) >= 3:
        bottom_xy = np.asarray(base_polygon, dtype=float)
        if not _is_ccw(bottom_xy.tolist()):
            bottom_xy = bottom_xy[::-1].copy()
        n = len(bottom_xy)
        outward = _outward_directions(bottom_xy.tolist())
    else:
        n = max(3, int(n_walls))
        angles = np.linspace(0.0, 2 * np.pi, n, endpoint=False) + np.pi / n
        cos_max = max(float(np.max(np.abs(np.cos(angles)))), 1e-9)
        sin_max = max(float(np.max(np.abs(np.sin(angles)))), 1e-9)
        rx = (width / 2.0) / cos_max
        ry = (length / 2.0) / sin_max
        bottom_xy = np.column_stack([rx * np.cos(angles), ry * np.sin(angles)])
        outward = np.column_stack([np.cos(angles), np.sin(angles)])

    scale = max(0.05, 1.0 + float(taper))
    twist_rad = np.radians(twist)
    c_t, s_t = np.cos(twist_rad), np.sin(twist_rad)
    R2d = np.array([[c_t, -s_t], [s_t, c_t]])
    top_xy = (bottom_xy * scale) @ R2d.T

    if wall_inclinations is not None and len(wall_inclinations) > 0:
        incl = np.zeros(n)
        src = np.asarray(wall_inclinations, dtype=float)
        incl[: min(n, len(src))] = src[: min(n, len(src))]
        wall_disp = float(height) * np.tan(np.radians(incl))
        vertex_disp = np.zeros(n)
        for i in range(n):
            vertex_disp[i] = 0.5 * (wall_disp[(i - 1) % n] + wall_disp[i])
        top_xy[:, 0] += outward[:, 0] * vertex_disp
        top_xy[:, 1] += outward[:, 1] * vertex_disp

    return bottom_xy, top_xy, outward, n


def _line_intersect_polygon(polygon_xy, slice_value, axis):
    """Devuelve coordenadas (en el OTRO eje) donde la linea axis=slice_value
    cruza las aristas del poligono. axis: 0 (linea vertical) o 1 (horizontal).
    """
    intersections = []
    n = len(polygon_xy)
    for i in range(n):
        j = (i + 1) % n
        v1, v2 = polygon_xy[i], polygon_xy[j]
        a1, a2 = v1[axis], v2[axis]
        if (a1 - slice_value) * (a2 - slice_value) > 1e-12:
            continue
        if abs(a1 - a2) < 1e-12:
            continue
        t = (slice_value - a1) / (a2 - a1)
        if 0.0 <= t <= 1.0:
            other = v1[1 - axis] + t * (v2[1 - axis] - v1[1 - axis])
            intersections.append(other)
    return intersections


def _augment_polygon_with_ridge(bottom_xy, top_xy, ridge_offset):
    """Inserta vertices en el poligono donde la cumbre del gable cruza las
    aristas. Devuelve (new_bottom, new_top, ridge_indices).
    ridge_indices = indices en new_top de los vertices recien insertados.
    """
    px, py = top_xy[:, 0], top_xy[:, 1]
    x_min, x_max = float(px.min()), float(px.max())
    y_min, y_max = float(py.min()), float(py.max())
    range_x, range_y = x_max - x_min, y_max - y_min
    ridge_offset = max(-0.99, min(0.99, float(ridge_offset)))

    if range_x <= range_y:
        slice_axis = 0
        slice_value = (x_min + x_max) / 2.0 + ridge_offset * range_x / 2.0
    else:
        slice_axis = 1
        slice_value = (y_min + y_max) / 2.0 + ridge_offset * range_y / 2.0

    new_bottom, new_top = [], []
    ridge_indices = []
    n = len(top_xy)
    for i in range(n):
        new_bottom.append(bottom_xy[i].copy())
        new_top.append(top_xy[i].copy())
        j = (i + 1) % n
        a1 = top_xy[i, slice_axis]
        a2 = top_xy[j, slice_axis]
        if (a1 - slice_value) * (a2 - slice_value) < -1e-9:
            t = (slice_value - a1) / (a2 - a1)
            nb = bottom_xy[i] + t * (bottom_xy[j] - bottom_xy[i])
            nt = top_xy[i] + t * (top_xy[j] - top_xy[i])
            ridge_indices.append(len(new_top))
            new_bottom.append(nb)
            new_top.append(nt)
    return np.array(new_bottom), np.array(new_top), ridge_indices


def _triangulate_with_ridge(polygon, ridge_indices):
    """Triangula un poligono splitteandolo por una arista de cumbre.
    Solo soporta exactamente 2 vertices de cumbre (caso convexo). Si hay otros,
    cae al ear-clipping estandar.

    El split garantiza que la arista entre los 2 ridge vertices forme parte de la
    triangulacion (necesario para que el techo a dos aguas tenga la forma correcta).
    """
    if len(ridge_indices) != 2:
        return _triangulate(polygon)

    r1, r2 = sorted(ridge_indices)
    n = len(polygon)

    # Sub-poligono A: indices r1, r1+1, ..., r2 (en orden CCW del poligono original)
    idx_a = list(range(r1, r2 + 1))
    poly_a = [polygon[i] for i in idx_a]
    tris_a_local = _triangulate(poly_a)
    tris_a = [(idx_a[a], idx_a[b], idx_a[c]) for (a, b, c) in tris_a_local]

    # Sub-poligono B: r2, r2+1, ..., n-1, 0, 1, ..., r1
    idx_b = list(range(r2, n)) + list(range(0, r1 + 1))
    poly_b = [polygon[i] for i in idx_b]
    tris_b_local = _triangulate(poly_b)
    tris_b = [(idx_b[a], idx_b[b], idx_b[c]) for (a, b, c) in tris_b_local]

    return tris_a + tris_b


def _apply_gable_inplace(ceiling_verts, polygon_xy, peak_height, ridge_offset=0.0):
    """Techo a dos aguas: dos planos meeting en una cumbre.
    El eje de la cumbre es el LARGO del bbox; la pendiente corre por el CORTO.
    ridge_offset in [-1, 1]: 0 = centro de la pendiente.
    Aplica perfil triangular a TODOS los vertices (incluido boundary).
    """
    if peak_height <= 0:
        return
    px, py = polygon_xy[:, 0], polygon_xy[:, 1]
    x_min, x_max = float(px.min()), float(px.max())
    y_min, y_max = float(py.min()), float(py.max())
    range_x, range_y = x_max - x_min, y_max - y_min
    ridge_offset = max(-0.999, min(0.999, float(ridge_offset)))

    if range_x <= range_y:
        center, rad, idx = (x_min + x_max) / 2.0, max(range_x / 2.0, 1e-9), 0
    else:
        center, rad, idx = (y_min + y_max) / 2.0, max(range_y / 2.0, 1e-9), 1

    for v in ceiling_verts:
        t = max(-1.0, min(1.0, (v[idx] - center) / rad))
        if t <= ridge_offset:
            v[2] += peak_height * (t + 1.0) / max(ridge_offset + 1.0, 1e-9)
        else:
            v[2] += peak_height * (1.0 - t) / max(1.0 - ridge_offset, 1e-9)


def _apply_shed_inplace(ceiling_verts, polygon_xy, peak_height):
    """Techo inclinado de una sola caida (shed): rampa lineal de 0 a peak."""
    if peak_height <= 0:
        return
    px, py = polygon_xy[:, 0], polygon_xy[:, 1]
    x_min, x_max = float(px.min()), float(px.max())
    y_min, y_max = float(py.min()), float(py.max())
    range_x, range_y = x_max - x_min, y_max - y_min

    if range_x <= range_y:
        center, rad, idx = (x_min + x_max) / 2.0, max(range_x / 2.0, 1e-9), 0
    else:
        center, rad, idx = (y_min + y_max) / 2.0, max(range_y / 2.0, 1e-9), 1

    for v in ceiling_verts:
        t = max(-1.0, min(1.0, (v[idx] - center) / rad))
        v[2] += peak_height * (t + 1.0) / 2.0


def _arch_circle_params(W_half: float, arch_height: float):
    """Parametros del arco circular dado chord 2*W_half y peak height arch_height.

    Devuelve (R, z_offset, h_eff). El arco circular pasa por (-W_half, 0),
    (0, h_eff) y (W_half, 0), con todos los puntos a la misma distancia R del
    centro del circulo (curvatura uniforme). h_eff se cappea a W_half
    (semicirculo) — alturas mayores no tienen sentido geometrico (el arco
    sobresaldria de los muros).

    z(dx) = z_offset + sqrt(R^2 - dx^2)
    """
    h = min(float(arch_height), float(W_half))
    if h <= 1e-9 or W_half <= 1e-9:
        return None, None, 0.0
    R = (W_half * W_half + h * h) / (2.0 * h)
    return R, h - R, h


def _apply_arch_inplace(ceiling_verts, polygon_xy, arch_height,
                        boundary_mask=None):
    """Suma offset z (perfil de ARCO CIRCULAR) a los vertices INTERIORES.

    Los vertices de borde (boundary_mask[i]==True) se omiten -> el techo
    empalma sin huecos con la parte superior de las paredes.

    El arco corre a lo largo del eje MAS CORTO del bbox (barrel-vault con
    columna paralela al eje mas largo). Curvatura uniforme: todos los puntos
    de la superficie cilindrica estan a igual distancia R del eje del cilindro.
    """
    if arch_height <= 0:
        return

    px = polygon_xy[:, 0]
    py = polygon_xy[:, 1]
    x_min, x_max = float(px.min()), float(px.max())
    y_min, y_max = float(py.min()), float(py.max())
    range_x = x_max - x_min
    range_y = y_max - y_min

    if range_x <= range_y:
        center = (x_min + x_max) / 2.0
        W_half = max(range_x / 2.0, 1e-9)
        idx = 0
    else:
        center = (y_min + y_max) / 2.0
        W_half = max(range_y / 2.0, 1e-9)
        idx = 1

    R, z_offset, _ = _arch_circle_params(W_half, arch_height)
    if R is None:
        return

    for i, v in enumerate(ceiling_verts):
        if boundary_mask is not None and boundary_mask[i]:
            continue
        dx = v[idx] - center
        if abs(dx) >= W_half:
            continue
        val = R * R - dx * dx
        if val < 0:
            continue
        v[2] += z_offset + np.sqrt(val)


# ---------- API publica ----------
def make_room(width: float, length: float, height: float,
              n_walls: int = 4,
              taper: float = 0.0,
              twist: float = 0.0,
              ceiling_pitch_x: float = 0.0,
              ceiling_pitch_y: float = 0.0,
              floor_pitch_x: float = 0.0,
              floor_pitch_y: float = 0.0,
              arch_height: float = 0.0,
              wall_inclinations=None,
              base_polygon=None,
              roof_type: str = "arch",
              ridge_offset: float = 0.0,
              subdiv_levels: int = 4,
              shape: str = "polygon",
              curve_samples: int = 96,
              **_):
    """Devuelve (vertices, triangulos, aristas).
    roof_type: "flat" | "arch" | "gable" | "shed".
    ridge_offset: posicion de la cumbre para gable, in [-1, 1].
    subdiv_levels: niveles de subdivision del techo en arco.
        4 (default): techo suave para visualizacion.
        0: sin subdivision -> aristas del techo coinciden con aristas
           del polígono, malla TOPOLOGICAMENTE consistente con las paredes
           (watertight). Necesario para pasar la malla a gmsh sin huecos.

    shape: "polygon" (default) | "circle" | "ellipse".
        - "polygon": comportamiento original (usa n_walls o base_polygon).
        - "circle": planta circular de radio min(width, length)/2,
          muestreada en `curve_samples` puntos. Ignora n_walls y base_polygon.
        - "ellipse": planta eliptica de semiejes (width/2, length/2),
          muestreada en `curve_samples` puntos. Ignora n_walls y base_polygon.
    curve_samples: solo se usa con shape="circle" o "ellipse". Default 96
        (~0.05% de desviacion vs curva real para excentricidad moderada).
    """
    # Primitivas curvas: materializar como poligono fino antes de
    # entregar al pipeline (que sigue siendo polinomial). La informacion
    # parametrica (shape, width, length, curve_samples) queda accesible
    # via sample_room_curve(...) para consumers futuros (P2 isoparametrico).
    if shape in ("circle", "ellipse"):
        base_polygon = sample_room_curve(shape, width, length, curve_samples)

    bottom_xy, top_xy, _outward, n = _compute_polygon_and_top_xy(
        width, length, height, n_walls, taper, twist,
        wall_inclinations, base_polygon
    )

    rt = (roof_type or "arch").lower()
    has_relief = arch_height > 0 and rt in ("arch", "gable", "shed")

    # Para gable: insertamos vertices de cumbre en el poligono. Asi cada pared
    # perpendicular a la cumbre se parte en 2 sub-paredes (trapezoides), evitando
    # agujeros entre el techo a dos aguas y las paredes.
    ridge_indices = []
    if has_relief and rt == "gable":
        bottom_xy, top_xy, ridge_indices = _augment_polygon_with_ridge(
            bottom_xy, top_xy, ridge_offset
        )
        n = len(top_xy)

    # Piso
    bottom = np.column_stack([bottom_xy, np.zeros(n)])
    bottom = _apply_pitch(bottom, floor_pitch_x, floor_pitch_y,
                          pivot=np.array([0.0, 0.0, 0.0]))

    top_orig = np.column_stack([top_xy, np.full(n, float(height))])

    # Triangulacion del piso (mismas conexiones aplican al techo).
    # Para gable: split por la cumbre para que la arista del techo aparezca correcta.
    if has_relief and rt == "gable" and len(ridge_indices) == 2:
        floor_tris = _triangulate_with_ridge(bottom_xy.tolist(), ridge_indices)
    else:
        floor_tris = _triangulate(bottom_xy.tolist())

    if has_relief and rt == "arch":
        # Arco: necesita subdivision para curvas suaves.
        # Boundary mask -> el techo empalma con las paredes sin huecos.
        ceil_verts, ceil_tris, boundary_mask = _subdivide_triangles(
            top_orig, floor_tris, levels=int(subdiv_levels),
            n_polygon_boundary=n
        )
        _apply_arch_inplace(ceil_verts, top_xy, arch_height,
                            boundary_mask=boundary_mask)
    elif has_relief and rt == "gable":
        # Dos aguas: piecewise lineal, sin subdivision. El poligono ya esta
        # augmentado con vertices de cumbre.
        ceil_verts = top_orig.copy()
        ceil_tris = list(floor_tris)
        _apply_gable_inplace(ceil_verts, top_xy, arch_height, ridge_offset)
    elif has_relief and rt == "shed":
        # Inclinado: rampa lineal aplicada a las esquinas.
        ceil_verts = top_orig.copy()
        ceil_tris = list(floor_tris)
        _apply_shed_inplace(ceil_verts, top_xy, arch_height)
    else:
        ceil_verts = top_orig.copy()
        ceil_tris = list(floor_tris)

    # Pitch del techo (despues del arco -> rota toda la cupula junta)
    ceil_verts = _apply_pitch(
        ceil_verts, ceiling_pitch_x, ceiling_pitch_y,
        pivot=np.array([0.0, 0.0, float(height)])
    )

    # Vertice global = piso (n) + techo (n + subdivision)
    vertices = np.vstack([bottom, ceil_verts]).astype(np.float32)

    triangles = []
    # Piso (CW desde arriba -> normal hacia abajo)
    for (a, b, c) in floor_tris:
        triangles.append([a, c, b])
    # Techo (CCW desde arriba -> normal hacia arriba)
    for (a, b, c) in ceil_tris:
        triangles.append([n + a, n + b, n + c])
    # Paredes: usan los primeros n vertices del techo (los del poligono original)
    for i in range(n):
        j = (i + 1) % n
        triangles.append([i, j, n + j])
        triangles.append([i, n + j, n + i])
    triangles = np.array(triangles, dtype=np.int32)

    edges = []
    for i in range(n):
        j = (i + 1) % n
        edges.append([i, j])
        edges.append([n + i, n + j])
        edges.append([i, n + i])
    edges = np.array(edges, dtype=np.int32)

    return vertices, triangles, edges, n


def make_lofted_room(base_polygon, wall_profiles, *, corner_tol=1e-4):
    """Recinto LOFTEADO (Modelo 1 del plan_mejoras_v2.13): planta + perfil de
    TOPE por pared. Piso plano en z=0; techo = tapa que sigue los topes.

    Parameters
    ----------
    base_polygon : (n, 2)
        Footprint en planta (orden CCW). El piso es este poligono en z=0.
    wall_profiles : list de longitud n
        wall_profiles[i] describe la arista i -> (i+1). Es una secuencia
        [(t, z), ...] con t en [0, 1] a lo largo de la arista (t=0 = esquina i,
        t=1 = esquina i+1) y z = altura del tope [m] >= 0. Debe incluir t=0 y
        t=1. La altura de esquina compartida entre paredes adyacentes debe
        coincidir (se chequea con corner_tol). Un perfil plano [(0, H), (1, H)]
        reproduce una pared de altura constante H.

    Returns
    -------
    (vertices, triangles, edges, n_perimeter)
        Construccion CONFORME y watertight: piso y techo comparten el perimetro
        muestreado; las paredes son tiras de quads entre ambos. Con perfiles
        planos a H constante, el volumen es exactamente area_planta * H (oraculo
        de regresion contra el shoebox de make_room).

    Notas
    -----
    El techo se triangula por ear-clipping del perimetro (mismas diagonales que
    el piso); como todos sus vertices estan sobre el rim, queda determinado sin
    interpolar interior -> watertight garantizado. gmsh probablemente rechace la
    malla (T-junctions en aristas oblicuas), pero el voxel la come sin problema.
    """
    poly = np.asarray(base_polygon, dtype=float)
    if poly.shape[0] < 3:
        raise ValueError("base_polygon necesita >= 3 vertices")
    if not _is_ccw(poly.tolist()):
        raise ValueError("base_polygon debe estar en orden CCW")
    n = poly.shape[0]
    if len(wall_profiles) != n:
        raise ValueError(f"se esperaban {n} perfiles, llegaron {len(wall_profiles)}")

    def _norm_profile(prof):
        """Ordena por t, garantiza t=0 y t=1 (hold-flat si faltan)."""
        p = sorted(((float(t), float(z)) for t, z in prof), key=lambda q: q[0])
        if p[0][0] > 0.0:
            p = [(0.0, p[0][1])] + p
        if p[-1][0] < 1.0:
            p = p + [(1.0, p[-1][1])]
        return p

    # Perimetro muestreado: por arista tomamos t en [0, 1) (la esquina j la
    # aporta el t=0 de la arista siguiente -> sin duplicar vertices).
    perim_xy, rim_z = [], []
    profs = [_norm_profile(wp) for wp in wall_profiles]
    for i in range(n):
        j = (i + 1) % n
        # consistencia de altura en la esquina compartida j.
        z_end_i = profs[i][-1][1]
        z_start_next = profs[j][0][1]
        if abs(z_end_i - z_start_next) > corner_tol:
            raise ValueError(
                f"altura de esquina inconsistente entre pared {i} (z={z_end_i:.3f}) "
                f"y pared {j} (z={z_start_next:.3f}) en la esquina {j}")
        for (t, z) in profs[i][:-1]:           # incluye t=0, excluye t=1
            x = poly[i, 0] + t * (poly[j, 0] - poly[i, 0])
            y = poly[i, 1] + t * (poly[j, 1] - poly[i, 1])
            perim_xy.append((x, y))
            rim_z.append(z)

    M = len(perim_xy)
    perim_xy = np.asarray(perim_xy, dtype=float)
    rim_z = np.asarray(rim_z, dtype=float)

    floor = np.column_stack([perim_xy, np.zeros(M)])
    ceil = np.column_stack([perim_xy, rim_z])
    vertices = np.vstack([floor, ceil]).astype(np.float32)

    tris2d = _triangulate(perim_xy.tolist())

    triangles = []
    for (a, b, c) in tris2d:
        triangles.append([a, c, b])            # piso: normal hacia abajo
    for (a, b, c) in tris2d:
        triangles.append([M + a, M + b, M + c])   # techo: normal hacia arriba
    for k in range(M):                          # paredes: tiras de quads
        kn = (k + 1) % M
        triangles.append([k, kn, M + kn])
        triangles.append([k, M + kn, M + k])
    triangles = np.asarray(triangles, dtype=np.int32)

    edges = []
    for k in range(M):
        kn = (k + 1) % M
        edges.append([k, kn])                   # perimetro piso
        edges.append([M + k, M + kn])           # perimetro techo (rim)
        edges.append([k, M + k])                # vertical
    edges = np.asarray(edges, dtype=np.int32)

    return vertices, triangles, edges, M


def origin_offset(vertices, mode):
    """Offset (3,) que hay que RESTAR a la malla para cumplir la convencion
    de origen (0,0,0) elegida. Vector cero si no hay que mover nada.

    mode:
      - "auto"   : cada camino usa su convencion natural (parametrico centrado,
                   planta dibujada como se dibujo, CAD centrado al importar).
                   Es el comportamiento historico -> compatibilidad con .room
                   guardados. Offset cero.
      - "center" : el centro del AABB en planta (XY) cae en (0, 0).
      - "corner" : la esquina inferior-izquierda del AABB (xmin, ymin) cae en
                   (0, 0) -> el recinto vive en el cuadrante positivo.

    Solo traslada en XY (el piso ya vive en z=0 en todos los caminos; el CAD
    se apoya en z=0 al importar). Usa el AABB de TODA la malla: con taper o
    paredes inclinadas el tope puede sobresalir de la planta, y el AABB total
    es lo que el usuario ve en el visor.
    """
    m = (mode or "auto").lower()
    v = np.asarray(vertices)
    if m in ("auto", "") or len(v) == 0:
        return np.zeros(3)
    xmin, xmax = float(v[:, 0].min()), float(v[:, 0].max())
    ymin, ymax = float(v[:, 1].min()), float(v[:, 1].max())
    if m == "corner":
        return np.array([xmin, ymin, 0.0])
    if m == "center":
        return np.array([(xmin + xmax) / 2.0, (ymin + ymax) / 2.0, 0.0])
    raise ValueError(f"origin_mode desconocido: {mode!r} (auto|center|corner)")


def anchor_vertices(vertices, mode):
    """Re-ancla la malla segun la convencion de origen (ver origin_offset)."""
    off = origin_offset(vertices, mode)
    if abs(off[0]) < 1e-12 and abs(off[1]) < 1e-12:
        return vertices
    v = np.asarray(vertices)
    return (v - off).astype(v.dtype)


def build_room_geometry(params: dict):
    """Punto unico de construccion de la superficie del recinto desde `params`.

    Despacha: si `params` trae `base_polygon` + `wall_profiles` consistentes
    (mismo largo) -> recinto LOFTEADO (`make_lofted_room`, Modelo 1). Si no ->
    prisma parametrico (`make_room`). Devuelve (vertices, triangles, edges, n),
    igual firma que `make_room`. Si los perfiles son invalidos, cae al prisma
    de forma defensiva (no rompe el render).

    `params["origin_mode"]` ("auto" | "center" | "corner") re-ancla la malla
    resultante segun la convencion de origen elegida (ver anchor_vertices).
    """
    poly = params.get("base_polygon")
    profiles = params.get("wall_profiles")
    out = None
    if poly and profiles and len(poly) >= 3 and len(profiles) == len(poly):
        try:
            out = make_lofted_room(poly, profiles)
        except Exception:
            out = None   # perfiles invalidos -> prisma
    if out is None:
        out = make_room(**params)
    v, t, e, n = out
    v = anchor_vertices(v, params.get("origin_mode", "auto"))
    return v, t, e, n


def make_arch_ribs(width=6.0, length=8.0, height=3.0, n_walls=4,
                   taper=0.0, twist=0.0, arch_height=0.0,
                   ceiling_pitch_x=0.0, ceiling_pitch_y=0.0,
                   wall_inclinations=None, base_polygon=None,
                   roof_type="arch", n_ribs=5, n_points=30, **_):
    """Costillas del arco para visualizar en 3D.
    Solo se generan para roof_type='arch'.
    Las costillas siguen el contorno real del polygon top (con wall_inclinations)
    y reciben ceiling_pitch al final, asi siempre empalman con las aristas
    actuales del techo.
    """
    rt = (roof_type or "arch").lower()
    if arch_height <= 0 or rt != "arch":
        return []

    _bottom, top_xy, _outward, n = _compute_polygon_and_top_xy(
        width, length, height, n_walls, taper, twist,
        wall_inclinations, base_polygon
    )

    px, py = top_xy[:, 0], top_xy[:, 1]
    x_min, x_max = float(px.min()), float(px.max())
    y_min, y_max = float(py.min()), float(py.max())
    range_x, range_y = x_max - x_min, y_max - y_min
    h = float(height)

    ribs = []

    if range_x <= range_y:
        cx, W_half = (x_min + x_max) / 2.0, max(range_x / 2.0, 1e-9)
        R, z_offset, _ = _arch_circle_params(W_half, arch_height)
        for y_pos in np.linspace(y_min, y_max, n_ribs + 2)[1:-1]:
            ints = _line_intersect_polygon(top_xy, y_pos, axis=1)
            if len(ints) < 2:
                continue
            x_a, x_b = float(min(ints)), float(max(ints))
            pts = []
            for s in np.linspace(0.0, 1.0, n_points):
                xv = x_a + s * (x_b - x_a)
                dx = xv - cx
                if R is None or abs(dx) >= W_half:
                    z_add = 0.0
                else:
                    val = R * R - dx * dx
                    z_add = z_offset + np.sqrt(val) if val >= 0 else 0.0
                pts.append([xv, y_pos, h + z_add])
            rib = np.array(pts, dtype=float)
            rib = _apply_pitch(rib, ceiling_pitch_x, ceiling_pitch_y,
                               pivot=np.array([0.0, 0.0, h]))
            ribs.append(rib.astype(np.float32))
    else:
        cy, W_half = (y_min + y_max) / 2.0, max(range_y / 2.0, 1e-9)
        R, z_offset, _ = _arch_circle_params(W_half, arch_height)
        for x_pos in np.linspace(x_min, x_max, n_ribs + 2)[1:-1]:
            ints = _line_intersect_polygon(top_xy, x_pos, axis=0)
            if len(ints) < 2:
                continue
            y_a, y_b = float(min(ints)), float(max(ints))
            pts = []
            for s in np.linspace(0.0, 1.0, n_points):
                yv = y_a + s * (y_b - y_a)
                dy = yv - cy
                if R is None or abs(dy) >= W_half:
                    z_add = 0.0
                else:
                    val = R * R - dy * dy
                    z_add = z_offset + np.sqrt(val) if val >= 0 else 0.0
                pts.append([x_pos, yv, h + z_add])
            rib = np.array(pts, dtype=float)
            rib = _apply_pitch(rib, ceiling_pitch_x, ceiling_pitch_y,
                               pivot=np.array([0.0, 0.0, h]))
            ribs.append(rib.astype(np.float32))

    return ribs


def room_metrics(vertices, triangles):
    v = vertices.astype(np.float64)
    a = v[triangles[:, 0]]
    b = v[triangles[:, 1]]
    c = v[triangles[:, 2]]
    cross = np.cross(b - a, c - a)
    tri_areas = 0.5 * np.linalg.norm(cross, axis=1)
    surface = float(tri_areas.sum())
    volume = float(np.abs(np.einsum('ij,ij->i', a, cross).sum()) / 6.0)
    return volume, surface

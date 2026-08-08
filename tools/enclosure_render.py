#!/usr/bin/env python3
"""
Raytraced renders of the AsciiArt enclosure.

Geometry is built from docs/panel-connectors-guide.html, not invented:

    footprint      92 x 105 mm      (x = east-west, y = north-south)
    height         62 mm north, 25 mm south, 19 deg fascia
    parting plane  z = 25 mm        (base tray below, sloped lid above)
    wall           3 mm
    camera lens    z = 31 mm, centred on the north face
    ports          mini-HDMI south, USB-C (PWR IN) north, both on the east wall,
                   both centred on z = 25 so the plane halves them
    fascia, north to south: encoder knob, 2.4in panel, shutdown button

Everything is a signed distance field, marched in numpy. The floor is
intersected analytically and excluded from the object SDF, which is most of
the speed. Shading is one area-light key plus a sky fill, SDF soft shadows,
SDF ambient occlusion, GGX specular and an optional diffuse GI bounce.

    python3 enclosure_render.py hero     [--w 1200] [--ss 2] [--gi 1]
    python3 enclosure_render.py exploded

Pure stdlib + numpy: no PIL, no OpenGL, no Blender. PNG is written by hand.
"""

import math
import os
import struct
import sys
import time
import zlib

import numpy as np

F = np.float32

# ---------------------------------------------------------------- dimensions

W_EW = 92.0                      # east-west footprint
D_NS = 105.0                     # north-south footprint
H_S = 25.0                       # south height == parting plane
H_N = 62.0                       # north height
WALL = 3.0
FLOOR_T = 3.0
PART_Z = 25.0
SLOPE = math.atan2(H_N - H_S, D_NS)      # 19.4 deg
M_SLOPE = math.tan(SLOPE)
COS_A, SIN_A = math.cos(SLOPE), math.sin(SLOPE)
FACE_LEN = D_NS / COS_A                  # 111.3 mm of fascia

LID_S_Y = -42.6                  # lid stops here; base carries a flat deck south of it

CAM_Z = 31.0                     # camera lens centre on the north wall
PORT_HDMI_Y = -12.0              # mini-HDMI, south end of the Pi's port edge
PORT_USBC_Y = 18.0               # USB-C PWR IN, north end

# positions along the fascia, measured from its south edge
S_BUTTON = 15.0
S_PANEL = 48.0
S_KNOB = 92.0
SCREEN_W, SCREEN_H = 48.9, 36.7  # ILI9341 2.4in active area, landscape

BIG = F(1e5)

# ------------------------------------------------------------------ sdf math


def sd_box(p, b, r=0.0):
    """Exact SDF of a box of half-extents b, optionally rounded by r."""
    q = np.abs(p) - (np.asarray(b, F) - r)
    m = np.maximum(q, 0.0)
    return np.sqrt((m * m).sum(-1)) + np.minimum(q.max(-1), 0.0) - r


def sd_cyl(p, axis, half, rad):
    """Capped cylinder aligned to axis 0/1/2, centred at the origin."""
    o = [0, 1, 2]
    o.remove(axis)
    d = np.sqrt(p[..., o[0]] ** 2 + p[..., o[1]] ** 2) - rad
    h = np.abs(p[..., axis]) - half
    return np.minimum(np.maximum(d, h), 0.0) + np.sqrt(
        np.maximum(d, 0.0) ** 2 + np.maximum(h, 0.0) ** 2
    )


def smax(a, b, k):
    h = np.clip(0.5 + 0.5 * (a - b) / k, 0.0, 1.0)
    return b + (a - b) * h + k * h * (1.0 - h)


def plane_fascia(p, off=0.0):
    """Signed distance to the sloped outer face; positive above it."""
    return (p[..., 2] - M_SLOPE * p[..., 1] - (PART_Z + M_SLOPE * D_NS / 2)) * COS_A + off


def fascia_frame():
    """Origin, up-slope tangent, east tangent and outward normal of the fascia."""
    o = np.array([0.0, -D_NS / 2, PART_Z], F)
    u = np.array([0.0, COS_A, SIN_A], F)          # south -> north, up the slope
    v = np.array([1.0, 0.0, 0.0], F)              # east
    n = np.array([0.0, -SIN_A, COS_A], F)         # out of the face
    return o, u, v, n


FO, FU, FV, FN = fascia_frame()


def to_fascia(p, s, lift=0.0):
    """World point -> fascia-local (east, up-slope, out-of-face) about station s."""
    q = p - (FO + FU * s + np.array([0.0, 0.0, lift], F))
    return np.stack([q @ FV, q @ FU, q @ FN], -1)


# -------------------------------------------------------------------- scene

# material ids
(M_BASE, M_LID, M_SCREEN, M_KNOB, M_RING, M_LENSBTN, M_CAMLENS, M_PCB, M_BLACK,
 M_HAT, M_CONN, M_FLOOR) = range(12)
N_PARTS = 11


def sdf_parts(p, lift, interior):
    """Distance to each material group. Returns a list of length N_PARTS."""
    out = [None] * N_PARTS

    # ---- base tray -------------------------------------------------------
    shell = sd_box(p - np.array([0, 0, PART_Z / 2], F),
                   (W_EW / 2, D_NS / 2, PART_Z / 2), r=1.4)
    cav = sd_box(p - np.array([0, 0, (FLOOR_T + 90) / 2], F),
                 (W_EW / 2 - WALL, D_NS / 2 - WALL, (90 - FLOOR_T) / 2), r=1.0)
    base = np.maximum(shell, -cav)
    # flat deck closing the strip south of the lid
    deck = sd_box(p - np.array([0, (-D_NS / 2 + LID_S_Y) / 2, PART_Z - 1.5], F),
                  (W_EW / 2 - WALL, (LID_S_Y + D_NS / 2) / 2, 1.5))
    base = np.minimum(base, deck)

    # ---- lid -------------------------------------------------------------
    q = p - np.array([0, 0, lift], F)
    lshell = smax(sd_box(q - np.array([0, 0, H_N / 2], F),
                         (W_EW / 2, D_NS / 2, H_N / 2), r=1.4),
                  plane_fascia(q), 1.6)
    lcav = np.maximum(sd_box(q - np.array([0, 0, H_N / 2], F),
                             (W_EW / 2 - WALL, D_NS / 2 - WALL, H_N / 2 + 5), r=1.0),
                      plane_fascia(q, WALL))
    lid = np.maximum(lshell, -lcav)
    lid = np.maximum(lid, (PART_Z + 0.35) - q[..., 2])  # 0.35 mm parting gap
    lid = np.maximum(lid, -(q[..., 1] - LID_S_Y))      # nothing south of the deck

    # ---- holes through the shell ----------------------------------------
    # camera lens, north wall
    camlid = sd_cyl(q - np.array([0, D_NS / 2, CAM_Z], F), 1, 12.0, 4.7)
    lid = np.maximum(lid, -camlid)

    # vent slots above the camera
    for i in range(5):
        v = sd_box(q - np.array([0, D_NS / 2, 47.0 + i * 3.4], F), (9.0, 8.0, 1.1), r=0.5)
        lid = np.maximum(lid, -v)

    # connector pockets on the east wall, halved by the parting plane
    hdmi = sd_box(p - np.array([W_EW / 2, PORT_HDMI_Y, PART_Z], F), (8.0, 5.9, 2.5), r=0.6)
    usbc = sd_box(p - np.array([W_EW / 2, PORT_USBC_Y, PART_Z], F), (8.0, 4.8, 1.9), r=0.6)
    hdmil = sd_box(q - np.array([W_EW / 2, PORT_HDMI_Y, PART_Z], F), (8.0, 5.9, 2.5), r=0.6)
    usbcl = sd_box(q - np.array([W_EW / 2, PORT_USBC_Y, PART_Z], F), (8.0, 4.8, 1.9), r=0.6)
    base = np.maximum(base, -np.minimum(hdmi, usbc))
    lid = np.maximum(lid, -np.minimum(hdmil, usbcl))

    # The connectors are one piece each, captured between the two shells, so
    # they live in world space and stay with the base when the lid lifts.
    ex = W_EW / 2
    sh_h = sd_box(p - np.array([ex - 1.7, PORT_HDMI_Y, PART_Z], F), (2.7, 5.4, 2.15), r=0.7)
    sh_u = sd_box(p - np.array([ex - 1.7, PORT_USBC_Y, PART_Z], F), (2.7, 4.3, 1.55), r=0.75)
    mo_h = sd_box(p - np.array([ex - 1.0, PORT_HDMI_Y, PART_Z], F), (3.8, 4.4, 1.3), r=0.45)
    mo_u = sd_box(p - np.array([ex - 1.0, PORT_USBC_Y, PART_Z], F), (3.8, 3.35, 0.72), r=0.7)
    conn = np.maximum(np.minimum(sh_h, sh_u), -np.minimum(mo_h, mo_u))
    out[M_CONN] = conn
    # black inside each mouth: the HDMI cavity and the USB-C tongue
    tongue = sd_box(p - np.array([ex - 4.3, PORT_USBC_Y, PART_Z], F), (1.7, 2.85, 0.33), r=0.3)
    hdmi_in = sd_box(p - np.array([ex - 4.6, PORT_HDMI_Y, PART_Z], F), (1.6, 4.3, 1.2), r=0.4)
    conn_black = np.minimum(tongue, hdmi_in)

    # screen aperture + a shallow recess frame around it
    fp = to_fascia(q, S_PANEL)
    ap = sd_box(fp, (SCREEN_W / 2, SCREEN_H / 2, 12.0), r=0.8)
    rec = sd_box(fp - np.array([0, 0, -0.5], F), (SCREEN_W / 2 + 2.2, SCREEN_H / 2 + 2.2, 1.2), r=1.0)
    lid = np.maximum(lid, -np.minimum(ap, rec))

    # knob bushing hole and button hole
    kp = to_fascia(q, S_KNOB)
    lid = np.maximum(lid, -sd_cyl(kp, 2, 12.0, 3.6))
    bp = to_fascia(q, S_BUTTON)
    lid = np.maximum(lid, -sd_cyl(bp, 2, 12.0, 8.0))

    out[M_BASE] = base
    out[M_LID] = lid

    # ---- screen ----------------------------------------------------------
    out[M_SCREEN] = sd_box(fp - np.array([0, 0, -2.0], F), (SCREEN_W / 2, SCREEN_H / 2, 0.7))

    # ---- encoder knob ----------------------------------------------------
    knob = sd_cyl(kp - np.array([0, 0, 7.0], F), 2, 7.0, 10.0)
    knob = np.maximum(knob, -sd_cyl(kp - np.array([0, 0, 15.6], F), 2, 2.0, 7.6))  # dished top
    out[M_KNOB] = knob

    # ---- shutdown button -------------------------------------------------
    ring = sd_cyl(bp - np.array([0, 0, 1.2], F), 2, 1.6, 9.2)
    out[M_RING] = np.maximum(ring, -sd_cyl(bp, 2, 9.0, 6.4))
    out[M_LENSBTN] = sd_cyl(bp - np.array([0, 0, 1.4], F), 2, 1.5, 6.4)

    # ---- camera lens sitting in the north wall ---------------------------
    # barrel recessed into the bore, with the front element at the bottom of it
    lp = q - np.array([0, D_NS / 2 - 3.7, CAM_Z], F)
    barrel = np.maximum(sd_cyl(lp, 1, 3.4, 4.5), -sd_cyl(lp, 1, 4.2, 3.3))
    elem = sd_cyl(q - np.array([0, D_NS / 2 - 6.0, CAM_Z], F), 1, 0.45, 3.35)
    out[M_CAMLENS] = np.minimum(barrel, elem)

    # ---- interior, exploded view only -----------------------------------
    if interior:
        pi_z = FLOOR_T + 8 + 2                     # PiSugar board + pogo gap
        pcb = sd_box(p - np.array([12.0, 0.0, pi_z + 0.8], F), (15.0, 32.5, 0.8))
        sugar = sd_box(p - np.array([12.0, -2.0, FLOOR_T + 4.0], F), (14.0, 30.0, 4.0), r=1.0)
        out[M_PCB] = np.minimum(pcb, sugar)

        hdr = sd_box(p - np.array([12.0 - 15.0 + 3.5, 0.0, pi_z + 1.6 + 5.5], F),
                     (2.5, 25.4, 5.5))
        hat = sd_box(p - np.array([12.0, 0.0, pi_z + 1.6 + 11 + 0.8], F), (15.0, 30.0, 0.8))
        out[M_HAT] = hat
        cammod = sd_box(p - np.array([0.0, D_NS / 2 - WALL - 4.5, CAM_Z], F),
                        (12.5, 4.5, 12.0), r=0.8)
        ribbon = sd_box(p - np.array([0.0, 34.0, pi_z + 3.0], F), (7.5, 8.0, 0.3))
        out[M_BLACK] = np.minimum(conn_black,
                                  np.minimum(hdr, np.minimum(cammod, ribbon)))
    else:
        out[M_PCB] = np.full(p.shape[:-1], BIG, F)
        out[M_BLACK] = conn_black
        out[M_HAT] = np.full(p.shape[:-1], BIG, F)

    return out


def sdf(p, lift, interior):
    parts = sdf_parts(p, lift, interior)
    d = parts[0]
    for q in parts[1:]:
        d = np.minimum(d, q)
    return d


# --------------------------------------------------------------- ascii screen

GLYPHS = {
    ' ': [0, 0, 0, 0, 0, 0, 0],
    '.': [0, 0, 0, 0, 0, 0, 0b00100],
    ':': [0, 0b00100, 0, 0, 0, 0b00100, 0],
    '-': [0, 0, 0, 0b01110, 0, 0, 0],
    '=': [0, 0, 0b01110, 0, 0b01110, 0, 0],
    '+': [0, 0, 0b00100, 0b01110, 0b00100, 0, 0],
    '*': [0, 0b00100, 0b10101, 0b01110, 0b10101, 0b00100, 0],
    '#': [0b01010, 0b01010, 0b11111, 0b01010, 0b11111, 0b01010, 0b01010],
    '%': [0b11001, 0b11010, 0b00010, 0b00100, 0b01000, 0b01011, 0b10011],
    '@': [0b01110, 0b10001, 0b10111, 0b10101, 0b10111, 0b10000, 0b01110],
}
RAMP = ' .:-=+*#%@'
GRID_W, GRID_H = 64, 24


def screen_texture():
    """A 64x24 ASCII frame, rasterised to a (24*7, 64*5) ink mask."""
    gx, gy = np.meshgrid(np.arange(GRID_W), np.arange(GRID_H))
    u = (gx + 0.5) / GRID_W
    v = (gy + 0.5) / GRID_H
    # a head-and-shoulders bust, lit from the left, over a falling background
    ar = 1.4
    head = np.exp(-(((u - 0.5) * ar / 0.155) ** 2 + ((v - 0.34) / 0.205) ** 2))
    body = np.exp(-(((u - 0.5) * ar / 0.44) ** 2 + ((v - 1.06) / 0.40) ** 2))
    subj = np.maximum(head, body)
    shade = 0.52 + 0.48 * np.cos(np.clip((u - 0.33) * 2.6, -1.45, 1.45))
    img = subj * shade * 1.45 + (1 - subj) * (0.115 - 0.075 * v)
    img += 0.022 * np.sin(u * 37.0) * np.sin(v * 23.0)
    img = np.clip(img, 0, 1)

    idx = np.clip((img * (len(RAMP) - 1) + 0.5).astype(int), 0, len(RAMP) - 1)
    tex = np.zeros((GRID_H * 7, GRID_W * 5), F)
    for k, ch in enumerate(RAMP):
        rows = GLYPHS[ch]
        ys, xs = np.where(idx == k)
        if len(ys) == 0:
            continue
        for r in range(7):
            bits = rows[r]
            if not bits:
                continue
            for c in range(5):
                if bits & (1 << (4 - c)):
                    tex[ys * 7 + r, xs * 5 + c] = 1.0
    return tex


SCREEN_TEX = screen_texture()


def screen_colour(p, lift):
    """Emissive colour of the panel at world points p."""
    fp = to_fascia(p - np.array([0, 0, lift], F), S_PANEL)
    u = np.clip((fp[..., 0] + SCREEN_W / 2) / SCREEN_W, 0, 0.9999)
    v = np.clip((SCREEN_H / 2 - fp[..., 1]) / SCREEN_H, 0, 0.9999)
    th, tw = SCREEN_TEX.shape
    # 2x2 box filter so the glyphs stay legible when a pixel spans several texels
    acc = np.zeros(u.shape, F)
    for du, dv in ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25)):
        xi = np.clip((u * tw + du).astype(np.int32), 0, tw - 1)
        yi = np.clip((v * th + dv).astype(np.int32), 0, th - 1)
        acc += SCREEN_TEX[yi, xi]
    ink = acc * 0.25
    glow = 0.055
    amber = np.array([1.00, 0.72, 0.26], F)
    return (ink[..., None] * amber * 2.9 + glow * amber * 0.45)


# ------------------------------------------------------------------ materials

# albedo, roughness, metalness, emissive scale
MATS = {
    M_BASE:    (np.array([0.150, 0.154, 0.166], F), 0.58, 0.0),
    M_LID:     (np.array([0.150, 0.154, 0.166], F), 0.58, 0.0),
    M_SCREEN:  (np.array([0.02, 0.02, 0.02], F), 0.08, 0.0),
    M_KNOB:    (np.array([0.66, 0.665, 0.675], F), 0.26, 1.0),
    M_RING:    (np.array([0.86, 0.865, 0.875], F), 0.11, 1.0),
    M_LENSBTN: (np.array([0.40, 0.045, 0.035], F), 0.20, 0.0),
    M_CAMLENS: (np.array([0.016, 0.018, 0.024], F), 0.06, 0.0),
    M_PCB:     (np.array([0.050, 0.140, 0.072], F), 0.42, 0.0),
    M_BLACK:   (np.array([0.040, 0.040, 0.046], F), 0.48, 0.0),
    M_HAT:     (np.array([0.155, 0.058, 0.048], F), 0.44, 0.0),   # red FR4 protoboard
    M_CONN:    (np.array([0.700, 0.706, 0.715], F), 0.29, 1.0),   # nickel connector shell
    M_FLOOR:   (np.array([0.170, 0.172, 0.182], F), 0.50, 0.0),
}

KEY_DIR = None
KEY_COL = np.array([1.00, 0.968, 0.925], F) * 3.60
FILL_DIR = None
FILL_COL = np.array([0.58, 0.68, 0.88], F) * 0.50
RIM_DIR = None
RIM_COL = np.array([0.86, 0.90, 1.00], F) * 0.80


def _norm(v):
    v = np.asarray(v, F)
    return v / np.linalg.norm(v)


KEY_DIR = _norm([-0.42, -0.62, 0.66])     # over the viewer's left shoulder
FILL_DIR = _norm([0.78, -0.30, 0.30])     # low right fill
RIM_DIR = _norm([0.10, 0.86, 0.42])       # from behind, north, rakes the top edges


AMB_MUL = 0.42


def set_lights(view):
    """Re-aim the rig per camera. The north view looks at the wall the south
    key never reaches, so it gets its own key rather than a lift in exposure."""
    global KEY_DIR, FILL_DIR, RIM_DIR, AMB_MUL
    AMB_MUL = 0.66 if view == "exploded" else 0.42
    if view == "north":
        KEY_DIR = _norm([0.34, 0.60, 0.72])
        FILL_DIR = _norm([-0.80, 0.18, 0.28])
        RIM_DIR = _norm([-0.05, -0.88, 0.47])
    else:
        KEY_DIR = _norm([-0.42, -0.62, 0.66])
        FILL_DIR = _norm([0.78, -0.30, 0.30])
        RIM_DIR = _norm([0.10, 0.86, 0.42])


def sky(d):
    """Studio environment: bright above, neutral horizon, dark below."""
    t = np.clip(d[..., 2] * 0.5 + 0.5, 0, 1)[..., None]
    up = np.array([0.60, 0.66, 0.78], F)
    hz = np.array([0.24, 0.245, 0.26], F)
    dn = np.array([0.055, 0.055, 0.062], F)
    c = np.where(t > 0.5, hz + (up - hz) * (t - 0.5) * 2.0, dn + (hz - dn) * t * 2.0)
    return c.astype(F)


def sky_spec(d, sharp=1.0):
    """As sky(), plus the two softboxes.

    `sharp` fades the softboxes out as the reflection is blurred. A rough
    surface spreads that energy over the whole hemisphere, and the directional
    key already pays for it through GGX -- without this the softbox is counted
    twice and every matte face washes out.
    """
    c = sky(d)
    if np.isscalar(sharp) and sharp <= 0.0:
        return c
    kb = np.clip((d @ KEY_DIR - 0.82) / 0.18, 0, 1)
    fb = np.clip((d @ FILL_DIR - 0.88) / 0.12, 0, 1)
    box = (kb * kb * 7.0)[..., None] * np.array([1.00, 0.98, 0.95], F)
    box = box + (fb * fb * 1.6)[..., None] * np.array([0.80, 0.86, 1.00], F)
    return c + box * (sharp if np.isscalar(sharp) else sharp[..., None])


# ---------------------------------------------------------------- ray marching

MAXSTEPS = 110
BSPHERE_C = np.array([0.0, 0.0, 32.0], F)
BSPHERE_R = 105.0


def _sphere_range(ro, rd, lift):
    c = BSPHERE_C + np.array([0, 0, lift * 0.5], F)
    r = BSPHERE_R + lift * 0.6
    oc = ro - c
    b = (oc * rd).sum(-1)
    cc = (oc * oc).sum(-1) - r * r
    disc = b * b - cc
    ok = disc > 0
    sq = np.sqrt(np.maximum(disc, 0))
    return ok, np.maximum(-b - sq, 0.0), -b + sq


def march(ro, rd, lift, interior, tmax=900.0):
    """Returns (hit, t). Objects only; the floor is handled analytically."""
    n = ro.shape[0]
    t = np.zeros(n, F)
    hit = np.zeros(n, bool)
    ok, t0, t1 = _sphere_range(ro, rd, lift)
    t[:] = t0
    idx = np.where(ok & (t0 < tmax))[0]
    if idx.size == 0:
        return hit, t
    tend = np.minimum(t1, tmax)
    for _ in range(MAXSTEPS):
        p = ro[idx] + rd[idx] * t[idx][:, None]
        d = sdf(p, lift, interior)
        eps = np.maximum(0.0025 * t[idx], 0.012)
        h = d < eps
        hit[idx[h]] = True
        t[idx] += d * 0.92
        alive = (~h) & (t[idx] < tend[idx])
        idx = idx[alive]
        if idx.size == 0:
            break
    return hit, t


def normal(p, lift, interior, h=0.035):
    """Tetrahedron-tap gradient: 4 SDF evaluations instead of 6."""
    k = np.array([[1, -1, -1], [-1, -1, 1], [-1, 1, -1], [1, 1, 1]], F)
    g = np.zeros_like(p)
    for kk in k:
        g += kk * sdf(p + kk * h, lift, interior)[..., None]
    return g / np.maximum(np.linalg.norm(g, axis=-1, keepdims=True), 1e-6)


def soft_shadow(ro, rd, lift, interior, k=10.0, tmin=0.35, tmax=400.0):
    n = ro.shape[0]
    res = np.ones(n, F)
    t = np.full(n, tmin, F)
    idx = np.arange(n)
    for _ in range(56):
        p = ro[idx] + rd[idx] * t[idx][:, None]
        d = sdf(p, lift, interior)
        res[idx] = np.minimum(res[idx], k * d / np.maximum(t[idx], 1e-4))
        t[idx] += np.clip(d, 0.05, 12.0)
        alive = (res[idx] > 0.002) & (t[idx] < tmax)
        idx = idx[alive]
        if idx.size == 0:
            break
    return np.clip(res, 0.0, 1.0)


def ambient_occ(p, nrm, lift, interior):
    occ = np.zeros(p.shape[0], F)
    sca = 1.0
    for i in range(1, 6):
        hh = 0.22 * i * i * 0.55
        d = sdf(p + nrm * hh, lift, interior)
        occ += (hh - d) * sca
        sca *= 0.72
    return np.clip(1.0 - 2.4 * occ, 0.0, 1.0)


def ggx(nrm, v, l, rough, f0):
    h = v + l
    h /= np.maximum(np.linalg.norm(h, axis=-1, keepdims=True), 1e-6)
    nh = np.clip((nrm * h).sum(-1), 0, 1)
    nv = np.clip((nrm * v).sum(-1), 1e-4, 1)
    nl = np.clip((nrm * l).sum(-1), 0, 1)
    vh = np.clip((v * h).sum(-1), 0, 1)
    a = np.maximum(rough * rough, 1e-3)
    a2 = a * a
    den = nh * nh * (a2 - 1.0) + 1.0
    dist = a2 / (math.pi * den * den + 1e-9)
    kk = a * 0.5
    gv = nv / (nv * (1 - kk) + kk)
    gl = nl / (nl * (1 - kk) + kk)
    fr = f0 + (1.0 - f0) * (1.0 - vh)[..., None] ** 5
    spec = (dist * gv * gl / (4 * nv + 1e-6))[..., None] * fr
    return spec


# --------------------------------------------------------------------- shading


def floor_hit(ro, rd):
    denom = rd[..., 2]
    ok = denom < -1e-6
    t = np.where(ok, -ro[..., 2] / np.where(ok, denom, -1.0), 1e9)
    return ok & (t > 0), t.astype(F)


def classify(p, lift, interior):
    parts = sdf_parts(p, lift, interior)
    st = np.stack(parts, 0)
    return st.argmin(0).astype(np.int32)


def shade(p, nrm, view, mat, lift, interior, depth):
    """view points from the surface toward the eye."""
    n = p.shape[0]
    col = np.zeros((n, 3), F)
    albedo = np.zeros((n, 3), F)
    rough = np.zeros(n, F)
    metal = np.zeros(n, F)
    for m, (a, r, mt) in MATS.items():
        sel = mat == m
        if not sel.any():
            continue
        albedo[sel] = a
        rough[sel] = r
        metal[sel] = mt

    # printed layer lines on the shell: 0.2 mm banding, normal + roughness only
    pr = (mat == M_BASE) | (mat == M_LID)
    if pr.any():
        band = np.sin(p[pr, 2] * (2 * math.pi / 0.42))
        tilt = 1.0 - np.abs(nrm[pr, 2])            # only on near-vertical faces
        nrm[pr] = nrm[pr] + np.stack(
            [np.zeros(int(pr.sum()), F), np.zeros(int(pr.sum()), F),
             np.ones(int(pr.sum()), F)], -1) * (band * 0.042 * tilt)[..., None]
        nrm[pr] /= np.maximum(np.linalg.norm(nrm[pr], axis=-1, keepdims=True), 1e-6)
        rough[pr] = rough[pr] + band * 0.038 * tilt

    # knurl on the knob
    kn = mat == M_KNOB
    if kn.any():
        kp = to_fascia(p[kn] - np.array([0, 0, lift], F), S_KNOB)
        ang = np.arctan2(kp[..., 1], kp[..., 0])
        knurl = np.sin(ang * 30.0) * np.clip(1.0 - np.abs(kp[..., 2] - 7.0) / 7.0, 0, 1)
        tang = np.stack([-np.sin(ang), np.cos(ang), np.zeros(ang.shape, F)], -1)
        tw = tang @ np.stack([FV, FU, FN])
        nrm[kn] = nrm[kn] + tw * (knurl * 0.30)[..., None]
        nrm[kn] /= np.maximum(np.linalg.norm(nrm[kn], axis=-1, keepdims=True), 1e-6)

    f0 = np.where(metal[..., None] > 0.5, albedo, np.full((n, 3), 0.04, F))
    diff_alb = albedo * (1.0 - metal[..., None])

    ao = ambient_occ(p, nrm, lift, interior)
    off = p + nrm * 0.12

    for ldir, lcol, kk, cast in ((KEY_DIR, KEY_COL, 9.0, True),
                                 (FILL_DIR, FILL_COL, 4.0, True),
                                 (RIM_DIR, RIM_COL, 6.0, True)):
        nl = np.clip(nrm @ ldir, 0, 1)
        live = nl > 0.001
        sh = np.zeros(n, F)
        if live.any():
            if cast:
                sh[live] = soft_shadow(off[live], np.broadcast_to(ldir, (live.sum(), 3)).copy(),
                                       lift, interior, k=kk)
            else:
                sh[live] = 1.0
        L = np.broadcast_to(ldir, (n, 3))
        contrib = (nl * sh)[..., None] * lcol
        col += diff_alb * contrib / math.pi
        col += ggx(nrm, view, L, rough, f0) * contrib

    # ambient from the sky, occluded
    col += diff_alb * sky(nrm) * (ao * AMB_MUL)[..., None]

    # environment specular. f0 is the albedo for metal, 0.04 for dielectrics, and
    # the reflection vector is blurred toward the normal as roughness rises.
    ndv = np.clip((nrm * view).sum(-1), 0.0, 1.0)[..., None]
    rdir = 2.0 * ndv * nrm - view
    blur = (rough * rough)[..., None]
    rdir = rdir * (1.0 - blur) + nrm * blur
    rdir /= np.maximum(np.linalg.norm(rdir, axis=-1, keepdims=True), 1e-6)
    fmax = np.maximum(1.0 - rough[..., None], f0)
    fres = f0 + (fmax - f0) * (1.0 - ndv) ** 5
    sharp = np.clip(1.0 - rough, 0.0, 1.0) ** 3
    col += sky_spec(rdir, sharp) * fres * (ao * 0.92)[..., None] * (1.0 - 0.45 * blur)

    # emissive panel and button lens
    sc = mat == M_SCREEN
    if sc.any():
        col[sc] += screen_colour(p[sc], lift)
    bl = mat == M_LENSBTN
    if bl.any():
        col[bl] += np.array([0.95, 0.16, 0.10], F) * 0.55

    # one diffuse bounce
    if depth > 0:
        col += diff_alb * gi_bounce(off, nrm, lift, interior) * ao[..., None]

    return col


def gi_bounce(p, nrm, lift, interior, samples=2):
    """Cosine-weighted diffuse bounce, direct lighting only at the hit point."""
    acc = np.zeros((p.shape[0], 3), F)
    for k in range(samples):
        acc += _gi_sample(p, nrm, lift, interior, 7 + 101 * k)
    return acc / samples


def _gi_sample(p, nrm, lift, interior, seed):
    n = p.shape[0]
    rng = np.random.default_rng(seed)
    u1 = rng.random(n).astype(F)
    u2 = rng.random(n).astype(F)
    r = np.sqrt(u1)
    th = 2 * math.pi * u2
    # build a frame around nrm
    a = np.where(np.abs(nrm[:, 2:3]) < 0.9, np.array([0, 0, 1], F), np.array([1, 0, 0], F))
    t1 = np.cross(a, nrm)
    t1 /= np.maximum(np.linalg.norm(t1, axis=-1, keepdims=True), 1e-6)
    t2 = np.cross(nrm, t1)
    d = (t1 * (r * np.cos(th))[..., None] + t2 * (r * np.sin(th))[..., None] +
         nrm * np.sqrt(np.maximum(1 - u1, 0))[..., None])
    d /= np.maximum(np.linalg.norm(d, axis=-1, keepdims=True), 1e-6)

    hit, t = march(p, d, lift, interior, tmax=260.0)
    fok, ft = floor_hit(p, d)
    use_floor = fok & (~hit | (ft < t))
    out = sky(d) * 0.55

    if hit.any():
        i = np.where(hit & ~use_floor)[0]
        if i.size:
            q = p[i] + d[i] * t[i][:, None]
            nq = normal(q, lift, interior)
            mq = classify(q, lift, interior)
            alb = np.zeros((i.size, 3), F)
            for m, (aa, rr, mm) in MATS.items():
                s = mq == m
                if s.any():
                    alb[s] = aa
            lam = np.clip(nq @ KEY_DIR, 0, 1)[..., None] * KEY_COL / math.pi
            lam += np.clip(nq @ FILL_DIR, 0, 1)[..., None] * FILL_COL / math.pi
            out[i] = alb * lam * 0.65
            sc = mq == M_SCREEN
            if sc.any():
                out[i[sc]] += screen_colour(q[sc], lift) * 0.8
    if use_floor.any():
        i = np.where(use_floor)[0]
        q = p[i] + d[i] * ft[i][:, None]
        out[i] = MATS[M_FLOOR][0] * 0.9 * floor_shadowing(q, lift, interior)[..., None]
    return out * 0.85


def floor_shadowing(q, lift, interior):
    up = np.broadcast_to(np.array([0, 0, 1], F), q.shape).copy()
    nl = max(KEY_DIR[2], 0.0)
    sh = soft_shadow(q + up * 0.12,
                     np.broadcast_to(KEY_DIR, q.shape).copy(), lift, interior, k=8.0)
    return np.clip(nl * sh + 0.25, 0, 1)


def floor_pattern(q):
    """Very slight large-scale mottle so the sweep is not dead flat."""
    m = (np.sin(q[..., 0] * 0.021) * np.sin(q[..., 1] * 0.017) * 0.5 +
         np.sin(q[..., 0] * 0.006 + 1.7) * 0.5)
    return 1.0 + 0.035 * m


# ------------------------------------------------------------------- rendering


def look_at(eye, target, up=(0, 0, 1)):
    f = _norm(np.array(target, F) - np.array(eye, F))
    r = _norm(np.cross(f, np.array(up, F)))
    u = np.cross(r, f)
    return f, r, u


def render(view, width, ss, gi, chunk=120_000):
    if view == "hero":
        eye = np.array([188.0, -252.0, 124.0], F)
        target = np.array([-3.0, -7.0, 29.0], F)
        fov, lift, interior, aspect = 25.0, 0.0, False, 4 / 3
    elif view == "north":
        eye = np.array([214.0, 233.0, 148.0], F)
        target = np.array([2.0, 12.0, 33.0], F)
        fov, lift, interior, aspect = 25.0, 0.0, False, 4 / 3
    elif view == "ports":          # close-up of the east wall, for checking
        eye = np.array([230.0, -70.0, 62.0], F)
        target = np.array([44.0, 2.0, 26.0], F)
        fov, lift, interior, aspect = 22.0, 0.0, False, 4 / 3
    elif view == "exploded":
        eye = np.array([252.0, -226.0, 224.0], F)
        target = np.array([0.0, 1.0, 50.0], F)
        fov, lift, interior, aspect = 29.0, 55.0, True, 4 / 3
    else:
        raise SystemExit("view must be hero, north or exploded")

    set_lights(view)
    height = int(round(width / aspect))
    WW, HH = width * ss, height * ss
    f, r, u = look_at(eye, target)
    scale = math.tan(math.radians(fov) * 0.5)

    px = (np.arange(WW, dtype=F) + 0.5) / WW * 2 - 1
    py = 1 - (np.arange(HH, dtype=F) + 0.5) / HH * 2
    gx, gy = np.meshgrid(px, py)
    dirs = (f + r * (gx * scale * aspect)[..., None] + u * (gy * scale)[..., None])
    dirs /= np.linalg.norm(dirs, axis=-1, keepdims=True)
    dirs = dirs.reshape(-1, 3).astype(F)
    ro = np.broadcast_to(eye, dirs.shape).copy()

    img = np.zeros((HH * WW, 3), F)
    n = dirs.shape[0]
    t0 = time.time()
    for a in range(0, n, chunk):
        b = min(a + chunk, n)
        img[a:b] = trace(ro[a:b], dirs[a:b], lift, interior, gi)
        done = b / n
        el = time.time() - t0
        sys.stderr.write("\r  %5.1f%%  %6.1fs elapsed, ~%.0fs left   "
                         % (done * 100, el, el / max(done, 1e-6) * (1 - done)))
        sys.stderr.flush()
    sys.stderr.write("\n")

    img = img.reshape(HH, WW, 3)
    if ss > 1:
        img = img.reshape(height, ss, width, ss, 3).mean(axis=(1, 3))
    return img, (gx, gy)


def trace(ro, rd, lift, interior, gi):
    n = ro.shape[0]
    col = np.zeros((n, 3), F)

    hit, t = march(ro, rd, lift, interior)
    fok, ft = floor_hit(ro, rd)
    use_floor = fok & (~hit | (ft < t)) & (ft < 1400.0)
    obj = hit & ~use_floor
    bg = ~(obj | use_floor)

    # backdrop: a soft studio sweep
    if bg.any():
        d = rd[bg]
        v = np.clip(d[..., 2] * 2.4 + 0.42, 0, 1)[..., None]
        top = np.array([0.072, 0.077, 0.090], F)
        bot = np.array([0.190, 0.194, 0.206], F)
        col[bg] = bot + (top - bot) * v

    if obj.any():
        i = np.where(obj)[0]
        p = ro[i] + rd[i] * t[i][:, None]
        nrm = normal(p, lift, interior)
        mat = classify(p, lift, interior)
        col[i] = shade(p, nrm, -rd[i], mat, lift, interior, depth=gi)

    if use_floor.any():
        i = np.where(use_floor)[0]
        q = ro[i] + rd[i] * ft[i][:, None]
        up = np.broadcast_to(np.array([0, 0, 1], F), (i.size, 3)).copy()
        alb = MATS[M_FLOOR][0] * floor_pattern(q)[..., None]
        c = np.zeros((i.size, 3), F)
        for ldir, lcol, kk in ((KEY_DIR, KEY_COL, 8.0), (FILL_DIR, FILL_COL, 4.0)):
            nl = max(float(ldir[2]), 0.0)
            if nl <= 0:
                continue
            sh = soft_shadow(q + up * 0.12,
                             np.broadcast_to(ldir, (i.size, 3)).copy(), lift, interior, k=kk)
            c += alb * (nl * sh)[..., None] * lcol / math.pi
        ao = ambient_occ(q, up, lift, interior)
        c += alb * sky(up) * (ao * 0.45)[..., None]
        # grazing sheen
        fres = 0.03 + 0.30 * (1.0 - np.clip((-rd[i, 2]), 0, 1)) ** 4
        c += sky_spec(np.stack([rd[i, 0], rd[i, 1], -rd[i, 2]], -1), 0.10) * \
            fres[..., None] * (ao * 0.7)[..., None]
        # fade the floor into the backdrop with distance
        fade = np.clip((ft[i] - 340.0) / 620.0, 0, 1)[..., None]
        c = c * (1 - fade) + np.array([0.150, 0.154, 0.166], F) * fade
        col[i] = c

    return col


# ------------------------------------------------------------------------ out


def aces(x):
    a, b, c, d, e = 2.51, 0.03, 2.43, 0.59, 0.14
    return np.clip((x * (a * x + b)) / (x * (c * x + d) + e), 0, 1)


def to_png(img, path, vignette=0.20):
    h, w, _ = img.shape
    y, x = np.mgrid[0:h, 0:w]
    nx = (x / (w - 1) - 0.5) * 2
    ny = (y / (h - 1) - 0.5) * 2
    v = 1.0 - vignette * np.clip((nx * nx * 0.85 + ny * ny), 0, 1.6)
    out = img * v[..., None]
    out = aces(out * 0.82)
    out = np.power(np.clip(out, 0, 1), 1 / 2.2)
    # Just enough dither to break 8-bit banding in the backdrop, and no more:
    # this noise is incompressible, and at 1.6/255 it was a third of the PNG.
    rng = np.random.default_rng(3)
    out = np.clip(out + (rng.random(out.shape).astype(F) - 0.5) * (0.7 / 255.0), 0, 1)
    b8 = (out * 255.0 + 0.5).astype(np.uint8)

    raw = b"".join(b"\x00" + b8[i].tobytes() for i in range(h))

    def chunk(tag, data):
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
    return len(png)


def main():
    view = sys.argv[1] if len(sys.argv) > 1 else "hero"
    args = dict(w=1200, ss=2, gi=1)
    for i, a in enumerate(sys.argv):
        if a.startswith("--") and i + 1 < len(sys.argv):
            k = a[2:]
            if k in args:
                args[k] = int(sys.argv[i + 1])
    here = os.path.dirname(os.path.abspath(__file__))
    out = os.path.join(here, "enclosure-%s.png" % view)
    print("rendering %s at %dx%d, %dx supersample, gi=%d"
          % (view, args["w"], round(args["w"] * 3 / 4), args["ss"], args["gi"]))
    t0 = time.time()
    img, _ = render(view, args["w"], args["ss"], args["gi"])
    nb = to_png(img, out)
    print("wrote %s  (%.0f KB, %.1f s)" % (out, nb / 1024, time.time() - t0))


if __name__ == "__main__":
    main()

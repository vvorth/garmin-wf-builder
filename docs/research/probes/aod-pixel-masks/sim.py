"""Pixel-pattern mask vs jitter: host-side simulation on real wfb AOD renders."""
import sys, json
from pathlib import Path
import numpy as np
sys.path.insert(0, "/home/vvorth/claude/garmin-wf-builder")
from wfb.build import load, resolve_all, select_devices
from wfb.devices import DeviceDatabase
from wfb.diagnostics import Bag
from wfb.preview import render, PreviewOptions
from dataclasses import replace

db = DeviceDatabase(Path.home() / ".Garmin/ConnectIQ/Devices")

def frames(design, minutes, device="fenix847mm"):
    bag = Bag(); face = load(Path(design), bag)
    devs = select_devices(face, db, bag, [device])
    resolved, _ = resolve_all(face, devs, bag)
    r = resolved[0] if isinstance(resolved, list) else list(resolved.values())[0] if isinstance(resolved, dict) else resolved
    opts = PreviewOptions(scale=1, mask_shape=False, aod=True)
    out = []
    for m in minutes:
        img = render(r, replace(opts, time=(m // 60, m % 60, 0)))
        out.append(np.asarray(img.convert("RGB"), dtype=np.float64) / 255.0)
    return np.stack(out)  # T,H,W,3

def lin(c):
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)

def luminance(f):
    l = lin(f); return 0.2126 * l[..., 0] + 0.7152 * l[..., 1] + 0.0722 * l[..., 2]

# masks: function (t, H, W) -> bool array of pixels allowed on
def m_none(t, H, W): return np.ones((H, W), bool)
def m_rot2x2(t, H, W):  # user's example 1: ((1,0),(1,0)) rotated 90deg each minute
    tiles = [np.array([[1,0],[1,0]]), np.array([[1,1],[0,0]]), np.array([[0,1],[0,1]]), np.array([[0,0],[1,1]])]
    k = tiles[t % 4]; return np.tile(k, (H // 2 + 1, W // 2 + 1))[:H, :W].astype(bool)
def m_checker(t, H, W):  # 2-phase checkerboard
    y, x = np.mgrid[:H, :W]; return ((x + y + t) % 2) == 0
def m_brick(t, H, W):  # user's example 2: ((1,0,0,0),(0,0,1,0)) shifted one column per minute
    y, x = np.mgrid[:H, :W]; return ((x - t - 2 * (y % 2)) % 4) == 0
def m_brick8(t, H, W):  # 25% duty, 4 phases, lit set x ≡ 2y + t (mod 4): a 4x4 tile of 1/4 duty
    y, x = np.mgrid[:H, :W]; return ((x - 2 * y - t) % 4) == 0

MASKS = {"none": m_none, "rot2x2(50%)": m_rot2x2, "checker(50%)": m_checker,
         "brick(25%)": m_brick, "diag4(25%)": m_brick8}

def disk(H, W):
    y, x = np.mgrid[:H, :W]; cy, cx = (H - 1) / 2, (W - 1) / 2
    return ((y - cy) ** 2 + (x - cx) ** 2) <= (min(H, W) / 2) ** 2

def analyse(F, mask_fn, dim=1.0):
    T, H, W, _ = F.shape; D = disk(H, W); n = D.sum()
    lit = (F.max(axis=3) > 0)
    M = np.stack([mask_fn(t, H, W) for t in range(T)])
    shown = lit & M
    lum = luminance(F * dim) * M
    litfrac = (shown & D).reshape(T, -1).sum(1) / n
    lumfrac = (lum * D).reshape(T, -1).sum(1) / n
    # longest run of consecutive lit minutes per pixel
    run = np.zeros((H, W), int); best = np.zeros((H, W), int)
    for t in range(T):
        run = np.where(shown[t], run + 1, 0); best = np.maximum(best, run)
    ever = lit.any(0) & D
    over3 = ((best > 3) & ever).sum() / max(ever.sum(), 1)
    # detail retention: share of the unmasked image's lit pixels that stay lit per frame
    retention = (shown & D).reshape(T, -1).sum(1) / np.maximum((lit & D).reshape(T, -1).sum(1), 1)
    # visibility of 1-px-wide detail: fraction of each frame's lit pixels with no lit 4-neighbour after masking
    iso = []
    for t in range(T):
        s = shown[t]; nb = np.zeros_like(s)
        nb[1:] |= s[:-1]; nb[:-1] |= s[1:]; nb[:, 1:] |= s[:, :-1]; nb[:, :-1] |= s[:, 1:]
        iso.append((s & ~nb).sum() / max(s.sum(), 1))
    return dict(lit_max=float(litfrac.max()), lum_max=float(lumfrac.max()),
                longest_run=int(best[ever].max()) if ever.any() else 0,
                share_over_3min=float(over3), retention=float(retention.mean()),
                isolated_px=float(np.mean(iso)))

if __name__ == "__main__":
    minutes = list(range(600, 600 + int(sys.argv[2]))) if len(sys.argv) > 2 else list(range(600, 660))
    F = frames(sys.argv[1], minutes)
    for name, fn in MASKS.items():
        print(f"{name:14s}", json.dumps(analyse(F, fn)))

def _queen(k):
    def fn(t, H, W):
        y, x = np.mgrid[:H, :W]; c = (x - 2 * y) % 5
        return np.isin(c, [(t + j) % 5 for j in range(k)])
    return fn
MASKS.update({"queen5(20%)": _queen(1), "queen5x2(40%)": _queen(2), "queen5x3(60%)": _queen(3)})

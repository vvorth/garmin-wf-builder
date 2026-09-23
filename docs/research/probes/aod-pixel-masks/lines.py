import numpy as np, sim
H = W = 64
def line(kind, off):
    img = np.zeros((H, W), bool)
    for i in range(8, 56):
        if kind == "horizontal": img[20 + off, i] = True
        if kind == "vertical": img[i, 20 + off] = True
        if kind == "diag45": img[i, i - 8 + off] = True
        if kind == "antidiag": img[i, 63 - i - off] = True
    return img
print(f"{'mask':14s} " + " ".join(f"{k:>22s}" for k in ("horizontal","vertical","diag45","antidiag")))
for name, fn in sim.MASKS.items():
    cells = []
    for kind in ("horizontal", "vertical", "diag45", "antidiag"):
        worst_vis, gone = 1.0, 0
        for off in range(5):          # every phase alignment of the line
            L = line(kind, off)
            for t in range(20):
                vis = (L & fn(t, H, W)).sum() / L.sum()
                worst_vis = min(worst_vis, vis); gone += vis == 0
        cells.append(f"min {worst_vis:4.0%} vanish {gone:2d}/100")
    print(f"{name:14s} " + " ".join(f"{c:>22s}" for c in cells))

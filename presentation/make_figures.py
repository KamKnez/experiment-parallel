"""Erzeugt Zusatzdiagramme aus den summary.csv (misst nichts neu)."""
import csv, pathlib
import matplotlib.pyplot as plt

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = pathlib.Path(__file__).resolve().parent / "img"
COL = {"rust": "#2a78d6", "java": "#eb6834", "go": "#1baf7a", "cpp": "#eda100", "scala": "#e87ba4"}
LANGS = ["rust", "java", "go", "cpp", "scala"]
NAME = {"rust": "Rust", "java": "Java", "go": "Go", "cpp": "C++", "scala": "Scala"}
ALGOS = [("primes", "Primes (datenparallel)"), ("fib", "Fib (taskparallel)"), ("msort", "Merge Sort (speicherlastig)")]

def load(d):
    t = {}
    with open(ROOT / d / "summary.csv") as f:
        for r in csv.DictReader(f):
            t[(r["algo"], r["lang"], int(r["workers"]))] = r
    return t

lin, win = load("results-linux"), load("results-windows")
plt.rcParams.update({"font.size": 12, "axes.spines.top": False, "axes.spines.right": False})

# 1) Absolute Zeiten bei 8 Workern (Linux), sortiert, mit sequentieller Zeit als Marker
fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
for ax, (a, title) in zip(axs, ALGOS):
    order = sorted(LANGS, key=lambda l: float(lin[(a, l, 8)]["median_s"]))
    for i, l in enumerate(order):
        v = float(lin[(a, l, 8)]["median_s"]); s = float(lin[(a, l, 0)]["median_s"])
        ax.bar(i, v, color=COL[l])
        ax.text(i, v, f"{v:.2f}", ha="center", va="bottom", fontsize=10)
        ax.plot([i - .4, i + .4], [s, s], color="#444", lw=1.6, ls="--")
    ax.set_xticks(range(5)); ax.set_xticklabels([NAME[l] for l in order])
    ax.set_ylim(0, max(float(lin[(a, l, 0)]["median_s"]) for l in LANGS) * 1.12)
    ax.set_title(title, fontsize=12); ax.set_ylabel("Median-Zeit [s]")
axs[1].plot([], [], color="#444", ls="--", label="sequentielle Zeit der jeweiligen Sprache"); axs[1].legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.1))
fig.suptitle("Absolute Laufzeit bei 8 Workern (Balken) vs. sequentiell (gestrichelt), Linux", y=1.02)
fig.tight_layout(); fig.savefig(OUT / "absolute.png", dpi=170, bbox_inches="tight")

# 2) Speedup bei 8 Workern: Linux vs Windows
fig, axs = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
for ax, (a, title) in zip(axs, ALGOS):
    for i, l in enumerate(LANGS):
        for k, (d, h) in enumerate([(lin, None), (win, "//")]):
            r = d[(a, l, 8)]; v = float(r["speedup"])
            err = [[v - float(r["speedup_ci_low"])], [float(r["speedup_ci_high"]) - v]]
            ax.bar(i + (k - .5) * .38, v, .36, color=COL[l], hatch=h, alpha=1 if k == 0 else .6,
                   edgecolor="white", yerr=err, ecolor="#333", capsize=2)
    ax.axhline(8, color="#888", ls="--", lw=1)
    ax.set_xticks(range(5)); ax.set_xticklabels([NAME[l] for l in LANGS]); ax.set_title(title, fontsize=12)
axs[0].set_ylabel("Speedup bei 8 Workern"); axs[0].set_ylim(0, 8.6)
fig.suptitle("Speedup bei 8 Workern: Linux (voll) vs. Windows (schraffiert), 95%-Intervall; gestrichelt = ideal", y=1.02)
fig.tight_layout(); fig.savefig(OUT / "linux_vs_windows.png", dpi=170, bbox_inches="tight")

# 3) Serial Fraction (Karp-Flatt) ueber Worker, Linux
fig, axs = plt.subplots(1, 3, figsize=(13, 4.2))
for ax, (a, title) in zip(axs, ALGOS):
    for l in LANGS:
        ys = [max(float(lin[(a, l, p)]["serial_fraction"]) * 100, 0) for p in (2, 4, 8)]
        ax.plot([2, 4, 8], ys, marker="o", color=COL[l], label=NAME[l], lw=2)
    ax.set_xscale("log", base=2); ax.set_xticks([2, 4, 8]); ax.set_xticklabels(["2", "4", "8"])
    ax.set_title(title, fontsize=12); ax.set_xlabel("Anzahl Worker"); ax.set_ylim(bottom=0)
    ax.grid(axis="y", color="#ddd")
axs[0].set_ylabel("Serial Fraction [%]"); axs[0].legend(frameon=False)
fig.suptitle("Serial Fraction in % je Anzahl Worker, Linux (niedriger = besser, 0 = ideal)", y=1.02)
fig.tight_layout(); fig.savefig(OUT / "serial_fraction.png", dpi=170, bbox_inches="tight")

# ---------------------------------------------------------------- Erklaergrafiken
from matplotlib.patches import FancyBboxPatch, Rectangle
WC = ["#4c6ef5", "#f08c00", "#12b886", "#be4bdb", "#e03131", "#0c8599", "#868e96", "#a9822a"]

def box(ax, x, y, w, h, fc, text="", tc="white", fs=11, ec="white", lw=1.5, bold=False):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.06", fc=fc, ec=ec, lw=lw))
    if text:
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", color=tc, fontsize=fs, fontweight="bold" if bold else "normal")

def blank(w=12.5, h=3.7):
    fig, ax = plt.subplots(figsize=(w, h)); ax.axis("off"); return fig, ax

# A) Primes: Chunks mit wachsender Arbeit, dynamisch verteilt
fig, ax = blank(12.5, 3.5); ax.set_xlim(0, 13.4); ax.set_ylim(-1.3, 3.5)
owners = [0, 1, 2, 3, 0, 1, 3, 2, 1, 0, 2, 3]
for i, o in enumerate(owners):
    hgt = 0.7 + i * 0.1
    box(ax, 0.6 + i * 1.0, 0.5, 0.9, hgt, WC[o], f"Chunk\n{i + 1}", fs=9)
ax.text(13.0, 0.9, "…", fontsize=22, ha="center")
ax.annotate("", xy=(13.2, 0.15), xytext=(0.6, 0.15), arrowprops=dict(arrowstyle="->", color="#555", lw=1.5))
ax.text(0.6, -0.2, "0", fontsize=11); ax.text(12.6, -0.2, "15 Mio.", fontsize=11, ha="right")
ax.text(6.6, -0.2, "Zahlenbereich, in Chunks zu je 10.000 Zahlen geteilt (≈ 1.500 Chunks)", ha="center", fontsize=11, color="#333")
ax.text(0.6, 3.15, "Höhe = Rechenaufwand: große Zahlen dauern länger", fontsize=11, color="#555")
for k in range(4):
    box(ax, 2.6 + k * 2.3, -1.15, 0.35, 0.35, WC[k], ec=WC[k])
    ax.text(3.05 + k * 2.3, -0.98, f"Worker {k + 1}", fontsize=11, va="center")
fig.savefig(OUT / "algo_primes.png", dpi=170, bbox_inches="tight")

# B) Fib: Task-Baum fib(6) mit Cutoff 4
fig, ax = blank(12.5, 4.2); ax.set_xlim(-0.8, 12.6); ax.set_ylim(-0.7, 3.7)
Y = {0: 3.2, 1: 2.2, 2: 1.2, 3: 0.2}
nodes = {  # id: (x, depth, label, kind)
    "r": (2.4, 0, "fib(6)", "split"), "a": (1.25, 1, "fib(5)", "split"), "c": (3.5, 1, "fib(4)", "split"),
    "a1": (0.5, 2, "fib(4)", "split"), "b": (2.0, 2, "fib(3)", "seq"), "c1": (3.0, 2, "fib(3)", "seq"), "c2": (4.0, 2, "fib(2)", "seq"),
    "a11": (0.0, 3, "fib(3)", "seq"), "a12": (1.0, 3, "fib(2)", "seq"),
}
edges = [("r", "a", 1), ("r", "c", 0), ("a", "a1", 1), ("a", "b", 0), ("c", "c1", 1), ("c", "c2", 0), ("a1", "a11", 1), ("a1", "a12", 0)]
for p, c, spawn in edges:
    x0, d0 = nodes[p][0], nodes[p][1]; x1, d1 = nodes[c][0], nodes[c][1]
    ax.annotate("", xy=(x1, Y[d1] + 0.3), xytext=(x0, Y[d0] - 0.02),
                arrowprops=dict(arrowstyle="-|>", color="#f08c00" if spawn else "#555", lw=2.2 if spawn else 1.4, ls="-" if spawn else "--"))
for k, (x, d, lab, kind) in nodes.items():
    box(ax, x - 0.42, Y[d], 0.84, 0.3, "#2a78d6" if kind == "split" else "#adb5bd", lab, fs=10, bold=True, tc="white" if kind == "split" else "#222")
tx = 6.2
ax.text(tx, 3.3, "Wie liest man das?", fontsize=12, fontweight="bold")
ax.plot([tx, tx + 0.8], [2.85, 2.85], color="#f08c00", lw=2.6); ax.text(tx + 1.0, 2.85, "fib(n−1) wird als Task an einen freien Worker gegeben", va="center", fontsize=11)
ax.plot([tx, tx + 0.8], [2.4, 2.4], color="#555", lw=1.6, ls="--"); ax.text(tx + 1.0, 2.4, "fib(n−2) rechnet derselbe Worker selbst weiter", va="center", fontsize=11)
box(ax, tx, 1.88, 0.8, 0.3, "#2a78d6", "n ≥ 4", fs=9, bold=True); ax.text(tx + 1.0, 2.03, "teilt weiter auf (Cutoff noch nicht erreicht)", va="center", fontsize=11)
box(ax, tx, 1.4, 0.8, 0.3, "#adb5bd", "n < 4", fs=9, tc="#222", bold=True); ax.text(tx + 1.0, 1.55, "Cutoff erreicht: rechnet alleine zu Ende, ohne neue Tasks", va="center", fontsize=11)
ax.text(tx, 0.8, "Danach: Der Worker wartet auf den Task und addiert beide Ergebnisse (Join).", fontsize=11, va="center")
ax.text(tx, 0.2, "Im Experiment: fib(45) mit Cutoff 30 → rund 1.600 Tasks", fontsize=11, va="center", color="#c0392b", fontweight="bold")
ax.text(tx, -0.35, "(Bild: kleines Beispiel fib(6) mit Cutoff 4)", fontsize=10, color="#666")
fig.savefig(OUT / "algo_fib.png", dpi=170, bbox_inches="tight")

# C) Merge Sort: unten alle Worker beschaeftigt, oben immer weniger
fig, ax = blank(12.5, 4.0); ax.set_xlim(-2.9, 12.6); ax.set_ylim(-0.3, 4.4)
W = 12.0 / 8
rows = [  # (y, blocks, label)
    (3.5, 8, "1. Sortieren: viele kleine Stücke,\nalle 8 Worker beschäftigt"),
    (2.5, 4, "2. Zusammenmischen: 4 Merges\n(4 Worker)"),
    (1.5, 2, "3. 2 Merges\n(2 Worker)"),
    (0.5, 1, "4. Letzter Merge: ganze 50 Mio.\nZahlen, nur 1 Worker"),
]
for y, n, lab in rows:
    bw = 8 / n * W
    for i in range(n):
        box(ax, i * bw + 0.02, y, bw - 0.04, 0.7, WC[(i * 8 // n)] if n > 1 else WC[0], "", ec="white", lw=2)
    ax.text(-0.15, y + 0.35, lab, ha="right", va="center", fontsize=10.5, color="#222")
for y, n, _ in rows[1:]:
    pass
for y in (3.2, 2.2, 1.2):
    ax.annotate("", xy=(6, y - 0.05), xytext=(6, y + 0.27), arrowprops=dict(arrowstyle="-|>", color="#555", lw=1.8))
ax.text(6, 0.05, "Farbe = welcher Worker die Arbeit macht", ha="center", fontsize=11, color="#555")
fig.savefig(OUT / "algo_msort.png", dpi=170, bbox_inches="tight")

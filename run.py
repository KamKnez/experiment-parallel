#!/usr/bin/env python3
"""Build all benchmarks, measure them repeatedly at 1..N workers, and plot the results.

N defaults to the number of physical cores. Every measurement is a fresh process,
and each round runs all configurations in a new random order, so slow drift (heat,
background load) spreads over all configurations instead of hitting one of them.

Examples
  python3 run.py                        # full run: 10 rounds, default sizes
  python3 run.py --quick                # small sizes, 3 rounds: smoke test
  python3 run.py --max-workers 16       # also test the logical cores
  python3 run.py --langs rust,go --algos fib --reps 20
  python3 run.py --primes-n 5000000 --fib-n 38 --fib-cutoff 23   # custom size
  python3 run.py --replot               # rebuild summary and plots from raw.csv

Speedup S(p) = median T(sequential code) / median T(p workers), each language
against its own sequential version. Efficiency E(p) = S(p) / p.
Serial fraction (Karp-Flatt) e(p) = (1/S - 1/p) / (1 - 1/p).
Intervals are 95% bootstrap intervals of the median (or of the median ratio).
Outputs go to results/: raw.csv, summary.csv, speedup.png, stats.png
"""
import argparse
import csv
import os
import random
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "results"

# Default sizes: each sequential run takes roughly 2-6 s on a modern CPU, because
# every configuration is measured many times.
# n - cutoff = 15, so fib creates the same number of tasks (~1600) at any size.
# msort: 50M 64-bit numbers (400 MB) is far bigger than the CPU caches; n / cutoff
# gives about 1000 sequential leaves.
SIZES = {"primes": 15_000_000, "fib": 45, "cutoff": 30,
         "msort": 50_000_000, "msort_cutoff": 50_000}
QUICK = {"primes": 2_000_000, "fib": 34, "cutoff": 19,
         "msort": 2_000_000, "msort_cutoff": 2_000}

NOISY_CV_PCT = 5.0  # above this run-to-run spread, a configuration is flagged
BOOTSTRAP = 2000

# fixed series order -> fixed colors (color follows the language, not the rank)
COLORS = {"rust": "#2a78d6", "java": "#eb6834", "go": "#1baf7a",
          "cpp": "#eda100", "scala": "#e87ba4"}
TITLES = {"primes": "Data parallel: counting primes",
          "fib": "Task parallel: recursive Fibonacci",
          "msort": "Memory heavy: merge sort"}
INK, MUTED, GRID = "#2b2b2a", "#6b6a64", "#e4e3dd"

LANGS = {
    "rust": [str(ROOT / "rust/target/release/bench")],
    "go": [str(ROOT / "go/bench")],
    "java": ["java", "-cp", str(ROOT / "java"), "Bench"],
    "cpp": [str(ROOT / "cpp/bench")],
    "scala": ["java", "-jar", str(ROOT / "scala/bench.jar")],
}


def physical_cores():
    """Physical core count; os.cpu_count() would also count SMT siblings."""
    try:
        out = subprocess.run(["lscpu", "-p=CORE,SOCKET"], capture_output=True,
                             text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return os.cpu_count()
    return len({line for line in out.splitlines() if not line.startswith("#")})


def build(selected):
    steps = {
        "go": (["go", "build", "-o", "bench", "."], ROOT / "go"),
        "rust": (["cargo", "build", "--release", "-q"], ROOT / "rust"),
        "java": (["javac", "Bench.java"], ROOT / "java"),
        "cpp": (["g++", "-std=c++20", "-O3", "-fopenmp", "main.cpp", "-o", "bench"], ROOT / "cpp"),
        "scala": (["scala-cli", "--power", "package", "--assembly", "--preamble=false",
                   "--server=false", "-f", "-o", "bench.jar", "Bench.scala"], ROOT / "scala"),
    }
    for lang, (cmd, cwd) in steps.items():
        if lang in selected:
            print(f"building {lang} ...", flush=True)
            subprocess.run(cmd, cwd=cwd, check=True)


def worker_counts(max_w):
    ws, w = [], 1
    while w < max_w:
        ws.append(w)
        w *= 2
    ws.append(max_w)
    return ws


def run(cmd, algo, workers, n, cutoff):
    """One fresh process doing one timed repetition."""
    cmd = cmd + [algo, str(workers), str(n), str(cutoff), "1"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
    value, secs = next(line.split()[1:] for line in out.splitlines() if line.startswith("RESULT"))
    return int(value), float(secs)


def write_csv(name, rows):
    with open(OUT / name, "w", newline="") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)


def interval(stat):
    """95% percentile bootstrap interval of stat(), which must resample by itself."""
    samples = sorted(stat() for _ in range(BOOTSTRAP))
    return samples[int(0.025 * BOOTSTRAP)], samples[int(0.975 * BOOTSTRAP) - 1]


def summarize(raw):
    times = defaultdict(list)
    n_of = {}
    for r in raw:
        key = (r["algo"], r["lang"], r["workers"])
        times[key].append(r["seconds"])
        n_of[key] = r["n"]

    rng = random.Random(0)
    med = statistics.median
    resample = lambda ts: med(rng.choices(ts, k=len(ts)))
    rows = []
    for (algo, lang, w), ts in times.items():
        base = times[(algo, lang, 0)]
        s = med(base) / med(ts)
        s_lo, s_hi = interval(lambda: resample(base) / resample(ts))
        t_lo, t_hi = interval(lambda: resample(ts))
        q1, _, q3 = statistics.quantiles(ts, n=4) if len(ts) > 1 else (ts[0], 0, ts[0])
        mean = statistics.fmean(ts)
        stdev = statistics.stdev(ts) if len(ts) > 1 else 0.0
        p = max(w, 1)
        rows.append({
            "algo": algo, "lang": lang, "workers": w, "n": n_of[(algo, lang, w)], "runs": len(ts),
            "median_s": round(med(ts), 6), "ci_low_s": round(t_lo, 6), "ci_high_s": round(t_hi, 6),
            "mean_s": round(mean, 6), "stdev_s": round(stdev, 6),
            "min_s": round(min(ts), 6), "q1_s": round(q1, 6), "q3_s": round(q3, 6),
            "max_s": round(max(ts), 6), "cv_pct": round(100 * stdev / mean, 2),
            "speedup": round(s, 3), "speedup_ci_low": round(s_lo, 3), "speedup_ci_high": round(s_hi, 3),
            "efficiency": round(s / p, 3),
            "serial_fraction": round((1 / s - 1 / p) / (1 - 1 / p), 4) if p > 1 else "",
        })
    rows.sort(key=lambda r: (r["algo"], r["lang"], r["workers"]))
    return rows


def report(summary):
    print(f"\n{'algo':6} {'lang':6} {'workers':>7} {'median':>9} {'speedup':>8} "
          f"{'95% interval':>14} {'eff':>5} {'cv%':>6}")
    for r in summary:
        label = "seq" if r["workers"] == 0 else r["workers"]
        ci = f"{r['speedup_ci_low']:.2f}-{r['speedup_ci_high']:.2f}"
        print(f"{r['algo']:6} {r['lang']:6} {label!s:>7} {r['median_s']:8.3f}s {r['speedup']:8.2f} "
              f"{ci:>14} {r['efficiency']:5.2f} {r['cv_pct']:6.2f}")
    noisy = [r for r in summary if r["cv_pct"] > NOISY_CV_PCT]
    if noisy:
        print(f"\nNOISY (cv > {NOISY_CV_PCT:g}%), treat with care:")
        for r in noisy:
            print(f"  {r['algo']} {r['lang']} workers={r['workers']}: cv={r['cv_pct']:.1f}%")


def series(summary, algo, lang, *keys, min_workers=1):
    """Columns of one plotted line; empty when the language has no data."""
    rows = [r for r in summary if r["algo"] == algo and r["lang"] == lang
            and r["workers"] >= min_workers]
    return [[r[k] for r in rows] for k in ("workers", *keys)] if rows else None


def style(ax, xlabel, ylabel):
    ax.set_xlabel(xlabel, color=MUTED)
    ax.set_ylabel(ylabel, color=MUTED)
    ax.grid(True, color=GRID, lw=0.8)
    ax.set_axisbelow(True)
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_color(GRID)
    ax.tick_params(which="both", colors=MUTED)


def line(ax, xs, ys, lang):
    ax.plot(xs, ys, lw=2, color=COLORS[lang], marker="o", ms=7,
            markeredgecolor="white", markeredgewidth=1.5, label=lang, zorder=3)


def plot_speedup(plt, summary, algos, max_w):
    fig, axes = plt.subplots(1, len(algos), figsize=(6.2 * len(algos), 4.8), squeeze=False)
    for ax, algo in zip(axes[0], algos):
        ax.plot([1, max_w], [1, max_w], ls=(0, (4, 4)), lw=1.2, color=MUTED, zorder=1)
        ax.annotate("ideal", (max_w, max_w), xytext=(-4, 4), textcoords="offset points",
                    ha="right", fontsize=9, color=MUTED)
        top = max([max_w] + [r["speedup_ci_high"] for r in summary if r["algo"] == algo]) * 1.12
        ends = []
        for lang in COLORS:
            data = series(summary, algo, lang, "speedup", "speedup_ci_low", "speedup_ci_high")
            if not data:
                continue
            xs, ys, lo, hi = data
            ax.fill_between(xs, lo, hi, color=COLORS[lang], alpha=0.18, lw=0, zorder=2)
            line(ax, xs, ys, lang)
            ends.append([ys[-1], ys[-1], lang])
        # end-of-line labels, nudged apart so they never overlap
        ends.sort()
        gap = top * 0.055
        for i in range(1, len(ends)):
            ends[i][1] = max(ends[i][1], ends[i - 1][1] + gap)
        for y, ylab, lang in ends:
            ax.annotate(f"{lang} {y:.2f}×", (max_w, y), xytext=(max_w + 0.12 * max_w ** 0.5, ylab),
                        textcoords="data", va="center", fontsize=9, color=INK)
        ax.set_title(TITLES[algo], loc="left", fontsize=12, color=INK, pad=10)
        style(ax, "workers (threads)", "speedup vs own sequential code")
        ax.set_xticks(worker_counts(max_w))
        ax.set_xlim(0.5, max_w * 1.4)
        ax.set_ylim(0, top)
        ax.legend(frameon=False, fontsize=9, loc="upper left", labelcolor=INK)
    fig.tight_layout()
    fig.savefig(OUT / "speedup.png", dpi=150)


def plot_stats(plt, matplotlib, summary, algos, max_w):
    """One row per algorithm, one column per statistic."""
    ticks = worker_counts(max_w)
    fig, axes = plt.subplots(len(algos), 4, figsize=(17, 3.5 * len(algos) + 0.6), squeeze=False)
    for row, algo in zip(axes, algos):
        eff, tm, cv, sf = row
        for lang in COLORS:
            data = series(summary, algo, lang, "efficiency", "median_s", "ci_low_s",
                          "ci_high_s", "cv_pct")
            if not data:
                continue
            xs, e, med, lo, hi, c = data
            line(eff, xs, e, lang)
            tm.fill_between(xs, lo, hi, color=COLORS[lang], alpha=0.18, lw=0, zorder=2)
            line(tm, xs, med, lang)
            line(cv, xs, c, lang)
            xs2, f = series(summary, algo, lang, "serial_fraction", min_workers=2)
            line(sf, xs2, f, lang)

        eff.axhline(1, ls=(0, (4, 4)), lw=1.2, color=MUTED, zorder=1)
        eff.set_ylim(0, 1.15)
        cv.axhline(NOISY_CV_PCT, ls=(0, (4, 4)), lw=1.2, color=MUTED, zorder=1)
        cv.annotate(f"noisy above {NOISY_CV_PCT:g}%", (1, NOISY_CV_PCT), xytext=(0, 4),
                    textcoords="offset points", ha="left", fontsize=9, color=MUTED)
        cv.set_ylim(bottom=0)
        tm.set_yscale("log")
        style(eff, "workers", "efficiency (speedup / workers)")
        style(tm, "workers", "median seconds (log scale)")
        style(cv, "workers", "run-to-run spread, cv %")
        style(sf, "workers", "serial fraction (Karp-Flatt)")
        for ax in row:
            ax.set_xscale("log", base=2)
            ax.set_xticks(ticks, labels=[str(t) for t in ticks])
            ax.minorticks_off()
        sf.set_xticks([t for t in ticks if t > 1], labels=[str(t) for t in ticks if t > 1])
        plain = matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:g}")
        tm.yaxis.set_minor_locator(matplotlib.ticker.LogLocator(base=10, subs=(2, 5)))
        tm.yaxis.set_major_formatter(plain)
        tm.yaxis.set_minor_formatter(plain)
        eff.set_title(TITLES[algo], loc="left", fontsize=12, color=INK, pad=10)

    handles = [h for h in axes[0][0].get_lines() if h.get_label() in COLORS]
    fig.legend(handles, [h.get_label() for h in handles], loc="upper left", ncols=len(handles),
               frameon=False, fontsize=10, labelcolor=INK, bbox_to_anchor=(0.01, 1.0))
    fig.tight_layout(rect=(0, 0, 1, 1 - 0.4 / fig.get_figheight()))
    fig.savefig(OUT / "stats.png", dpi=150)


def plot(summary, algos, max_w):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker

    plot_speedup(plt, summary, algos, max_w)
    plot_stats(plt, matplotlib, summary, algos, max_w)
    print(f"plots -> {OUT / 'speedup.png'}, {OUT / 'stats.png'}")


def finish(raw, max_w):
    summary = summarize(raw)
    write_csv("summary.csv", summary)
    print(f"data -> {OUT / 'summary.csv'}, {OUT / 'raw.csv'}")
    report(summary)
    algos = [a for a in TITLES if any(r["algo"] == a for r in summary)]
    plot(summary, algos, max_w)


def load_raw():
    with open(OUT / "raw.csv", newline="") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["workers"], r["n"] = int(r["workers"]), int(r["n"])
        r["seconds"] = float(r["seconds"])
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--langs", default=",".join(LANGS))
    ap.add_argument("--algos", default="primes,fib,msort")
    ap.add_argument("--reps", type=int, default=10,
                    help="rounds: fresh-process measurements of every configuration")
    ap.add_argument("--max-workers", type=int, default=physical_cores(),
                    help="highest worker count (default: physical cores)")
    ap.add_argument("--quick", action="store_true", help="tiny sizes, 3 rounds")
    ap.add_argument("--primes-n", type=int, help="override n for primes (all languages)")
    ap.add_argument("--fib-n", type=int, help="override n for fib (all languages)")
    ap.add_argument("--fib-cutoff", type=int, help="override fib cutoff (all languages)")
    ap.add_argument("--msort-n", type=int, help="override n for msort (all languages)")
    ap.add_argument("--msort-cutoff", type=int, help="override msort cutoff (all languages)")
    ap.add_argument("--no-build", action="store_true")
    ap.add_argument("--replot", action="store_true",
                    help="measure nothing; rebuild summary and plots from results/raw.csv")
    args = ap.parse_args()

    if args.replot:
        raw = load_raw()
        finish(raw, max(r["workers"] for r in raw))
        return

    selected = [l for l in args.langs.split(",") if l in LANGS]
    algos = args.algos.split(",")
    reps = 3 if args.quick else args.reps
    sizes = QUICK if args.quick else SIZES
    if not args.no_build:
        build(selected)
    OUT.mkdir(exist_ok=True)

    jobs = {
        "primes": (args.primes_n or sizes["primes"], args.fib_cutoff or sizes["cutoff"]),
        "fib": (args.fib_n or sizes["fib"], args.fib_cutoff or sizes["cutoff"]),
        "msort": (args.msort_n or sizes["msort"], args.msort_cutoff or sizes["msort_cutoff"]),
    }
    plan = [(a, l, w) for a in algos for l in selected
            for w in [0] + worker_counts(args.max_workers)]
    rng = random.Random()
    raw, expected = [], {}  # expected is per algo: every language must agree
    start = time.monotonic()
    for rep in range(reps):
        rng.shuffle(plan)
        for i, (algo, lang, w) in enumerate(plan, 1):
            n, cutoff = jobs[algo]
            value, secs = run(LANGS[lang], algo, w, n, cutoff)
            if expected.setdefault(algo, value) != value:
                sys.exit(f"WRONG RESULT: {lang} {algo} workers={w}: {value}, "
                         f"expected {expected[algo]}")
            label = "seq" if w == 0 else w
            print(f"round {rep + 1}/{reps} {i:>3}/{len(plan)}  {algo:6} {lang:6} "
                  f"workers={label!s:>3}  {secs:8.3f}s", flush=True)
            raw.append({"algo": algo, "lang": lang, "workers": w, "n": n,
                        "cutoff": cutoff if algo != "primes" else "", "rep": rep,
                        "seconds": secs, "result": value})
        write_csv("raw.csv", raw)  # keep finished rounds if a later one fails
        print(f"round {rep + 1} done, {(time.monotonic() - start) / 60:.1f} min elapsed", flush=True)

    finish(raw, args.max_workers)


if __name__ == "__main__":
    main()

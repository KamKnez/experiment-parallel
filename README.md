# Multicore speedup: Rust vs Go vs Java vs C++ vs Scala

How much faster does each language get when the same problem goes from one core
to many? Three CPU-bound algorithms, written the same way in all five languages.

| | Algorithm | How it's parallelised |
|---|---|---|
| **Data parallel** | Count primes in `[0, n]` by trial division | Range split into chunks of 10,000 numbers; workers take chunks on demand (dynamic scheduling) |
| **Task parallel** | Recursive `fib(n)` with a cutoff | Each call with `n >= cutoff` spawns `fib(n-1)` as a task and computes `fib(n-2)` itself; below the cutoff it runs sequentially |
| **Memory heavy** | Merge sort of `n` generated 64-bit numbers | Each range of size `>= cutoff` spawns the left half and sorts the right half itself; merges are sequential and allocate a buffer each |

| Language | Data parallel | Task parallel |
|---|---|---|
| Rust | `rayon` parallel iterator | `rayon::join` |
| Go | goroutines + atomic chunk counter | goroutine + channel per spawn |
| Java | `ForkJoinPool.invokeAll` | `RecursiveTask` fork/join |
| C++ | OpenMP `parallel for schedule(dynamic, 1)` | OpenMP `task` / `taskwait` |
| Scala | one `Future` per chunk on a `ForkJoinPool` | `Future` per spawn, joined with a non-blocking `flatMap` |

## Requirements

Python 3.10+ with `matplotlib` (only for `run.py`, the driver), Go 1.22+, Rust (cargo;
downloads `rayon`), JDK 17+, g++ with OpenMP, and
[`scala-cli`](https://scala-cli.virtuslab.org/) (downloads the Scala compiler on first build).

## Run

```bash
python3 run.py --quick          # smoke test, tiny sizes, 3 rounds
python3 run.py                  # full experiment (10 rounds, 1..physical cores), takes a while
python3 run.py --reps 5         # fewer rounds, wider intervals
python3 run.py --max-workers 16 # also test the logical cores
python3 run.py --replot         # rebuild summary and plots from raw.csv, measures nothing
python3 run.py --help
```

On Windows, use `python` instead of `python3`. The C++ build needs MinGW-w64 g++
(its OpenMP is libgomp, as on Linux), and the Rust build needs the MSVC Build Tools.

Results land in `results/`:
- `summary.csv`: per language/algorithm/worker count: time statistics (median, mean, stdev,
  min, quartiles, max, cv), speedup, efficiency and serial fraction, with 95% intervals
- `raw.csv`: every single measurement, saved after each round
- `speedup.png`: speedup curves with the ideal line and 95% interval bands
- `stats.png`: efficiency, median time, run-to-run spread and serial fraction per algorithm

Each program can also be run by hand:
`<program> <primes|fib|msort> <workers> <n> <cutoff> <reps>` (workers `0` = plain sequential code).

## What is measured

- **Speedup** `S(p) = T_seq / T_p`. Each language is compared with **its own plain
  sequential code** (not the parallel code run with one worker), so the overhead of
  the parallel machinery is visible.
- **Efficiency** `E(p) = S(p) / p`.
- Median of `--reps` rounds. Each round measures every configuration once, as a **fresh
  process**, in a new random order, so slow drift such as heat can't favour one configuration.
- Variability: `cv` is stdev / mean of the run times. Configurations above 5% are listed as noisy.
- Intervals are 95% bootstrap intervals of the median. For speedup, both medians are resampled.
- **Serial fraction** (Karp-Flatt) `e(p) = (1/S − 1/p) / (1 − 1/p)` estimates the share of work
  that behaves as sequential. If it grows with `p`, overhead is growing, not just a fixed serial part.
- Pool start-up is **inside** the timing, because that is
  part of what parallelism costs in each language. The exception is C++: OpenMP keeps
  its threads between parallel regions, so only the first rep pays for starting them.
- Java and Scala do one untimed warm-up run first, so the JIT has compiled the hot code.
- Workers go up to the number of **physical** cores by default.
- Merge sort only times the sort. Generating the input and computing the checksum are outside it.
- Merge sort stresses memory bandwidth, the allocator and the GC. The top merge runs on one
  thread over the whole array, so speedup stays well below ideal by design. On the JVM, GC
  threads also help the sequential baseline, which lowers Java's and Scala's measured speedup.
- Results are checked: every run must return the same value as the sequential run.

## Problem sizes

All languages use the same inputs: primes `n` = 15,000,000 and fib `n` / cutoff = 45 / 30.
Sizes are kept moderate because every configuration is measured many times.

`n − cutoff = 15`, so every language creates the same number of fib tasks (~1,600).
Merge sort uses `n` = 50,000,000 (about 400 MB, plus a copy and merge buffers) and cutoff = 50,000,
which gives about 1,000 sequential leaves.

Use `--primes-n`, `--fib-n`, `--fib-cutoff`, `--msort-n` and `--msort-cutoff` to change the size.

Known answers for checking: π(10⁶) = 78,498, π(2·10⁷) = 1,270,607, fib(30) = 832,040, fib(42) = 267,914,296.

## Good experimental practice

- Run on an otherwise idle machine, plugged in. Close the browser.
- `--max-workers` above the physical core count puts workers on hyperthreads, and
  the curve will bend there. That is expected, not a bug.
- Turbo boost makes single-core runs relatively faster than all-core runs, which
  lowers measured speedup. If you can, fix the CPU frequency (Linux:
  `cpupower frequency-set -g performance`, or disable turbo) or at least report it.
- Things worth varying afterwards:
  - the fib cutoff (`--fib-cutoff`): smaller means more, tinier tasks, so per-task overhead dominates;
  - the prime chunk size (`CHUNK` in each program).

# CLAUDE.md: parallel-bench

## Goal
Experiment: compare how much **speedup** Rust, Go, Java, C++ and Scala get when the
same CPU-bound problem goes from single-threaded code to many cores. The focus is
relative scaling (each language vs **its own** sequential code), not raw speed.
Three algorithms:

- **Data parallel**: count primes in `[0, n]` by trial division. The range is
  split into chunks of `CHUNK = 10_000` numbers, which workers take on demand
  (dynamic scheduling).
- **Task parallel**: recursive `fib(n)` with a cutoff. If `n >= cutoff`, spawn
  `fib(n-1)` as a task and compute `fib(n-2)` in place, then join. Below the
  cutoff, run plain sequential recursion. The `n < 2` guard is also required in
  the parallel version.
- **Memory heavy**: top-down merge sort of `n` generated 64-bit numbers. If the
  range has size `>= cutoff`, spawn the left half, sort the right half in place,
  join, then merge. Below the cutoff, run plain sequential merge sort. Merges are
  always sequential, and each allocates a buffer for the left half.

## Layout
```
go/main.go, go.mod   goroutines; GOMAXPROCS = workers; atomic chunk counter; channel per spawn
rust/src/main.rs     rayon: into_par_iter().with_max_len(1) / rayon::join; pool built per run
java/Bench.java      ForkJoinPool: invokeAll(callables) / RecursiveTask; 1 untimed JIT warm-up
cpp/main.cpp         OpenMP: parallel for schedule(dynamic, 1) / task + taskwait
scala/Bench.scala    Futures on a ForkJoinPool, non-blocking flatMap join; 1 untimed JIT warm-up
run.py               builds all, runs workers = seq,1,2,4,..,physical cores in shuffled rounds,
                     checks results,
                     writes results/{raw.csv,summary.csv,speedup.png,stats.png}
README.md            user-facing docs + methodology
```

## Shared CLI contract (keep identical across languages)
`<prog> <primes|fib|msort> <workers> <n> <cutoff> <reps>`
- `workers = 0` means plain sequential code. This is the baseline, deliberately
  not the parallel code run with 1 worker.
- Prints one line per rep: `RESULT <value> <seconds>`. run.py parses only these lines.
- Pool start-up is **inside** the timed region (on purpose). C++ exception: libgomp
  reuses its threads, so only the first rep pays for starting them.

## Design decisions (don't silently change)
- **msort input:** LCG `x = x * 6364136223846793005 + 1442695040888963407` (wrapping,
  seed 42), value `x >>> 33`. Result: `h = h * 31 + v` (wrapping) over the sorted
  array, then `h >>> 1`. Both must stay identical across languages. Generation and
  checksum are outside the timing, and each rep sorts a fresh copy.
- **msort uses its own merge sort, never a library sort**, and allocates per merge
  on purpose, so allocator and GC costs are part of the result.
- **Python is only the driver.** The Python benchmark was removed; run.py stays.
- **Scala join is non-blocking.** `Await` inside a pool thread would pin the worker,
  so results are combined with `flatMap`. This also differs from Java's fork/join on
  the same pool type, which is part of the comparison.
- **Workers stop at physical cores** (`physical_cores()` in run.py, via `lscpu`, or
  PowerShell on Windows).
  `--max-workers` overrides this.
- **run.py compares results across languages**, not just across worker counts.
- **Repetition:** `--reps` (default 10) is the number of rounds. Each round runs every
  configuration once in a fresh process (bench `reps` arg = 1), in a new shuffled order.
  Don't go back to repeating inside one process: run-to-run JIT and layout effects
  would be hidden.
- **Statistics:** 95% bootstrap intervals of medians; cv above 5% is flagged as noisy;
  Karp-Flatt serial fraction for p > 1. Outliers are never dropped.
- **Sizes** (`SIZES` in run.py): primes 15M, fib 45 with cutoff 30, msort 50M with
  cutoff 50k, for all languages.
  - `n - cutoff = 15`, so every language creates the same number of tasks (~1,600).
  - `--primes-n`, `--fib-n`, `--fib-cutoff`, `--msort-n` and `--msort-cutoff` override the sizes.
- **Plot:** fixed color per language (rust blue `#2a78d6`, go aqua `#1baf7a`,
  java orange `#eb6834`, cpp yellow `#eda100`, scala magenta `#e87ba4`), kept
  in the order rust, java, go, cpp, scala, which passes the palette check for lines.
  It has an ideal dashed line, end labels nudged apart, one y-axis, and the
  y-limit allows results above the ideal line.
- **Speedup** `S(p) = median T_seq / median T_p`; **efficiency** `E = S/p`.

## Correctness values
- Primes: π(10⁶) = 78,498 · π(2·10⁷) = 1,270,607.
- Fibonacci: fib(30) = 832,040 · fib(42) = 267,914,296.
- run.py exits with `WRONG RESULT` if any run differs from the sequential one.

## Commands
```bash
python3 run.py --quick                    # smoke test (tiny sizes, 3 rounds)
python3 run.py                            # full run, 10 rounds, 1..physical cores
python3 run.py --replot                   # rebuild summary and plots from raw.csv
python3 run.py --langs rust,go --algos fib --reps 7
python3 run.py --max-workers 16           # also test the logical cores
python3 run.py --no-build                 # skip compiling
```
Build steps (run.py runs these):
- `go build -o bench .` in `go/`
- `cargo build --release` in `rust/`
- `javac Bench.java` in `java/`
- `g++ -std=c++20 -O3 -fopenmp main.cpp -o bench` in `cpp/` (no `-march=native`, to match the others)
- `scala-cli --power package --assembly --preamble=false --server=false -f -o bench.jar Bench.scala` in `scala/`

## Requirements
Python 3.10+ with matplotlib, Go 1.22+, Rust/cargo (rayon from crates.io), and a
**JDK** 17+ (needs `javac`, not just the JRE), g++ with OpenMP, and `scala-cli`.
On Ubuntu: `sudo apt install openjdk-21-jdk-headless`.

## Status / history
- Python was replaced by C++ and Scala on 2026-10-31. C++ was verified against the
  known answers and through run.py at that point.
- msort was added on 2026-10-31. The user's `--quick` run covered all five languages,
  including Scala, and they agreed on primes, fib and the msort checksum at small sizes.
- The user runs the experiments; don't run them unprompted. The repeated-rounds run.py
  and stats.png were only tested with `--replot` on synthetic data in a scratch copy.
- Test run on a 2-core cloud sandbox: all languages reached ~1.5–2.1× at 2
  workers. That sandbox was too small and noisy for real conclusions; results
  slightly above 2× there were noise. **The real experiment still needs to run
  on the user's multi-core machine.**
- User's machine: Ubuntu 24.04 (zsh), OpenJDK 21 runtime. `javac` was missing,
  and the fix is to install `openjdk-21-jdk-headless`.
- User also runs it natively on Windows 11 (8 cores / 16 threads) to contrast with a
  colleague's Linux PC: Python 3.12 (`python`, not `python3`), Go 1.26, Rust 1.99 MSVC,
  JDK 23, MinGW g++ 13.2, matplotlib, scala-cli (via Chocolatey; not on winget). The
  Windows `--quick` run worked on 2026-10-31.

- Full runs finished on 2026-10-31: `results-linux/` (colleague's Ryzen 7 5800X desktop,
  Ubuntu) and `results-windows/` (user's Ryzen 7 5800HS laptop, Windows 11). Same sizes,
  10 rounds, workers 0/1/2/4/8. README "Test system" describes both machines.

## Known limitations / possible next steps
- **C++ fib scales poorly under libgomp:** ~4.3× at 8 workers (others ~7.5×, from the
  older run). Replacing `taskwait` with `taskgroup` only reached ~5.1×, so the cause
  isn't fully explained. `taskwait` stays because it matches the spawn/join design.
- **Windows support (added 2026-10-31, not yet run end-to-end):** on `win32`, binaries are
  `bench.exe`, physical cores come from PowerShell `Win32_Processor`, and commands are
  resolved with `shutil.which` (scala-cli may be a `.cmd`/`.bat`). C++ there is MinGW g++
  (libgomp), and Rust uses the MSVC toolchain.
- **Possible extra experiments:**
  - sweep the fib cutoff to measure per-task overhead;
  - vary `CHUNK` (it must stay identical in all 5 files);
  - weak scaling (problem size grows with the number of workers);
  - note turbo boost / CPU governor effects.
- Project docs also live in the claude.ai Project "Experiment" (`claude/experiment-design.md`).

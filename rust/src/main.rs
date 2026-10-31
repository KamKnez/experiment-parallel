//! Parallel speedup benchmark - Rust (rayon work-stealing pool).
//!
//! Usage: bench <algo> <workers> <n> <cutoff> <reps>
//!
//!   algo     primes | fib | msort
//!   workers  0 = plain sequential code, >=1 = parallel with that many workers
//!   n        primes: count primes in [0, n];  fib: compute fib(n);
//!           msort: sort n generated numbers
//!   cutoff   fib, msort: subproblems with n < cutoff run sequentially
//!   reps     number of timed repetitions
//!
//! Prints one line per repetition:  RESULT <value> <seconds>

use rayon::prelude::*;
use std::time::Instant;

const CHUNK: u64 = 10_000; // numbers per data-parallel work item

// ---------- data parallel: count primes by trial division ----------

fn is_prime(n: u64) -> bool {
    if n < 2 {
        return false;
    }
    if n < 4 {
        return true;
    }
    if n % 2 == 0 {
        return false;
    }
    let mut i = 3;
    while i * i <= n {
        if n % i == 0 {
            return false;
        }
        i += 2;
    }
    true
}

fn count_range(lo: u64, hi: u64) -> u64 {
    (lo..hi).filter(|&k| is_prime(k)).count() as u64
}

fn primes_seq(n: u64) -> u64 {
    count_range(0, n + 1)
}

fn primes_par(n: u64) -> u64 {
    let nchunks = (n + 1).div_ceil(CHUNK) as usize;
    (0..nchunks)
        .into_par_iter()
        .with_max_len(1) // one chunk = one task -> dynamic scheduling
        .map(|c| {
            let lo = c as u64 * CHUNK;
            count_range(lo, (lo + CHUNK).min(n + 1))
        })
        .sum()
}

// ---------- task parallel: recursive Fibonacci with a cutoff ----------

fn fib(n: u64) -> u64 {
    if n < 2 {
        n
    } else {
        fib(n - 1) + fib(n - 2)
    }
}

fn fib_par(n: u64, cutoff: u64) -> u64 {
    if n < cutoff || n < 2 {
        return fib(n);
    }
    let (a, b) = rayon::join(|| fib_par(n - 1, cutoff), || fib_par(n - 2, cutoff));
    a + b
}

// ---------- merge sort: parallel recursion, sequential merge ----------

// Same generator and checksum in every language, so all must print the same value.
fn generate(n: usize) -> Vec<u64> {
    let mut x: u64 = 42;
    (0..n)
        .map(|_| {
            x = x
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            x >> 33
        })
        .collect()
}

fn checksum(a: &[u64]) -> u64 {
    a.iter().fold(0u64, |h, &v| h.wrapping_mul(31).wrapping_add(v)) >> 1
}

// The buffer for the left half is allocated per merge: allocation is part of the test.
fn merge(a: &mut [u64], mid: usize) {
    let left = a[..mid].to_vec();
    let (mut i, mut j, mut k) = (0, mid, 0);
    while i < left.len() && j < a.len() {
        if left[i] <= a[j] {
            a[k] = left[i];
            i += 1;
        } else {
            a[k] = a[j];
            j += 1;
        }
        k += 1;
    }
    while i < left.len() {
        a[k] = left[i];
        i += 1;
        k += 1;
    }
}

fn msort_seq(a: &mut [u64]) {
    if a.len() < 2 {
        return;
    }
    let mid = a.len() / 2;
    let (l, r) = a.split_at_mut(mid);
    msort_seq(l);
    msort_seq(r);
    merge(a, mid);
}

fn msort_par(a: &mut [u64], cutoff: usize) {
    if a.len() < cutoff || a.len() < 2 {
        return msort_seq(a);
    }
    let mid = a.len() / 2;
    let (l, r) = a.split_at_mut(mid);
    rayon::join(|| msort_par(l, cutoff), || msort_par(r, cutoff));
    merge(a, mid);
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    if args.len() < 6 {
        eprintln!("usage: bench <primes|fib|msort> <workers> <n> <cutoff> <reps>");
        std::process::exit(2);
    }
    let algo = args[1].as_str();
    let workers: usize = args[2].parse().unwrap();
    let n: u64 = args[3].parse().unwrap();
    let cutoff: u64 = args[4].parse().unwrap();
    let reps: usize = args[5].parse().unwrap();

    let data = if algo == "msort" { generate(n as usize) } else { Vec::new() };

    for _ in 0..reps {
        let mut a = data.clone(); // fresh input, generated outside the timing
        let t0 = Instant::now();
        let result = if workers == 0 {
            match algo {
                "primes" => primes_seq(n),
                "fib" => fib(n),
                "msort" => {
                    msort_seq(&mut a);
                    0
                }
                _ => panic!("unknown algo {algo}"),
            }
        } else {
            // pool start-up is part of the measured cost, as in other languages
            let pool = rayon::ThreadPoolBuilder::new()
                .num_threads(workers)
                .build()
                .unwrap();
            pool.install(|| match algo {
                "primes" => primes_par(n),
                "fib" => fib_par(n, cutoff),
                "msort" => {
                    msort_par(&mut a, cutoff as usize);
                    0
                }
                _ => panic!("unknown algo {algo}"),
            })
        };
        let secs = t0.elapsed().as_secs_f64();
        let result = if algo == "msort" { checksum(&a) } else { result };
        println!("RESULT {} {:.6}", result, secs);
    }
}

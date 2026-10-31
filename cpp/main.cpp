// Parallel speedup benchmark - C++ (OpenMP).
//
// Usage: bench <algo> <workers> <n> <cutoff> <reps>
//
//   algo     primes | fib | msort
//   workers  0 = plain sequential code, >=1 = parallel with that many workers
//   n        primes: count primes in [0, n];  fib: compute fib(n);
//            msort: sort n generated numbers
//   cutoff   fib, msort: subproblems with n < cutoff run sequentially
//   reps     number of timed repetitions
//
// Prints one line per repetition:  RESULT <value> <seconds>

#include <omp.h>

#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <memory>
#include <string>
#include <vector>

static const int64_t CHUNK = 10'000; // numbers per data-parallel work item

// ---------- data parallel: count primes by trial division ----------

static bool is_prime(int64_t n) {
    if (n < 2) return false;
    if (n < 4) return true;
    if (n % 2 == 0) return false;
    for (int64_t i = 3; i * i <= n; i += 2) {
        if (n % i == 0) return false;
    }
    return true;
}

static int64_t count_range(int64_t lo, int64_t hi) { // [lo, hi)
    int64_t c = 0;
    for (int64_t k = lo; k < hi; k++) {
        if (is_prime(k)) c++;
    }
    return c;
}

static int64_t primes_seq(int64_t n) { return count_range(0, n + 1); }

static int64_t primes_par(int64_t n, int workers) {
    const int64_t nchunks = (n + 1 + CHUNK - 1) / CHUNK;
    int64_t total = 0;
    // schedule(dynamic, 1): one chunk = one task, handed out on demand
#pragma omp parallel for num_threads(workers) schedule(dynamic, 1) reduction(+ : total)
    for (int64_t c = 0; c < nchunks; c++) {
        const int64_t lo = c * CHUNK;
        total += count_range(lo, std::min(lo + CHUNK, n + 1));
    }
    return total;
}

// ---------- task parallel: recursive Fibonacci with a cutoff ----------

static int64_t fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

static int64_t fib_task(int n, int cutoff) {
    if (n < cutoff || n < 2) return fib(n);
    int64_t a;
#pragma omp task default(none) shared(a) firstprivate(n, cutoff) // spawn
    a = fib_task(n - 1, cutoff);
    const int64_t b = fib_task(n - 2, cutoff); // other half here
#pragma omp taskwait
    return a + b; // join
}

static int64_t fib_par(int n, int cutoff, int workers) {
    int64_t result = 0;
#pragma omp parallel num_threads(workers) default(none) shared(result) firstprivate(n, cutoff)
#pragma omp single
    result = fib_task(n, cutoff);
    return result;
}

// ---------- merge sort: parallel recursion, sequential merge ----------

// Same generator and checksum in every language, so all must print the same value.
static std::vector<int64_t> generate(int64_t n) {
    std::vector<int64_t> a(n);
    uint64_t x = 42;
    for (auto& v : a) {
        x = x * 6364136223846793005ULL + 1442695040888963407ULL;
        v = static_cast<int64_t>(x >> 33);
    }
    return a;
}

static int64_t checksum(const std::vector<int64_t>& a) {
    uint64_t h = 0;
    for (int64_t v : a) h = h * 31 + static_cast<uint64_t>(v);
    return static_cast<int64_t>(h >> 1);
}

// The buffer for the left half is allocated per merge: allocation is part of the test.
static void merge(int64_t* a, int64_t mid, int64_t len) {
    auto left = std::make_unique_for_overwrite<int64_t[]>(mid);
    std::copy(a, a + mid, left.get());
    int64_t i = 0, j = mid, k = 0;
    while (i < mid && j < len) a[k++] = left[i] <= a[j] ? left[i++] : a[j++];
    while (i < mid) a[k++] = left[i++];
}

static void msort_seq(int64_t* a, int64_t len) {
    if (len < 2) return;
    const int64_t mid = len / 2;
    msort_seq(a, mid);
    msort_seq(a + mid, len - mid);
    merge(a, mid, len);
}

static void msort_task(int64_t* a, int64_t len, int64_t cutoff) {
    if (len < cutoff || len < 2) return msort_seq(a, len);
    const int64_t mid = len / 2;
#pragma omp task default(none) firstprivate(a, mid, cutoff) // spawn
    msort_task(a, mid, cutoff);
    msort_task(a + mid, len - mid, cutoff); // other half here
#pragma omp taskwait
    merge(a, mid, len); // join
}

static void msort_par(int64_t* a, int64_t len, int64_t cutoff, int workers) {
#pragma omp parallel num_threads(workers) default(none) firstprivate(a, len, cutoff)
#pragma omp single
    msort_task(a, len, cutoff);
}

int main(int argc, char** argv) {
    if (argc < 6) {
        std::fprintf(stderr, "usage: bench <primes|fib|msort> <workers> <n> <cutoff> <reps>\n");
        return 2;
    }
    const std::string algo = argv[1];
    const int workers = std::stoi(argv[2]);
    const int64_t n = std::stoll(argv[3]);
    const int cutoff = std::stoi(argv[4]);
    const int reps = std::stoi(argv[5]);
    const bool msort = algo == "msort";
    if (algo != "primes" && algo != "fib" && !msort) {
        std::fprintf(stderr, "unknown algo %s\n", algo.c_str());
        return 2;
    }

    std::vector<int64_t> data;
    if (msort) data = generate(n);

    for (int r = 0; r < reps; r++) {
        std::vector<int64_t> a = data; // fresh input, generated outside the timing
        const auto t0 = std::chrono::steady_clock::now();
        int64_t result = 0;
        if (msort) {
            if (workers == 0) msort_seq(a.data(), n);
            else msort_par(a.data(), n, cutoff, workers);
        } else if (algo == "primes") {
            result = workers == 0 ? primes_seq(n) : primes_par(n, workers);
        } else {
            result = workers == 0 ? fib(static_cast<int>(n))
                                  : fib_par(static_cast<int>(n), cutoff, workers);
        }
        const std::chrono::duration<double> secs = std::chrono::steady_clock::now() - t0;
        if (msort) result = checksum(a);
        std::printf("RESULT %lld %.6f\n", static_cast<long long>(result), secs.count());
        std::fflush(stdout);
    }
    return 0;
}

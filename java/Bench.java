// Parallel speedup benchmark - Java (ForkJoinPool).
//
// Usage: java Bench <algo> <workers> <n> <cutoff> <reps>
//
//   algo     primes | fib | msort
//   workers  0 = plain sequential code, >=1 = parallel with that many workers
//   n        primes: count primes in [0, n];  fib: compute fib(n);
//            msort: sort n generated numbers
//   cutoff   fib, msort: subproblems with n < cutoff run sequentially
//   reps     number of timed repetitions
//
// One untimed warm-up run is done first so the JIT has compiled the hot code.
// Prints one line per timed repetition:  RESULT <value> <seconds>

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.Callable;
import java.util.concurrent.ForkJoinPool;
import java.util.concurrent.Future;
import java.util.concurrent.RecursiveAction;
import java.util.concurrent.RecursiveTask;

public class Bench {
    static final long CHUNK = 10_000; // numbers per data-parallel work item

    // ---------- data parallel: count primes by trial division ----------

    static boolean isPrime(long n) {
        if (n < 2) return false;
        if (n < 4) return true;
        if (n % 2 == 0) return false;
        for (long i = 3; i * i <= n; i += 2) {
            if (n % i == 0) return false;
        }
        return true;
    }

    static long countRange(long lo, long hi) { // [lo, hi)
        long c = 0;
        for (long k = lo; k < hi; k++) if (isPrime(k)) c++;
        return c;
    }

    static long primesSeq(long n) { return countRange(0, n + 1); }

    static long primesPar(long n, ForkJoinPool pool) throws Exception {
        long nchunks = (n + 1 + CHUNK - 1) / CHUNK;
        List<Callable<Long>> tasks = new ArrayList<>();
        for (long c = 0; c < nchunks; c++) {
            final long lo = c * CHUNK, hi = Math.min(lo + CHUNK, n + 1);
            tasks.add(() -> countRange(lo, hi)); // one chunk = one task
        }
        long total = 0;
        for (Future<Long> f : pool.invokeAll(tasks)) total += f.get();
        return total;
    }

    // ---------- task parallel: recursive Fibonacci with a cutoff ----------

    static long fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

    static class FibTask extends RecursiveTask<Long> {
        final int n, cutoff;
        FibTask(int n, int cutoff) { this.n = n; this.cutoff = cutoff; }

        @Override
        protected Long compute() {
            if (n < cutoff || n < 2) return fib(n);
            FibTask a = new FibTask(n - 1, cutoff);
            a.fork();                                         // spawn
            long b = new FibTask(n - 2, cutoff).compute();    // other half here
            return a.join() + b;                              // join
        }
    }

    // ---------- merge sort: parallel recursion, sequential merge ----------

    // Same generator and checksum in every language, so all must print the same value.
    static long[] generate(int n) {
        long[] a = new long[n];
        long x = 42;
        for (int i = 0; i < n; i++) {
            x = x * 6364136223846793005L + 1442695040888963407L;
            a[i] = x >>> 33;
        }
        return a;
    }

    static long checksum(long[] a) {
        long h = 0;
        for (long v : a) h = h * 31 + v;
        return h >>> 1;
    }

    // The buffer for the left half is allocated per merge: allocation is part of the test.
    static void merge(long[] a, int lo, int mid, int hi) {
        long[] left = Arrays.copyOfRange(a, lo, mid);
        int i = 0, j = mid, k = lo;
        while (i < left.length && j < hi) a[k++] = left[i] <= a[j] ? left[i++] : a[j++];
        while (i < left.length) a[k++] = left[i++];
    }

    static void msortSeq(long[] a, int lo, int hi) { // [lo, hi)
        if (hi - lo < 2) return;
        int mid = lo + (hi - lo) / 2;
        msortSeq(a, lo, mid);
        msortSeq(a, mid, hi);
        merge(a, lo, mid, hi);
    }

    static class SortTask extends RecursiveAction {
        final long[] a;
        final int lo, hi, cutoff;
        SortTask(long[] a, int lo, int hi, int cutoff) {
            this.a = a; this.lo = lo; this.hi = hi; this.cutoff = cutoff;
        }

        @Override
        protected void compute() {
            if (hi - lo < cutoff || hi - lo < 2) { msortSeq(a, lo, hi); return; }
            int mid = lo + (hi - lo) / 2;
            SortTask left = new SortTask(a, lo, mid, cutoff);
            left.fork();                                      // spawn
            new SortTask(a, mid, hi, cutoff).compute();       // other half here
            left.join();                                      // join
            merge(a, lo, mid, hi);
        }
    }

    // For msort, sorts a in place and returns 0; main computes the checksum untimed.
    static long runOnce(String algo, int workers, long n, int cutoff, long[] a) throws Exception {
        boolean msort = algo.equals("msort");
        if (workers == 0) {
            if (msort) { msortSeq(a, 0, a.length); return 0; }
            return algo.equals("primes") ? primesSeq(n) : fib((int) n);
        }
        ForkJoinPool pool = new ForkJoinPool(workers); // start-up is part of the cost
        try {
            if (msort) { pool.invoke(new SortTask(a, 0, a.length, cutoff)); return 0; }
            return algo.equals("primes") ? primesPar(n, pool)
                                         : pool.invoke(new FibTask((int) n, cutoff));
        } finally {
            pool.shutdown();
        }
    }

    public static void main(String[] args) throws Exception {
        if (args.length < 5 || !List.of("primes", "fib", "msort").contains(args[0])) {
            System.err.println("usage: java Bench <primes|fib|msort> <workers> <n> <cutoff> <reps>");
            System.exit(2);
        }
        String algo = args[0];
        int workers = Integer.parseInt(args[1]);
        long n = Long.parseLong(args[2]);
        int cutoff = Integer.parseInt(args[3]);
        int reps = Integer.parseInt(args[4]);

        boolean msort = algo.equals("msort");
        long[] data = msort ? generate((int) n) : new long[0];

        runOnce(algo, workers, n, cutoff, data.clone()); // JIT warm-up, not timed
        for (int r = 0; r < reps; r++) {
            long[] a = data.clone(); // fresh input, generated outside the timing
            long t0 = System.nanoTime();
            long result = runOnce(algo, workers, n, cutoff, a);
            double secs = (System.nanoTime() - t0) / 1e9;
            if (msort) result = checksum(a);
            System.out.printf("RESULT %d %.6f%n", result, secs);
        }
    }
}

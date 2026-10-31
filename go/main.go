// Parallel speedup benchmark - Go.
//
// Usage: bench <algo> <workers> <n> <cutoff> <reps>
//
//	algo     primes | fib | msort
//	workers  0 = plain sequential code, >=1 = parallel with that many workers
//	n        primes: count primes in [0, n];  fib: compute fib(n);
//	         msort: sort n generated numbers
//	cutoff   fib, msort: subproblems with n < cutoff run sequentially
//	reps     number of timed repetitions
//
// Prints one line per repetition:  RESULT <value> <seconds>
package main

import (
	"fmt"
	"os"
	"runtime"
	"slices"
	"strconv"
	"sync"
	"sync/atomic"
	"time"
)

const chunk int64 = 10_000 // numbers per data-parallel work item

// ---------- data parallel: count primes by trial division ----------

func isPrime(n int64) bool {
	if n < 2 {
		return false
	}
	if n < 4 {
		return true
	}
	if n%2 == 0 {
		return false
	}
	for i := int64(3); i*i <= n; i += 2 {
		if n%i == 0 {
			return false
		}
	}
	return true
}

func countRange(lo, hi int64) int64 { // [lo, hi)
	var c int64
	for k := lo; k < hi; k++ {
		if isPrime(k) {
			c++
		}
	}
	return c
}

func primesSeq(n int64) int64 { return countRange(0, n+1) }

func primesPar(n int64, workers int) int64 {
	nchunks := (n + 1 + chunk - 1) / chunk
	var next int64 = -1 // shared chunk counter -> dynamic scheduling
	var total int64
	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			var local int64
			for {
				c := atomic.AddInt64(&next, 1)
				if c >= nchunks {
					break
				}
				lo := c * chunk
				local += countRange(lo, min(lo+chunk, n+1))
			}
			atomic.AddInt64(&total, local)
		}()
	}
	wg.Wait()
	return total
}

// ---------- task parallel: recursive Fibonacci with a cutoff ----------

func fib(n int) int64 {
	if n < 2 {
		return int64(n)
	}
	return fib(n-1) + fib(n-2)
}

func fibPar(n, cutoff int) int64 {
	if n < cutoff || n < 2 {
		return fib(n)
	}
	ch := make(chan int64, 1)
	go func() { ch <- fibPar(n-1, cutoff) }() // spawn
	b := fibPar(n-2, cutoff)                  // do the other half ourselves
	return <-ch + b                           // join
}

// ---------- merge sort: parallel recursion, sequential merge ----------

// Same generator and checksum in every language, so all must print the same value.
func generate(n int64) []int64 {
	a := make([]int64, n)
	x := uint64(42)
	for i := range a {
		x = x*6364136223846793005 + 1442695040888963407
		a[i] = int64(x >> 33)
	}
	return a
}

func checksum(a []int64) int64 {
	var h uint64
	for _, v := range a {
		h = h*31 + uint64(v)
	}
	return int64(h >> 1)
}

// The buffer for the left half is allocated per merge: allocation is part of the test.
func merge(a []int64, mid int) {
	left := slices.Clone(a[:mid])
	i, j, k := 0, mid, 0
	for i < len(left) && j < len(a) {
		if left[i] <= a[j] {
			a[k] = left[i]
			i++
		} else {
			a[k] = a[j]
			j++
		}
		k++
	}
	for i < len(left) {
		a[k] = left[i]
		i++
		k++
	}
}

func msortSeq(a []int64) {
	if len(a) < 2 {
		return
	}
	mid := len(a) / 2
	msortSeq(a[:mid])
	msortSeq(a[mid:])
	merge(a, mid)
}

func msortPar(a []int64, cutoff int) {
	if len(a) < cutoff || len(a) < 2 {
		msortSeq(a)
		return
	}
	mid := len(a) / 2
	ch := make(chan struct{}, 1)
	go func() { // spawn
		msortPar(a[:mid], cutoff)
		ch <- struct{}{}
	}()
	msortPar(a[mid:], cutoff) // do the other half ourselves
	<-ch                      // join
	merge(a, mid)
}

func main() {
	if len(os.Args) < 6 {
		fmt.Fprintln(os.Stderr, "usage: bench <primes|fib|msort> <workers> <n> <cutoff> <reps>")
		os.Exit(2)
	}
	algo := os.Args[1]
	workers, _ := strconv.Atoi(os.Args[2])
	n, _ := strconv.ParseInt(os.Args[3], 10, 64)
	cutoff, _ := strconv.Atoi(os.Args[4])
	reps, _ := strconv.Atoi(os.Args[5])

	// The Go scheduler runs goroutines on GOMAXPROCS OS threads, so that is
	// the "number of workers". Sequential mode gets one.
	runtime.GOMAXPROCS(max(workers, 1))

	var data, a []int64
	if algo == "msort" {
		data = generate(n)
	}

	for r := 0; r < reps; r++ {
		a = slices.Clone(data) // fresh input, generated outside the timing
		t0 := time.Now()
		var result int64
		switch {
		case algo == "primes" && workers == 0:
			result = primesSeq(n)
		case algo == "primes":
			result = primesPar(n, workers)
		case algo == "fib" && workers == 0:
			result = fib(int(n))
		case algo == "fib":
			result = fibPar(int(n), cutoff)
		case algo == "msort" && workers == 0:
			msortSeq(a)
		case algo == "msort":
			msortPar(a, cutoff)
		default:
			fmt.Fprintln(os.Stderr, "unknown algo", algo)
			os.Exit(2)
		}
		secs := time.Since(t0).Seconds()
		if algo == "msort" {
			result = checksum(a)
		}
		fmt.Printf("RESULT %d %.6f\n", result, secs)
	}
}

//> using scala 3.3.6

// Parallel speedup benchmark - Scala (Futures on a ForkJoinPool).
//
// Usage: java -jar bench.jar <algo> <workers> <n> <cutoff> <reps>
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

import java.util.Arrays
import java.util.concurrent.ForkJoinPool
import scala.concurrent.{Await, ExecutionContext, Future}
import scala.concurrent.duration.Duration

object Bench:
  val Chunk = 10_000L // numbers per data-parallel work item

  // ---------- data parallel: count primes by trial division ----------

  def isPrime(n: Long): Boolean =
    if n < 2 then return false
    if n < 4 then return true
    if n % 2 == 0 then return false
    var i = 3L
    while i * i <= n do
      if n % i == 0 then return false
      i += 2
    true

  def countRange(lo: Long, hi: Long): Long = // [lo, hi)
    var c = 0L
    var k = lo
    while k < hi do
      if isPrime(k) then c += 1
      k += 1
    c

  def primesSeq(n: Long): Long = countRange(0, n + 1)

  def primesPar(n: Long)(using ExecutionContext): Future[Long] =
    val nchunks = (n + 1 + Chunk - 1) / Chunk
    val chunks = (0L until nchunks).map { c => // one chunk = one Future
      Future {
        val lo = c * Chunk
        countRange(lo, math.min(lo + Chunk, n + 1))
      }
    }
    Future.foldLeft(chunks)(0L)(_ + _)

  // ---------- task parallel: recursive Fibonacci with a cutoff ----------

  def fib(n: Int): Long = if n < 2 then n else fib(n - 1) + fib(n - 2)

  // Non-blocking join: Await inside a pool thread would pin that worker, so the
  // results are combined with a callback instead.
  def fibPar(n: Int, cutoff: Int)(using ExecutionContext): Future[Long] =
    if n < cutoff || n < 2 then Future.successful(fib(n))
    else
      val a = Future(fibPar(n - 1, cutoff)).flatten // spawn
      val b = fibPar(n - 2, cutoff)                 // other half here
      a.flatMap(x => b.map(x + _))                  // join

  // ---------- merge sort: parallel recursion, sequential merge ----------

  // Same generator and checksum in every language, so all must print the same value.
  def generate(n: Int): Array[Long] =
    val a = new Array[Long](n)
    var x = 42L
    var i = 0
    while i < n do
      x = x * 6364136223846793005L + 1442695040888963407L
      a(i) = x >>> 33
      i += 1
    a

  def checksum(a: Array[Long]): Long =
    var h = 0L
    var i = 0
    while i < a.length do
      h = h * 31 + a(i)
      i += 1
    h >>> 1

  // The buffer for the left half is allocated per merge: allocation is part of the test.
  def merge(a: Array[Long], lo: Int, mid: Int, hi: Int): Unit =
    val left = Arrays.copyOfRange(a, lo, mid)
    var i = 0
    var j = mid
    var k = lo
    while i < left.length && j < hi do
      if left(i) <= a(j) then
        a(k) = left(i)
        i += 1
      else
        a(k) = a(j)
        j += 1
      k += 1
    while i < left.length do
      a(k) = left(i)
      i += 1
      k += 1

  def msortSeq(a: Array[Long], lo: Int, hi: Int): Unit = // [lo, hi)
    if hi - lo >= 2 then
      val mid = lo + (hi - lo) / 2
      msortSeq(a, lo, mid)
      msortSeq(a, mid, hi)
      merge(a, lo, mid, hi)

  def msortPar(a: Array[Long], lo: Int, hi: Int, cutoff: Int)(using ExecutionContext): Future[Unit] =
    if hi - lo < cutoff || hi - lo < 2 then Future.successful(msortSeq(a, lo, hi))
    else
      val mid = lo + (hi - lo) / 2
      val left = Future(msortPar(a, lo, mid, cutoff)).flatten // spawn
      val right = msortPar(a, mid, hi, cutoff)                // other half here
      left.flatMap(_ => right).map(_ => merge(a, lo, mid, hi)) // join

  // For msort, sorts a in place and returns 0; main computes the checksum untimed.
  def runOnce(algo: String, workers: Int, n: Long, cutoff: Int, a: Array[Long]): Long =
    if workers == 0 then
      algo match
        case "primes" => primesSeq(n)
        case "fib"    => fib(n.toInt)
        case _        => msortSeq(a, 0, a.length); 0L
    else
      val pool = new ForkJoinPool(workers) // start-up is part of the cost
      try
        given ExecutionContext = ExecutionContext.fromExecutorService(pool)
        val result = algo match
          case "primes" => primesPar(n)
          case "fib"    => Future(fibPar(n.toInt, cutoff)).flatten
          case _        => Future(msortPar(a, 0, a.length, cutoff)).flatten.map(_ => 0L)
        Await.result(result, Duration.Inf)
      finally pool.shutdown()

  def main(args: Array[String]): Unit =
    if args.length < 5 || !Set("primes", "fib", "msort").contains(args(0)) then
      System.err.println("usage: java -jar bench.jar <primes|fib|msort> <workers> <n> <cutoff> <reps>")
      System.exit(2)
    val algo = args(0)
    val workers = args(1).toInt
    val n = args(2).toLong
    val cutoff = args(3).toInt
    val reps = args(4).toInt

    val msort = algo == "msort"
    val data = if msort then generate(n.toInt) else Array.empty[Long]

    runOnce(algo, workers, n, cutoff, data.clone()) // JIT warm-up, not timed
    for _ <- 0 until reps do
      val a = data.clone() // fresh input, generated outside the timing
      val t0 = System.nanoTime()
      val computed = runOnce(algo, workers, n, cutoff, a)
      val secs = (System.nanoTime() - t0) / 1e9
      val result = if msort then checksum(a) else computed
      println(f"RESULT $result%d $secs%.6f")

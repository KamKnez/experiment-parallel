# Handout: Multicore-Speedup von Rust, Go, Java, C++ und Scala

Kamilo Knezevic · Stefan Wild · LV Wissenschaftliches Arbeiten und Schreiben

*Dieses Dokument ist für uns zum Lernen und Nachschlagen gedacht, nicht für das Publikum. Alle Zahlen stammen aus `results-linux/summary.csv` und `results-windows/summary.csv`. Wo etwas Vermutung ist und nicht gemessen, steht es ausdrücklich dabei.*

---

## 1. Worum geht es in einem Absatz

Wir haben dieselben drei CPU-lastigen Aufgaben (Primzahlen zählen, rekursives Fibonacci, Merge Sort) in fünf Sprachen geschrieben, einmal rein sequentiell und einmal parallel mit 1, 2, 4 und 8 Workern. Gemessen wurde auf zwei Rechnern mit je 8 physischen Kernen. Die Hauptkennzahl ist der **Speedup gegenüber dem eigenen sequentiellen Code** der jeweiligen Sprache. Es geht also darum, wie gut eine Sprache *skaliert*. Zusätzlich haben wir die absolute Laufzeit angeschaut, weil Speedup allein nicht sagt, wer schnell ist.

**Forschungsfrage:** Wie stark profitieren Rust, Go, Java, C++ und Scala vom Wechsel von sequentiellem zu parallelem Code auf mehreren Kernen, und hängt das von der Art des Problems ab?

**Kurzantwort:** Die Art des Problems bestimmt das Skalieren stärker als die Sprache. Reine Rechenarbeit skaliert überall fast ideal (7,2 – 7,6× von 8). Speicherlastiges Sortieren schafft nur 2,9 – 4,7×. Bei Tasks fällt nur C++ (OpenMP) deutlich ab (4,4×). Eine „beste Sprache“ gibt es nicht pauschal: Rust ist bei den beiden Rechenaufgaben absolut am schnellsten, bei Merge Sort liegen Scala und Java knapp vorn.

---

## 2. Begriffe und Hintergrund

**Warum Parallelität?** Die Taktfrequenz steigt seit Mitte der 2000er kaum noch (Leistungsaufnahme und Abwärme). Mehr Leistung gibt es durch mehr Kerne. Software muss die Kerne aber selbst nutzen.

**Speedup** S(p) = T_seq / T_p. Wie viel schneller ist der parallele Lauf mit p Workern als der sequentielle? Ideal ist S(p) = p.

**Effizienz** E(p) = S(p) / p. Anteil der idealen Beschleunigung, der erreicht wird. Bei 8 Workern bedeutet 100 % einen Speedup von 8.

**Amdahls Gesetz.** Besteht ein Programm zu einem Anteil s aus sequentieller Arbeit, gilt S(p) ≤ 1 / (s + (1 − s)/p). Der sequentielle Teil begrenzt also den maximalen Speedup, egal wie viele Kerne man hat. Beispiel: s = 10 % → maximal 10×, bei 8 Kernen höchstens 4,7×.

**Serial Fraction nach Karp-Flatt.** Aus einem gemessenen Speedup lässt sich schätzen, welcher Anteil sich „wie sequentiell“ verhält: e(p) = (1/S − 1/p) / (1 − 1/p).
- bleibt e(p) bei steigendem p ungefähr gleich → fester sequentieller Anteil (Amdahl)
- wächst e(p) mit p → zusätzlicher Overhead, der mit der Worker-Zahl mitwächst (Synchronisation, Speicher, Scheduler)
- ist e(p) ≈ 0 → praktisch voll parallel

**Work-Stealing.** Jeder Worker hat eine eigene Warteschlange mit Tasks. Hat ein Worker nichts mehr zu tun, „stiehlt“ er Tasks von einem anderen. Das gleicht ungleiche Arbeit gut aus und vermeidet eine zentrale Warteschlange als Engpass. Genutzt von Rayon (Rust), Go-Scheduler, Java ForkJoinPool und Scala Futures (auf ForkJoinPool).

**Cutoff.** Bei rekursiven Aufgaben gibt es eine Schwelle, ab der nicht mehr in Tasks aufgeteilt wird. Ohne sie wären die Tasks winzig und der Verwaltungsaufwand größer als die Nutzarbeit.

**cv (Variationskoeffizient)** = Standardabweichung / Mittelwert der Laufzeiten, in Prozent. Maß für die Streuung. Hier sind unter 1 – 3 % normal, über 5 % gilt als verrauscht.

**Bootstrap-Intervall.** Wir ziehen aus den 10 Messungen immer wieder mit Zurücklegen, berechnen jedes Mal den Median und nehmen den mittleren 95-%-Bereich. Das zeigt, wie sicher der Median ist, ohne eine Verteilungsannahme zu treffen.

**JIT, GC, Warm-up.** Java und Scala laufen auf der JVM. Der Just-in-Time-Compiler übersetzt heißen Code erst zur Laufzeit, und der Garbage Collector räumt Speicher auf. Deshalb gibt es einen Warm-up-Lauf vor der Messung.

---

## 3. Die drei Algorithmen im Detail

### 3.1 Datenparallel: Primzahlen zählen
- Aufgabe: Zähle alle Primzahlen in [0, n] mit n = 15.000.000 per Probedivision.
- Die Zahlen werden in Chunks zu je 10.000 aufgeteilt. Worker holen sich Chunks dynamisch (atomarer Zähler bzw. dynamischer Scheduler).
- Warum dynamisch: Die Arbeit pro Zahl ist ungleich (größere Zahlen brauchen länger). Feste Aufteilung würde einige Worker früher fertig werden lassen.
- Keine Abhängigkeiten zwischen den Chunks, kaum Speicherzugriffe. Das ist der „Idealfall“ für Parallelität.
- Prüfwert: π(10⁶) = 78.498, π(2·10⁷) = 1.270.607. Für n = 15 Mio. ist der Wert 970.704 (aus den Rohdaten).

**In einfachen Worten:** Ein Stapel Aufgabenzettel (je 10.000 Zahlen prüfen) liegt auf dem Tisch, jeder Helfer nimmt sich den nächsten, sobald er fertig ist. Ein fester Anteil pro Helfer wäre unfair, weil große Zahlen länger dauern.

### 3.2 Taskparallel: Fibonacci
- Aufgabe: `fib(45)` rekursiv. Ist n ≥ cutoff (30), wird `fib(n-1)` als Task gestartet, `fib(n-2)` im aktuellen Thread berechnet, danach Join und Addition. Darunter läuft normale sequentielle Rekursion. Die Abbruchbedingung `n < 2` gilt auch in der parallelen Variante.
- Bewusst ein „schlechter“ Algorithmus, weil er viel reine Rechenarbeit erzeugt.
- Es entstehen etwa 1.600 Tasks (n − cutoff = 15), in jeder Sprache gleich viele.
- Der Task-Baum ist ungleichmäßig: `fib(n-1)` ist größer als `fib(n-2)`. Der Scheduler muss gut balancieren.
- Prüfwerte: fib(30) = 832.040, fib(42) = 267.914.296. Rohdaten: fib(45) = 1.134.903.170.

**In einfachen Worten:** Eine große Aufgabe teilt sich in zwei kleinere. Eine gibt man einem freien Kollegen, die andere macht man selbst, dann addiert man. Ganz unten sind die Aufgaben so klein, dass Weitergeben mehr kostet als Selbstrechnen (Cutoff).

### 3.3 Speicherlastig: Merge Sort
- Aufgabe: 50 Millionen 64-Bit-Zahlen (ca. 400 MB) per Top-Down-Merge-Sort sortieren.
- Bei Bereichsgröße ≥ 50.000: linke Hälfte als Task, rechte Hälfte selbst sortieren, Join, dann mergen. Darunter sequentiell. Das ergibt ca. 1.000 sequentielle Blätter.
- Der Merge selbst ist immer sequentiell und legt einen Puffer für die linke Hälfte an (Absicht: Allokator- und GC-Kosten sollen im Ergebnis stecken).
- Wir benutzen **kein** Library-Sort, sondern in allen Sprachen den gleichen eigenen Algorithmus.
- Eingabe: Pseudozufallszahlen per LCG `x = x * 6364136223846793005 + 1442695040888963407` (mit Überlauf, Seed 42), Wert `x >>> 33`. Prüfsumme: `h = h * 31 + v` über das sortierte Array, dann `h >>> 1`. Beides identisch in allen Sprachen. Erzeugen und Prüfsumme sind außerhalb der Zeitmessung, jeder Lauf sortiert eine frische Kopie.

**In einfachen Worten:** Man teilt einen Kartenstapel, bis jeder nur ein kleines Häufchen hat, sortiert die Häufchen und mischt sie paarweise wieder zusammen. Unten arbeiten alle gleichzeitig, oben immer weniger. Der letzte Merge geht über alle 50 Mio. Zahlen und läuft auf einem Worker. Darum skaliert Merge Sort schlechter.

**Warum diese Wahl?** Die drei Aufgaben haben je einen anderen Flaschenhals: Rechenleistung (Primes), Task-Verwaltung und Scheduling (Fib), Speicherbandbreite und Allokation (Merge Sort).

---

## 4. Die fünf Sprachen und ihre Modelle

| Sprache | Datenparallel | Taskparallel | Laufzeit / Besonderheit |
|---|---|---|---|
| Rust | Rayon: `into_par_iter().with_max_len(1)` | `rayon::join` | nativ, kein GC, Pool pro Lauf gebaut |
| Go | Goroutines, atomarer Chunk-Zähler, `GOMAXPROCS` = Worker | Goroutine + Channel je Spawn | eigener Scheduler, GC |
| Java | `ForkJoinPool.invokeAll` | `RecursiveTask` (fork/join) | JVM, JIT, GC, 1 Warm-up |
| C++ | OpenMP `parallel for schedule(dynamic, 1)` | OpenMP `task` + `taskwait` | nativ, libgomp |
| Scala | `Future` je Chunk auf ForkJoinPool | `Future`, Join per `flatMap` (nicht blockierend) | JVM, JIT, GC, 1 Warm-up |

Hinweise:
- **Scala joint nicht blockierend.** Ein `Await` in einem Pool-Thread würde den Worker festhalten. Daher werden Ergebnisse mit `flatMap` verknüpft. Das unterscheidet Scala bewusst von Javas Fork/Join auf demselben Pool-Typ.
- **C++/OpenMP:** libgomp behält seine Threads zwischen parallelen Regionen. Deshalb zahlt nur der erste Lauf den Thread-Start. In unserem Design läuft aber jeder Lauf in einem frischen Prozess, also zählt der Start trotzdem mit.
- Das ist ein Vergleich von **gleichem Design mit jeweils üblichen Mitteln**, nicht von gleichem Code. Das ist eine Limitation (Abschnitt 9).

---

## 5. Methodik

**Gemeinsame Schnittstelle:** `<prog> <primes|fib|msort> <workers> <n> <cutoff> <reps>`. `workers = 0` bedeutet reiner sequentieller Code. Jedes Programm gibt pro Lauf `RESULT <wert> <sekunden>` aus. Das Python-Skript `run.py` ist nur Treiber (Kompilieren, Starten, Prüfen, Auswerten, Plotten).

**Baseline:** Der echte sequentielle Code, nicht der parallele Code mit 1 Worker. So zeigt sich auch der Overhead der Parallelisierung (Speedup bei 1 Worker ≈ 1,00 heißt: kaum Overhead).

**Worker-Stufen:** 0 (sequentiell), 1, 2, 4, 8. Das Maximum ist die Zahl der **physischen** Kerne. Hyperthreads (16 logische) wurden nicht benutzt.

**Wiederholungen:** 10 Runden. In jeder Runde läuft jede Konfiguration (Sprache × Algorithmus × Worker) einmal in einem **frischen Prozess**, und die Reihenfolge wird pro Runde neu gemischt. Gründe:
- frischer Prozess: sonst blieben JIT-Zustand und Speicherlayout zwischen Läufen gleich, und die Streuung zwischen Läufen wäre versteckt
- zufällige Reihenfolge: langsamer Drift (Hitze, Takt) begünstigt keine Konfiguration

**Zeitmessung:** Thread-Pool-Start liegt im gemessenen Bereich (bewusst, gehört zu den Kosten). Java und Scala machen einmal einen ungemessenen Warm-up-Lauf. Bei Merge Sort wird nur die Sortierung gemessen.

**Statistik:** Median, 95-%-Bootstrap-Intervall, Quartile, cv. Konfigurationen mit cv > 5 % gelten als verrauscht. **Ausreißer werden nie entfernt.** Speedup = Median T_seq / Median T_p, Effizienz = S/p, Serial Fraction nach Karp-Flatt (nur für p > 1).

**Korrektheit:** `run.py` vergleicht jeden Lauf mit dem sequentiellen Ergebnis, auch zwischen den Sprachen. Bei Abweichung bricht es mit `WRONG RESULT` ab.

**Größen:** Primes n = 15 Mio. · Fib n = 45, Cutoff 30 · Merge Sort n = 50 Mio., Cutoff 50.000.

---

## 6. Testsysteme

| | Linux (Hauptdatensatz) | Windows |
|---|---|---|
| Maschine | Desktop | ASUS Zenbook UX425QA (Laptop, am Netz) |
| CPU | AMD Ryzen 7 5800X | AMD Ryzen 7 5800HS |
| Kerne / Threads | 8 / 16 | 8 / 16 |
| Takt | bis 4,85 GHz | 3,2 GHz Basis, bis 4,4 GHz Boost |
| L3 | 32 MiB | 16 MiB |
| RAM | 62 GiB | 15,4 GiB |
| OS | Ubuntu 24.04.5, Linux 7.0 | Windows 11 Home 25H2 |
| Energie | `powersave`-Governor, Boost an | „Balanced“ mit Modus „Best performance“, Boost an |
| C++ | g++ 13.3.0 | MinGW-w64 g++ 13.2.0 |
| Rust | 1.95.0 | 1.99.0 (MSVC) |
| Go | 1.25.4 | 1.26.1 |
| Java | OpenJDK 21 | Oracle JDK 23 |
| Scala | 3.3.6 | 3.3.6 |

Gemeinsam: C++ mit `-std=c++20 -O3 -fopenmp` (kein `-march=native`), Rayon 1.12.0, 10 Runden, gleiche Größen.

---

## 7. Ergebnisse

### 7.1 Speedup bei 8 Workern (Linux, mit Effizienz)

| | Primes | Fib | Merge Sort |
|---|---|---|---|
| Rust | 7,53× (94 %) | 7,53× (94 %) | 4,07× (51 %) |
| Go | 7,59× (95 %) | 7,54× (94 %) | 4,68× (59 %) |
| Java | 7,21× (90 %) | 6,81× (85 %) | 4,17× (52 %) |
| C++ | 7,63× (95 %) | 4,38× (55 %) | 2,92× (37 %) |
| Scala | 7,16× (90 %) | 7,59× (95 %) | 4,24× (53 %) |

### 7.2 Speedup über alle Worker (Linux)

| Algo | Sprache | 1 | 2 | 4 | 8 |
|---|---|---|---|---|---|
| Primes | Rust | 1,00 | 1,98 | 3,82 | 7,53 |
| | Go | 1,00 | 1,98 | 3,85 | 7,59 |
| | Java | 1,00 | 1,98 | 3,80 | 7,21 |
| | C++ | 1,00 | 1,99 | 3,87 | 7,63 |
| | Scala | 1,00 | 1,98 | 3,81 | 7,16 |
| Fib | Rust | 1,00 | 1,99 | 3,85 | 7,53 |
| | Go | 1,00 | 1,98 | 3,87 | 7,54 |
| | Java | 1,00 | 2,00 | 3,72 | 6,81 |
| | C++ | 1,07 | 1,71 | 2,42 | 4,38 |
| | Scala | 1,00 | 2,05 | 4,04 | 7,59 |
| Merge Sort | Rust | 1,00 | 1,86 | 2,94 | 4,07 |
| | Go | 0,99 | 1,85 | 3,21 | 4,68 |
| | Java | 0,98 | 1,82 | 2,89 | 4,17 |
| | C++ | 1,00 | 1,72 | 2,55 | 2,92 |
| | Scala | 0,96 | 1,80 | 2,90 | 4,24 |

### 7.3 Absolute Laufzeiten, Linux (Median in Sekunden)

| Algo | Sprache | sequentiell | 8 Worker |
|---|---|---|---|
| Primes | Rust | 1,96 | **0,26** |
| | C++ | 2,27 | 0,30 |
| | Go | 2,28 | 0,30 |
| | Java | 2,29 | 0,32 |
| | Scala | 2,29 | 0,32 |
| Fib | Rust | 2,20 | **0,29** |
| | C++ | **1,57** | 0,36 |
| | Java | 3,06 | 0,45 |
| | Scala | 3,53 | 0,47 |
| | Go | 4,48 | 0,59 |
| Merge Sort | Scala | 4,59 | **1,08** |
| | Java | 4,72 | 1,13 |
| | Rust | 4,68 | 1,15 |
| | Go | 5,58 | 1,19 |
| | C++ | **4,58** | 1,57 |

### 7.4 Serial Fraction (Linux, bei 2 / 4 / 8 Workern, in %)

| | Primes | Fib | Merge Sort |
|---|---|---|---|
| Rust | 1,3 / 1,5 / 0,9 | 0,5 / 1,3 / 0,9 | 7,5 / 12,0 / 13,8 |
| Go | 0,9 / 1,3 / 0,8 | 0,9 / 1,1 / 0,9 | 8,0 / 8,3 / 10,1 |
| Java | 0,9 / 1,7 / 1,6 | 0,3 / 2,5 / 2,5 | 9,9 / 12,7 / 13,1 |
| C++ | 0,6 / 1,1 / 0,7 | 17,2 / 21,7 / 11,8 | 16,4 / 19,0 / 24,8 |
| Scala | 1,1 / 1,7 / 1,7 | ≈ 0 (negativ) / ≈ 0 / 0,8 | 11,3 / 12,6 / 12,7 |

### 7.5 Windows (Speedup bei 8 Workern und absolute Zeit)

| Algo | Sprache | Speedup 8 | Zeit 8 Worker [s] | sequentiell [s] |
|---|---|---|---|---|
| Primes | Rust | 6,30 | **0,37** | 2,33 |
| | Go | 6,86 | 0,39 | 2,70 |
| | Scala | 6,48 | 0,42 | 2,70 |
| | C++ | 6,40 | 0,42 | 2,69 |
| | Java | 6,42 | 0,42 | 2,70 |
| Fib | C++ | 4,71 | **0,40** | 1,91 |
| | Rust | 6,71 | 0,41 | 2,74 |
| | Java | 6,03 | 0,59 | 3,56 |
| | Scala | 5,98 | 0,63 | 3,78 |
| | Go | 6,84 | 0,72 | 4,94 |
| Merge Sort | Go | 4,61 | **1,42** | 6,56 |
| | Java | 4,38 | 1,43 | 6,25 |
| | Rust | 4,78 | 1,43 | 6,85 |
| | Scala | 3,78 | 1,69 | 6,38 |
| | C++ | 3,42 | 1,85 | 6,35 |

---

## 8. Was man aus den Ergebnissen lesen kann

1. **Datenparallel skaliert fast ideal.** Alle Sprachen 7,2 – 7,6× bei 8 Workern. Serial Fraction ≈ 1 %. Die Wahl der Sprache ist hier fast egal. Java und Scala liegen etwas darunter (Effizienz knapp 90 %), möglicherweise wegen JVM-Hintergrundthreads (JIT, GC). Das haben wir nicht getrennt gemessen.

2. **Bei Tasks zeigt sich die Laufzeitumgebung.** Rust, Go und Scala erreichen 7,5 – 7,6×, Java 6,8×. C++ erreicht nur 4,4×. Das Intervall für C++ ist eng (4,34 – 4,50), es ist also kein Zufall. Schon bei 2 Workern fehlt viel (1,71 statt 2). Serial Fraction 12 – 22 % schon bei 2 Workern, dann nicht weiter wachsend. Das passt eher zu hohen festen Kosten pro Task als zu einem Engpass, der mit p wächst. Die Ursache haben wir nicht geklärt. Ein Austausch von `taskwait` gegen `taskgroup` brachte nur ca. 5,1×. Plausible Vermutung: Verwaltung der OpenMP-Tasks in libgomp (zentrale Queue, Sperren). Profiling fehlt.

3. **Speicherlast begrenzt alle Sprachen.** Merge Sort 2,9 – 4,7× bei 8 Workern, Effizienz 37 – 59 %. Zwei Effekte:
   - *Sequentielle Merges.* Der oberste Merge läuft über das ganze Array auf einem Thread, dann zwei halb so große usw. Die Gesamtarbeit beträgt etwa n·log₂(n) ≈ 25,6·n, die „kritische Kette“ etwa 2·n. Nach einer groben Greedy-Abschätzung (T_p ≈ W/p + Kette) ergibt sich ein Speedup von höchstens ≈ 25,6 / (25,6/8 + 2) ≈ 4,9×. Gemessen sind 4,1 – 4,7× für vier Sprachen, was gut dazu passt (Go am nächsten). Das ist eine Überschlagsrechnung, kein Beweis.
   - *Speicherbandbreite und Allokation.* Jede Merge-Stufe liest und schreibt das ganze Array, 8 Kerne teilen sich die Bandbreite, und jeder Merge allokiert einen Puffer. Die Serial Fraction steigt mit p (z. B. Rust 7,5 → 12,0 → 13,8 %), was auf wachsenden Overhead hindeutet, nicht nur auf einen festen Anteil.

4. **Der Parallel-Overhead ist klein.** Bei 1 Worker liegt der Speedup bei ≈ 1,00 (Primes, Fib). Ausnahmen: Java (0,98) und Scala (0,96) bei Merge Sort. C++-Fib mit 1,07 ist sogar schneller als der sequentielle Code, wahrscheinlich ein Compiler-Effekt (anderes Inlining/Codelayout). Das ist nicht untersucht.

5. **Hohe Streuung ist ein Warnsignal.** Verrauscht (cv > 5 %): C++-Fib und C++-Msort bei 4 Workern auf Linux (11 % bzw. 9 %), mehrere Konfigurationen auf Windows (bis 16 %). Dort sind die Intervalle breiter, und kleine Unterschiede sollte man nicht interpretieren.

6. **Windows verhält sich qualitativ gleich, nur schlechter.** Speedup bei 8 Workern 5 – 15 % niedriger (Primes 6,3 – 6,9 statt 7,2 – 7,6). Mögliche Gründe: Laptop (Boost und Thermik), OS-Scheduler, Hintergrundlast. Nicht getrennt untersucht. Dass beide Systeme dasselbe Muster zeigen, stärkt die Aussage, dass Problemtyp und Runtime entscheidend sind.

### 8.1 Welche Sprache ist am besten?

Das hängt von der Frage ab:

- **Beste Skalierung (relativ):** Bei Primes gibt es keinen echten Sieger. Bei Fib sind Rust, Go und Scala gleichauf, C++ klar schwächer. Bei Merge Sort hat Go den höchsten Speedup (4,68×), C++ den niedrigsten.
- **Schnellste Zeit (absolut, 8 Worker, Linux):** Rust gewinnt Primes (0,26 s) und Fib (0,29 s). Merge Sort gewinnt Scala (1,08 s), dicht gefolgt von Java (1,13 s) und Rust (1,15 s). Der Abstand der drei ist klein, vor allem auf Windows (alle ≈ 1,4 s).
- **Am konsistentesten:** Rust (zweimal Platz 1, einmal Mittelfeld, auf Windows ähnlich).
- **Vorsicht: Speedup ≠ Geschwindigkeit.**
  - Go-Fib hat 7,5× Speedup, ist aber sequentiell (4,48 s) und bei 8 Workern (0,59 s) die langsamste Sprache. Eine langsame Baseline macht einen hohen Speedup leichter. Warum Go-Fib sequentiell so langsam ist, haben wir nicht untersucht (denkbar: weniger aggressive Optimierung rekursiver Aufrufe).
  - C++-Fib ist sequentiell am schnellsten (1,57 s), skaliert aber nur 4,4×, und liegt bei 8 Workern trotzdem auf Platz 2 (0,36 s).
  - C++-Merge-Sort ist sequentiell am schnellsten (4,58 s), bei 8 Workern aber am langsamsten (1,57 s).
- **Rust vorn bei Primes:** In beiden Datensätzen ist Rust sequentiell ca. 14 % schneller als die anderen (Linux 1,96 vs. 2,27 s). Warum, haben wir nicht untersucht.

---

## 9. Unterfragen und Antworten

| Unterfrage | Antwort |
|---|---|
| 1. Wie skaliert jede Sprache bei Rechenarbeit, Tasks und Speicherlast? | Primes: alle 7,2 – 7,6× (Effizienz 90 – 95 %). Fib: Rust, Go, Scala 7,5 – 7,6×, Java 6,8×, C++ 4,4×. Merge Sort: 2,9 – 4,7× (Effizienz 37 – 59 %). Windows gleiches Muster, 5 – 15 % schwächer. |
| 2. Wo geht Effizienz verloren? | Primes: praktisch nirgends (Serial Fraction ≈ 1 %). Merge Sort: sequentielle Merges und Speicher (8 – 25 %, steigt mit p). C++-Fib: hohe feste Kosten pro Task (12 – 22 %), Ursache nicht geklärt. |
| 3. Ist die Sprache mit dem besten Speedup auch die schnellste? | Nein, nicht zwingend. Go-Fib: 7,5× Speedup, aber absolut Letzter. C++-Msort: sequentiell Erster, bei 8 Workern Letzter. Rust ist bei Primes und Fib am schnellsten, bei Merge Sort liegen Scala und Java knapp vorn. |

---

## 10. Limitationen (ehrlich benennen)

- **Interne Validität.** Gute Kontrollen (frische Prozesse, zufällige Reihenfolge, Ergebnisprüfung, Ausreißer bleiben drin). Aber: Aussagen zu *Ursachen* (z. B. C++-Tasks, Allokator) sind Vermutungen. Es gab kein Profiling.
- **Externe Validität.** Drei Algorithmen, je eine Problemgröße, 8 physische Kerne, eine CPU-Familie (AMD Zen 3), ein Compiler/Runtime je System. Für 64 Kerne, Intel oder ARM gilt das nicht automatisch.
- **Gleiches Design ≠ optimaler Code.** In jeder Sprache wurde das übliche Parallel-Modell mit derselben Struktur benutzt. Ein Experte könnte je Sprache anders optimieren (z. B. C++-Tasks anders gruppieren).
- **Boost und Energie.** Ein Kern läuft höher getaktet als alle Kerne zusammen, das senkt den gemessenen Speedup leicht. Auf Linux war der Governor `powersave` mit Boost.
- **Zwei Systeme, unterschiedliche Software-Versionen.** Java 21 vs. 23, Go 1.25 vs. 1.26 usw. Unterschiede zwischen Linux und Windows sind daher nicht allein auf das Betriebssystem zurückzuführen.
- **Nur 10 Runden.** Reicht für Mediane und Intervalle, aber nicht für sehr feine Unterschiede (< ca. 5 %).
- **Hyperthreads nicht getestet.** Worker > 8 würden SMT nutzen.

**Ausblick (nicht gemacht):** Cutoff-Sweep (Overhead pro Task), andere Chunk-Größe, Worker bis 16 (SMT), Weak Scaling, Profiling von C++-Fib und Merge Sort.

---

## 11. Mögliche Fragen und Antworten

**Warum der eigene sequentielle Code als Baseline, nicht „parallel mit 1 Worker“?**
Parallel mit 1 Worker enthält schon Overhead (Tasks, Synchronisation). Der Vergleich mit echtem sequentiellen Code zeigt diesen Overhead. Er war klein (Speedup bei 1 Worker ≈ 1,00).

**Warum Median statt Mittelwert?**
Der Median ist robust gegen einzelne Ausreißer (z. B. ein Lauf, in dem das OS kurz etwas anderes tut). Bei Mittelwerten würde ein Ausreißer das Ergebnis verschieben.

**Warum 10 Runden in frischen Prozessen?**
Wiederholungen im selben Prozess verstecken Streuung durch JIT und Speicherlayout. Mit frischen Prozessen und zufälliger Reihenfolge ist jede Messung unabhängiger.

**Warum wurden Ausreißer nicht entfernt?**
Ausreißer zu entfernen, ist ein Freiheitsgrad, mit dem man Ergebnisse „schönen“ kann. Stattdessen nutzen wir den Median und weisen auf Streuung (cv) hin.

**Warum nur bis 8 Worker, obwohl 16 Threads da sind?**
Mehr als 8 Worker landen auf Hyperthreads, die sich Kerne teilen. Die Kurve würde abknicken, aber nicht wegen der Sprache. Wir wollten die Sprachen auf echten Kernen vergleichen.

**Warum skaliert Merge Sort so schlecht?**
Sequentielle Merges (Top-Merge über das ganze Array) und Speicherbandbreite/Allokation. Eine grobe Überschlagsrechnung ergibt ca. 4,9× als Obergrenze bei 8 Kernen, gemessen sind bis 4,7×.

**Warum ist C++ bei Fib so schlecht?**
Wissen wir nicht sicher. Es ist reproduzierbar (Linux und Windows, enges Intervall). Vermutung: Overhead der OpenMP-Task-Verwaltung in libgomp. `taskgroup` statt `taskwait` brachte nur 5,1×. Das wäre ein Anlass für Profiling.

**Was ist ein Cutoff, und warum 30?**
Unterhalb der Schwelle läuft Fib sequentiell, damit nicht Milliarden winziger Tasks entstehen. Bei Fib 45 und Cutoff 30 sind es ≈ 1.600 Tasks (n − cutoff = 15), in allen Sprachen gleich viele.

**Ist die „beste Sprache“ Rust?**
Bei den zwei Rechenaufgaben ja (schnellste Zeit), bei Merge Sort nicht (Scala/Java knapp vorn). Aussage nur für unser Setup.

**Warum ist Scala-Fib bei 2 Workern 2,05× (über ideal)?**
Das ist Rauschen: Das 95-%-Intervall (2,02 – 2,10) liegt knapp über 2, und die Serial Fraction wird dadurch negativ. Ein echter superlinearer Effekt ist unwahrscheinlich. Wir behandeln es als Messungenauigkeit.

**Wie weiß man, dass alle Programme dasselbe berechnen?**
Jeder Lauf liefert einen Wert (Anzahl Primzahlen, fib-Wert, Prüfsumme des sortierten Arrays). `run.py` vergleicht ihn mit dem sequentiellen Ergebnis, auch zwischen den Sprachen, und bricht bei Abweichung ab.

**Was würdet ihr als Nächstes machen?**
Cutoff-Sweep (misst Task-Overhead), Profiling von C++-Fib, mehr Kerne/SMT, andere CPU-Architektur.

---

## 12. Glossar

| Begriff | Bedeutung |
|---|---|
| Speedup | T_seq / T_p |
| Effizienz | Speedup / Anzahl Worker |
| Amdahl | sequentieller Anteil begrenzt den maximalen Speedup |
| Karp-Flatt | Schätzung des sequentiellen Anteils aus gemessenem Speedup |
| Work-Stealing | leere Worker stehlen Tasks von anderen |
| Task | kleine Arbeitseinheit, die der Scheduler verteilt |
| Cutoff | Schwelle, unter der nicht mehr in Tasks geteilt wird |
| Join | Warten, bis ein Task fertig ist |
| JIT | Übersetzung zur Laufzeit (JVM) |
| GC | Garbage Collector, räumt Speicher auf |
| SMT / Hyperthreading | zwei logische Threads teilen sich einen physischen Kern |
| Boost | kurzzeitig höherer CPU-Takt |
| cv | Streuung in % (Standardabweichung / Mittelwert) |
| Bootstrap | Neuziehen der Messwerte mit Zurücklegen, um Unsicherheit zu schätzen |
| LCG | einfacher Pseudozufallsgenerator (Linear Congruential Generator) |
| Strong Scaling | gleiche Problemgröße, mehr Kerne (das haben wir gemessen) |
| Weak Scaling | Problemgröße wächst mit den Kernen (nicht gemessen) |

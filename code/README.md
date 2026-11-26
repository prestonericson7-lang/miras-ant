# The code

## `ant.c`: the census on a CPU

One C file, no libraries, integers only. It runs every start of an *n* by *n* box (*n* = 3 to 6) until its road is proven or the cap is reached, then prints the census and the chain.

```
cc -O2 -o ant ant.c
./ant n=4 part=0/1
```

Arguments: `n=<3..6>`, `part=<p>/<P>` (run part *p* of *P* equal parts of the box), `cap=<steps>` (default 1,048,576), `grid=<side>` (default 2048; the grid does not wrap, and an ant that reaches its edge is counted "off the grid"), `clear=1` (clear the whole grid between starts: the slow check of the faster "stamp" trick, which must give the same chain), `oeis=1` (the blank grid's black-cell count against OEIS A255938).

It prints, per part: proven, unresolved and off-grid counts, the onsets by powers of two, the eight slowest starts, the CPU time, and `ANT: done chain <16 hex digits>`. The chain is an FNV-1a hash over every start's (onset, drift) in order, then the totals: any machine that runs the same part must print the same chain.

Known chains: 3 by 3 `441f36ea4c690157`; 4 by 4 `34cf86e864c370ff` (halves `33aa595d2cfedd2c`, `4accd0048d31c714`); 5 by 5 halves `e20b2fe5aaee8d3e`, `45a49c821381faf4`.

## `gpu/`: the 6 by 6 on two GPUs

- `ant_gpu4.cl`: the OpenCL kernel. `ant.c`'s rules and proof line for line, one GPU thread walking one start at a time on its own bit grid, plus the doorway features: the 104-step approach fingerprint, the stumble (mismatches against the road at the best phase) and the backward reach. Its chain is the same definition as `ant.c`'s, hashed on the card.
- `ant_census6d.py`: the runner. It cuts the 2^36 starts into 256 parts of 2^28, claims the next free part (so two cards can share the box), runs it in chunks of 2^24, and writes the part's result as `census6/done/part_NNN.json` beside itself (or in `dir=...`). Example: `python -I ant_census6d.py dev=Arc threads=65536 G=1024`. To test it on a box whose chain is known: `n=4 part_bits=16 chunk_bits=12` runs the whole 4 by 4 as one part and must give `34cf86e864c370ff`.
- `clrt.py`: a small OpenCL loader through `ctypes` and Windows' own `OpenCL.dll`, so nothing is installed.
- `census_summary.py`: reads every finished part and writes the whole box's summary (`python census_summary.py [folder]`).

The runner was written for Windows (the OpenCL loader and its one-worker-per-card check). The 6 by 6 was counted by four successive versions of it on an Intel Arc Pro B70 and an NVIDIA RTX 2080 SUPER, from November 20 to November 23, 2026. The versions differ only in speed and bookkeeping: how they wait on the card, how they hash the chain, and how they record a start that doesn't finish (none did). Every version gives the same chain. This is the last one.

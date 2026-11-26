/* ant.c -- THE ANT CENSUS (11-18, Mira's own line): every start in an n x n box (the ant at the box's center
   facing up; start c = the n*n-bit picture, bit k = cell k black, k = row * n + col), each run exactly until its highway is PROVEN or the cap.
   Langton's ant: on white turn right, on black turn left; flip the cell; step forward. Integers only; the same source for the PC and the boards.
   THE PROOF (exact; the ledger's argument): the last 1024 steps are kept (cell, color seen on entry). At step t the newest 104-step period B is
   compared with the one before it, A: every cell of B the matching cell of A shifted by one drift u in {(2,2), (2,-2), (-2,2), (-2,-2)} with the same
   entry color. Then m = span/4 + 1 consecutive periods must be shift-equal that way (span = the footprint's extent along u in projection units;
   4m > span closes every overlap of the footprint with its own translates inside the verified history), and every cell of the footprint shifted
   by k*u (k = 1, 2, ...) that lies in no earlier translate must be white now, checked up to the furthest black cell in direction u (the furthest
   black cell in each diagonal direction is kept as cells turn black; beyond it everything is white). By determinism the ant then repeats the
   period forever. The ONSET is the first step of the oldest verified period. Arguments: n=<3..6> part=<p>/<P> [cap=<steps>, default 1048576]
   [grid=<side>, default 2048] [clear=1: clear the grid between starts, the slow check of the stamp trick] [oeis=1: the empty start's black-cell
   count against OEIS A255938 (a(n+104) = a(n) + 12 for n > 9976), the convention check]. Prints the census and an FNV chain over every start's
   (onset, drift) in order, then CTIME and the chain line. */
#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <stdlib.h>
#include <time.h>

#define PER 104
#define HIST 1024
#define MAXM 8

static uint64_t chain = 0xcbf29ce484222325ull;
static void hash64(uint64_t v) { for (int i = 0; i < 8; i++) { chain ^= (v >> (8 * i)) & 0xff; chain *= 0x100000001b3ull; } }

static uint16_t *g; static int G, GHALF; static uint16_t gen = 1;
static int hx[HIST], hy[HIST]; static uint8_t hc[HIST];
static int32_t maxp[4];                                   /* the furthest black cell's projection, per diagonal direction */
static const int DX[4] = {2, 2, -2, -2}, DY[4] = {2, -2, 2, -2};
static inline int proj(int u, int x, int y) { return (DX[u] / 2) * x + (DY[u] / 2) * y; }
static inline int color_at(int x, int y) { const uint16_t v = g[(size_t)y * G + x]; return (v >> 1) == gen ? (v & 1) : 0; }
static inline void set_black(int x, int y) { g[(size_t)y * G + x] = (uint16_t)((gen << 1) | 1); for (int u = 0; u < 4; u++) { const int p = proj(u, x, y); if (p > maxp[u]) maxp[u] = p; } }
static inline void set_white(int x, int y) { g[(size_t)y * G + x] = (uint16_t)(gen << 1); }

/* is cell (x, y) in the footprint S (the 104 cells of the newest period, held at ring indices base..base+103) shifted by j*u? */
static int in_translate(int x, int y, int j, int u, int base) {
    const int sx = x - j * DX[u], sy = y - j * DY[u];
    for (int i = 0; i < PER; i++) { const int k = (base + i) & (HIST - 1); if (hx[k] == sx && hy[k] == sy) return 1; }
    return 0;
}

/* the proof at step t (t = the index of the newest recorded step) -> the onset (>= 0) with *udrift set, or -1 (not proven at this t) */
static long proof(long t, int *udrift) {
    if (t < 2 * PER - 1) return -1;
    const int b0 = (int)((t - PER + 1) & (HIST - 1)), a0 = (int)((t - 2 * PER + 1) & (HIST - 1));
    const int dx = hx[b0] - hx[a0], dy = hy[b0] - hy[a0];
    if ((dx != 2 && dx != -2) || (dy != 2 && dy != -2) || hc[b0] != hc[a0]) return -1;   /* the cheap pre-check, every step */
    const int u = (dx > 0 ? 0 : 2) + (dy > 0 ? 0 : 1);
    /* the footprint's span along u, from the newest period */
    int pmin = 1 << 30, pmax = -(1 << 30);
    for (int i = 0; i < PER; i++) { const int k = (b0 + i) & (HIST - 1); const int p = proj(u, hx[k], hy[k]); if (p < pmin) pmin = p; if (p > pmax) pmax = p; }
    const int m = (pmax - pmin) / 4 + 1;
    if (m > MAXM || t < (long)m * PER - 1) return -1;
    /* m consecutive periods, each the previous one shifted by u with the same entry colors */
    for (int q = 1; q < m; q++) {
        const int nb = (int)((t - (long)q * PER + 1) & (HIST - 1)), na = (int)((t - (long)(q + 1) * PER + 1) & (HIST - 1));
        for (int i = 0; i < PER; i++) {
            const int kb = (nb + i) & (HIST - 1), ka = (na + i) & (HIST - 1);
            if (hx[kb] != hx[ka] + dx || hy[kb] != hy[ka] + dy || hc[kb] != hc[ka]) return -1;
        }
    }
    /* every fresh cell of every future translate is white now: k = 1 .. K, K reaching past the furthest black cell in direction u */
    int K = (maxp[u] - pmin) / 4 + 1; if (K < 1) K = 1;
    for (int k = 1; k <= K; k++) {
        for (int i = 0; i < PER; i++) {
            const int kk = (b0 + i) & (HIST - 1);
            const int x = hx[kk] + k * dx, y = hy[kk] + k * dy;
            if (x < 0 || y < 0 || x >= G || y >= G) return -1;    /* the translate leaves the grid: not provable here (the start ends OUT or unresolved) */
            if (!color_at(x, y)) continue;
            int earlier = 0;
            for (int j = -(m - 1); j < k && !earlier; j++) earlier = in_translate(x, y, j, u, b0);
            if (!earlier) return -1;
        }
    }
    *udrift = u;
    return t - (long)m * PER + 1;
}

int main(int argc, char **argv) {
    int n = 0, part = 0, nparts = 1, clear = 0, oeis = 0; long cap = 1048576; G = 2048;
    for (int i = 1; i < argc; i++) {
        if (!strncmp(argv[i], "n=", 2)) n = atoi(argv[i] + 2);
        else if (!strncmp(argv[i], "part=", 5)) sscanf(argv[i] + 5, "%d/%d", &part, &nparts);
        else if (!strncmp(argv[i], "cap=", 4)) cap = atol(argv[i] + 4);
        else if (!strncmp(argv[i], "grid=", 5)) G = atoi(argv[i] + 5);
        else if (!strncmp(argv[i], "clear=", 6)) clear = atoi(argv[i] + 6);
        else if (!strncmp(argv[i], "oeis=", 5)) oeis = atoi(argv[i] + 5);
    }
    if (oeis) n = 3;
    if (n < 3 || n > 6 || nparts < 1 || part < 0 || part >= nparts || cap < 2 * PER || G < 256 || G > 8192 || (G & (G - 1))) {
        printf("ANT: n=3..6 part=p/P [cap=steps] [grid=256..8192, a power of two] [clear=1] [oeis=1]\n"); return 1; }
    g = (uint16_t *)calloc((size_t)G * G, sizeof(uint16_t));
    if (!g) { printf("ANT: no memory for a %d x %d grid\n", G, G); return 1; }
    GHALF = G / 2;
    const int bits = n * n;
    const uint64_t T = 1ull << bits, lo = (T / nparts) * part, hi = part == nparts - 1 ? T : (T / nparts) * (part + 1);
    if (oeis) printf("ANT: oeis check, the empty start, %ld steps, grid %d\n", cap, G);
    else printf("ANT: ant1, box %d x %d, part %d/%d: starts %llu..%llu (%llu of %llu), cap %ld, grid %d%s\n", n, n, part, nparts,
                (unsigned long long)lo, (unsigned long long)hi - 1, (unsigned long long)(hi - lo), (unsigned long long)T, cap, G, clear ? ", cleared between starts" : "");
    uint64_t proven = 0, unresolved = 0, out = 0, hist[64] = {0}, sumonset = 0, drifts[4] = {0}, maxc = 0; long maxonset = -1;
    uint64_t slowc[8]; long slowo[8]; int nslow = 0;   /* the eight slowest starts (the largest onsets), kept in order of finding */
    clock_t c0 = clock();
    for (uint64_t c = oeis ? 0 : lo; c < (oeis ? 1 : hi); c++) {
        if (clear) { memset(g, 0, (size_t)G * G * sizeof(uint16_t)); gen = 1; }
        else { gen++; if (gen == 32768) { memset(g, 0, (size_t)G * G * sizeof(uint16_t)); gen = 1; } }
        for (int u = 0; u < 4; u++) maxp[u] = -(1 << 30);
        for (int k = 0; k < bits; k++) if ((c >> k) & 1) set_black(GHALF - n / 2 + k % n, GHALF - n / 2 + k / n);
        int x = GHALF, y = GHALF, d = 0;                   /* d: 0 up (y-1), 1 right (x+1), 2 down (y+1), 3 left (x-1) */
        long onset = -1; int u = -1; long t;
        uint64_t black = 0; static uint32_t a[13000]; long n0 = -1;   /* oeis: a(t) = black cells after t moves */
        if (oeis) { for (int k = 0; k < bits; k++) black += (c >> k) & 1; a[0] = (uint32_t)black; }
        for (t = 0; t < cap; t++) {
            if (x == 0 || y == 0 || x == G - 1 || y == G - 1) { onset = -2; break; }
            const int col = color_at(x, y);
            const int k = (int)(t & (HIST - 1)); hx[k] = x; hy[k] = y; hc[k] = (uint8_t)col;
            if (col) { set_white(x, y); d = (d + 3) & 3; black--; } else { set_black(x, y); d = (d + 1) & 3; black++; }
            if (d == 0) y--; else if (d == 1) x++; else if (d == 2) y++; else x--;
            if (oeis && t + 1 < 13000) a[t + 1] = (uint32_t)black;
            if (onset < 0 && !oeis) { onset = proof(t, &u); if (onset >= 0) break; }
            if (oeis && onset < 0) { onset = proof(t, &u); if (onset >= 0) { /* keep running to fill a[] */ } }
        }
        if (oeis) {
            for (long s = 0; s + 1104 < 13000; s++) { int ok = 1; for (long q = s; q < s + 1000 && ok; q++) ok = a[q + 104] == a[q] + 12; if (ok) { n0 = s; break; } }
            printf("ANT oeis: a(9976) %u a(9977) %u a(10080) %u a(10081) %u; a(n+104) = a(n) + 12 holds for 1000 consecutive n from n = %ld; my proven onset %ld, drift %s\n",
                   a[9976], a[9977], a[10080], a[10081], n0, onset, u < 0 ? "none" : (u == 0 ? "(2,2)" : u == 1 ? "(2,-2)" : u == 2 ? "(-2,2)" : "(-2,-2)"));
            hash64((uint64_t)n0); hash64((uint64_t)onset);
            break;
        }
        if (onset >= 0) {
            proven++; sumonset += (uint64_t)onset; drifts[u]++;
            int b = 0; while ((1L << (b + 1)) <= onset && b < 62) b++; hist[b]++;
            if (onset > maxonset) { maxonset = onset; maxc = c; }
            if (nslow < 8) { slowc[nslow] = c; slowo[nslow] = onset; nslow++; }
            else { int w = 0; for (int i = 1; i < 8; i++) if (slowo[i] < slowo[w]) w = i; if (onset > slowo[w]) { slowo[w] = onset; slowc[w] = c; } }
            hash64((uint64_t)onset); hash64((uint64_t)u);
        } else if (onset == -2) { out++; hash64(0xffffffffffffffffull); hash64(2); }
        else { unresolved++; hash64(0xffffffffffffffffull); hash64(1); }
    }
    clock_t c1 = clock();
    if (!oeis) {
        printf("ANT box %d part %d/%d: proven %llu; unresolved %llu; out %llu;", n, part, nparts, (unsigned long long)proven, (unsigned long long)unresolved, (unsigned long long)out);
        hash64(proven); hash64(unresolved); hash64(out);
        printf(" onsets by powers of two:"); for (int b = 0; b < 63; b++) if (hist[b]) { printf(" [2^%d,2^%d): %llu;", b, b + 1, (unsigned long long)hist[b]); hash64(((uint64_t)b << 56) ^ hist[b]); }
        printf(" sum %llu; largest %ld at start %llx;", (unsigned long long)sumonset, maxonset, (unsigned long long)maxc); hash64(sumonset); hash64((uint64_t)maxonset); hash64(maxc);
        printf(" drifts (2,2) %llu (2,-2) %llu (-2,2) %llu (-2,-2) %llu", (unsigned long long)drifts[0], (unsigned long long)drifts[1], (unsigned long long)drifts[2], (unsigned long long)drifts[3]);
        for (int i = 0; i < 4; i++) hash64(drifts[i]);
        printf("\nANT slowest %d:", nslow); for (int i = 0; i < nslow; i++) printf(" %llx:%ld", (unsigned long long)slowc[i], slowo[i]); printf("\n");
    }
    if (c0 != (clock_t)-1 && c1 != (clock_t)-1 && c1 >= c0) printf("CTIME box %d part %d/%d: %.1f s (process clock)\n", n, part, nparts, (double)(c1 - c0) / CLOCKS_PER_SEC);
    printf("ANT: done chain %016llx\n", (unsigned long long)chain);
    free(g);
    return 0;
}

/* ant_gpu.cl -- THE ANT CENSUS ON THE GPU (11-20, Mira's own line). Integers only. The same rules and the same
   proof of a highway as ../ant.c, line for line: on a white cell turn right, on a black cell turn left, flip it, step; the last
   1024 steps kept (cell, color seen); a highway proven when m consecutive 104-step periods repeat shifted by one diagonal drift with equal entry
   colors and every fresh cell ahead is white. Each GPU thread walks one start at a time on its own bit grid (G x G cells, one bit a cell), takes
   the next start from a shared counter when it finishes, and stops each launch after S steps so no launch runs long (its state is kept between
   launches). After a start ends, only the rectangle its ant touched is cleared. The host hashes every start's (onset, drift) in order on the GPU
   (chain_hash), so the census chain is ant.c's by construction when the outcomes are equal: that equality is the acceptance. */
#define PER 104
#define HIST 1024
#define MAXM 8
#define NST 16

__constant int DXc[4] = {2, 2, -2, -2};
__constant int DYc[4] = {2, -2, 2, -2};

inline int proj(int u, int x, int y) { return (DXc[u] / 2) * x + (DYc[u] / 2) * y; }
inline int getbit(__global const uint *gr, int GW, int x, int y) { return (int)((gr[y * GW + (x >> 5)] >> (x & 31)) & 1u); }
inline void setbit(__global uint *gr, int GW, int x, int y) { gr[y * GW + (x >> 5)] |= (1u << (x & 31)); }
inline void clrbit(__global uint *gr, int GW, int x, int y) { gr[y * GW + (x >> 5)] &= ~(1u << (x & 31)); }

int in_translate(__global const short *hx, __global const short *hy, int x, int y, int j, int u, int base) {
    const int sx = x - j * DXc[u], sy = y - j * DYc[u];
    for (int i = 0; i < PER; i++) { const int k = (base + i) & (HIST - 1); if (hx[k] == sx && hy[k] == sy) return 1; }
    return 0;
}

/* ant.c's proof, verbatim but for the memory it reads */
long proof(long t, int *udrift, __global const short *hx, __global const short *hy, __global const uchar *hc,
           __global const uint *gr, int G, int GW, const int *maxp) {
    if (t < 2 * PER - 1) return -1;
    const int b0 = (int)((t - PER + 1) & (HIST - 1)), a0 = (int)((t - 2 * PER + 1) & (HIST - 1));
    const int dx = hx[b0] - hx[a0], dy = hy[b0] - hy[a0];
    if ((dx != 2 && dx != -2) || (dy != 2 && dy != -2) || hc[b0] != hc[a0]) return -1;
    const int u = (dx > 0 ? 0 : 2) + (dy > 0 ? 0 : 1);
    int pmin = 1 << 30, pmax = -(1 << 30);
    for (int i = 0; i < PER; i++) { const int k = (b0 + i) & (HIST - 1); const int p = proj(u, hx[k], hy[k]); if (p < pmin) pmin = p; if (p > pmax) pmax = p; }
    const int m = (pmax - pmin) / 4 + 1;
    if (m > MAXM || t < (long)m * PER - 1) return -1;
    for (int q = 1; q < m; q++) {
        const int nb = (int)((t - (long)q * PER + 1) & (HIST - 1)), na = (int)((t - (long)(q + 1) * PER + 1) & (HIST - 1));
        for (int i = 0; i < PER; i++) {
            const int kb = (nb + i) & (HIST - 1), ka = (na + i) & (HIST - 1);
            if (hx[kb] != hx[ka] + dx || hy[kb] != hy[ka] + dy || hc[kb] != hc[ka]) return -1;
        }
    }
    int K = (maxp[u] - pmin) / 4 + 1; if (K < 1) K = 1;
    for (int k = 1; k <= K; k++) {
        for (int i = 0; i < PER; i++) {
            const int kk = (b0 + i) & (HIST - 1);
            const int x = hx[kk] + k * dx, y = hy[kk] + k * dy;
            if (x < 0 || y < 0 || x >= G || y >= G) return -1;
            if (!getbit(gr, GW, x, y)) continue;
            int earlier = 0;
            for (int j = -(m - 1); j < k && !earlier; j++) earlier = in_translate(hx, hy, x, y, j, u, b0);
            if (!earlier) return -1;
        }
    }
    *udrift = u;
    return t - (long)m * PER + 1;
}

__kernel void zero_u32(__global uint *a, const ulong nwords) {
    const ulong i = get_global_id(0);
    if (i < nwords) a[i] = 0u;
}

/* state per thread (NST ints): 0 active (0 needs a start, 1 running, 2 done), 1 idx, 2 x, 3 y, 4 d, 5 t, 6..9 maxp, 10 bx0, 11 bx1, 12 by0, 13 by1 */
__kernel void ant_run(const int n, const ulong lo, const uint count, const uint cap, const int G, const int GW, const uint S,
                      __global uint *grids, __global short *hxs, __global short *hys, __global uchar *hcs,
                      __global uint *ctr, __global int *st, __global int *onsets, __global uchar *drifts,
                      __global uchar *stumble, __global ushort *reachs, __global ulong *h104s, const int store_h,
                      __global const ulong *known, const int nknown, __global uint *knowncnt,
                      __global uint *stumhist, __global uint *reachhist) {
    const size_t tid = get_global_id(0);
    __global uint *gr = grids + tid * (size_t)G * (size_t)GW;
    __global short *hx = hxs + tid * HIST; __global short *hy = hys + tid * HIST; __global uchar *hc = hcs + tid * HIST;
    __global int *s = st + tid * NST;
    int active = s[0]; uint idx = (uint)s[1]; int x = s[2], y = s[3], d = s[4]; uint t = (uint)s[5];
    int maxp[4]; maxp[0] = s[6]; maxp[1] = s[7]; maxp[2] = s[8]; maxp[3] = s[9];
    int bx0 = s[10], bx1 = s[11], by0 = s[12], by1 = s[13];
    const int GH = G / 2, bits = n * n;
    uint budget = S;
    while (budget > 0 && active != 2) {
        if (active == 0) {
            idx = atomic_inc(&ctr[0]);
            if (idx >= count) { active = 2; break; }
            const ulong c = lo + (ulong)idx;
            for (int u = 0; u < 4; u++) maxp[u] = -(1 << 30);
            bx0 = GH - n / 2; bx1 = GH - n / 2 + n - 1; by0 = bx0; by1 = bx1;
            for (int k = 0; k < bits; k++) if ((c >> k) & 1UL) {
                const int cx = GH - n / 2 + k % n, cy = GH - n / 2 + k / n;
                setbit(gr, GW, cx, cy);
                for (int u = 0; u < 4; u++) { const int p = proj(u, cx, cy); if (p > maxp[u]) maxp[u] = p; }
            }
            x = GH; y = GH; d = 0; t = 0; active = 1;
        }
        int finished = 0, udr = -1; long onset = -1;
        while (budget > 0) {
            budget--;
            if (t >= cap) { onset = -1; finished = 1; break; }
            if (x == 0 || y == 0 || x == G - 1 || y == G - 1) { onset = -2; finished = 1; break; }
            const int col = getbit(gr, GW, x, y);
            const int k = (int)(t & (HIST - 1)); hx[k] = (short)x; hy[k] = (short)y; hc[k] = (uchar)col;
            if (x < bx0) bx0 = x; if (x > bx1) bx1 = x; if (y < by0) by0 = y; if (y > by1) by1 = y;
            if (col) { clrbit(gr, GW, x, y); d = (d + 3) & 3; }
            else { setbit(gr, GW, x, y); for (int u = 0; u < 4; u++) { const int p = proj(u, x, y); if (p > maxp[u]) maxp[u] = p; } d = (d + 1) & 3; }
            if (d == 0) y--; else if (d == 1) x++; else if (d == 2) y++; else x--;
            onset = proof((long)t, &udr, hx, hy, hc, gr, G, GW, maxp);
            t++;
            if (onset >= 0) { finished = 1; break; }
        }
        if (finished) {
            onsets[idx] = (int)onset; drifts[idx] = (uchar)(onset >= 0 ? udr : 255);
            /* THE DOOR FEATURES (proven starts only; the ring holds the steps t - 1023 .. t at the proof, and t - onset <= 831):
               the 104-step door's fingerprint (ant3's approach hash, D = 104: the colors seen at onset - 1, onset - 2, ..., a missing step counted as 2);
               the stumble: the fewest mismatches between the window onset - 104 .. onset - 1 and the road's period onset .. onset + 103 over all 104
               phases (255 when the start's onset is under 104); the backward reach: how many steps just before the onset already follow the road. */
            if (onset >= 0) {
                const long tt = (long)t - 1;                              /* the step the proof landed on */
                long jav = 1023 - (tt - onset); if (jav > onset) jav = onset;   /* steps before the onset still in the ring */
                ulong h = 0xcbf29ce484222325UL;
                for (int j = 1; j <= PER; j++) { const uint v = j <= jav ? (uint)hc[(onset - j) & (HIST - 1)] : 2u; h ^= (ulong)v; h *= 0x100000001b3UL; }
                int stum = 255;
                if (jav >= PER) {
                    int best = PER;
                    for (int ph = 0; ph < PER && best > 0; ph++) {
                        int mm = 0;
                        for (int i = 0; i < PER && mm < best; i++) mm += hc[(onset - PER + i) & (HIST - 1)] != hc[(onset + ((i + ph) % PER)) & (HIST - 1)];
                        if (mm < best) best = mm;
                    }
                    stum = best;
                }
                long reach = 0; while (reach < jav && hc[(onset - reach - 1) & (HIST - 1)] == hc[(onset - reach - 1 + PER) & (HIST - 1)]) reach++;
                stumble[idx] = (uchar)stum; reachs[idx] = (ushort)reach;
                if (store_h) h104s[idx] = h;
                atomic_inc(&stumhist[stum]);
                atomic_inc(&reachhist[reach < 1023 ? reach : 1023]);
                for (int q = 0; q < nknown; q++) if (known[q] == h) atomic_inc(&knowncnt[q]);
            } else { stumble[idx] = 254; reachs[idx] = 0; if (store_h) h104s[idx] = 0UL; }
            for (int yy = by0; yy <= by1; yy++) for (int w = bx0 >> 5; w <= (bx1 >> 5); w++) gr[yy * GW + w] = 0u;
            atomic_inc(&ctr[1]);
            active = 0;
        }
    }
    s[0] = active; s[1] = (int)idx; s[2] = x; s[3] = y; s[4] = d; s[5] = (int)t;
    s[6] = maxp[0]; s[7] = maxp[1]; s[8] = maxp[2]; s[9] = maxp[3]; s[10] = bx0; s[11] = bx1; s[12] = by0; s[13] = by1;
}

/* the census chain, ant.c's order: per start hash64(onset) hash64(drift), or hash64(~0) hash64(2) for out, hash64(~0) hash64(1) unresolved */
__kernel void chain_hash(__global const int *onsets, __global const uchar *drifts, const uint from, const uint to, __global ulong *ch) {
    if (get_global_id(0) != 0) return;
    /* ant_gpu3 (11-21): the same chain, faster. An onset under 2^24 has five zero bytes on top, a drift is one byte with seven zero bytes on
       top, and FNV-1a's step on a zero byte is only a multiply by P, so those runs fold into one multiply by P^6 and one by P^8: 4 multiplies a
       start instead of 16, the same value exactly. Anything else takes the old 16-step path. */
    const ulong P = 0x100000001b3UL, P6 = 0xdc966432edf1c639UL, P8 = 0x1efac7090aef4a21UL;
    ulong h = ch[0];
    for (uint i = from; i < to; i++) {
        const int o = onsets[i];
        if (o >= 0 && o < (1 << 24)) {
            const ulong v = (ulong)o;
            h ^= v & 0xffUL; h *= P;
            h ^= (v >> 8) & 0xffUL; h *= P;
            h ^= (v >> 16) & 0xffUL; h *= P6;
            h ^= (ulong)drifts[i]; h *= P8;
        } else {
            ulong v1, v2;
            if (o >= 0) { v1 = (ulong)o; v2 = (ulong)drifts[i]; }
            else if (o == -2) { v1 = 0xffffffffffffffffUL; v2 = 2UL; }
            else { v1 = 0xffffffffffffffffUL; v2 = 1UL; }
            for (int b = 0; b < 8; b++) { h ^= (v1 >> (8 * b)) & 0xffUL; h *= P; }
            for (int b = 0; b < 8; b++) { h ^= (v2 >> (8 * b)) & 0xffUL; h *= P; }
        }
    }
    ch[0] = h;
}

/* ant_gpu4 (11-21): the same chain as chain_hash, with the reads taken off the critical path. Run it as ONE work-group (global = local = 256):
   the group loads CT starts at a time from global memory into local memory together, then work-item 0 hashes them from local memory in order
   with chain_hash's own folded steps (an onset under 2^24: 4 multiplies; anything else: the 16-step path). The same 64-bit value. */
#define CT 2048
__kernel void chain_hash_tiled(__global const int *onsets, __global const uchar *drifts, const uint from, const uint to, __global ulong *ch) {
    __local int lo[CT];
    __local uchar ld[CT];
    const uint lid = get_local_id(0), ls = get_local_size(0);
    const ulong P = 0x100000001b3UL, P6 = 0xdc966432edf1c639UL, P8 = 0x1efac7090aef4a21UL;
    ulong h = ch[0];
    for (uint base = from; base < to; base += CT) {
        const uint n = (to - base < CT) ? (to - base) : CT;
        for (uint j = lid; j < n; j += ls) { lo[j] = onsets[base + j]; ld[j] = drifts[base + j]; }
        barrier(CLK_LOCAL_MEM_FENCE);
        if (lid == 0) {
            for (uint j = 0; j < n; j++) {
                const int o = lo[j];
                if (o >= 0 && o < (1 << 24)) {
                    const ulong v = (ulong)o;
                    h ^= v & 0xffUL; h *= P;
                    h ^= (v >> 8) & 0xffUL; h *= P;
                    h ^= (v >> 16) & 0xffUL; h *= P6;
                    h ^= (ulong)ld[j]; h *= P8;
                } else {
                    ulong v1, v2;
                    if (o >= 0) { v1 = (ulong)o; v2 = (ulong)ld[j]; }
                    else if (o == -2) { v1 = 0xffffffffffffffffUL; v2 = 2UL; }
                    else { v1 = 0xffffffffffffffffUL; v2 = 1UL; }
                    for (int b = 0; b < 8; b++) { h ^= (v1 >> (8 * b)) & 0xffUL; h *= P; }
                    for (int b = 0; b < 8; b++) { h ^= (v2 >> (8 * b)) & 0xffUL; h *= P; }
                }
            }
        }
        barrier(CLK_LOCAL_MEM_FENCE);
    }
    if (lid == 0) ch[0] = h;
}

"""ant_census6d.py (11-21-2026, ~10 AM; a copy of ant_census6c.py, which stays as it is, made by make_census6d.py): the same counting and
the same chains; the one change: the chain hash runs as chain_hash_tiled in ant_gpu4.cl (a work-group of 256 loads 2,048 starts at a
time into local memory, its first work-item hashes them in order: the same value without waiting on each read). Its own stop file
census6d.stop; its own logs worker6d_*.log. What follows is ant_census6c.py's own description.
ant_census6c.py (11-21-2026, ~9:5x AM; a copy of ant_census6b.py, which stays as it is, made by make_census6c.py): the same counting and
the same chains, with the card no longer idle at the end of each chunk: no sleep while the last ants of a chunk drain, the chain hash
folded to 4 multiplies a start (ant_gpu3.cl, the same value), and the onset histogram in one pass instead of 63. Its own stop file:
census6c.stop; its own logs worker6c_*.log. What follows is ant_census6b.py's own description.
ant_census6b.py (11-21-2026, 12:2x AM; a copy of ant_census6.py, which stays as it is): the same counting and the same chains; only the
waiting changes: after a launch is handed to the card, the worker sleeps for 85 percent of the last launch time before asking the card to finish,
so the driver no longer spins a whole CPU core while the card works (measured 11-21 12:17 AM: ant_census6.py held one core at 96 to 100 percent
per card). Its own stop file: census6b.stop. What follows is ant_census6.py's own description.
ant_census6.py (11-21-2026, a copy of ant_six.py; ant_six.py itself untouched): the same runner and the same chains, plus the start of every
ant that leaves its grid or runs out of steps written into its part's result (bad_starts, as hex:code, -2 out, -1 unresolved), so the census has no
holes that cannot be finished; its own folder census6 (beside this file, or dir=...) and stop file census.stop; defaults from the 11-21 timing (threads 65536,
grid 1024). What follows is ant_six.py's own description.
ant_six.py -- THE 6 x 6 BOX ON THE GPUS (11-20-2026, Mira's own line). Every one of the 2^36 starts in the
6 x 6 box, run exactly by ant_gpu2.cl (ant.c's rules and proof, validated against the CPU on the 3 x 3, 4 x 4 and 5 x 5 boxes), with the door
features. The box is cut into 256 parts of 2^28 starts (part p = starts p * 2^28 .. (p + 1) * 2^28 - 1); each part has its own chain in ant.c's
definition (every start's (onset, drift) in order, then the part's totals), so any part can be checked later by another machine. One worker a
device: it claims the next free part (census6/claims/part_NNN, refreshed every minute; a claim not refreshed for 15 minutes is
free again), runs it in chunks of 2^24 starts, and writes the part's result to six/done/part_NNN.json. A restart resumes at the next free part;
a crash loses at most the part in hand. Stop: six/six.stop (each worker finishes its part and exits). The CPU only orders the work.
Usage: python -I ant_six.py dev=Arc threads=32768 G=2048 [S=40000] [known=hex,hex,...] [parts=lo-hi]"""
import ctypes as C
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import clrt  # noqa: E402

SIX = os.path.join(HERE, "census6")   # the published copy: results beside the code unless dir=... is given
N_BITS, PART_BITS, CHUNK_BITS = 36, 28, 24
NPARTS = 1 << (N_BITS - PART_BITS)
MASK = (1 << 64) - 1
STALE = 15 * 60


def h64(ch, v):
    v &= MASK
    for i in range(8):
        ch ^= (v >> (8 * i)) & 0xff
        ch = (ch * 0x100000001b3) & MASK
    return ch


def now():
    return time.strftime("%m-%d %I:%M:%S %p")


def claim_next(tag, prange):
    os.makedirs(os.path.join(SIX, "claims"), exist_ok=True)
    os.makedirs(os.path.join(SIX, "done"), exist_ok=True)
    for p in range(prange[0], prange[1] + 1):
        if os.path.exists(os.path.join(SIX, "done", f"part_{p:03d}.json")):
            continue
        cl = os.path.join(SIX, "claims", f"part_{p:03d}")
        try:
            if os.path.exists(cl) and time.time() - os.path.getmtime(cl) > STALE:
                os.remove(cl)
            fd = os.open(cl, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{tag} pid {os.getpid()} {now()}\n".encode())
            os.close(fd)
            return p, cl
        except FileExistsError:
            continue
    return None, None


def main():
    global SIX, N_BITS, PART_BITS, CHUNK_BITS, NPARTS
    args = dict(a.split("=", 1) for a in sys.argv[1:])
    n = int(args.get("n", 6))   # n, part_bits, chunk_bits, dir: settable only to test the runner on boxes whose chains are known
    N_BITS, PART_BITS, CHUNK_BITS = n * n, int(args.get("part_bits", 28)), int(args.get("chunk_bits", 24))
    NPARTS = 1 << (N_BITS - PART_BITS)
    SIX = args.get("dir", SIX)
    dev_word = args.get("dev", "Arc")
    NT, S, G = int(args.get("threads", 65536)), int(args.get("S", 40000)), int(args.get("G", 1024))
    cap = 1048576
    known_list = [int(x, 16) for x in args.get("known", "e9c1b911ac6d4769,8a33a4f21c86757a,1724e4c665c5b745,b4089a72f60ea5e2").split(",") if x]
    pr = args.get("parts", f"0-{NPARTS - 1}").split("-")
    prange = (int(pr[0]), int(pr[1]))
    GW, CH = G // 32, 1 << CHUNK_BITS
    # one worker a device: if this device's worker file names a live process, step aside (safe to start twice, or from a restart script)
    os.makedirs(SIX, exist_ok=True)
    wf = os.path.join(SIX, f"worker_{dev_word}.pid")
    if os.path.exists(wf):
        try:
            oldpid = int(open(wf).read().split()[0])
            k32 = C.WinDLL("kernel32")
            hproc = k32.OpenProcess(0x1000, False, oldpid)          # PROCESS_QUERY_LIMITED_INFORMATION
            alive = False
            if hproc:
                code = C.c_ulong()
                alive = bool(k32.GetExitCodeProcess(hproc, C.byref(code))) and code.value == 259   # STILL_ACTIVE
                k32.CloseHandle(hproc)
            if alive and oldpid != os.getpid():
                print(f"CENSUS6 {now()}: a worker for {dev_word} is already running (pid {oldpid}); this one steps aside", flush=True)
                return 0
        except (ValueError, OSError):
            pass
    with open(wf, "w") as fh:
        fh.write(f"{os.getpid()} {now()}\n")
    dev = clrt.Device(dev_word)
    tag = dev_word   # the published copy: the card's name alone
    prog = dev.program(open(os.path.join(HERE, "ant_gpu4.cl")).read())
    k_zero, k_run, k_chain = dev.kernel(prog, "zero_u32"), dev.kernel(prog, "ant_run"), dev.kernel(prog, "chain_hash_tiled")
    gwords = NT * G * GW
    grids = dev.buf_out(gwords * 4)
    hxs, hys, hcs = dev.buf_out(NT * 1024 * 2), dev.buf_out(NT * 1024 * 2), dev.buf_out(NT * 1024)
    ctr, st = dev.buf_out(16), dev.buf_out(NT * 16 * 4)
    onsets, drifts, stumble, reachs, h104s = dev.buf_out(CH * 4), dev.buf_out(CH), dev.buf_out(CH), dev.buf_out(CH * 2), dev.buf_out(8)
    known = dev.buf_out(8 * max(1, len(known_list)))
    dev.write(known, np.array(known_list or [0], dtype=np.uint64))
    knowncnt, stumhist, reachhist, chb = dev.buf_out(4 * max(1, len(known_list))), dev.buf_out(256 * 4), dev.buf_out(1024 * 4), dev.buf_out(8)
    zg = ((gwords + 255) // 256) * 256
    dev.run(k_zero, zg, [grids, C.c_uint64(gwords)], 256)
    dev.finish()
    print(f"CENSUS6 {now()}: worker {tag} ({dev.name}), threads {NT}, grid {G}, steps a launch {S}, parts {prange[0]}-{prange[1]}", flush=True)
    stopf = os.path.join(SIX, "census6d.stop")
    while not os.path.exists(stopf):
        p, clp = claim_next(tag, prange)
        if p is None:
            print(f"CENSUS6 {now()}: no free part left for {tag}", flush=True)
            break
        t0 = time.time()
        plo = p << PART_BITS
        print(f"CENSUS6 {now()}: {tag} took part {p} (starts {plo:x}..{plo + (1 << PART_BITS) - 1:x})", flush=True)
        dev.write(knowncnt, np.zeros(max(1, len(known_list)), np.uint32))
        dev.write(stumhist, np.zeros(256, np.uint32))
        dev.write(reachhist, np.zeros(1024, np.uint32))
        dev.write(chb, np.array([0xcbf29ce484222325], dtype=np.uint64))
        proven = unres = out = 0
        bad_starts = []
        est = 0.0
        hist = np.zeros(63, np.int64)
        ssum, maxonset, maxc, dcount, launches = 0, -1, 0, np.zeros(4, np.int64), 0
        cbuf = np.zeros(4, np.uint32)
        on, dr = np.zeros(CH, np.int32), np.zeros(CH, np.uint8)
        for ci in range(1 << (PART_BITS - CHUNK_BITS)):
            lo = plo + ci * CH
            dev.write(ctr, np.zeros(4, np.uint32))
            dev.write(st, np.zeros(NT * 16, np.int32))
            draining, est_keep = False, est
            while True:
                tl0 = time.time()
                dev.run(k_run, NT, [C.c_int(n), C.c_uint64(lo), C.c_uint(CH), C.c_uint(cap), C.c_int(G), C.c_int(GW), C.c_uint(S),
                                    grids, hxs, hys, hcs, ctr, st, onsets, drifts,
                                    stumble, reachs, h104s, C.c_int(0), known, C.c_int(len(known_list)), knowncnt, stumhist, reachhist])
                if est > 0.05:
                    time.sleep(est * 0.85)
                dev.finish()
                est = time.time() - tl0
                launches += 1
                dev.read(ctr, cbuf)
                if int(cbuf[1]) >= CH:
                    break
                if int(cbuf[0]) >= CH:   # 6c: every start of the chunk is handed out; the launches left are short, so no sleep before them
                    if not draining:
                        draining, est_keep = True, est
                    est = 0.0
            if draining:
                est = est_keep
            for f in range(0, CH, 1 << 20):
                dev.run(k_chain, 256, [onsets, drifts, C.c_uint(f), C.c_uint(min(CH, f + (1 << 20))), chb], 256)
                dev.finish()
            dev.read(onsets, on)
            dev.read(drifts, dr)
            pm = on >= 0
            proven += int(pm.sum())
            out += int((on == -2).sum())
            unres += int((on == -1).sum())
            badi = np.nonzero(on < 0)[0]
            if badi.size and len(bad_starts) < 100000:
                bad_starts.extend(f"{lo + int(i):x}:{int(on[i])}" for i in badi[:100000 - len(bad_starts)])
            nn = on[pm]   # 6c: one pass: an onset o >= 1 is in bin bit_length(o) - 1 (frexp's exponent, exact for these integers), 0 in bin 0
            if nn.size:
                hb = np.frexp(nn.astype(np.float64))[1].astype(np.int64) - 1
                hb[hb < 0] = 0
                hist += np.bincount(hb, minlength=63)[:63]
            ssum += int(on[pm].astype(np.int64).sum())
            if pm.any():
                m = int(on.max())
                if m > maxonset:
                    maxonset, maxc = m, lo + int(np.argmax(on))
                dcount += np.bincount(dr[pm], minlength=4)[:4]
            os.utime(clp, None)
            print(f"CENSUS6 {now()}: {tag} part {p} chunk {ci + 1} of {1 << (PART_BITS - CHUNK_BITS)} done, {time.time() - t0:.0f} s", flush=True)
        chv = np.zeros(1, np.uint64)
        dev.read(chb, chv)
        chain = int(chv[0])
        chain = h64(chain, proven)
        chain = h64(chain, unres)
        chain = h64(chain, out)
        for b in range(63):
            if hist[b]:
                chain = h64(chain, (b << 56) ^ int(hist[b]))
        chain = h64(chain, ssum)
        chain = h64(chain, maxonset)
        chain = h64(chain, maxc)
        for i in range(4):
            chain = h64(chain, int(dcount[i]))
        sh, rh, kc = np.zeros(256, np.uint32), np.zeros(1024, np.uint32), np.zeros(max(1, len(known_list)), np.uint32)
        dev.read(stumhist, sh)
        dev.read(reachhist, rh)
        dev.read(knowncnt, kc)
        res = {"part": p, "starts": [plo, plo + (1 << PART_BITS) - 1], "worker": tag, "device": dev.name, "grid": G, "threads": NT,
               "proven": proven, "unresolved": unres, "out": out, "bad_starts": bad_starts, "hist": {str(b): int(hist[b]) for b in range(63) if hist[b]},
               "sum": ssum, "largest": maxonset, "largest_at": f"{maxc:x}", "drifts": [int(x) for x in dcount],
               "stumble_hist": {str(i): int(sh[i]) for i in range(256) if sh[i]}, "reach_hist": {str(i): int(rh[i]) for i in range(1024) if rh[i]},
               "known_doors": {f"{h:016x}": int(kc[i]) for i, h in enumerate(known_list)},
               "chain": f"{chain:016x}", "seconds": round(time.time() - t0, 1), "launches": launches, "finished": now()}
        tmp = os.path.join(SIX, "done", f"part_{p:03d}.json.tmp")
        with open(tmp, "w") as fh:
            json.dump(res, fh)
        os.replace(tmp, os.path.join(SIX, "done", f"part_{p:03d}.json"))
        os.remove(clp)
        print(f"CENSUS6 {now()}: {tag} part {p} DONE: proven {proven}, unresolved {unres}, out {out}, largest {maxonset} at {maxc:x}, "
              f"chain {chain:016x}, {res['seconds']} s", flush=True)
    print(f"CENSUS6 {now()}: worker {tag} stops", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""census_summary.py (Mira, 11-21-2026): reads every finished piece of the 6 x 6 census (data/census6/done/part_NNN.json, or the folder given as its one argument) and
prints the whole box so far beside the smaller boxes (ANT_FACTS): starts, proofs, the onset (mean, power-of-two histogram, the longest), the four
known doors' shares, the stumble (10 or fewer mismatches between the 104 steps before the onset and the road's period, at the best phase), the
backward reach, the road's four directions. Writes the same text to census6/SUMMARY.md. Reads files only; the census runs on without it."""
import glob, json, os, sys, datetime
C = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'census6')
recs = [json.load(open(f)) for f in sorted(glob.glob(C + '/done/part_*.json'))]
if not recs:
    sys.exit('no finished pieces yet')
def add(d, k, v): d[k] = d.get(k, 0) + v
N = P = OUT = UNR = SUM = 0; hist, sth, rch, doors = {}, {}, {}, {}; drift = [0, 0, 0, 0]; bad = []; longest = (-1, '', -1)
for r in recs:
    P += r['proven']; OUT += r['out']; UNR += r['unresolved']; N += r['proven'] + r['out'] + r['unresolved']; SUM += r['sum']
    for k, v in r['hist'].items(): add(hist, int(k), v)
    for k, v in r.get('stumble_hist', {}).items(): add(sth, int(k), v)
    for k, v in r.get('reach_hist', {}).items(): add(rch, int(k), v)
    for k, v in r['known_doors'].items(): add(doors, k, v)
    for i in range(4): drift[i] += r['drifts'][i]
    bad += r.get('bad_starts', [])
    if r['largest'] > longest[0]: longest = (r['largest'], r['largest_at'], r['part'])
def share(n): return f'{n / P * 100:.3f} percent' if P else '-'
def cnt(d, lo, hi): return sum(v for k, v in d.items() if lo <= k <= hi)
st_counted = sum(v for k, v in sth.items() if k < 254)
med, acc = None, 0
for k in sorted(k for k in sth if k < 254):
    acc += sth[k]
    if acc * 2 >= st_counted: med = k; break
L = []
L.append(f'# The 6 x 6 ant census, summary of the finished pieces ({datetime.datetime.now():%m-%d %I:%M %p}, by census_summary.py)')
L.append('')
L.append(f'Pieces finished: {len(recs)} of 256 ({", ".join(str(r["part"]) for r in recs)}). Starts: {N:,} of 68,719,476,736 ({N / (1 << 36) * 100:.2f} percent).')
L.append(f'Proven: {P:,}. Off the grid: {OUT}. Unresolved: {UNR}. Starts listed to finish later: {len(bad)}.')
L.append(f'Onset (the step the road is proven to begin): mean {SUM / P:,.1f}; the longest {longest[0]:,} at start {longest[1]} (piece {longest[2]}).')
L.append('Onset by powers of two: ' + '; '.join(f'2^{b} to 2^{b + 1}: {hist[b]:,}' for b in sorted(hist)))
names = {'e9c1b911ac6d4769': 'the main door', '8a33a4f21c86757a': 'door 2', '1724e4c665c5b745': 'door 3', 'b4089a72f60ea5e2': 'door 4'}
L.append('Known doors (the 104-step approach fingerprints): ' + '; '.join(f'{names.get(k, k)} {v:,} ({share(v)})' for k, v in doors.items()) + '. The main door before: 3 x 3 15.04, 4 x 4 16.56, 5 x 5 16.95, the shuffled 6 x 6 sample 17.481 percent.')
L.append(f'The stumble (10 or fewer mismatches at the best phase): {cnt(sth, 0, 10):,} ({share(cnt(sth, 0, 10))}); 4 or fewer {cnt(sth, 0, 4):,}; exactly 0, a perfect false period, {sth.get(0, 0):,}; median mismatches {med}. Before: 4 x 4 19.44, 5 x 5 19.03 percent.')
L.append(f'The backward reach: 0 steps {rch.get(0, 0):,} ({share(rch.get(0, 0))}); 1 to 4 {cnt(rch, 1, 4):,}; 5 to 16 {cnt(rch, 5, 16):,}; 17 to 103 {cnt(rch, 17, 103):,}; 104 or more {cnt(rch, 104, 10 ** 6):,}; the farthest {max(rch) if rch else "-"}. Before: 5 x 5 62.1 percent at 0, the farthest 31.')
L.append(f'The road\'s four directions: {", ".join(f"{d:,}" for d in drift)} ({", ".join(f"{d / P * 100:.2f}" for d in drift)} percent).')
L.append(f'Every piece\'s chain: ' + ', '.join(f'{r["part"]}: {r["chain"]}' for r in recs))
txt = '\n'.join(L) + '\n'
open(C + '/SUMMARY.md', 'w', encoding='utf-8').write(txt); print(txt)

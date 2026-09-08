# Jelly × SecBench.js baseline

Before building taint analysis on top of Jelly, we wanted to know how the
existing points-to/call-graph engine behaves on real-world vulnerable code —
does it run cleanly, how fast, how much memory, how big are the resulting
call graphs, and where (if anywhere) does it break. This is that baseline:
plain Jelly, no taint layer, no vulnerability matching (`-v`), run across
every case in [SecBench.js](https://github.com/cristianstaicu/SecBench.js).

**Live dashboard (charts + tables built from this data):**
https://claude.ai/code/artifact/36e80826-dc9e-48ca-abf1-63db0d25eaa5
(private artifact — share from its own page if others need to see it)

## What SecBench.js is

600 (603 on disk, see below) real, historically-reported npm vulnerabilities
across 5 classes, each shipped as a runnable PoC: a `package.json` pinning
the exact vulnerable dependency version plus metadata (CVE id, advisory
links, fixed version, sink location), and a jest `*.test.js` file that
`require()`s the package and drives it to the vulnerable sink.

| Class | Folder | Cases |
|---|---|---|
| Prototype pollution | `prototype-pollution` | 193 |
| ReDoS | `redos` | 98 |
| Command injection | `command-injection` | 101 |
| Path traversal | `path-traversal` | 171 |
| Arbitrary code injection | `code-injection` | 40 |

We used each case's `*.test.js` file directly as the Jelly entry point —
it's never executed (Jelly is static-only), just parsed and analyzed as if
it were the "application" using the vulnerable library.

## Method / parameters

- **Jelly**: `0.13.0`, built from source (`npm install && npm run build`).
- **Node**: `v26.8.1`.
- **Command per case**: `node lib/main.js <case>.test.js --basedir <case-dir>`
  — no `--ignore-dependencies` (full dependency tree followed, matching how
  taint analysis will need to run), no `-v` (no vulnerability matching —
  that's a separate Jelly feature we deliberately didn't exercise here).
- **Heap**: `NODE_OPTIONS=--max-old-space-size=8192` (8GB) for every case,
  applied uniformly after the default ~4GB limit turned out to be too low
  for a handful of cases (see below).
- **Per-case timeout**: 1800s, as an infrastructure safety net only (so one
  hung case couldn't stall the whole batch) — never actually hit; every
  failure below is a clean exit or an OOM crash, not a hang.
- **npm install**: run fresh per case (`npm install --no-audit --no-fund`)
  before analysis, skipped if `node_modules` already existed or if the case
  has no `package.json` (one ReDoS case requires only a shared local util,
  no npm dependency at all).
- Run on 2026-09-04, on a 15GB-RAM Linux machine.

## Headline numbers

- **603 cases** on disk → **2 excluded** as malformed upstream SecBench.js
  directories (no test file / no `package.json`, not analysis failures) →
  **601 real cases** attempted.
- **587 clean successes (97.7% of attempted, 97.3% of the full 603)**.
- **6 OOM/crash** (1.0%), **8 npm-install failures** (1.3%) — see "Where it
  breaks" below; none are Jelly logic bugs.
- **0 hangs, 0 timeouts, 0 non-OOM crashes.**

### Cost (clean-success cases, n=587)

| Metric | Median | p90 | Max |
|---|---|---|---|
| Wall time (full process, shell-measured) | 0.42s | 1.1s | 58.84s |
| Jelly-reported analysis time (solver only) | 62ms | 721ms | 57.98s |
| Peak memory | 36MB | 143MB | 7,396MB |

Wall time vs. analysis time: wall time wraps the entire `node lib/main.js`
process from the shell (Node startup + JS parsing + solver + teardown);
analysis time is the "Analysis time" figure Jelly itself prints (solver
phase only). The gap (0.42s vs 62ms at the median) is mostly fixed
per-process Node/V8 startup cost — it dominates because most cases here are
small, sub-second analyses.

This distribution is heavily right-skewed: the *median* case is a small
single-file PoC, and the tail is full-dependency-tree packages (see "Heaviest
cases" below).

### Call graph size (clean-success cases, n=587)

| Metric | Median | p90 | Max |
|---|---|---|---|
| Modules reached | 2 | 30 | 909 |
| Functions | 12 | 574 | 3,976 |
| Packages | 2 | 7 | 138 |
| Call→function edges | 15 | 1,333 | 153,978 |
| Function→function edges | 12 | — | 63,257 |

Totals across all 587 cases: **930,294** call→function edges, **570,309**
function→function edges, over **97,998** analyzed functions and **9,875**
modules.

Call-site precision (median across clean-success cases):

- **44.4%** of call sites resolve to 0 or 1 callee (precisely resolved)
- **0%** (median; mean 2.2%) resolve to 2+ callees (polymorphic)
- **54.0%** go to native/external/unmodeled code
- **14.3%** of functions have zero callers (dead from the entry point)
- **64.5%** of functions are reachable from the entry file (mean 62.2%) —
  expected for PoC-shaped code, since each test exercises one vulnerable
  path rather than the whole package. This is the reachability ceiling any
  taint analysis built on top will inherit.

Edge count does **not** track module count: `command-injection/libnmap_0.4.11`
produces 54,420 call→function edges from just 67 modules — more than
`prototype-pollution/mathjs_7.4.0` gets out of 909 modules. Call-graph
density and dependency-tree size are independent variables; don't assume one
predicts the other when estimating taint-analysis cost per case.

### Outcome by class

| Class | Cases | Success | OOM | npm-fail | Median time | Median memory |
|---|---|---|---|---|---|---|
| Prototype pollution | 193 | 190 | 2 | 0 | 0.43s | 38MB |
| ReDoS | 98 | 97 | 1 | 0 | 0.44s | 43MB |
| Command injection | 101 | 92 | 3 | 6 | 0.43s | 38MB |
| Path traversal | 171 | 169 | 0 | 1 | 0.39s | 32MB |
| Code injection | 40 | 39 | 0 | 1 | 0.51s | 54MB |

(1 further case skipped per class where noted above: 1 malformed dir each in
prototype-pollution and path-traversal.)

### Heaviest cases

**Slowest** (wall time): `code-injection/mathjs_3.10.3` (58.84s),
`mathjs_3.9.0` (56.91s), `redos/three_0.122.0` (46.34s), `redos/ramda_0.27.1`
(8.79s), `command-injection/libnmap_0.4.11` (5.79s), `prototype-pollution/mathjs_7.4.0`
(4.54s), `style-dictionary_2.10.2` (4.08s), `total.js_3.4.6` ×2 (~3.7s each),
`redos/ethers_5.2.0` (3.39s).

**Largest call graph** (modules / functions): `mathjs_7.4.0` (909 / 3,976),
`mathjs_3.10.3` (515 / 2,441), `mathjs_3.9.0` (512 / 2,414),
`locutus_2.0.11` (364 / 770), `ramda_0.27.1` (332 / 520), `mout_1.0.0`
(264 / 353), `checkit_0.7.0` (257 / 341), `nis-utils_0.6.10` (243 / 1,563),
`nitro-server_1.3.3` (231 / 1,906), `modjs_0.4.0` (212 / 2,090).

**Noisiest**: `code-injection/mathjs_3.10.3` and `mathjs_3.9.0` produced
10,634 and 10,595 warnings respectively — by far the largest warning counts
in the corpus (median across all cases is 3). Worth a look before building
taint analysis on top of either.

## Where it breaks

### 6 OOM/crash cases — one root cause

Every OOM traces to a **single monolithic bundled/dist `.js` file** (tens of
thousands of lines, usually auto-generated) somewhere in the dependency
tree. Module *count* and overall dependency-tree size do not predict this:

| Case | Culprit file(s) | Evidence |
|---|---|---|
| `command-injection/monorepo-build_0.1.9` | `prettier/bin-prettier.js` (46,328 lines), `index.js` (44,254), `standalone.js` (31,825) | OOM at 507 modules reached; excluding just `prettier` drops the run to 538MB / 3.3s |
| `command-injection/buns_1.1.6` | `rx/dist/rx.all.compat.js` (12,650), `rx.all.js` (12,388) | OOM at 836 modules reached |
| `command-injection/apiconnect-cli-plugins_6.0.2` | `swagger-client.browser.js` (66,543) + 5 `apidom-*` adapter bundles (28k–35k lines each) | OOM at 2,872 modules reached |
| `prototype-pollution/jointjs_2.2.1` | nested `demo/ts-demo/node_modules` pulls in the full TypeScript compiler: `tsserver.js`, `tsserverlibrary.js`, `typescriptServices.js` (117k–125k lines each) | OOM at only 57 modules reached |
| `prototype-pollution/jointjs_3.4.0` | same, larger version — `tsserver.js` alone is 147,731 lines | OOM at only **7** modules reached |
| `redos/jspdf_2.1.1` | three near-duplicate ~36,000-line builds shipped side by side (`jspdf.umd.js`, `jspdf.es.js`, `jspdf.node.js`) | OOM at 252 modules reached |

`redos/three_0.122.0` is a **near-miss** that confirms the same mechanism
from the other side: only 2 modules reached, yet 7.4GB peak memory and 46s,
entirely from one 51,012-line `three.module.js`. It stayed a clean success
only because it landed just under the 8GB cap.

We confirmed the mechanism directly on `monorepo-build_0.1.9`: re-running
with `--exclude-packages prettier` drops it from an 8GB OOM to 538MB/3.3s in
3.3 seconds, with Jelly logging a single `Ignoring module
prettier@1.19.1:index.js` and continuing — no error, because nothing needed
to execute (Jelly never runs the test file, only parses/analyzes it).
`--max-indirections 2` (Jelly's indirection-bounding option, meant to curb
combinatorial blowups from chained indirect calls) did **not** help — the
same case still blew past 8GB in "Round 1" of the solver with 243,233
constraint variables / 326,700 tokens / 607,013 subset constraints, meaning
the growth isn't coming from indirection chains.

**Practical implication for taint analysis**: if the taint layer chokes on
any of these same 6 cases specifically, that's very likely inherited from
this base-Jelly limitation, not a new bug in the taint extension. Any
*other* case failing under taint-but-not-under-base-Jelly is a genuine
taint-layer issue worth chasing on its own.

### 8 npm-install failures — all environment/benchmark-data issues

| Case | Reason |
|---|---|
| `command-injection/corenlp-js-interface_1.0.3` | exact version unpublished from npm (registry rot) |
| `command-injection/corenlp-js-prefab_1.0.1` | exact version unpublished from npm (registry rot) |
| `command-injection/effect_1.0.4` | exact version unpublished; the "effect" name has since been reused by an unrelated package |
| `command-injection/gity_1.0.5` | exact version unpublished from npm (registry rot) |
| `command-injection/jison_0.4.17` | **SecBench.js metadata bug** — its `package.json` lists dependency `install-package` instead of `jison` |
| `command-injection/lycwed-spritesheetjs_1.2.5` | depends on a GitLab git-URL package; npm 12 here has git-dependency fetching disabled by default (supply-chain hardening) |
| `path-traversal/srverqq_1.0.0` | exact version unpublished from npm (registry rot) |
| `code-injection/mongoosemask_0.0.6` | depends on a GitHub tarball URL; npm 12 here has remote-tarball fetching disabled by default |

None of these are Jelly defects — 4 are packages that have simply
disappeared from the npm registry since SecBench.js was built (unavoidable
benchmark rot for any suite pinned to historical npm versions), 1 is a typo
in SecBench.js's own data, and 2 are blocked by this machine's npm
security policy around git/remote-tarball dependencies (could be re-enabled
per-case if needed, but we left the default in place).

### 2 malformed SecBench.js directories (excluded before counting)

`prototype-pollution/aurelia-path_1.1.0` (only Dockerfiles, no test file or
`package.json`) and `path-traversal/config` (a stray helper folder, not a
case) — both upstream SecBench.js quirks, not something we generated.

## Contents of this folder

- **`scripts/run_secbench_class.sh <secbench-class-dir> <jelly-repo-dir> <results-dir>`**
  Runs one SecBench.js vulnerability-class folder: for each
  `<module>_<version>/` case, `npm install`s if needed, then runs
  `node lib/main.js <case>.test.js --basedir <case-dir>`, logging exit code,
  wall time, and full stdout/stderr per case.
- **`scripts/run_secbench_all.sh <secbench-repo-dir> <jelly-repo-dir> <results-dir>`**
  Same, but sweeps all 5 official classes — this produced `results/`.
- **`scripts/parse_secbench_results.py <results-dir>`**
  Parses `summary.csv` + the per-case logs into `parsed.csv` (one row per
  case: modules/functions/edges/time/memory/warnings/etc., regex-scraped
  from Jelly's own stdout summary lines) and `aggregate.json` (overall +
  per-class stats, distributions, top-10s, OOM/failure lists).
- **`results/summary.csv`** — one row per case: class, module, npm install
  status, Jelly exit code, wall-clock seconds.
- **`results/parsed.csv`** — the full enriched per-case table.
- **`results/aggregate.json`** — computed overall + per-class statistics
  (source of every number in this README).
- **`results/per_class.json`, `results/hist.json`, `results/edges_hist.json`**
  — smaller derived slices consumed directly by `dashboard.html`.
- **`results/logs/<class>__<module>.log`** — full raw, unmodified stdout/stderr
  for every one of the 601 attempted cases (~3.3MB total) — the source of
  truth if you want to re-derive anything the parser didn't extract, or see
  exactly what Jelly printed for a given case.
- **`dashboard.html`** — source of the published dashboard artifact above;
  self-contained, viewable by opening directly in a browser.

## Reproducing

```bash
git clone https://github.com/cristianstaicu/SecBench.js
cd jelly && npm install && npm run build   # if not already built
./secbench-baseline/scripts/run_secbench_all.sh ../SecBench.js . ./secbench-baseline/results
python3 ./secbench-baseline/scripts/parse_secbench_results.py ./secbench-baseline/results
```

Re-running should reproduce the same shape of results, though exact npm-fail
cases may drift over time as more historical package versions get
unpublished from the registry.

"""
Sample-size precision planning for H1's primary comparison (decision record
section 6): how wide the 95% confidence interval of the mean paired difference
in buyer surplus share (zh - en; no deal = 0; untruncated) would be with 40, 60
or 80 case pairs.

No game data is read. Every input below is an assumption: the pilot is far too
small to estimate them, and calibration only happens after the case pool is
frozen, which already needs the number of pairs.

Three parts:
  1. Analytic half-widths, t(0.975, n-1) * SD_d / sqrt(n), for a grid of
     paired-difference SDs (SD_d), also as a share of the budget B: a share
     difference h is h * (1 - C/B) of B.
  2. Pairs needed for a target half-width.
  3. Simulation of games with no deals (share 0) and over-budget deals
     (negative share): the SD_d each no-deal rate implies, the resulting
     half-widths, and whether the paired t interval and a case-level bootstrap
     percentile interval keep 95% coverage, with and without a language effect.

Writes experiments/precision_sim.csv (part 3) and prints every table as
Markdown (used in experiments/precision_sim.md).

  .venv\\Scripts\\python -m experiments.precision_sim
"""

import csv
import math
import os
from statistics import NormalDist

import numpy as np

SEED = 20261019
N_GRID = (40, 60, 80)
SD_GRID = (0.2, 0.3, 0.4, 0.5, 0.6)
# C/B candidates for the budget conversion; 0.889 is the pilot placeholder.
CB_GRID = (0.7, 0.8, 0.889)
TARGET_GRID = (0.05, 0.075, 0.10, 0.125, 0.15)

# Part 3 model. Each case has an effect shared by its two games; each game ends
# in no deal with probability p0 (share 0, independently in the two languages,
# which is the conservative choice); otherwise its share is
# MU + case effect + N(0, sigma_e), except that with probability `tail` it is an
# over-budget deal with share uniform on [TAIL_LOW, 0).
MU = 0.6
SIGMA_CASE = 0.10
TAIL_LOW = -1.0
P0_GRID = (0.0, 0.1, 0.2, 0.3, 0.4)
SIGMA_E_GRID = (0.15, 0.25)
TAIL_GRID = (0.0, 0.05)
# Language effects: none; zh deals 0.10 higher; zh no-deal rate 0.10 higher.
EFFECTS = ("none", "shift", "no_deal")
EFFECT_SIZE = 0.10

REPS = 2000
BOOT_REPS = 1000
BOOT_B = 499
BOOT_CHUNK = 50
BIG = 400_000

OUTPUT_CSV = os.path.join("experiments", "precision_sim.csv")


def t_quantile(p, df):
    """Student t quantile by the Cornish-Fisher expansion (no scipy in the
    environment); off by less than 1e-4 for df >= 20."""
    z = NormalDist().inv_cdf(p)
    g1 = (z**3 + z) / 4
    g2 = (5 * z**5 + 16 * z**3 + 3 * z) / 96
    g3 = (3 * z**7 + 19 * z**5 + 17 * z**3 - 15 * z) / 384
    return z + g1 / df + g2 / df**2 + g3 / df**3


def half_width(sd, n):
    return t_quantile(0.975, n - 1) * sd / math.sqrt(n)


def pairs_needed(sd, target):
    n = 2
    while half_width(sd, n) > target:
        n += 1
    return n


def language_params(p0, effect):
    """(p0, mu) of the en and zh games."""
    en = (p0, MU)
    if effect == "shift":
        zh = (p0, MU + EFFECT_SIZE)
    elif effect == "no_deal":
        zh = (p0 + EFFECT_SIZE, MU)
    else:
        zh = en
    return en, zh


def expected_share(p0, mu, tail):
    return (1 - p0) * ((1 - tail) * mu + tail * TAIL_LOW / 2)


def draw_diffs(rng, shape, p0, sigma_e, tail, effect):
    """Paired differences zh - en, one per case."""
    case = rng.normal(0, SIGMA_CASE, shape)
    shares = []
    for game_p0, game_mu in language_params(p0, effect):
        share = game_mu + case + rng.normal(0, sigma_e, shape)
        if tail:
            share = np.where(rng.random(shape) < tail, rng.uniform(TAIL_LOW, 0, shape), share)
        shares.append(np.where(rng.random(shape) < game_p0, 0.0, share))
    return shares[1] - shares[0]


def bootstrap_intervals(rng, d):
    """Case-level bootstrap percentile intervals, one per row of d."""
    reps, n = d.shape
    lo, hi = np.empty(reps), np.empty(reps)
    for start in range(0, reps, BOOT_CHUNK):
        block = d[start:start + BOOT_CHUNK]
        rows = np.arange(len(block))[:, None, None]
        idx = rng.integers(0, n, (len(block), BOOT_B, n))
        means = block[rows, idx].mean(axis=2)
        lo[start:start + len(block)] = np.percentile(means, 2.5, axis=1)
        hi[start:start + len(block)] = np.percentile(means, 97.5, axis=1)
    return lo, hi


def simulate():
    scenarios = [
        (p0, sigma_e, tail, effect)
        for p0 in P0_GRID
        for sigma_e in SIGMA_E_GRID
        for tail in TAIL_GRID
        for effect in EFFECTS
    ]
    seeds = np.random.SeedSequence(SEED).spawn(len(scenarios))
    rows = []
    for (p0, sigma_e, tail, effect), seed in zip(scenarios, seeds):
        rng = np.random.default_rng(seed)
        (p_en, mu_en), (p_zh, mu_zh) = language_params(p0, effect)
        true_diff = expected_share(p_zh, mu_zh, tail) - expected_share(p_en, mu_en, tail)
        implied_sd = float(draw_diffs(rng, (BIG,), p0, sigma_e, tail, effect).std(ddof=1))
        for n in N_GRID:
            d = draw_diffs(rng, (REPS, n), p0, sigma_e, tail, effect)
            mean = d.mean(axis=1)
            h = t_quantile(0.975, n - 1) * d.std(axis=1, ddof=1) / math.sqrt(n)
            lo, hi = bootstrap_intervals(rng, d[:BOOT_REPS])
            rows.append({
                "p0_en": p0,
                "sigma_e": sigma_e,
                "tail": tail,
                "effect": effect,
                "n_pairs": n,
                "true_diff": round(true_diff, 4),
                "implied_sd_d": round(implied_sd, 4),
                "analytic_halfwidth": round(half_width(implied_sd, n), 4),
                "t_halfwidth_mean": round(float(h.mean()), 4),
                "t_coverage": round(float((np.abs(mean - true_diff) <= h).mean()), 4),
                "boot_halfwidth_mean": round(float(((hi - lo) / 2).mean()), 4),
                "boot_coverage": round(float(((lo <= true_diff) & (true_diff <= hi)).mean()), 4),
            })
    return rows


def md_table(header, body):
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in body]
    return "\n".join(lines)


def pct(x):
    return f"{100 * x:.1f}%"


def main():
    print("## 1. Half-width by SD_d (share units)\n")
    print(md_table(
        ["SD_d"] + [f"n = {n}" for n in N_GRID],
        [[sd] + [f"{half_width(sd, n):.3f}" for n in N_GRID] for sd in SD_GRID],
    ))
    for cb in CB_GRID:
        print(f"\n## 1b. Half-width as % of budget, C/B = {cb}\n")
        print(md_table(
            ["SD_d"] + [f"n = {n}" for n in N_GRID],
            [[sd] + [pct(half_width(sd, n) * (1 - cb)) for n in N_GRID] for sd in SD_GRID],
        ))
    ratio = {n: (t_quantile(0.975, n - 1) + t_quantile(0.80, n - 1)) / t_quantile(0.975, n - 1) for n in N_GRID}
    print("\nMDE (two-sided 0.05, power 0.80) / half-width: "
          + ", ".join(f"n = {n}: {r:.3f}" for n, r in ratio.items()))

    print("\n## 2. Pairs needed for a target half-width (share units)\n")
    print(md_table(
        ["SD_d"] + [f"h = {t}" for t in TARGET_GRID],
        [[sd] + [pairs_needed(sd, t) for t in TARGET_GRID] for sd in SD_GRID],
    ))

    rows = simulate()
    with open(OUTPUT_CSV, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print("\n## 3a. No-deal rate -> SD_d and half-width (no language effect)\n")
    body = []
    for r in rows:
        if r["effect"] != "none" or r["n_pairs"] != N_GRID[0]:
            continue
        hw = {s["n_pairs"]: s["t_halfwidth_mean"] for s in rows
              if (s["p0_en"], s["sigma_e"], s["tail"], s["effect"]) == (r["p0_en"], r["sigma_e"], r["tail"], "none")}
        body.append([r["p0_en"], r["sigma_e"], r["tail"], f"{r['implied_sd_d']:.3f}"]
                    + [f"{hw[n]:.3f}" for n in N_GRID])
    print(md_table(["p0", "sigma_e", "tail", "SD_d"] + [f"half-width n = {n}" for n in N_GRID], body))

    print("\n## 3b. Coverage of 95% intervals (t / bootstrap)\n")
    body = []
    for effect in EFFECTS:
        for n in N_GRID:
            sub = [r for r in rows if r["effect"] == effect and r["n_pairs"] == n]
            t_cov = [r["t_coverage"] for r in sub]
            b_cov = [r["boot_coverage"] for r in sub]
            body.append([effect, n, f"{min(t_cov):.3f}-{max(t_cov):.3f}", f"{min(b_cov):.3f}-{max(b_cov):.3f}"])
    print(md_table(["effect", "n", "t coverage (min-max)", "bootstrap coverage (min-max)"], body))
    worst = sorted(rows, key=lambda r: r["t_coverage"])[:5]
    print("\nLowest t coverage:")
    for r in worst:
        print(f"  {r}")
    print(f"\nwrote {OUTPUT_CSV} ({len(rows)} rows)")


if __name__ == "__main__":
    main()

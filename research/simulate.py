"""
Synthetic splint recordings with known wear, for stress-testing detectors.

The physics is the same first-order sensor model the HMM assumes, so results
are optimistic about the model's core assumption. What this tests is
robustness to things the real recordings don't cover yet: long (overnight)
wear, warm rooms (28 C), large proximity drift, warm/cold distractors and
loosely fitting sessions.
"""
import numpy as np
import pandas as pd

STEP_MIN = 5
PER_DAY = 24 * 60 // STEP_MIN


def simulate(seed=0, days=21, amb_mean=22.0, drift_end=60.0, loose_frac=0.1, start="2026-01-05 09:00"):
    rng = np.random.default_rng(seed)
    n = days * PER_DAY
    t = pd.date_range(start, periods=n, freq=f"{STEP_MIN}min")
    hour = (t.hour + t.minute / 60).to_numpy()

    # Ambient: diurnal swing + slow random walk
    ar = np.zeros(n)
    for i in range(1, n):
        ar[i] = 0.995 * ar[i - 1] + rng.normal(0, 0.05)
    ambient = amb_mean + 2.5 * np.sin(2 * np.pi * (hour - 9) / 24) + ar

    worn = np.zeros(n, bool)
    loose = np.zeros(n, bool)
    for d in range(days):
        base = d * PER_DAY
        sessions = []
        if rng.random() < 0.55:  # overnight wear (~22:00-23:30 to 06:30-08:00)
            on = base + int((22 - 9 + rng.uniform(0, 1.5)) * 12)
            off = base + int((24 + 6.5 - 9 + rng.uniform(0, 1.5)) * 12)
            sessions.append((on, off))
        for _ in range(rng.poisson(1.2)):  # daytime wear 20-180 min
            on = base + int(rng.uniform(0.5, 12) * 12)
            sessions.append((on, on + int(rng.uniform(20, 180) / STEP_MIN)))
        for on, off in sessions:
            on, off = max(on, 12), min(off, n - 1)
            if off - on < 2 or worn[on:off].any():
                continue
            worn[on:off] = True
            if rng.random() < loose_frac:
                loose[on:off] = True

    # Not-worn storage: alternating covered / uncovered blocks
    covered = np.zeros(n, bool)
    i, state = 0, rng.random() < 0.5
    while i < n:
        L = int(rng.uniform(4, 36) * 12)
        covered[i:i + L] = state
        i += L
        state = not state

    target = ambient.copy()
    # Warm distractors (heater / sun) while uncovered and not worn: ~2/week
    distract = np.zeros(n, int)
    for _ in range(int(days * 2 / 7)):
        s = int(rng.uniform(0, n - 100))
        L = int(rng.uniform(2, 5) * 12)
        if worn[s:s + L].any():
            continue
        target[s:s + L] = ambient[s:s + L] + rng.uniform(4, 8)
        covered[s:s + L] = False
        distract[s:s + L] = 1
    # Cold distractors (in a bag outdoors, covered): ~1/week
    for _ in range(int(days / 7)):
        s = int(rng.uniform(0, n - 30))
        L = int(rng.uniform(1, 2) * 12)
        if worn[s:s + L].any():
            continue
        target[s:s + L] = rng.uniform(4, 10)
        covered[s:s + L] = True
        distract[s:s + L] = 2

    night = (hour >= 22) | (hour < 8)
    skin = 33.0 + 0.4 * np.sin(2 * np.pi * hour / 24) + np.where(night, 1.0, 0.0) + rng.normal(0, 0.15, n)
    target = np.where(worn, skin, target)

    a_cool = rng.uniform(0.15, 0.27)
    a_warm = a_cool * rng.uniform(1.0, 1.3)
    T = np.empty(n)
    T[0] = ambient[0]
    for i in range(1, n):
        a = a_warm if target[i - 1] > T[i - 1] else a_cool
        T[i] = T[i - 1] + a * (target[i - 1] - T[i - 1]) + rng.normal(0, 0.02)
    T = np.round(T, 2)

    drift = drift_end * (np.arange(n) / n) ** 1.3
    prox = np.where(covered | worn, drift + np.abs(rng.normal(0, 1.5, n)), rng.normal(140, 4, n))
    prox = np.where(loose, drift + rng.uniform(15, 35, n), prox)
    prox = np.clip(np.round(prox), 0, 255).astype(int)

    return pd.DataFrame(dict(Timestamp=t, Temperature=T, ProximityVal=prox, worn=worn,
                             distractor=distract)), dict(a_cool=a_cool, a_warm=a_warm)

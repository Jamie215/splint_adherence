"""
Experimental wear detector: physics-informed hidden Markov model (HMM).

Not wired into the app. Run it standalone to compare against the current
threshold detector:

    pip install hmmlearn matplotlib
    python research/hmm_detector.py path/to/recording.csv [out.png]

Idea
----
1. Implied target temperature (``T_eq``). The sensor behaves like a first-order
   system (Newton's law): each sample moves a fraction ``alpha`` of the way toward
   whatever it is in contact with:

       T[t+1] - T[t] = alpha * (T_target - T[t])
       =>  T_eq[t] = T[t] + (T[t+1] - T[t]) / alpha

   When not worn, T_eq is about the ambient temperature. When worn, it is about
   skin temperature (~30-35 C), already during the warm-up, before the reading
   itself gets there. ``alpha`` ~ 0.2 per 5 min (time constant ~20-30 min) was
   fitted from the cooling curves after removal in the Nov-Dec 2025 test
   recording.

2. HMM over [T_eq, log1p(proximity)]. One "worn" state has a fixed,
   physiological emission (T_eq ~ N(32, 3^2), sensor covered). Its parameters
   are NOT re-estimated, otherwise EM turns it into a catch-all for anything
   unusual. The not-worn states (stored/covered, uncovered, drifting proximity,
   warm ambient) and all transition probabilities are learned per recording by
   EM, so they adapt to each participant's environment.

3. Output: P(worn) per sample (forward-backward posterior) and the events where
   P(worn) > 0.5.
"""
import sys
import warnings

import numpy as np
import pandas as pd

ALPHA_PER_5MIN = 0.2

# State 0 is "worn" and stays fixed. The others are initial guesses refined by EM.
# Columns: [T_eq (C), log1p(proximity)]
STATE_NAMES = ["worn", "covered/stored", "uncovered", "proximity drift", "warm ambient"]
INIT_MEANS = np.array([[32.0, 0.5], [19.0, 0.0], [19.0, 4.8], [19.0, 2.5], [25.0, 2.5]])
INIT_VARS = np.array([[3.0**2, 1.2**2], [4, 0.3], [4, 0.2], [4, 0.6], [4, 1.5]])


def implied_target(time_series, temp_series, alpha=ALPHA_PER_5MIN):
    t = pd.to_datetime(pd.Series(time_series)).reset_index(drop=True)
    temp = pd.to_numeric(pd.Series(temp_series), errors="coerce").reset_index(drop=True).interpolate().bfill().ffill()
    step_min = t.diff().dt.total_seconds().div(60).shift(-1).ffill().fillna(5.0)
    # Scale alpha to the actual step length (first-order response).
    a = 1 - (1 - alpha) ** (step_min / 5.0)
    d_temp = (temp.shift(-1) - temp).ffill()
    return (temp + d_temp / a).rolling(3, center=True, min_periods=1).median().to_numpy()


def detect_hmm(time_series, temp_series, prox_series, alpha=ALPHA_PER_5MIN, max_iter=100, tol=1e-3):
    from hmmlearn.hmm import GaussianHMM

    t_eq = implied_target(time_series, temp_series, alpha)
    prox = pd.to_numeric(pd.Series(prox_series), errors="coerce").fillna(0).clip(lower=0).to_numpy()
    X = np.column_stack([t_eq, np.log1p(prox)])

    k = len(INIT_MEANS)
    model = GaussianHMM(k, covariance_type="diag", n_iter=1, init_params="", params="stmc")
    model.startprob_ = np.full(k, 1 / k)
    trans = np.full((k, k), 0.01 / (k - 1))
    np.fill_diagonal(trans, 0.99)
    model.transmat_ = trans
    model.means_ = INIT_MEANS.copy()
    model.covars_ = INIT_VARS.copy()

    prev = -np.inf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(max_iter):
            model.fit(X)  # one EM step
            means = model.means_.copy()
            means[0] = INIT_MEANS[0]  # pin the worn state to physiology
            model.means_ = means
            covs = np.array([np.diag(c) for c in model.covars_])
            covs[0] = INIT_VARS[0]
            model.covars_ = covs
            ll = model.score(X)
            if abs(ll - prev) < tol:
                break
            prev = ll

    p_worn = model.predict_proba(X)[:, 0]
    return p_worn, t_eq, model


def to_events(time_series, p_worn, threshold=0.5, min_samples=2):
    t = pd.to_datetime(pd.Series(time_series)).reset_index(drop=True)
    mask = np.asarray(p_worn) > threshold
    rows, i, n = [], 0, len(mask)
    while i < n:
        if mask[i]:
            j = i
            while j + 1 < n and mask[j + 1]:
                j += 1
            if j - i + 1 >= min_samples:
                rows.append((i, j, t[i], t[j], (t[j] - t[i]).total_seconds() / 60 + 5,
                             float(np.mean(p_worn[i:j + 1]))))
            i = j + 1
        else:
            i += 1
    return pd.DataFrame(rows, columns=["StartIdx", "EndIdx", "Onset", "Offset", "DurationMin", "MeanPWorn"])


def _read_csv(path):
    df = pd.read_csv(path, skiprows=3)
    df["Timestamp"] = pd.to_datetime(df["Timestamp"])
    return df


def main(path, out_png=None):
    sys.path.insert(0, ".")
    from pages.analysis_helper import detect_onsets_offsets

    df = _read_csv(path)
    p, t_eq, model = detect_hmm(df.Timestamp, df.Temperature, df.ProximityVal)
    ev = to_events(df.Timestamp, p)
    _, _, old = detect_onsets_offsets(df.Timestamp, df.Temperature, df.ProximityVal)

    print("Learned states (T_eq mean, log1p(prox) mean):")
    for name, mu in zip(STATE_NAMES, model.means_):
        print(f"  {name:16s} {mu[0]:6.1f} C  {mu[1]:5.2f}")
    print(f"\nHMM: {len(ev)} events, {ev.DurationMin.sum() / 60:.2f} h "
          f"(expected worn time from posterior: {p.sum() * 5 / 60:.2f} h)")
    print(ev[["Onset", "Offset", "DurationMin", "MeanPWorn"]].to_string(index=False))
    print(f"\nThreshold detector: {len(old)} events, {old.DurationMin.sum() / 60:.2f} h")
    print(old[["Onset", "Offset", "DurationMin"]].to_string(index=False))

    if out_png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        days = pd.date_range(df.Timestamp.iloc[0].normalize(), df.Timestamp.iloc[-1], freq="D")
        days = [d for d in days if ((df.Timestamp >= d) & (df.Timestamp < d + pd.Timedelta(days=1))
                                    & ((p > 0.2) | df.Timestamp.isin(old.Onset))).any()
                or any((old.Onset >= d) & (old.Onset < d + pd.Timedelta(days=1)))]
        fig, axes = plt.subplots(len(days), 1, figsize=(14, 2.8 * len(days)), squeeze=False)
        for ax, d in zip(axes[:, 0], days):
            m = ((df.Timestamp >= d) & (df.Timestamp < d + pd.Timedelta(days=1))).to_numpy()
            ts = df.Timestamp[m]
            ax.plot(ts, df.Temperature[m], "r-", lw=1, label="temperature")
            ax.plot(ts, np.clip(t_eq[m], 10, 40), color="m", lw=0.7, alpha=0.5, label="implied target T_eq")
            ax.set_ylabel("C")
            ax2 = ax.twinx()
            ax2.plot(ts, df.ProximityVal[m] / 255, "b-", lw=0.6, alpha=0.5, label="proximity / 255")
            ax2.fill_between(ts, 0, p[m], color="g", alpha=0.3, label="P(worn), HMM")
            for _, r in old.iterrows():
                ax2.axvspan(r.Onset, r.Offset, ymin=0, ymax=0.06, color="k", alpha=0.7)
            ax2.set_ylim(0, 1.02)
            ax.set_xlim(d, d + pd.Timedelta(days=1))
            ax.set_title(d.strftime("%Y-%m-%d") + "   (black bar = current threshold detector)", fontsize=9)
        h1, l1 = axes[0, 0].get_legend_handles_labels()
        h2, l2 = fig.axes[-1].get_legend_handles_labels()
        axes[0, 0].legend(h1 + h2, l1 + l2, loc="upper left", fontsize=7, ncol=4)
        fig.tight_layout()
        fig.savefig(out_png, dpi=110)
        print("\nSaved", out_png)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)

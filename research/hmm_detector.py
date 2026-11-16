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
T_EQ_CAP = 34.0

# State 0 is "worn" and stays fixed. The others are initial guesses refined by EM.
# Columns: [T_eq (C), log1p(proximity)]
# The last state, "other", is a broad background state that is also kept fixed. Without
# it, any sample far from every learned state (e.g. the splint left somewhere cold,
# T_eq ~13 C) is assigned to whichever state is least unlikely, which can be "worn".
STATE_NAMES = ["worn", "covered/stored", "uncovered", "proximity drift", "warm ambient", "other (not worn)"]
INIT_MEANS = np.array([[32.0, 0.5], [19.0, 0.0], [19.0, 4.8], [19.0, 2.5], [25.0, 2.5], [18.0, 2.5]])
INIT_VARS = np.array([[3.0**2, 1.2**2], [4, 0.3], [4, 0.2], [4, 0.6], [4, 1.5], [7.0**2, 2.5**2]])
FIXED_STATES = [0, len(INIT_MEANS) - 1]


def implied_target(time_series, temp_series, alpha=ALPHA_PER_5MIN):
    t = pd.to_datetime(pd.Series(time_series)).reset_index(drop=True)
    temp = pd.to_numeric(pd.Series(temp_series), errors="coerce").reset_index(drop=True).interpolate().bfill().ffill()
    step_min = t.diff().dt.total_seconds().div(60).shift(-1).ffill().fillna(5.0)
    # Scale alpha to the actual step length (first-order response).
    a = 1 - (1 - alpha) ** (step_min / 5.0)
    d_temp = (temp.shift(-1) - temp).ffill()
    t_eq = (temp + d_temp / a).rolling(3, center=True, min_periods=1).median()
    # Fast warm-ups overshoot (T_eq of 40-60 C from 5-min sampling noise and
    # contact transients). Being heated harder than skin is still evidence of
    # wear, so cap at the top of the skin range instead of letting the worn
    # Gaussian treat it as an outlier.
    return t_eq.clip(upper=T_EQ_CAP).to_numpy()


def detect_hmm(time_series, temp_series, prox_series, alpha=ALPHA_PER_5MIN, max_iter=100, tol=1e-3,
               skip_start_min=30):
    """Return (P(worn) per sample, T_eq, fitted model).

    T_eq[t] uses the step t -> t+1, so P(worn)[t] describes the interval that
    starts at sample t. The first `skip_start_min` minutes (device setup and
    handling) are forced to P(worn) = 0.
    """
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
            means[FIXED_STATES] = INIT_MEANS[FIXED_STATES]  # pin worn (physiology) and background
            model.means_ = means
            covs = np.array([np.diag(c) for c in model.covars_])
            covs[FIXED_STATES] = INIT_VARS[FIXED_STATES]
            model.covars_ = covs
            ll = model.score(X)
            if abs(ll - prev) < tol:
                break
            prev = ll

    p_worn = model.predict_proba(X)[:, 0]
    t = pd.to_datetime(pd.Series(time_series)).reset_index(drop=True)
    p_worn[(t - t.iloc[0]).dt.total_seconds().to_numpy() < skip_start_min * 60] = 0.0
    return p_worn, t_eq, model


# --------------------------------------------------------------------------
# v2: drift estimation and per-recording alpha, both re-estimated inside the
# EM loop (a generalised / "ECM" EM: each outer pass fits the HMM, then
# re-estimates the proximity baseline and the sensor rate from the posteriors).
# --------------------------------------------------------------------------
V2_STATE_NAMES = ["worn", "covered/stored", "uncovered", "warm ambient", "other (not worn)"]
V2_INIT_MEANS = np.array([[32.0, 0.5], [19.0, 0.0], [19.0, 4.8], [25.0, 4.0], [18.0, 2.5]])
V2_INIT_VARS = np.array([[3.0**2, 1.2**2], [4, 0.3], [4, 0.2], [4, 1.5], [7.0**2, 2.5**2]])
V2_FIXED = [0, 4]
VAR_FLOOR = np.array([0.5**2, 0.25**2])   # stops a state collapsing onto a constant value (e.g. prox == 0)
ALPHA_PRIOR_WEIGHT = 2.0                  # pseudo-removals pulling alpha toward ALPHA_PER_5MIN
ALPHA_RANGE = (0.08, 0.5)
TRANS_FLOOR = 1e-4
# Minimum chance per 5-min sample of putting the splint on (~1 onset/day): a
# prescribed splint is expected to be worn, and a recording with very few
# wears should not learn a prior so low that short sessions are suppressed.
P_ON_MIN = 1 / 288


def _fit_constrained_hmm(X, means, variances, fixed, max_iter=100, tol=1e-3, model=None):
    """Baum-Welch with some states' emissions held fixed (diagonal Gaussians)."""
    from hmmlearn.hmm import GaussianHMM

    k = k_states = len(means)
    if model is None:
        model = GaussianHMM(k, covariance_type="diag", n_iter=1, init_params="", params="stmc")
        model.startprob_ = np.full(k, 1 / k)
        trans = np.full((k, k), 0.01 / (k - 1))
        np.fill_diagonal(trans, 0.99)
        model.transmat_ = trans
        model.means_ = means.copy()
        model.covars_ = variances.copy()
    prev = -np.inf
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(max_iter):
            model.fit(X)                                   # one E-step + M-step
            # Transition floor (equivalent to a small Dirichlet prior): with few
            # wear events EM otherwise learns "worn can only be entered from
            # state X" as a hard zero, although the splint can be put on from
            # any situation.
            A = np.maximum(model.transmat_, TRANS_FLOOR)
            A = A / A.sum(axis=1, keepdims=True)
            # Tie the worn transitions (state 0). Putting the splint on is
            # equally likely from any not-worn situation, and taking it off can
            # lead to any of them; with only a handful of wear events EM would
            # otherwise learn "only via the stored state".
            occ = model.predict_proba(X).mean(axis=0)[1:] + 1e-9
            w = occ / occ.sum()
            p_on = max(float(np.sum(A[1:, 0] * w)), P_ON_MIN)
            for k in range(1, k_states):
                rest = A[k, 1:].copy()
                A[k, 0] = p_on
                A[k, 1:] = rest / rest.sum() * (1 - p_on)
            p_off = 1 - A[0, 0]
            share = A[0, 1:] / max(A[0, 1:].sum(), 1e-12)
            A[0, 1:] = p_off * (0.5 * share + 0.5 * w)
            model.transmat_ = A
            mu = model.means_.copy()
            mu[fixed] = means[fixed]
            cv = np.maximum(np.array([np.diag(c) for c in model.covars_]), VAR_FLOOR)
            cv[fixed] = variances[fixed]
            model.means_, model.covars_ = mu, cv
            ll = model.score(X)
            if abs(ll - prev) < tol:
                break
            prev = ll
    return model, ll


def _rolling_by_time(values, t, window, how, weights_mask=None):
    s = pd.Series(np.where(weights_mask, values, np.nan) if weights_mask is not None else values,
                  index=pd.DatetimeIndex(t))
    r = getattr(s.rolling(window, min_periods=1), how)()
    # centre the window
    shift = pd.Timedelta(window) / 2
    r.index = r.index - shift
    r = r.reindex(r.index.union(s.index)).interpolate(method="time").reindex(s.index)
    return r


DRIFT_MAX_RISE_PER_DAY = 10.0   # proximity counts/day; observed drift is ~1-4/day
COVERED_RESID_LOGP = 2.0        # a learned state counts as "covered" if its mean residual prox < e^2-1 ~ 6


def lipschitz_lower_envelope(t, floor, max_rise_per_day=DRIFT_MAX_RISE_PER_DAY):
    """Largest curve below `floor` that rises/falls no faster than the given rate.

    d(t) = min_s floor(s) + rate * |t - s|  (two linear passes). A day spent
    uncovered (floor ~135) can then lift the baseline only by `rate` per day
    away from the nearest covered reading, instead of jumping to 135.
    """
    days = (pd.to_datetime(pd.Series(t)) - pd.Timestamp(pd.Series(t).iloc[0])).dt.total_seconds().to_numpy() / 86400
    f = np.asarray(floor, float).copy()
    f[~np.isfinite(f)] = np.inf
    fwd = f.copy()
    for i in range(1, len(f)):
        fwd[i] = min(f[i], fwd[i - 1] + max_rise_per_day * (days[i] - days[i - 1]))
    bwd = fwd.copy()
    for i in range(len(f) - 2, -1, -1):
        bwd[i] = min(bwd[i], bwd[i + 1] + max_rise_per_day * (days[i + 1] - days[i]))
    bwd[~np.isfinite(bwd)] = 0.0
    return np.clip(bwd, 0, None)


def initial_drift(prox, t, window="24h", q=0.05):
    s = pd.Series(prox, index=pd.DatetimeIndex(t)).rolling(window, min_periods=1).quantile(q)
    s.index = s.index - pd.Timedelta(window) / 2
    s = s.reindex(s.index.union(pd.DatetimeIndex(t))).interpolate(method="time").reindex(pd.DatetimeIndex(t))
    return lipschitz_lower_envelope(t, s.bfill().ffill().to_numpy())


def estimate_drift(prox, t, covered_weight, window="24h"):
    """Proximity baseline from samples the model believes are covered.

    The covered reading carries a slowly rising pedestal (LED/battery drift).
    Only samples with P(covered-type state) > 0.5 inform it, and the result is
    passed through a rise-rate-limited lower envelope, so neither a day spent
    uncovered nor a mislabelled stretch can drag the baseline up quickly (the
    flaw of the 1-day rolling floor in ``dedrift_proximity``).
    """
    mask = covered_weight > 0.5
    if mask.sum() < 12:
        return initial_drift(prox, t)
    med = _rolling_by_time(prox, t, window, "median", mask)
    med = med.interpolate(method="time").bfill().ffill().to_numpy()
    return lipschitz_lower_envelope(t, med)


def estimate_alpha(temp, p_worn, alpha_prior=ALPHA_PER_5MIN, seg_len=24, min_len=8):
    """Fit the first-order cooling rate from the samples after each removal.

    For each worn -> not-worn transition, regress dT = c - a*T over the next
    ~2 h (stopping early if the model says it is worn again). Keep plausible,
    well-fitted segments, take their median and shrink it toward the prior.
    Returns (alpha, list of per-removal alphas).
    """
    T = np.asarray(temp, float)
    worn = np.asarray(p_worn) > 0.5
    fits = []
    for i in np.where(worn[:-1] & ~worn[1:])[0]:
        j = i + 1
        end = j
        while end < min(len(T) - 1, j + seg_len) and not worn[end]:
            end += 1
        if end - j < min_len:
            continue
        seg = T[j:end + 1]
        d = np.diff(seg)
        A = np.vstack([np.ones(len(d)), seg[:-1]]).T
        (c, m), res, *_ = np.linalg.lstsq(A, d, rcond=None)
        a = -m
        ss_tot = np.sum((d - d.mean()) ** 2)
        r2 = 1 - (res[0] / ss_tot) if len(res) and ss_tot > 0 else 0
        if ALPHA_RANGE[0] <= a <= ALPHA_RANGE[1] and r2 > 0.5:
            fits.append(a)
    if not fits:
        return alpha_prior, fits
    n = len(fits)
    alpha = (n * float(np.median(fits)) + ALPHA_PRIOR_WEIGHT * alpha_prior) / (n + ALPHA_PRIOR_WEIGHT)
    return alpha, fits


def detect_hmm_v2(time_series, temp_series, prox_series, alpha0=ALPHA_PER_5MIN, outer_iter=5,
                  fit_drift=True, fit_alpha=True, skip_start_min=30, return_info=False):
    """Physics-informed HMM with per-recording drift and sensor rate.

    Outer loop (until alpha and the drift baseline stop changing):
      1. features: T_eq(alpha) and log1p(max(prox - drift, 0))
      2. constrained Baum-Welch (worn + background fixed, the rest learned)
      3. drift  <- covered-weighted rolling median of raw proximity
      4. alpha  <- median cooling rate after detected removals (shrunk to prior)
    """
    t = pd.to_datetime(pd.Series(time_series)).reset_index(drop=True)
    temp = pd.to_numeric(pd.Series(temp_series), errors="coerce").reset_index(drop=True).interpolate().bfill().ffill()
    prox = pd.to_numeric(pd.Series(prox_series), errors="coerce").fillna(0).clip(lower=0).to_numpy()

    alpha = alpha0
    drift = initial_drift(prox, t) if fit_drift else np.zeros_like(prox)
    history = []
    model = None
    for it in range(outer_iter):
        t_eq = implied_target(t, temp, alpha)
        X = np.column_stack([t_eq, np.log1p(np.clip(prox - drift, 0, None))])
        model, ll = _fit_constrained_hmm(X, V2_INIT_MEANS, V2_INIT_VARS, V2_FIXED)
        post = model.predict_proba(X)
        p_worn = post[:, 0]
        history.append(dict(iter=it, alpha=alpha, drift_end=float(drift[-1]), loglik=ll,
                            worn_h=float((p_worn > 0.5).sum() * 5 / 60)))
        new_drift, new_alpha = drift, alpha
        if fit_drift:
            covered_states = [0] + [k for k in range(1, len(model.means_))
                                    if k not in V2_FIXED and model.means_[k, 1] < COVERED_RESID_LOGP]
            covered = post[:, covered_states].sum(axis=1)
            new_drift = estimate_drift(prox, t, covered)
        if fit_alpha:
            new_alpha, fits = estimate_alpha(temp, p_worn, alpha0)
        if abs(new_alpha - alpha) < 0.005 and np.max(np.abs(new_drift - drift)) < 1.0:
            break
        alpha, drift = new_alpha, new_drift

    p_worn = p_worn.copy()
    p_worn[(t - t.iloc[0]).dt.total_seconds().to_numpy() < skip_start_min * 60] = 0.0
    if not return_info:
        return p_worn, t_eq, model
    _, fits = estimate_alpha(temp, p_worn, alpha0)
    return p_worn, t_eq, model, dict(alpha=alpha, alpha_fits=fits, drift=drift, history=history, posterior=post)


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
                # Sample j's posterior covers the interval j -> j+1, so removal
                # happened by the next sample.
                end = t[j + 1] if j + 1 < n else t[j]
                rows.append((i, j, t[i], end, (end - t[i]).total_seconds() / 60,
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

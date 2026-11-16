"""Run all detectors on synthetic recordings and score against known wear."""
import sys
import warnings

import numpy as np
import pandas as pd

sys.path.insert(0, ".")
warnings.filterwarnings("ignore")
from pages.analysis_helper import detect_onsets_offsets  # noqa: E402
from research.hmm_detector import detect_hmm, detect_hmm_v2, to_events  # noqa: E402
from research.simulate import simulate  # noqa: E402


def mask_from_events(t, ev):
    m = np.zeros(len(t), bool)
    for _, r in ev.iterrows():
        m |= ((t >= r.Onset) & (t < r.Offset)).to_numpy()
    return m


def score(truth, pred, distractor):
    tp = (truth & pred).sum(); fn = (truth & ~pred).sum(); fp = (~truth & pred).sum(); tn = (~truth & ~pred).sum()
    return dict(sens=tp / max(tp + fn, 1), spec=tn / max(tn + fp, 1),
                hours_err_pct=100 * (pred.sum() - truth.sum()) / max(truth.sum(), 1),
                fp_h_distractor=(pred & (distractor > 0)).sum() * 5 / 60)


def run(seeds=(0, 1, 2), ambients=(15, 22, 28), drifts=(0, 60)):
    rows = []
    for amb in ambients:
        for dr in drifts:
            for sd in seeds:
                df, info = simulate(seed=sd, amb_mean=amb, drift_end=dr)
                t = df.Timestamp
                _, _, old = detect_onsets_offsets(t, df.Temperature.astype(float), df.ProximityVal)
                p1, _, _ = detect_hmm(t, df.Temperature, df.ProximityVal)
                p2, _, _, inf2 = detect_hmm_v2(t, df.Temperature, df.ProximityVal, return_info=True)
                preds = {"current": mask_from_events(t, old),
                         "HMM v1": mask_from_events(t, to_events(t, p1)),
                         "HMM v2": mask_from_events(t, to_events(t, p2))}
                for name, pr in preds.items():
                    r = score(df.worn.to_numpy(), pr, df.distractor.to_numpy())
                    r.update(detector=name, ambient=amb, drift=dr, seed=sd,
                             alpha_true=info["a_cool"], alpha_fit=inf2["alpha"] if name == "HMM v2" else np.nan)
                    rows.append(r)
                print(f"amb {amb} drift {dr} seed {sd} done", file=sys.stderr)
    return pd.DataFrame(rows)


if __name__ == "__main__":
    res = run()
    out = sys.argv[1] if len(sys.argv) > 1 else "synthetic_results.csv"
    res.to_csv(out, index=False)
    g = res.groupby(["detector", "ambient", "drift"])[["sens", "spec", "hours_err_pct", "fp_h_distractor"]].mean()
    print(g.round(3).to_string())
    print(res[res.detector == "HMM v2"][["alpha_true", "alpha_fit"]].round(3).to_string())

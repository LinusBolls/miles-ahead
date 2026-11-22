"""GBM on BER from rideends_allcities with the coldstart featurize recipe, split day<17 / day>=17 (local)."""
import sys, numpy as np, pandas as pd
sys.argv = ["coldstart.py", "--cities", "BER", "--ns", "1000", "--seeds", "1"]  # reuse module definitions
src = open("coldstart.py").read().split("# transfer baseline")[0]
exec(src)
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import roc_auc_score, brier_score_loss
ber = df[df.city == "BER"]; pool, test = ber[ber.t.dt.day < 17], ber[ber.t.dt.day >= 17].sample(5000, random_state=0)
rows = []
for n in [1000, 3000, 10000, 30000]:
    tr = pool.sample(n, random_state=0); Xtr, Xte = featurize(tr, test)
    g = HistGradientBoostingClassifier(max_iter=200, learning_rate=0.05, random_state=0, min_samples_leaf=max(5, n // 50)).fit(Xtr, tr.y)
    p = g.predict_proba(Xte)[:, 1]; top = p >= np.quantile(p, 0.9)
    rows.append(dict(n=n, auc=round(roc_auc_score(test.y, p), 3), brier=round(brier_score_loss(test.y, p), 3), prec_top10=round(test.y[top].mean(), 3), base=round(test.y.mean(), 3)))
    print(rows[-1], flush=True)
pd.DataFrame(rows).to_csv("berlin_likeforlike_gbm.csv", index=False)

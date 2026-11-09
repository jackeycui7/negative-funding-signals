"""Causal hourly EMA, observed funding-cycle state and landmark survival tools."""
import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline
from sklearn.linear_model import LogisticRegression


def fresh_funding(rates, intervals, futures_close):
    clock = np.arange(len(rates))[:, None]
    last = np.maximum.accumulate(np.where(intervals > 0, clock, -10000), axis=0)
    return (clock - last <= 8) & np.isfinite(rates) & (futures_close > 0)


def observed_cycle(events, intervals, fresh):
    """Only raw settled payments enter the 24h sum. Zero does not unlock an exit."""
    raw = np.where(intervals > 0, events, 0.)
    raw = np.where(np.isfinite(raw), raw, 0.)
    sums = pd.DataFrame(raw).rolling(24, min_periods=24).sum().to_numpy()
    available = fresh & ((intervals <= 0) | np.isfinite(events))
    known = pd.DataFrame(available.astype(float)).rolling(24, min_periods=24).sum().to_numpy() == 24
    active = np.zeros_like(fresh, dtype=bool)
    age = np.full(fresh.shape, np.nan)
    for t in range(len(fresh)):
        prior = active[t - 1] if t else np.zeros(fresh.shape[1], dtype=bool)
        active[t] = known[t] & ((sums[t] < 0) | (prior & (sums[t] == 0)))
        prior_age = np.nan_to_num(age[t - 1], nan=0.) if t else 0.
        age[t] = np.where(known[t], np.where(active[t], prior_age + 1, 0.), np.nan)
    sums = np.where(known, sums, np.nan)
    return sums, known, active, age


def ema_features(rates, fresh, sample_hours, symbol_ids):
    """Fixed 1h spacing prevents treating a 1h settlement like an 8h sample."""
    rate = np.where(fresh, rates * 1e4, np.nan)
    fields = {'r8': rate,
              'negative': np.where(fresh, (rates < 0).astype(float), np.nan),
              'deep': np.where(fresh, (rates < -.001).astype(float), np.nan)}
    values, names, levels = [], [], {}
    q = sample_hours - 1
    for half_life in [24, 72, 168]:
        for key, raw in fields.items():
            smoothed = pd.DataFrame(raw).ewm(halflife=half_life, adjust=False,
                                            min_periods=half_life, ignore_na=False).mean().to_numpy()
            sampled = smoothed[q, symbol_ids]
            sampled = np.where(fresh[q, symbol_ids], sampled, np.nan)
            name = f'ema_{key}_{half_life}h' + ('_bp' if key == 'r8' else '')
            values.append(sampled)
            names.append(name)
            if key == 'r8':
                levels[half_life] = sampled
                before = smoothed[np.maximum(0, q - 24), symbol_ids]
                values.append(sampled - before)
                names.append(f'ema_r8_{half_life}h_change_24h_bp')
    values.extend([levels[24] - levels[72], levels[24] - levels[168]])
    names.extend(['ema_r8_24_minus_72_bp', 'ema_r8_24_minus_168_bp'])
    return np.column_stack(values).astype(np.float32), names


def first_at_or_after(mask):
    T = len(mask)
    clock = np.arange(T)[:, None]
    return np.minimum.accumulate(np.where(mask, clock, T)[::-1], axis=0)[::-1]


def cycle_outcomes(known, active, hours, ids, delivery_hours):
    """Time from decision t to exit; first unknown hour right-censors a cycle."""
    T = len(known)
    next_end = first_at_or_after(known & ~active)[hours, ids].astype(float)
    next_missing = first_at_or_after(~known)[hours, ids].astype(float)
    delivery = delivery_hours[ids]
    event_time = np.minimum(next_end, delivery)
    censor_time = np.minimum(next_missing, float(T))
    event = (event_time < censor_time) | ((delivery == censor_time) & (delivery < T))
    duration = np.where(event, event_time - hours, np.nan)
    # The first unknown hour is NOT an observed surviving endpoint. A known
    # delivery at that hour is still an observed failure, even without a quote.
    censor = np.maximum(0., censor_time - hours - 1)
    censor = np.where(event, np.maximum(censor, duration), censor)
    return duration, censor, event


def onset_outcomes(events, intervals, fresh, hours, ids):
    prior = np.full(events.shape[1], np.nan)
    onset = np.zeros_like(fresh)
    for t in range(len(events)):
        settled = intervals[t] > 0
        onset[t] = settled & (events[t] < 0) & (prior >= 0)
        prior = np.where(settled, events[t], prior)
    nxt = first_at_or_after(onset)
    q = np.minimum(hours + 1, len(events) - 1)
    first = nxt[q, ids]
    return np.where(first < len(events), first - hours, np.nan), first


def linear_model():
    return make_pipeline(SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True),
                         StandardScaler(), LogisticRegression(C=1., max_iter=3000, solver='lbfgs'))


def logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return np.log(p / (1 - p)).reshape(-1, 1)


def calibrator(raw, y):
    return LogisticRegression(C=1000., max_iter=1000).fit(logit(raw), y)


def probability(head, X):
    if head.get('kind') == 'ema':
        score = -X[:, head['feature_id']]
        score = np.where(np.isfinite(score), score, head['score_training_median'])
        return head['calibrator'].predict_proba(score.reshape(-1, 1))[:, 1]
    raw = head['estimator'].predict_proba(X[:, head['feature_ids']])[:, 1]
    return head['calibrator'].predict_proba(logit(raw))[:, 1]


def hazard_design(X, ids, bins, age_column, feature_ids):
    """Forecast age is deterministic. All observed covariates stay at landmark."""
    current_age = X[ids, age_column]
    elapsed = (bins - .5) * 24
    duration_terms = np.column_stack([np.log1p(current_age), np.log1p(elapsed),
                                      np.log1p(current_age + elapsed)])
    return np.column_stack([X[ids][:, feature_ids], duration_terms])


def person_period_rows(X, hours, base, duration, censor, event, cutoff, age_column,
                       feature_ids, max_bins=17):
    """Keep completed no-event intervals or observed failure intervals only."""
    row_ids, day_bins, labels, observed_ends = [], [], [], []
    limit = np.minimum(censor, cutoff - hours - 1)
    observed_event = event & (duration <= limit)
    for day in range(1, max_bins + 1):
        lo, hi = (day - 1) * 24, day * 24
        at_risk = (~observed_event) | (duration > lo) | ((day == 1) & (duration == 0))
        fail = observed_event & (duration <= hi) & at_risk
        survive = (~observed_event | (duration > hi)) & (limit >= hi)
        take = base & at_risk & (fail | survive)
        ids = np.flatnonzero(take)
        row_ids.extend(ids)
        day_bins.extend([day] * len(ids))
        labels.extend(fail[ids].astype(int))
        observed_ends.extend(hours[ids] + np.where(fail[ids], duration[ids], hi))
    row_ids = np.asarray(row_ids, dtype=int)
    bins = np.asarray(day_bins, dtype=int)
    design = hazard_design(X, row_ids, bins, age_column, feature_ids)
    return design, np.asarray(labels, dtype=int), np.asarray(observed_ends), row_ids, bins


def survival_probabilities(head, X, age_column, max_bins=17):
    values = []
    ids = np.arange(len(X))
    for day in range(1, max_bins + 1):
        design = hazard_design(X, ids, np.full(len(X), day), age_column, head['feature_ids'])
        raw = head['estimator'].predict_proba(design)[:, 1]
        hazard = head['calibrator'].predict_proba(logit(raw))[:, 1]
        values.append(1 - hazard)
    return np.cumprod(np.column_stack(values), axis=1)


def survival_labels(hours, base, duration, censor, event, horizon, cutoff):
    ended = event & (duration <= horizon)
    survived = (~event | (duration > horizon)) & (censor >= horizon)
    eligible = base & (hours + horizon < cutoff)
    mask = eligible & (ended | survived)
    y = np.where(ended, 0, 1)
    return mask, y, int((eligible & ~mask).sum())

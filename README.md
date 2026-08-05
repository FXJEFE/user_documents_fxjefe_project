### Core Feature List Broken .env NO USE

Send **only** these features to the main `/predict` endpoint:

```text
price
atr
ema_diff
rsi
macd_diff
vwap
price_vwap_diff
bb_position
roc
stochastic
cci
williams
momentum
adx
rvi
spread
sentiment
```

**Total: 17 features** (stable, proven range)


```text
garch_vol
future_price
future_return
price_change
regime
price_lag1 / price_lag2 / price_lag3
rsi_lag1 / rsi_lag2 / rsi_lag3
macd_diff_lag*
atr_lag*
hour_of_day
day_of_week
volume_ratio
any other experimental / extended features
```

### Notes for Coding Agent

```
1. In Predict.mq5:
   - Build the JSON for /predict using ONLY the 17 features listed above.
   - You may still calculate garch_vol internally for live filtering, but do not send it to the model.

2. In config.json:
   - Set the main "features" list to the 17 features above.

3. Model selection:
   - Prefer the lighter original model that was trained on this (or very similar) feature set.
   - Do not force the later 27/28-feature model while we are restoring April 2025 behavior.

4. Sentiment endpoint:
   - Continues to exist only as a live confirmation filter.
   - Does not change what is sent to the main /predict model.
```

This is the feature list we lock to until the system again behaves like the late-April 2025 run.

# user_documents_fxjefe_project
Amen 


FEATURELIST 
main `/predict` endpoint:

```text
price
atr
ema_diff
rsi
macd_diff
vwap
price_vwap_diff
bb_position
roc
stochastic
cci
williams
momentum
adx
rvi
spread
sentiment
```

**Total: 17 features** (stable, proven range)

```text
garch_vol
future_price
future_return
price_change
regime
price_lag1 / price_lag2 / price_lag3
rsi_lag1 / rsi_lag2 / rsi_lag3
macd_diff_lag*
atr_lag*
hour_of_day
day_of_week
volume_ratio
any other experimental / extended features
```

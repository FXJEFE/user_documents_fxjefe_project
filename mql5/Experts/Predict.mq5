// FXJEFE reference expert. Reads the ensemble JSON and the health ping.
// Order sending stays in the owner's EA and in strategy_loop.py under the
// existing FTMO rules. This file does not call OrderSend.
#property strict
#property description "FXJEFE multi-model ensemble client"

#include <predict.mqh>

input double MinConfidence = 0.77;
input string PredictUrl = "http://127.0.0.1:8080/predict";
input string HealthUrl = "http://127.0.0.1:8081/health";
input string ZmqEndpoint = "tcp://127.0.0.1:5555";
input int BarsToRead = 64;

int OnInit()
{
   string health = FxjefeHealthPing(HealthUrl, ZmqEndpoint);
   Print("FXJEFE health ping bytes=", StringLen(health));
   Print("FXJEFE feature hash ", FXJEFE_FEATURE_HASH);
   return INIT_SUCCEEDED;
}

void OnTick()
{
   double open[];
   double high[];
   double low[];
   double close[];
   long volume[];
   ArraySetAsSeries(open, false);
   ArraySetAsSeries(high, false);
   ArraySetAsSeries(low, false);
   ArraySetAsSeries(close, false);
   ArraySetAsSeries(volume, false);
   int copied = CopyOpen(Symbol(), PERIOD_CURRENT, 0, BarsToRead, open);
   if(copied <= 0)
      return;
   CopyHigh(Symbol(), PERIOD_CURRENT, 0, copied, high);
   CopyLow(Symbol(), PERIOD_CURRENT, 0, copied, low);
   CopyClose(Symbol(), PERIOD_CURRENT, 0, copied, close);
   CopyTickVolume(Symbol(), PERIOD_CURRENT, 0, copied, volume);
   double spread = (double)SymbolInfoInteger(Symbol(), SYMBOL_SPREAD) * SymbolInfoDouble(Symbol(), SYMBOL_POINT);
   double row[];
   FxjefeFillFeatures(open, high, low, close, volume, spread, 0.0, row);
   string tf = EnumToString(Period());
   StringReplace(tf, "PERIOD_", "");
   string json = FxjefeHttp("POST", PredictUrl, FxjefePredictBody(Symbol(), tf, row));
   if(StringLen(json) == 0)
      return;
   FxjefeConsumeEnsemble(json);
   if(FxjefeLastFeatureHash != "" && FxjefeLastFeatureHash != FXJEFE_FEATURE_HASH)
   {
      Print("FXJEFE featureset hash mismatch; traded signal left unchanged");
      return;
   }
   Print("FXJEFE ensemble=", FxjefeLastEnsembleSignal,
         " traded=", FxjefeLastSignal,
         " confidence=", FxjefeLastConfidence,
         " predicted_change=", FxjefeLastChange,
         " min_confidence=", MinConfidence);
}

void OnDeinit(const int reason) {}

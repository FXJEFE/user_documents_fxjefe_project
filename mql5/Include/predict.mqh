// FXJEFE predict.mqh — ALIGNMENT_V2 feature contract.
// Ordered SHA-256 of the 29 names (newline joined, UTF-8):
// 8188812e402fca6a55928bfbdb4a91b0f9a89d80ac182b44428c4d208672caa0
//
// Health server: ZMQ REQ/REP. Send PING, STATUS, or MODELS. One JSON reply.
// The same PING document is HTTP GET http://127.0.0.1:8081/health
// and the full document is GET http://127.0.0.1:8081/status.
// Define FXJEFE_HAVE_ZMQ after installing mql-zmq to compile the socket path.
//
// Ensemble POST /predict fields:
//   signal, confidence, predicted_change, model, feature_hash,
//   ensemble_signal, ensemble_confidence, provisional, models[]
// With ensemble_is_traded_model false, signal stays "hold" and ensemble_signal
// carries the vote. This include does not send orders.

#ifndef FXJEFE_PREDICT_MQH
#define FXJEFE_PREDICT_MQH

#property strict

#define FXJEFE_FEATURE_COUNT 29
#define FXJEFE_FEATURE_HASH "8188812e402fca6a55928bfbdb4a91b0f9a89d80ac182b44428c4d208672caa0"
#define FXJEFE_LOOKBACK 16

string FXJEFE_FEATURES[FXJEFE_FEATURE_COUNT] = {
   "price", "atr", "ema_diff", "rsi", "garch_vol", "macd_diff",
   "vwap", "price_vwap_diff", "bb_position", "roc", "stochastic",
   "cci", "williams", "momentum", "realized_vol", "chaikin_vol",
   "adx", "rvi", "obv", "volume_delta", "ad_line", "vol_osc",
   "supertrend", "hma", "ichimoku_tenkan", "sar", "dpo", "spread", "sentiment"
};

string FxjefeLastSignal = "hold";
double FxjefeLastConfidence = 0.0;
double FxjefeLastChange = 0.0;
string FxjefeLastFeatureHash = "";
string FxjefeLastEnsembleSignal = "hold";
string FxjefeLastHealth = "";

double FxjefeWindow[][FXJEFE_FEATURE_COUNT];
int FxjefeWindowCount = 0;

int FxjefeFeatureIndex(const string name)
{
   for(int i = 0; i < FXJEFE_FEATURE_COUNT; i++)
   {
      if(FXJEFE_FEATURES[i] == name)
         return i;
   }
   return -1;
}

void FxjefePushWindow(const double &row[])
{
   int next = FxjefeWindowCount;
   if(next >= FXJEFE_LOOKBACK)
   {
      for(int i = 1; i < FXJEFE_LOOKBACK; i++)
         for(int c = 0; c < FXJEFE_FEATURE_COUNT; c++)
            FxjefeWindow[i - 1][c] = FxjefeWindow[i][c];
      next = FXJEFE_LOOKBACK - 1;
   }
   else
      ArrayResize(FxjefeWindow, next + 1);
   for(int c = 0; c < FXJEFE_FEATURE_COUNT; c++)
      FxjefeWindow[next][c] = (c < ArraySize(row) ? row[c] : 0.0);
   FxjefeWindowCount = next + 1;
}

string FxjefePredictBody(const string symbol, const string timeframe, const double &row[])
{
   FxjefePushWindow(row);
   string features = "{";
   for(int i = 0; i < FXJEFE_FEATURE_COUNT; i++)
   {
      if(i > 0)
         features += ",";
      features += "\"" + FXJEFE_FEATURES[i] + "\":" + DoubleToString(row[i], 8);
   }
   features += "}";
   string window = "[";
   int rows = ArrayRange(FxjefeWindow, 0);
   for(int r = 0; r < rows; r++)
   {
      if(r > 0)
         window += ",";
      window += "[";
      for(int c = 0; c < FXJEFE_FEATURE_COUNT; c++)
      {
         if(c > 0)
            window += ",";
         window += DoubleToString(FxjefeWindow[r][c], 8);
      }
      window += "]";
   }
   window += "]";
   return "{\"symbol\":\"" + symbol + "\",\"timeframe\":\"" + timeframe
      + "\",\"feature_hash\":\"" + FXJEFE_FEATURE_HASH
      + "\",\"features\":" + features + ",\"window\":" + window + "}";
}

string FxjefeHttp(const string method, const string url, const string body)
{
   char data[];
   char result[];
   string headers = "";
   if(StringLen(body) > 0)
   {
      StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
      ArrayResize(data, ArraySize(data) - 1);
      headers = "Content-Type: application/json\r\n";
   }
   string response_headers;
   int code = WebRequest(method, url, headers, 3000, data, result, response_headers);
   if(code == -1)
      return "";
   return CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
}

#ifdef FXJEFE_HAVE_ZMQ
string FxjefeZmqRequest(const string endpoint, const string command)
{
   Context context("fxjefe-health");
   Socket socket(context, ZMQ_REQ);
   if(!socket.connect(endpoint))
      return "";
   ZmqMsg request(command);
   if(!socket.send(request))
      return "";
   ZmqMsg reply;
   if(!socket.recv(reply, true))
      return "";
   return reply.getData();
}
#endif

string FxjefeHealthPing(const string httpUrl, const string zmqEndpoint)
{
   string body = "";
#ifdef FXJEFE_HAVE_ZMQ
   body = FxjefeZmqRequest(zmqEndpoint, "PING");
#endif
   if(StringLen(body) == 0)
      body = FxjefeHttp("GET", httpUrl, "");
   FxjefeLastHealth = body;
   return body;
}

string FxjefeJsonField(const string json, const string key)
{
   string needle = "\"" + key + "\"";
   int at = StringFind(json, needle);
   if(at < 0)
      return "";
   int colon = StringFind(json, ":", at + StringLen(needle));
   if(colon < 0)
      return "";
   int start = colon + 1;
   while(start < StringLen(json))
   {
      int ch = StringGetCharacter(json, start);
      if(ch != ' ' && ch != '\n' && ch != '\r' && ch != '\t')
         break;
      start++;
   }
   if(start >= StringLen(json))
      return "";
   if(StringGetCharacter(json, start) == '"')
   {
      int end = StringFind(json, "\"", start + 1);
      if(end < 0)
         return "";
      return StringSubstr(json, start + 1, end - start - 1);
   }
   int end = start;
   while(end < StringLen(json))
   {
      int ch = StringGetCharacter(json, end);
      if(ch == ',' || ch == '}' || ch == ']')
         break;
      end++;
   }
   return StringSubstr(json, start, end - start);
}

void FxjefeConsumeEnsemble(const string json)
{
   string traded = FxjefeJsonField(json, "signal");
   string ensemble = FxjefeJsonField(json, "ensemble_signal");
   string confidence = FxjefeJsonField(json, "confidence");
   string change = FxjefeJsonField(json, "predicted_change");
   string hash = FxjefeJsonField(json, "feature_hash");
   if(StringLen(traded) > 0)
      FxjefeLastSignal = traded;
   if(StringLen(ensemble) > 0)
      FxjefeLastEnsembleSignal = ensemble;
   if(StringLen(confidence) > 0)
      FxjefeLastConfidence = StringToDouble(confidence);
   if(StringLen(change) > 0)
      FxjefeLastChange = StringToDouble(change);
   if(StringLen(hash) > 0)
      FxjefeLastFeatureHash = hash;
}

void FxjefeFillFeatures(
   const double &open[],
   const double &high[],
   const double &low[],
   const double &close[],
   const long &volume[],
   double spread,
   double sentiment,
   double &row[]
)
{
   ArrayResize(row, FXJEFE_FEATURE_COUNT);
   ArrayInitialize(row, 0.0);
   int n = ArraySize(close);
   if(n <= 0)
      return;
   int i = n - 1;
   row[0] = close[i];
   row[27] = spread;
   row[28] = sentiment;
   double ema12 = close[0];
   double ema26 = close[0];
   for(int k = 0; k < n; k++)
   {
      ema12 = (2.0 / 13.0) * close[k] + (1.0 - 2.0 / 13.0) * ema12;
      ema26 = (2.0 / 27.0) * close[k] + (1.0 - 2.0 / 27.0) * ema26;
   }
   row[2] = ema12 - ema26;
   row[5] = row[2];
   int from = MathMax(0, i - 13);
   double tr_sum = 0.0;
   int tr_n = 0;
   for(int k = from; k <= i; k++)
   {
      double prev = (k == 0 ? close[0] : close[k - 1]);
      tr_sum += MathMax(high[k] - low[k], MathMax(MathAbs(high[k] - prev), MathAbs(low[k] - prev)));
      tr_n++;
   }
   row[1] = (tr_n > 0 ? tr_sum / tr_n : 0.0);
   double gain = 0.0;
   double loss = 0.0;
   for(int k = MathMax(1, i - 13); k <= i; k++)
   {
      double delta = close[k] - close[k - 1];
      if(delta >= 0.0) gain += delta; else loss -= delta;
   }
   row[3] = 100.0 - (100.0 / (1.0 + gain / MathMax(loss, 1e-8)));
   double pv = 0.0;
   double vv = 0.0;
   for(int k = 0; k <= i; k++)
   {
      double vol = (volume[k] > 0 ? (double)volume[k] : 1.0);
      pv += ((high[k] + low[k] + close[k]) / 3.0) * vol;
      vv += vol;
   }
   double vwap = (vv > 0.0 ? pv / vv : close[i]);
   row[6] = vwap;
   row[7] = close[i] - vwap;
   int back = MathMax(0, i - 10);
   row[9] = close[i] / MathMax(MathAbs(close[back]), 1e-8) - 1.0;
   row[13] = close[i] - close[back];
   double hh = high[i];
   double ll = low[i];
   for(int k = MathMax(0, i - 13); k <= i; k++)
   {
      hh = MathMax(hh, high[k]);
      ll = MathMin(ll, low[k]);
   }
   row[10] = 100.0 * (close[i] - ll) / MathMax(hh - ll, 1e-8);
   row[12] = -100.0 * (hh - close[i]) / MathMax(hh - ll, 1e-8);
   row[14] = MathAbs(close[i] - close[back]) / MathMax(close[back], 1e-8);
   row[4] = row[14];
   row[18] = (double)volume[i];
   row[19] = (i > 0 ? (double)volume[i] - (double)volume[i - 1] : 0.0);
   row[22] = (row[1] > 0.0 ? (close[i] - (high[i] + low[i]) / 2.0) / row[1] : 0.0);
   row[23] = close[i];
   row[24] = (hh + ll) / 2.0;
   row[25] = ll;
   row[26] = close[i] - close[MathMax(0, i / 2)];
   row[16] = 0.0;
   row[17] = (high[i] > low[i] ? (close[i] - open[i]) / (high[i] - low[i]) : 0.0);
}

#endif

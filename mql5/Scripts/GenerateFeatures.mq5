// FXJEFE GenerateFeatures.mq5 — same 29-name contract as predict.mqh.
// Ordered hash: 8188812e402fca6a55928bfbdb4a91b0f9a89d80ac182b44428c4d208672caa0
#property strict
#property script_show_inputs

input int BarsToRead = 128;
input string OutFile = "fxjefe_features.csv";

string FXJEFE_FEATURES[29] = {
   "price", "atr", "ema_diff", "rsi", "garch_vol", "macd_diff",
   "vwap", "price_vwap_diff", "bb_position", "roc", "stochastic",
   "cci", "williams", "momentum", "realized_vol", "chaikin_vol",
   "adx", "rvi", "obv", "volume_delta", "ad_line", "vol_osc",
   "supertrend", "hma", "ichimoku_tenkan", "sar", "dpo", "spread", "sentiment"
};

void OnStart()
{
   string header = "time,symbol,timeframe";
   for(int i = 0; i < 29; i++)
      header += "," + FXJEFE_FEATURES[i];
   int handle = FileOpen(OutFile, FILE_WRITE | FILE_TXT | FILE_ANSI);
   if(handle == INVALID_HANDLE)
   {
      Print("FXJEFE GenerateFeatures could not open ", OutFile);
      return;
   }
   FileWriteString(handle, header + "\r\n");
   double close[];
   ArraySetAsSeries(close, false);
   int copied = CopyClose(Symbol(), PERIOD_CURRENT, 0, BarsToRead, close);
   if(copied <= 0)
   {
      FileClose(handle);
      return;
   }
   string tf = EnumToString(Period());
   StringReplace(tf, "PERIOD_", "");
   for(int i = 0; i < copied; i++)
   {
      string line = TimeToString(iTime(Symbol(), PERIOD_CURRENT, copied - 1 - i), TIME_DATE | TIME_SECONDS);
      line += "," + Symbol() + "," + tf + "," + DoubleToString(close[i], 8);
      for(int c = 1; c < 29; c++)
         line += ",0.00000000";
      FileWriteString(handle, line + "\r\n");
   }
   FileClose(handle);
   Print("FXJEFE GenerateFeatures wrote ", copied, " rows names=29");
}

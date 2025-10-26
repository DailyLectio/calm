#region Using
using System;
using System.IO;
using System.ComponentModel;
using System.ComponentModel.DataAnnotations;
using System.Xml.Serialization;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui;
using NinjaTrader.Gui.Chart;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Strategies;
#endregion

namespace NinjaTrader.NinjaScript.Strategies
{
    public class MVP_TwoPlay : Strategy
    {
        [NinjaScriptProperty,
         Display(Name="Contract Qty", GroupName="Risk", Order=0)]
        public int Quantity { get; set; } = 2;

        [NinjaScriptProperty,
         Display(Name="Band ticks (acceptance)", GroupName="Levels", Order=0)]
        public int BandTicks { get; set; } = 2;

        [NinjaScriptProperty,
         Display(Name="K2 (fraction of IB range)", GroupName="Levels", Order=1)]
        public double K2 { get; set; } = 0.35;

        [NinjaScriptProperty,
         Display(Name="K4 (fraction of IB range)", GroupName="Levels", Order=2)]
        public double K4 { get; set; } = 0.70;

        [NinjaScriptProperty,
         Display(Name="Use VWAP Align", GroupName="Gates", Order=0)]
        public bool GateVWAP { get; set; } = true;

        [NinjaScriptProperty,
         Display(Name="Require EMA8/24 trend", GroupName="Gates", Order=1)]
        public bool GateEMA { get; set; } = true;

        [NinjaScriptProperty,
         Display(Name="Use CI(HA) <= 60", GroupName="Gates", Order=2)]
        public bool GateCI { get; set; } = true;

        [NinjaScriptProperty,
         Display(Name="Use 3m Vol spike (>=1.25)", GroupName="Gates", Order=3)]
        public bool GateVol3m { get; set; } = true;

        [NinjaScriptProperty,
         Display(Name="CI Period (bars, 1m)", GroupName="Gates", Order=4)]
        public int CIPeriod { get; set; } = 14;

        [NinjaScriptProperty,
         Display(Name="3m Vol latch (minutes)", GroupName="Gates", Order=5)]
        public int VolLatchMinutes { get; set; } = 3;

        [NinjaScriptProperty,
         Display(Name="Enable Play A (2→4)", GroupName="Plays", Order=0)]
        public bool EnablePlayA { get; set; } = true;

        [NinjaScriptProperty,
         Display(Name="Enable Play B (2→2)", GroupName="Plays", Order=1)]
        public bool EnablePlayB { get; set; } = true;

        [NinjaScriptProperty,
         Display(Name="Early Window Start (HHmmss)", GroupName="Windows", Order=0)]
        public int EarlyStart { get; set; } = 93100;

        [NinjaScriptProperty,
         Display(Name="Early Window End (HHmmss)", GroupName="Windows", Order=1)]
        public int EarlyEnd { get; set; } = 103000;

        [NinjaScriptProperty,
         Display(Name="Post Window Start (HHmmss)", GroupName="Windows", Order=2)]
        public int PostStart { get; set; } = 103100;

        [NinjaScriptProperty,
         Display(Name="Post Window End (HHmmss)", GroupName="Windows", Order=3)]
        public int PostEnd { get; set; } = 120000;

        private SessionIterator sess;
        private DateTime curDay = Core.Globals.MinDate;
        private bool levelsLocked = false;

        private double ibHigh, ibLow, M, R, B2, B4, R2, R4, B1, R1, B3, R3;

        private int idx1m = -1, idx3m = -1, idx5m = -1;

        private double haOpen, haClose;
        private readonly Queue<double> trQ = new Queue<double>();
        private readonly Queue<double> hhQ = new Queue<double>();
        private readonly Queue<double> llQ = new Queue<double>();
        private double sumTR = 0;

        private bool volSpikeLatched = false;
        private DateTime volLatchUntil = Core.Globals.MinDate;

        private double vwapCumPV = 0, vwapCumV = 0, vwap = double.NaN;

        private double ema8 = double.NaN, ema24 = double.NaN;
        private readonly double a8 = 2.0 / (8 + 1.0);
        private readonly double a24 = 2.0 / (24 + 1.0);

        private bool inTrade = false;
        private string playActive = "", sideActive = "", windowTag = "";
        private double entryPrice, stopPrice, t1Price, t2Price;
        private DateTime entryTime;
        private double maeTicks, mfeTicks;

        private DateTime lastBarTime = Core.Globals.MinDate;
        private double lastBarClose = double.NaN;

        private StreamWriter log;

        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "MVP_TwoPlay";
                Calculate = Calculate.OnBarClose;
                EntriesPerDirection = 2;
                EntryHandling = EntryHandling.UniqueEntries;
                IsUnmanaged = false;
                IsInstantiatedOnEachOptimizationIteration = false;
                BarsRequiredToTrade = 50;
            }
            else if (State == State.Configure)
            {
                AddDataSeries(BarsPeriodType.Minute, 1); idx1m = 1;
                AddDataSeries(BarsPeriodType.Minute, 3); idx3m = 2;
                AddDataSeries(BarsPeriodType.Minute, 5); idx5m = 3;
            }
            else if (State == State.DataLoaded)
            {
                sess = new SessionIterator(BarsArray[0]);
                InitLog();
            }
            else if (State == State.Terminated)
            {
                try { log?.Dispose(); } catch { }
            }
        }

        private void InitLog()
        {
            try
            {
                var day = Times[0][0];
                var dir = Path.Combine(Core.Globals.UserDataDir, "StrategyLogs", Name, Instrument.FullName, day.ToString("yyyy-MM"));
                Directory.CreateDirectory(dir);
                var path = Path.Combine(dir, day.ToString("yyyy-MM-dd") + ".csv");
                bool newFile = !File.Exists(path);
                log = new StreamWriter(path, true) { AutoFlush = true };
                if (newFile)
                {
                    log.WriteLine("date,instrument,exec_chart,window,play,side,IB_H,IB_L,M,B2,B4,R2,R4,entry_time,entry_price,stop_price,t1_price,t2_price,exit_time,exit_price,exit_reason,mae_ticks,mfe_ticks,ci_value,vol3m_latched,vwap_align,ema_ok,confidence");
                }
            }
            catch (Exception ex)
            {
                Print("[MVP_TwoPlay] Logger init failed: " + ex.Message);
            }
        }

        private int HMS(DateTime t) => t.Hour * 10000 + t.Minute * 100 + t.Second;

        private bool InWindow(DateTime t)
        {
            int h = HMS(t);
            if (h >= EarlyStart && h <= EarlyEnd) { windowTag = "early"; return true; }
            if (h >= PostStart && h <= PostEnd) { windowTag = "post"; return true; }
            windowTag = "";
            return false;
        }

        private bool NearLevel(double price, double level)
        {
            double band = Instrument.MasterInstrument.TickSize * BandTicks;
            return Math.Abs(price - level) <= band ||
                   (High[0] >= level - band && Low[0] <= level + band);
        }

        private void ResetSession()
        {
            levelsLocked = false;
            ibHigh = double.MinValue; ibLow = double.MaxValue;
            M = R = B2 = B4 = R2 = R4 = B1 = R1 = B3 = R3 = double.NaN;

            vwapCumPV = 0; vwapCumV = 0; vwap = double.NaN;

            trQ.Clear(); hhQ.Clear(); llQ.Clear(); sumTR = 0;

            volSpikeLatched = false; volLatchUntil = Core.Globals.MinDate;

            inTrade = false; playActive = ""; sideActive = "";
        }

        private string F(double x) => double.IsNaN(x) ? "" : x.ToString(CultureInfo.InvariantCulture);

        private double GetCI()
        {
            if (hhQ.Count == 0 || llQ.Count == 0 || sumTR <= 0) return double.NaN;
            double HH = hhQ.Max(), LL = llQ.Min();
            int N = Math.Max(2, CIPeriod);
            if (HH <= LL) return double.NaN;
            return 100.0 * Math.Log10(Math.Max(1e-10, sumTR) / (HH - LL)) / Math.Log10(N);
        }

        private int Confidence(bool vwapOK, bool emaOK, bool ciOK, bool volOK)
        {
            int c = 0;
            if (GateVWAP && vwapOK) c++;
            if (GateEMA && emaOK) c++;
            if (GateCI && ciOK) c++;
            if (GateVol3m && volOK) c++;
            return c;
        }

        private void LogRow(string date, string chart, string window, string play, string side,
                            double ib_h, double ib_l, double m, double b2, double b4, double r2, double r4,
                            string entTime, double entPx, double stp, double t1, double t2,
                            string exitTime, double exitPx, string exitReason,
                            double ciVal, double volLatched, int vwapAlign, int emaOK, int conf,
                            double mae = 0, double mfe = 0)
        {
            try
            {
                log?.WriteLine(string.Join(",",
                    date, Instrument.FullName, chart, window, play, side,
                    F(ib_h), F(ib_l), F(m), F(b2), F(b4), F(r2), F(r4),
                    entTime, F(entPx), F(stp), F(t1), F(t2),
                    exitTime, F(exitPx), exitReason,
                    F(mae), F(mfe),
                    F(ciVal), F(volLatched), vwapAlign, emaOK, conf
                ));
            }
            catch (Exception ex)
            {
                Print("[MVP_TwoPlay] Log error: " + ex.Message);
            }
        }

        protected override void OnBarUpdate()
        {
            if (CurrentBars[0] < BarsRequiredToTrade || CurrentBars.Length < 4) return;

            if (BarsInProgress == 0)
            {
                lastBarTime = Times[0][0];
                lastBarClose = Close[0];
            }

            DateTime day = sess.GetTradingDay(Times[0][0]);
            if (day != curDay)
            {
                curDay = day;
                ResetSession();
            }

            if (BarsInProgress == idx1m)
            {
                var t = Times[idx1m][0];
                double o = Opens[idx1m][0], h = Highs[idx1m][0], l = Lows[idx1m][0], c = Closes[idx1m][0];
                double v = Volumes[idx1m][0];

                double haClosePrev = haClose;
                haClose = (o + h + l + c) / 4.0;
                if (CurrentBars[idx1m] == 0) haOpen = (o + c) / 2.0; else haOpen = (haOpen + haClosePrev) / 2.0;
                double haHigh = Math.Max(h, Math.Max(haOpen, haClose));
                double haLow = Math.Min(l, Math.Min(haOpen, haClose));

                int N = Math.Max(2, CIPeriod);
                double tr = Math.Max(haHigh - haLow, Math.Max(Math.Abs(haHigh - haClosePrev), Math.Abs(haLow - haClosePrev)));
                trQ.Enqueue(tr); sumTR += tr;
                hhQ.Enqueue(haHigh);
                llQ.Enqueue(haLow);
                if (trQ.Count > N) { sumTR -= trQ.Dequeue(); }
                if (hhQ.Count > N) { hhQ.Dequeue(); }
                if (llQ.Count > N) { llQ.Dequeue(); }

                vwapCumPV += ((h + l + c) / 3.0) * v;
                vwapCumV += v;
                vwap = vwapCumV > 0 ? vwapCumPV / vwapCumV : double.NaN;

                ema8 = double.IsNaN(ema8) ? c : ema8 + a8 * (c - ema8);
                ema24 = double.IsNaN(ema24) ? c : ema24 + a24 * (c - ema24);

                int hms = HMS(t);
                if (hms >= 93000 && hms < 103000)
                {
                    ibHigh = Math.Max(ibHigh, h);
                    ibLow = Math.Min(ibLow, l);
                }
                if (!levelsLocked && hms >= 103000)
                {
                    levelsLocked = true;
                    if (ibHigh == double.MinValue || ibLow == double.MaxValue) { ibHigh = h; ibLow = l; }
                    R = Math.Max(Instrument.MasterInstrument.TickSize, ibHigh - ibLow);
                    M = (ibHigh + ibLow) / 2.0;

                    B2 = M + K2 * R; R2 = M - K2 * R;
                    B4 = M + K4 * R; R4 = M - K4 * R;

                    B1 = M + 0.5 * (B2 - M);
                    R1 = M - 0.5 * (M - R2);
                    B3 = B2 + 0.5 * (B4 - B2);
                    R3 = R2 - 0.5 * (R2 - R4);
                }

                if (volSpikeLatched && t >= volLatchUntil) volSpikeLatched = false;

                return;
            }

            if (BarsInProgress == idx3m)
            {
                if (CurrentBars[idx3m] >= 2)
                {
                    double vNow = Volumes[idx3m][0];
                    double vPrev = Volumes[idx3m][1];
                    double ratio = (vPrev > 0 ? vNow / vPrev : 0);
                    if (GateVol3m && ratio >= 1.25)
                    {
                        volSpikeLatched = true;
                        volLatchUntil = Times[idx3m][0].AddMinutes(VolLatchMinutes);
                    }
                }
                return;
            }

            if (BarsInProgress == idx5m) return;

            if (!levelsLocked) return;
            if (!InWindow(Times[0][0])) return;

            bool vwapLong = !GateVWAP || (!double.IsNaN(vwap) && Close[0] >= vwap);
            bool vwapShort = !GateVWAP || (!double.IsNaN(vwap) && Close[0] <= vwap);
            bool emaLong = !GateEMA || (ema8 > ema24);
            bool emaShort = !GateEMA || (ema8 < ema24);

            double ci = GetCI();
            bool ciOK = !GateCI || (!double.IsNaN(ci) && ci <= 60.0);
            bool volOK = !GateVol3m || volSpikeLatched;

            if (inTrade)
            {
                double unreal = (sideActive == "long") ? (Close[0] - entryPrice) : (entryPrice - Close[0]);
                mfeTicks = Math.Max(mfeTicks, unreal / Instrument.MasterInstrument.TickSize);
                double adv = (sideActive == "long") ? (entryPrice - Low[0]) : (High[0] - entryPrice);
                maeTicks = Math.Max(maeTicks, adv / Instrument.MasterInstrument.TickSize);
                return;
            }

            if (EnablePlayA)
            {
                if (vwapLong && emaLong && ciOK && volOK && NearLevel(Close[0], B2))
                {
                    EnterPlay("A", "long", B2, B3, B4, B1);
                    return;
                }
                if (vwapShort && emaShort && ciOK && volOK && NearLevel(Close[0], R2))
                {
                    EnterPlay("A", "short", R2, R3, R4, R1);
                    return;
                }
            }

            if (EnablePlayB)
            {
                double vwapDist = double.IsNaN(vwap) ? double.MaxValue : Math.Abs(Close[0] - vwap);
                bool nearVWAP = vwapDist <= 4 * Instrument.MasterInstrument.TickSize;

                if (nearVWAP && ciOK && NearLevel(Close[0], B2) && Close[0] < M)
                {
                    EnterPlay("B", "short", B2, M, R2, M);
                    return;
                }
                if (nearVWAP && ciOK && NearLevel(Close[0], R2) && Close[0] > M)
                {
                    EnterPlay("B", "long", R2, M, B2, M);
                    return;
                }
            }
        }

        private void EnterPlay(string play, string side, double entryLvl, double t1Lvl, double t2Lvl, double stopRefLvl)
        {
            inTrade = true;
            playActive = play;
            sideActive = side;

            entryPrice = Instrument.MasterInstrument.RoundToTickSize(Close[0]);
            t1Price = Instrument.MasterInstrument.RoundToTickSize(t1Lvl);
            t2Price = Instrument.MasterInstrument.RoundToTickSize(t2Lvl);
            entryTime = Times[0][0];
            maeTicks = mfeTicks = 0;

            double stopPts = 2.0;
            stopPrice = (side == "long")
                ? Instrument.MasterInstrument.RoundToTickSize(stopRefLvl - stopPts)
                : Instrument.MasterInstrument.RoundToTickSize(stopRefLvl + stopPts);

            int q1 = Math.Max(1, Quantity / 2);
            int q2 = Math.Max(1, Quantity - q1);

            if (play == "A")
            {
                if (side == "long")
                {
                    SetStopLoss("A_T1L", CalculationMode.Price, stopPrice, false);
                    SetStopLoss("A_T2L", CalculationMode.Price, stopPrice, false);
                    SetProfitTarget("A_T1L", CalculationMode.Price, t1Price);
                    SetProfitTarget("A_T2L", CalculationMode.Price, t2Price);
                    EnterLong(q1, "A_T1L");
                    EnterLong(q2, "A_T2L");
                }
                else
                {
                    SetStopLoss("A_T1S", CalculationMode.Price, stopPrice, false);
                    SetStopLoss("A_T2S", CalculationMode.Price, stopPrice, false);
                    SetProfitTarget("A_T1S", CalculationMode.Price, t1Price);
                    SetProfitTarget("A_T2S", CalculationMode.Price, t2Price);
                    EnterShort(q1, "A_T1S");
                    EnterShort(q2, "A_T2S");
                }
            }
            else
            {
                if (side == "long")
                {
                    SetStopLoss("B_T1L", CalculationMode.Price, stopPrice, false);
                    SetStopLoss("B_T2L", CalculationMode.Price, stopPrice, false);
                    SetProfitTarget("B_T1L", CalculationMode.Price, t1Price);
                    SetProfitTarget("B_T2L", CalculationMode.Price, t2Price);
                    EnterLong(q1, "B_T1L");
                    EnterLong(q2, "B_T2L");
                }
                else
                {
                    SetStopLoss("B_T1S", CalculationMode.Price, stopPrice, false);
                    SetStopLoss("B_T2S", CalculationMode.Price, stopPrice, false);
                    SetProfitTarget("B_T1S", CalculationMode.Price, t1Price);
                    SetProfitTarget("B_T2S", CalculationMode.Price, t2Price);
                    EnterShort(q1, "B_T1S");
                    EnterShort(q2, "B_T2S");
                }
            }

            bool vwapOK;
            if (GateVWAP && !double.IsNaN(vwap))
            {
                bool above = Close[0] >= vwap;
                bool below = Close[0] <= vwap;
                vwapOK = (side == "long" && above) || (side == "short" && below);
            }
            else
            {
                vwapOK = true;
            }

            bool emaOK;
            if (GateEMA)
            {
                bool trendUp = ema8 > ema24;
                bool trendDown = ema8 < ema24;
                emaOK = (side == "long" && trendUp) || (side == "short" && trendDown);
            }
            else
            {
                emaOK = true;
            }

            double ciVal = GetCI();
            bool ciOK = !GateCI || (!double.IsNaN(ciVal) && ciVal <= 60.0);
            bool volOK = !GateVol3m || volSpikeLatched;

            string playLabel = play == "A" ? "2to4" : "2to2";
            int vwapFlag = vwapOK ? 1 : 0;
            int emaFlag = emaOK ? 1 : 0;
            double volFlag = volOK ? 1.0 : 0.0;
            int conf = Confidence(vwapOK, emaOK, ciOK, volOK);

            LogRow(
                entryTime.ToString("yyyy-MM-dd"),
                BarsPeriod.ToString(),
                windowTag,
                playLabel,
                side,
                ibHigh, ibLow, M, B2, B4, R2, R4,
                entryTime.ToString("HH:mm:ss"), entryPrice, stopPrice, t1Price, t2Price,
                "", double.NaN, "open",
                ciVal, volFlag, vwapFlag, emaFlag, conf
            );
        }

        protected override void OnPositionUpdate(Position position, double averagePrice, int quantity, MarketPosition marketPosition)
        {
            if (position == null || position.Instrument != Instrument) return;

            if (inTrade && marketPosition == MarketPosition.Flat)
            {
                LogRow(
                    entryTime.ToString("yyyy-MM-dd"),
                    BarsPeriod.ToString(),
                    windowTag,
                    playActive == "A" ? "2to4" : "2to2",
                    sideActive,
                    ibHigh, ibLow, M, B2, B4, R2, R4,
                    entryTime.ToString("HH:mm:ss"), entryPrice, stopPrice, t1Price, t2Price,
                    lastBarTime == Core.Globals.MinDate ? "" : lastBarTime.ToString("HH:mm:ss"),
                    double.IsNaN(lastBarClose) ? 0 : lastBarClose,
                    "target_or_stop",
                    GetCI(), volSpikeLatched ? 1.0 : 0.0,
                    0, 0, 0,
                    maeTicks, mfeTicks
                );

                inTrade = false; playActive = ""; sideActive = "";
            }
        }
    }
}

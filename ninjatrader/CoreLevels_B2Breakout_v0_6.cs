#region Using declarations
using System;
using System.IO;
using System.Linq;
using System.Text;
using System.Globalization;
using System.Collections.Generic;
using System.Reflection;

using System.ComponentModel.DataAnnotations;              // [Display]

using NinjaTrader.Cbi;
using NinjaTrader.Data;
using NinjaTrader.Gui.Chart;
using NinjaTrader.NinjaScript;
using NinjaTrader.NinjaScript.Indicators;
#endregion

// ---------------------------------------------------------------------
// CoreLevels_B2Breakout_v0_6  (core field renamed to coreCL to avoid
// method-group collisions; fixed integer series indexes used throughout)
// ---------------------------------------------------------------------
namespace NinjaTrader.NinjaScript.Strategies
{
    public class CoreLevels_B2Breakout_v0_6 : Strategy
    {
        // ===== Inputs =====
        [NinjaScriptProperty, Display(Name="Contracts", Order=0)] public int Contracts { get; set; } = 3;
        [NinjaScriptProperty, Display(Name="Scale1Qty (exit @ B4/R4)", Order=1)] public int Scale1Qty { get; set; } = 2;
        [NinjaScriptProperty, Display(Name="RunnerTrailMode (0=B4Lock,1=Hybrid)", Order=2)] public int RunnerTrailMode { get; set; } = 0;
        [NinjaScriptProperty, Display(Name="LockOn (0=Close,1=Touch)", Order=3)] public int LockOn { get; set; } = 0;
        [NinjaScriptProperty, Display(Name="LockBufTicks", Order=4)] public int LockBufTicks { get; set; } = 2;
        [NinjaScriptProperty, Display(Name="TrailBufTicks", Order=5)] public int TrailBufTicks { get; set; } = 2;
        [NinjaScriptProperty, Display(Name="StopBufTicks", Order=6)] public int StopBufTicks { get; set; } = 4;

        [NinjaScriptProperty, Display(Name="FixedStopTicks", Order=7)] public int FixedStopTicks { get; set; } = 16;
        [NinjaScriptProperty, Display(Name="StopMode (0=Level,1=Fixed,2=ATRx1.5)", Order=8)] public int StopMode { get; set; } = 0;

        [NinjaScriptProperty, Display(Name="UseTimeWindow", Order=9)] public bool UseTimeWindow { get; set; } = true;
        [NinjaScriptProperty, Display(Name="StartTime (HHmm)", Order=10)] public int StartTimeHHmm { get; set; } = 931;
        [NinjaScriptProperty, Display(Name="EndTime (HHmm)", Order=11)] public int EndTimeHHmm { get; set; } = 1200;

        // Filters
        [NinjaScriptProperty, Display(Name="UseVWAPAlign", Order=20)] public bool UseVWAPAlign { get; set; } = true;
        [NinjaScriptProperty, Display(Name="UseCI", Order=21)] public bool UseCI { get; set; } = true;
        [NinjaScriptProperty, Display(Name="CI Threshold", Order=22)] public double CI_Threshold { get; set; } = 60.0;
        [NinjaScriptProperty, Display(Name="UseVolSpike (3m vs prev bar)", Order=23)] public bool UseVolSpike { get; set; } = true;
        [NinjaScriptProperty, Display(Name="VolSpike %", Order=24)] public double VolSpikePct { get; set; } = 150.0;
        [NinjaScriptProperty, Display(Name="UseRVolUD", Order=25)] public bool UseRVolUD { get; set; } = true;
        [NinjaScriptProperty, Display(Name="RVol Min (3m/20SMA)", Order=26)] public double RVolMin { get; set; } = 1.5;
        [NinjaScriptProperty, Display(Name="UD Ratio Min (10 bars)", Order=27)] public double UDMin { get; set; } = 2.0;

        // Manual/locking
        [NinjaScriptProperty, Display(Name="UseManualLevels", Order=30)] public bool UseManualLevels { get; set; } = false;
        [NinjaScriptProperty, Display(Name="ManualLevelString", Order=31)] public string ManualLevelString { get; set; } = "";
        [NinjaScriptProperty, Display(Name="Man_B1", Order=32)] public double Man_B1 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_B2", Order=33)] public double Man_B2 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_B3", Order=34)] public double Man_B3 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_B4", Order=35)] public double Man_B4 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_B5", Order=36)] public double Man_B5 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_R1", Order=37)] public double Man_R1 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_R2", Order=38)] public double Man_R2 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_R3", Order=39)] public double Man_R3 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_R4", Order=40)] public double Man_R4 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_R5", Order=41)] public double Man_R5 { get; set; } = double.NaN;
        [NinjaScriptProperty, Display(Name="Man_POC", Order=42)] public double Man_POC { get; set; } = double.NaN;

        [NinjaScriptProperty, Display(Name="AutoLockAtTimes", Order=43)] public bool AutoLockAtTimes { get; set; } = true;
        [NinjaScriptProperty, Display(Name="LockHMS1 (093100)", Order=44)] public int LockHMS1 { get; set; } = 93100;
        [NinjaScriptProperty, Display(Name="LockHMS2 (103000)", Order=45)] public int LockHMS2 { get; set; } = 103000;
        [NinjaScriptProperty, Display(Name="UseLock2After", Order=46)] public bool UseLock2After { get; set; } = true;
        [NinjaScriptProperty, Display(Name="OneLongPerDay", Order=47)] public bool OneLongPerDay { get; set; } = true;
        [NinjaScriptProperty, Display(Name="OneShortPerDay", Order=48)] public bool OneShortPerDay { get; set; } = true;

        // ===== Internals =====
        private Indicator coreCL;                            // — renamed
        private SessionIterator sess;
        private Dictionary<string,int> pidx;
        private Levels today = new Levels();

        private DateTime lastTradeDate;
        private bool enteredLongToday, enteredShortToday;
        private bool lock1Done, lock2Done;
        private DateTime lastLockedDay = Core.Globals.MinDate;

        private double runnerStop = double.NaN;
        private double entryPriceLong = double.NaN, entryPriceShort = double.NaN;

        private Queue<double> vol3mHist = new Queue<double>();
        private int rvolPeriod = 20, udPeriod = 10;

        // internal session VWAP
        private double sessPV = 0.0, sessVol = 0.0, sessVWAP = double.NaN;

        // fixed series indexes (ints only — no method groups)
        private int CL_IDX1M = -1;
        private int CL_IDX3M = -1;

        private const string SigLongCore = "L_CORE";
        private const string SigLongRun  = "L_RUN";
        private const string SigShortCore= "S_CORE";
        private const string SigShortRun = "S_RUN";

        private double TickV => Instrument.MasterInstrument.TickSize;

        // ===== Lifecycle =====
        protected override void OnStateChange()
        {
            if (State == State.SetDefaults)
            {
                Name = "CoreLevels_B2Breakout_v0_6";
                Calculate = Calculate.OnBarClose;
                IsOverlay = true;
                IsInstantiatedOnEachOptimizationIteration = false;
            }
            else if (State == State.Configure)
            {
                AddDataSeries(BarsPeriodType.Minute, 1); // 1m
                if (!(BarsArray[0].BarsPeriod.BarsPeriodType == BarsPeriodType.Minute &&
                      BarsArray[0].BarsPeriod.Value == 3))
                    AddDataSeries(BarsPeriodType.Minute, 3); // 3m if primary isn’t 3m
            }
            else if (State == State.DataLoaded)
            {
                // resolve index numbers once (plain ints)
                CL_IDX1M = (BarsArray.Length >= 2 ? 1 :
                           (BarsArray[0].BarsPeriod.BarsPeriodType == BarsPeriodType.Minute &&
                            BarsArray[0].BarsPeriod.Value == 1 ? 0 : -1));
                if (BarsArray.Length >= 3) CL_IDX3M = 2;
                else if (BarsArray[0].BarsPeriod.BarsPeriodType == BarsPeriodType.Minute &&
                         BarsArray[0].BarsPeriod.Value == 3) CL_IDX3M = 0;
                else CL_IDX3M = -1;

                sess = new SessionIterator(BarsArray[0]);

                coreCL = FindCoreLevels();
                if (coreCL != null)
                {
                    try
                    {
                        coreCL.SetInput(Closes[0]);
                        AddChartIndicator(coreCL);
                        BuildPlotIndex();
                        Print("[CoreLevels] attached: " + coreCL.GetType().FullName);
                    }
                    catch (Exception ex)
                    {
                        Print("[CoreLevels] indicator attach failed: " + ex.Message);
                        coreCL = null;
                    }
                }
                else
                    Print("[CoreLevels] WARNING: could not auto-detect; UseManualLevels if needed.");
            }
        }

        protected override void OnBarUpdate()
        {
            // 3m aux
            if (BarsInProgress == CL_IDX3M) { UpdateVolume3mStats(); return; }

            if (CurrentBar < 10) return;

            // internal session VWAP
            if (Bars.IsFirstBarOfSession) { sessPV = 0.0; sessVol = 0.0; sessVWAP = Close[0]; }
            double typ = (High[0] + Low[0] + Close[0]) / 3.0;
            double v   = Volume[0];
            sessPV += typ * v;  sessVol += v;
            if (sessVol > 0) sessVWAP = sessPV / sessVol;

            var day = Times[0][0].Date;
            if (day != lastTradeDate)
            {
                enteredLongToday = enteredShortToday = false;
                lock1Done = lock2Done = false;
                lastTradeDate = day;
                today = new Levels();
            }

            if (AutoLockAtTimes && coreCL != null) TryLockLevels();

            if (!today.IsResolved)
            {
                ResolveLevels();
                if (today.IsResolved)
                    Print($"[CoreLevels] {day:yyyy-MM-dd} src={today.Source}  B1={today.B1} B2={today.B2} B3={today.B3} B4={today.B4} B5={today.B5}  R1={today.R1} R2={today.R2} R3={today.R3} R4={today.R4} R5={today.R5}  POC={today.POC}");
            }
            if (!today.IsResolved) return;

            if (UseTimeWindow && !WithinWindow(Times[0][0])) return;

            // manage first
            ManageOpenPositions();
            if (Position.MarketPosition != MarketPosition.Flat) return;

            bool longOK  = !enteredLongToday  && LongFiltersPass();
            bool shortOK = !enteredShortToday && ShortFiltersPass();

            bool crossUpB2   = CrossAbove(Close, today.B2, 1);
            bool crossDownR2 = CrossBelow(Close, today.R2, 1);

            if (longOK  && crossUpB2)   EnterLongBundle(today.B1);
            if (shortOK && crossDownR2) EnterShortBundle(today.R1);
        }

        // ===== Entries =====
        private void EnterLongBundle(double B1)
        {
            int coreQty = Math.Min(Scale1Qty, Contracts);
            int runQty  = Math.Max(0, Contracts - coreQty);
            if (coreQty <= 0) return;

            entryPriceLong = Close[0];

            double stop = entryPriceLong - FixedStopTicks * TickV;
            if (StopMode == 0 && IsFinite(B1))
                stop = Math.Min(entryPriceLong - TickV, B1 - StopBufTicks * TickV);
            else if (StopMode == 2)
                stop = entryPriceLong - 1.5 * ATR(14)[0];

            EnterLong(coreQty, SigLongCore);
            if (runQty > 0) EnterLong(runQty, SigLongRun);

            SetStopLoss(SigLongCore, CalculationMode.Price, stop, false);
            if (runQty > 0) SetStopLoss(SigLongRun, CalculationMode.Price, stop, false);

            if (OneLongPerDay) enteredLongToday = true;
        }

        private void EnterShortBundle(double R1)
        {
            int coreQty = Math.Min(Scale1Qty, Contracts);
            int runQty  = Math.Max(0, Contracts - coreQty);
            if (coreQty <= 0) return;

            entryPriceShort = Close[0];

            double stop = entryPriceShort + FixedStopTicks * TickV;
            if (StopMode == 0 && IsFinite(R1))
                stop = Math.Max(entryPriceShort + TickV, R1 + StopBufTicks * TickV);
            else if (StopMode == 2)
                stop = entryPriceShort + 1.5 * ATR(14)[0];

            EnterShort(coreQty, SigShortCore);
            if (runQty > 0) EnterShort(runQty, SigShortRun);

            SetStopLoss(SigShortCore, CalculationMode.Price, stop, false);
            if (runQty > 0) SetStopLoss(SigShortRun, CalculationMode.Price, stop, false);

            if (OneShortPerDay) enteredShortToday = true;
        }

        // ===== Exits =====
        private void ManageOpenPositions()
        {
            if (Position.MarketPosition == MarketPosition.Long)
            {
                bool lockOnClose = (LockOn == 0);
                if ((lockOnClose && Close[0] >= today.B4 && Close[1] < today.B4) ||
                    (!lockOnClose && High[0]  >= today.B4))
                {
                    ExitLong(SigLongCore);
                    RunnerLockLong();
                }
                TrailRunnerLong();
            }
            else if (Position.MarketPosition == MarketPosition.Short)
            {
                bool lockOnClose = (LockOn == 0);
                if ((lockOnClose && Close[0] <= today.R4 && Close[1] > today.R4) ||
                    (!lockOnClose && Low[0]   <= today.R4))
                {
                    ExitShort(SigShortCore);
                    RunnerLockShort();
                }
                TrailRunnerShort();
            }
        }

        private void RunnerLockLong()
        {
            double stop;
            if (RunnerTrailMode == 0)
                stop = today.B4 - LockBufTicks * TickV;
            else
                stop = Math.Max(Math.Max(GetVWAP() - TrailBufTicks*TickV, today.B3 - StopBufTicks*TickV),
                                entryPriceLong + 4*TickV);

            runnerStop = stop;
            SetStopLoss(SigLongRun, CalculationMode.Price, runnerStop, false);
        }

        private void RunnerLockShort()
        {
            double stop;
            if (RunnerTrailMode == 0)
                stop = today.R4 + LockBufTicks * TickV;
            else
                stop = Math.Min(Math.Min(GetVWAP() + TrailBufTicks*TickV, today.R3 + StopBufTicks*TickV),
                                entryPriceShort - 4*TickV);

            runnerStop = stop;
            SetStopLoss(SigShortRun, CalculationMode.Price, runnerStop, false);
        }

        private void TrailRunnerLong()
        {
            if (double.IsNaN(runnerStop)) return;
            double newStop = runnerStop;
            if (Close[0] > today.B3)
                newStop = Math.Max(runnerStop,
                                   Math.Max(GetVWAP() - TrailBufTicks*TickV, today.B3 - StopBufTicks*TickV));
            if (newStop > runnerStop + 0.0000001)
            {
                runnerStop = newStop;
                SetStopLoss(SigLongRun, CalculationMode.Price, runnerStop, false);
            }
        }

        private void TrailRunnerShort()
        {
            if (double.IsNaN(runnerStop)) return;
            double newStop = runnerStop;
            if (Close[0] < today.R3)
                newStop = Math.Min(runnerStop,
                                   Math.Min(GetVWAP() + TrailBufTicks*TickV, today.R3 + StopBufTicks*TickV));
            if (newStop < runnerStop - 0.0000001)
            {
                runnerStop = newStop;
                SetStopLoss(SigShortRun, CalculationMode.Price, runnerStop, false);
            }
        }

        // ===== Filters =====
        private bool LongFiltersPass()
        {
            if (UseVWAPAlign && !(Close[0] > GetVWAP())) return false;
            if (UseCI && !(ComputeCI_1m(14) < CI_Threshold)) return false;
            if (UseVolSpike && !VolSpike3m()) return false;
            if (UseRVolUD && !(GetRVol3m() >= RVolMin && GetUDRatio3m() >= UDMin)) return false;
            return true;
        }

        private bool ShortFiltersPass()
        {
            if (UseVWAPAlign && !(Close[0] < GetVWAP())) return false;
            if (UseCI && !(ComputeCI_1m(14) < CI_Threshold)) return false;
            if (UseVolSpike && !VolSpike3m()) return false;
            if (UseRVolUD && !(GetRVol3m() >= RVolMin && GetUDRatio3m() >= UDMin)) return false;
            return true;
        }

        private bool VolSpike3m()
        {
            int idx = CL_IDX3M;
            if (idx < 0 || CurrentBars[idx] < 1) return false;
            double v0 = (double)Volumes[idx][0];
            double v1 = (double)Volumes[idx][1];
            if (v1 <= 0) return false;
            return (100.0 * v0 / v1) >= VolSpikePct;
        }

        private double GetRVol3m()
        {
            int idx = CL_IDX3M;
            if (idx < 0 || vol3mHist.Count < rvolPeriod) return 0.0;
            double sma = vol3mHist.Average();
            if (sma <= 0.0) return 0.0;
            double v0 = (double)Volumes[idx][0];
            return v0 / sma;
        }

        private double GetUDRatio3m()
        {
            int idx = CL_IDX3M;
            if (idx < 0 || CurrentBars[idx] < udPeriod) return 0.0;
            double up = 0, dn = 0;
            for (int i=0;i<udPeriod && CurrentBars[idx]-i>=0;i++)
            {
                double o = Opens[idx][i], c = Closes[idx][i];
                double vv = (double)Volumes[idx][i];
                if (c >= o) up += vv; else dn += vv;
            }
            if (dn <= 0) return 999.0;
            return up / dn;
        }

        private void UpdateVolume3mStats()
        {
            int idx = CL_IDX3M;
            if (BarsInProgress != idx) return;
            double v0 = (double)Volumes[idx][0];
            vol3mHist.Enqueue(v0);
            while (vol3mHist.Count > rvolPeriod) vol3mHist.Dequeue();
        }

        private double ComputeCI_1m(int period)
        {
            int idx = CL_IDX1M;
            if (idx < 0 || CurrentBars[idx] < period + 1) return 100.0;

            double sumTR = 0.0;
            double hh = double.MinValue, ll = double.MaxValue;

            for (int i=0; i<period && CurrentBars[idx]-i>=0; i++)
            {
                double hi = Highs[idx][i];
                double lo = Lows[idx][i];
                double c1 = Closes[idx][i+1];

                double tr = Math.Max(hi - lo, Math.Max(Math.Abs(hi - c1), Math.Abs(lo - c1)));
                sumTR += tr;

                if (hi > hh) hh = hi;
                if (lo < ll) ll = lo;
            }
            double denom = hh - ll;
            if (denom <= Instrument.MasterInstrument.TickSize) return 100.0;

            double ci = 100.0 * Math.Log10(sumTR / denom) / Math.Log10(period);
            return Math.Max(0.0, Math.Min(100.0, ci));
        }

        private double GetVWAP() => (sessVol > 0 ? sessVWAP : Close[0]);

        // ===== Levels / Locking =====
        private void ResolveLevels()
        {
            if (UseManualLevels)
            {
                var man = ParseManualString(ManualLevelString);
                man.B1 = Use(Man_B1, man.B1); man.B2 = Use(Man_B2, man.B2); man.B3 = Use(Man_B3, man.B3); man.B4 = Use(Man_B4, man.B4); man.B5 = Use(Man_B5, man.B5);
                man.R1 = Use(Man_R1, man.R1); man.R2 = Use(Man_R2, man.R2); man.R3 = Use(Man_R3, man.R3); man.R4 = Use(Man_R4, man.R4); man.R5 = Use(Man_R5, man.R5);
                man.POC= Use(Man_POC,man.POC);
                if (man.Valid()) { today = man; today.Source="Manual"; today.IsResolved=true; return; }
            }

            if (coreCL != null && pidx != null)
            {
                var live = ReadFromIndicator();
                if (live.Valid()) { today = live; today.Source="IndicatorLive"; today.IsResolved=true; return; }
            }
        }

        private void TryLockLevels()
        {
            DateTime prev = Times[0][1], curr = Times[0][0];
            int prevH = prev.Hour*10000 + prev.Minute*100 + prev.Second;
            int currH = curr.Hour*10000 + curr.Minute*100 + curr.Second;

            if (!lock1Done && prevH < LockHMS1 && currH >= LockHMS1)
            {
                var L = ReadFromIndicator();
                if (L.Valid()) { today = L; today.Source = "Locked0931"; today.IsResolved = true; lastLockedDay = curr.Date; lock1Done = true; }
            }
            if (!lock2Done && prevH < LockHMS2 && currH >= LockHMS2)
            {
                var L = ReadFromIndicator();
                if (L.Valid()) { today = L; today.Source = "Locked1030"; today.IsResolved = true; lastLockedDay = curr.Date; lock2Done = true; }
            }
        }

        private Levels ReadFromIndicator()
        {
            Levels L = new Levels();
            if (coreCL == null || pidx == null) return L;

            L.B1 = ReadPlot("HiMid1");
            L.B2 = ReadPlot("HiMid2");
            L.B3 = ReadPlot("HiMid3");
            double eh = ReadPlot("ExpectedHigh");
            double ex = ReadPlot("ExtendedHigh");
            if (IsFinite(eh)) L.B4 = eh;
            if (IsFinite(ex)) L.B5 = ex;

            L.R1 = ReadPlot("LowMid1");
            L.R2 = ReadPlot("LowMid2");
            L.R3 = ReadPlot("LowMid3");
            double el = ReadPlot("ExpectedLow");
            double exl= ReadPlot("ExtendedLow");
            if (IsFinite(el))  L.R4 = el;
            if (IsFinite(exl)) L.R5 = exl;

            L.POC = ReadPlot("POC");

            if (L.Valid()) L.IsResolved = true;
            return L;
        }

        private double ReadPlot(string name)
{
    if (pidx == null) return double.NaN;
    if (!pidx.TryGetValue(name.ToLowerInvariant(), out int plot)) return double.NaN;

    // Use BarsArray[0].Count (plain int) instead of CurrentBar math,
    // and cap to 2000 bars back.
    int maxBack = Math.Min(2000, BarsArray[0].Count);
    for (int b = 0; b < maxBack; b++)
    {
        double v = coreCL.Values[plot][b];
        if (IsFinite(v)) return v;
    }
    return double.NaN;
}   

private void BuildPlotIndex()
{
    pidx = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);

    // Avoid "i < coreCL.Plots.Count" entirely; enumerate instead.
    int i = 0;
    foreach (var pl in coreCL.Plots)
    {
        string nm = pl?.Name ?? "";
        if (!string.IsNullOrWhiteSpace(nm))
            pidx[nm.ToLowerInvariant()] = i;
        i++;
    }
}

private Indicator FindCoreLevels()
{
    try
    {
        // Get all types safely from all loaded assemblies
        var allTypes =
            AppDomain.CurrentDomain.GetAssemblies()
            .SelectMany(a =>
            {
                try { return a.GetTypes(); }
                catch (ReflectionTypeLoadException ex) { return ex.Types.Where(x => x != null); }
                catch { return Array.Empty<Type>(); }
            });

        foreach (var t in allTypes)
        {
            if (t == null) continue;
            if (!typeof(Indicator).IsAssignableFrom(t)) continue;   // <- correct call
            if (t.IsAbstract) continue;

            // Heuristic: only consider likely BWT Core indicators
            string typeName = t.Name ?? "";
            if (typeName.IndexOf("Core", StringComparison.OrdinalIgnoreCase) < 0 &&
                typeName.IndexOf("BWT",  StringComparison.OrdinalIgnoreCase) < 0)
                continue;

            Indicator inst = null;
            try { inst = Activator.CreateInstance(t) as Indicator; }
            catch { /* skip unconstructible types */ }

            if (inst == null) continue;
            if (inst.Plots == null) continue;

            // Enumerate plots (avoid Count==0; no method-group ambiguity)
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (var pl in inst.Plots)
            {
                string pn = pl?.Name ?? "";
                if (!string.IsNullOrWhiteSpace(pn))
                    names.Add(pn);
            }

            // Signature we expect on Core Levels
            if (names.Contains("POC") && names.Contains("ExpectedHigh") && names.Contains("ExpectedLow"))
                return inst;
        }
    }
    catch { /* swallow and return null */ }

    return null;
}

        // ===== Utilities =====
        private bool WithinWindow(DateTime t)
        {
            int hhmm = t.Hour*100 + t.Minute;
            return hhmm >= StartTimeHHmm && hhmm <= EndTimeHHmm;
        }
        private static bool IsFinite(double v) => !(double.IsNaN(v) || double.IsInfinity(v));
        private double Use(double field, double fallback) => IsFinite(field) ? field : fallback;

        private Levels ParseManualString(string s)
        {
            Levels L = new Levels();
            if (string.IsNullOrWhiteSpace(s)) return L;

            var parts = s.Split(new char[]{',',';'}, StringSplitOptions.RemoveEmptyEntries);
            foreach (var raw in parts)
            {
                var kv = raw.Split(new char[]{'='}, 2);
                if (kv.Length != 2) continue;
                string key = kv[0].Trim().ToUpperInvariant();
                if (!double.TryParse(kv[1].Trim(), NumberStyles.Any, CultureInfo.InvariantCulture, out double val)) continue;

                switch (key)
                {
                    case "B1": L.B1=val; break; case "B2": L.B2=val; break; case "B3": L.B3=val; break;
                    case "B4": L.B4=val; break; case "B5": L.B5=val; break;
                    case "R1": L.R1=val; break; case "R2": L.R2=val; break; case "R3": L.R3=val; break;
                    case "R4": L.R4=val; break; case "R5": L.R5=val; break; case "POC": L.POC=val; break;
                }
            }
            if (L.Valid()) { L.IsResolved = true; L.Source="ManualString"; }
            return L;
        }

        private class Levels
        {
            public double B1=double.NaN,B2=double.NaN,B3=double.NaN,B4=double.NaN,B5=double.NaN;
            public double R1=double.NaN,R2=double.NaN,R3=double.NaN,R4=double.NaN,R5=double.NaN;
            public double POC=double.NaN;
            public bool IsResolved=false;
            public string Source="";

            private static bool Finite(double v) { return !(double.IsNaN(v) || double.IsInfinity(v)); }

            public bool Valid()
            {
                bool upOK = Finite(B1) && Finite(B2) && Finite(B3) && Finite(B4);
                bool dnOK = Finite(R1) && Finite(R2) && Finite(R3) && Finite(R4);
                return upOK || dnOK;
            }
        }
    }
}

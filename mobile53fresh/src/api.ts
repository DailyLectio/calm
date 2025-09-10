// src/api.ts
export type Devotion = {
  date: string;
  quote: string;
  quoteCitation: string;
  firstReading: string;
  psalmSummary: string;
  gospelSummary: string;
  saintReflection: string;
  dailyPrayer: string;
  theologicalSynthesis: string;
  exegesis: string;
  secondReading: string; // empty string on weekdays without a 2nd reading
  tags?: string[];
  usccbLink?: string;
  cycle?: string;
  weekdayCycle?: string;
  feast?: string;
  gospelReference?: string;
  firstReadingRef?: string;
  secondReadingRef?: string;
  psalmRef?: string;
  gospelRef?: string;
  lectionaryKey?: string;
};

const FEED_URL = "https://dailylectio.org/devotions.json";

// Helper: fetch JSON safely
async function getJSON<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} fetching ${url}`);
  }
  return (await res.json()) as T;
}

// Pick the entry whose date matches today's (in your local TZ)
export async function fetchToday(): Promise<Devotion | null> {
  const data = await getJSON<Devotion[]>(FEED_URL);

  // Normalize today as YYYY-MM-DD
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, "0");
  const dd = String(today.getDate()).padStart(2, "0");
  const todayKey = `${yyyy}-${mm}-${dd}`;

  // Find the matching entry (file is an array)
  const hit =
    data.find((d) => String(d.date).trim() === todayKey) ??
    null;

  return hit;
}
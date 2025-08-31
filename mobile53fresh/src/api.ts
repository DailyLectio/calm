import Constants from "expo-constants";
import type { Devotion } from "./types";

const FEED_URL =
  (Constants.expoConfig?.extra as any)?.FEED_URL ??
  "https://dailylectio.org/devotions.json";

export async function fetchToday(): Promise<Devotion | null> {
  const url = `${FEED_URL}?t=${Date.now()}`; // cache-bust
  const res = await fetch(url, { headers: { "Cache-Control": "no-cache" } });
  if (!res.ok) throw new Error(`Feed error ${res.status}`);
  const raw = await res.json();

  // Your endpoint returns an array; take the first item for the day.
  const item = Array.isArray(raw) ? raw[0] : raw;
  return (item ?? null) as Devotion | null;
}
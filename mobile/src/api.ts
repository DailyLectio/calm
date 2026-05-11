import Constants from "expo-constants";
import { DailyFeed } from "./types";

const FEED_URL = Constants.expoConfig?.extra?.FEED_URL as string;

export async function fetchToday(): Promise<DailyFeed> {
  const res = await fetch(FEED_URL, { headers: { "cache-control": "no-cache" } });
  if (!res.ok) throw new Error(`Feed error: ${res.status}`);
  return res.json();
}
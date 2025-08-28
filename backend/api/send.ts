import type { VercelRequest, VercelResponse } from "@vercel/node";
import { kv } from "@vercel/kv";
import { Expo } from "expo-server-sdk";

const expo = new Expo();
const MEM = new Set<string>(); // mirrors register.ts fallback

export default async function handler(_: VercelRequest, res: VercelResponse) {
  try {
    let tokens: string[] = [];
    try {
      const fromKv = await kv.smembers<string[]>("expoTokens");
      if (Array.isArray(fromKv)) tokens = fromKv;
    } catch {
      tokens = Array.from(MEM);
    }

    const messages = tokens
      .filter(t => Expo.isExpoPushToken(t))
      .map(t => ({
        to: t,
        title: "Today’s Lectio Link",
        body: "Tap to read today’s devotions.",
        data: { intent: "open_today" }
      }));

    const chunks = expo.chunkPushNotifications(messages);
    const tickets: any[] = [];
    for (const chunk of chunks) {
      const result = await expo.sendPushNotificationsAsync(chunk);
      tickets.push(...result);
    }
    return res.json({ ok: true, sent: messages.length, tickets });
  } catch (err: any) {
    return res.status(500).json({ error: err?.message || "unexpected error" });
  }
}
import type { VercelRequest, VercelResponse } from "@vercel/node";
import { kv } from "@vercel/kv";

// Fallback for local/dev if KV isn't configured (NOT persistent in production)
const MEM = new Set<string>();

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST") return res.status(405).send("Method not allowed");
  try {
    const { token } = req.body || {};
    if (!token || typeof token !== "string") return res.status(400).json({ error: "missing token" });

    let persisted = false;
    try {
      await kv.sadd("expoTokens", token);
      persisted = true;
    } catch {
      MEM.add(token);
    }
    return res.json({ ok: true, persisted });
  } catch (err: any) {
    return res.status(500).json({ error: err?.message || "unexpected error" });
  }
}
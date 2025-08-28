import type { VercelRequest, VercelResponse } from "@vercel/node";

const MEM = new Set<string>(); // dev fallback only (stateless across invocations)

export default async function handler(req: VercelRequest, res: VercelResponse) {
  if (req.method !== "POST") return res.status(405).send("Method not allowed");

  try {
    // handle both raw string and parsed JSON
    const body = typeof req.body === "string" ? JSON.parse(req.body) : req.body;
    const token = body?.token;
    if (!token || typeof token !== "string") return res.status(400).json({ error: "missing token" });

    let persisted = false;
    try {
      // dynamic import so lack of KV env won’t crash cold start
      const { kv } = await import("@vercel/kv");
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
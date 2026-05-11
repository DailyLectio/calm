import type { VercelRequest, VercelResponse } from "@vercel/node";

export default async function handler(_: VercelRequest, res: VercelResponse) {
  return res.status(200).json({ ok: true, now: Date.now() });
}
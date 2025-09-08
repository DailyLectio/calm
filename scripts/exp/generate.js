// Node 18+ (global fetch)
import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'research';

async function generateMarkdown() {
  console.log('Starting markdown generation…');

  if (!PERPLEXITY_API_KEY) {
    console.error('❌ Missing PERPLEXITY_API_KEY env var.');
    process.exit(1);
  }

  const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  const [y, m, d] = today.split('-');
  const yy = y.slice(-2);
  const mmddyy = `${m}${d}${yy}`; // e.g., 2025-09-08 -> "090825"

  const suggestedSources = [
    { name: "Vatican News", url: "https://www.vaticannews.va" },
    { name: "USCCB", url: "https://bible.usccb.org" },
    { name: "Catholic Online", url: "https://www.catholic.org" },
    { name: "Catholic Culture", url: "https://www.catholicculture.org" },
    { name: "EWTN", url: "https://www.ewtn.com" },
    { name: "Catholic News Agency", url: "https://www.catholicnewsagency.com" },
    { name: "New Advent Catholic Encyclopedia", url: "https://www.newadvent.org" },
    { name: "Catholic Gallery", url: "https://www.catholicgallery.org" },
    { name: "The Lectionary Page", url: "https://www.lectionarypage.net" },
    { name: "Aleteia", url: "https://aleteia.org" }
  ];
  const sourcesComment = suggestedSources.map((s, i) => `${i + 1}. ${s.name} - ${s.url}`).join('\n');

  // Ask for valid YAML frontmatter + placeholders only. No code fences.
  const prompt = `Generate a Catholic daily devotion as Markdown with YAML frontmatter for ${today}.
Rules:
- Do NOT include Markdown code fences.
- Start with YAML frontmatter delimited by '---' lines.
- Use today's date and the USCCB link matching today.
- Use clear headings only; no example citations inside the content body.

---
date: "${today}"
quote: "Short inspirational quote from today's Gospel (max 20 words)"
quoteCitation: "Jn 1:1"        # neutral placeholder
cycle: "Year X"
weekdayCycle: "Cycle Y"
feast: "Ordinary Time"
usccbLink: "https://bible.usccb.org/bible/readings/${mmddyy}.cfm"
gospelReference: "Gospel 10:2-24"     # neutral placeholder
firstReadingRef: "First 1:1-10"       # neutral placeholder
secondReadingRef: null                 # use null if intentionally omitted
psalmRef: "Psalm 1:1-6"               # neutral placeholder
tags: ["Tag1", "Tag2", "Tag3"]
---

<!-- Suggested Sources for Content Reference (non-mandatory):
${sourcesComment}
-->

# First Reading Summary
Provide a 120–180 word reflection on today’s first reading.

# Second Reading Summary
If there is a second reading, provide 60–120 words of reflection; otherwise write "No second reading today."

# Psalm Summary
Provide a 60–120 word reflection on today’s psalm.

# Gospel Summary
Provide a 120–180 word reflection on today’s gospel.

# Saint Reflection
Provide a 120–180 word reflection on today’s saint or feast.

# Daily Prayer
Provide a 3–6 sentence original prayer.

# Theological Synthesis
Provide a 3–6 sentence synthesis connecting all readings and the saint.

# Detailed Scriptural Exegesis
Provide a 700–1000 word scholarly exegesis with historical context.

<!-- END -->`;

  const payload = {
    model: MODEL,
    messages: [{ role: "user", content: prompt }],
    max_tokens: 5000,
    temperature: 0.2,
    // Removed "-reddit.com"
    search_domain_filter: [
      "bible.usccb.org",
      "vaticannews.va",
      "catholicculture.org",
      "catholic.org",
      "ewtn.com",
      "catholicnewsagency.com"
    ],
    search_recency_filter: "week"
  };

  try {
    const res = await fetch('https://api.perplexity.ai/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${PERPLEXITY_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    if (!res.ok) {
      const text = await res.text();
      throw new Error(`HTTP ${res.status}: ${text}`);
    }

    const data = await res.json();
    let markdown = data.choices?.[0]?.message?.content || '';
    markdown = stripCodeFences(markdown);

    // Optional visibility check
    if (!/^\s*---\s*\n/.test(markdown)) {
      console.warn('⚠️ Output did not start with YAML frontmatter. Writing as-is for visibility.');
    }

    await fs.mkdir('public/exp', { recursive: true });
    await fs.writeFile('public/exp/devotion.md', markdown, 'utf8');
    console.log('✅ Wrote public/exp/devotion.md');

    // Always emit JSON
    await emitJson(markdown);
    console.log('✅ Wrote public/exp/devotions.json');

  } catch (error) {
    console.error('❌ Error:', error?.stack || error);
    process.exit(1);
  }
}

// Robustly strip leading/trailing triple-backtick fences, including ```markdown
function stripCodeFences(text) {
  if (!text) return text;
  let t = String(text).replace(/\r\n/g, '\n').trim();
  const fence = '`'.repeat(3);

  // Remove a leading fenced line like ``` or ```markdown
  if (t.startsWith(fence)) {
    const firstNewline = t.indexOf('\n');
    t = firstNewline === -1 ? '' : t.slice(firstNewline + 1);
  }

  // Remove a trailing ``` fence, tolerating trailing spaces/newlines
  const trimmed = t.trimEnd();
  if (trimmed.endsWith(fence)) {
    // Find last occurrence of a line that is exactly ```
    const lastFenceIdx = trimmed.lastIndexOf('\n' + fence);
    if (lastFenceIdx !== -1) {
      t = trimmed.slice(0, lastFenceIdx).trimEnd();
    } else {
      // fence may be at the end with no preceding newline
      t = trimmed.slice(0, trimmed.length - fence.length).trimEnd();
    }
  }

  return t.trim();
}

/**
 * Emit JSON alongside the MD by parsing YAML frontmatter.
 * Uses 'yaml' package if present; otherwise falls back to a minimal parser.
 */
async function emitJson(markdown) {
  const fm = extractFrontmatter(markdown);
  if (!fm) {
    console.warn('⚠️ No frontmatter found; writing minimal devotions.json.');
    await fs.writeFile('public/exp/devotions.json', JSON.stringify({ error: 'no-frontmatter' }, null, 2), 'utf8');
    return;
  }

  // Try dynamic import of yaml; if not present, use fallback
  let parsed;
  try {
    const yaml = await importYamlIfAvailable();
    parsed = yaml ? yaml.parse(fm) : parseYamlFallback(fm);
  } catch {
    parsed = parseYamlFallback(fm);
  }

  const secondMissing =
    parsed.secondReadingRef == null ||
    String(parsed.secondReadingRef).trim().toLowerCase() === 'null' ||
    String(parsed.secondReadingRef).trim().toLowerCase() === 'none';

  const jsonOut = {
    date: parsed.date || '',
    quote: parsed.quote || '',
    quoteCitation: parsed.quoteCitation || '',
    cycle: parsed.cycle || '',
    weekdayCycle: parsed.weekdayCycle || '',
    feast: parsed.feast || 'Ordinary Time',
    usccbLink: parsed.usccbLink || '',
    gospelReference: parsed.gospelReference || '',
    firstReadingRef: parsed.firstReadingRef || '',
    secondReadingRef: secondMissing ? null : parsed.secondReadingRef || '',
    psalmRef: parsed.psalmRef || '',
    tags: Array.isArray(parsed.tags) ? parsed.tags : [],
    // Optional placeholders (ignored if your consumer doesn’t use them)
    sections: {
      firstReadingSummary: 'PLACEHOLDER_120_180_WORDS',
      secondReadingSummary: secondMissing ? 'No second reading today.' : 'PLACEHOLDER_60_120_WORDS',
      psalmSummary: 'PLACEHOLDER_60_120_WORDS',
      gospelSummary: 'PLACEHOLDER_120_180_WORDS',
      saintReflection: 'PLACEHOLDER_120_180_WORDS',
      dailyPrayer: 'PLACEHOLDER_3_6_SENTENCES',
      theologicalSynthesis: 'PLACEHOLDER_3_6_SENTENCES',
      detailedExegesis: 'PLACEHOLDER_700_1000_WORDS'
    }
  };

  await fs.writeFile('public/exp/devotions.json', JSON.stringify(jsonOut, null, 2), 'utf8');
}

function extractFrontmatter(md) {
  if (!md) return null;
  const m = md.match(/^---\s*\n([\s\S]*?)\n---/);
  return m ? m[1] : null;
}

// Try to import 'yaml' if it exists; return null if not
async function importYamlIfAvailable() {
  try {
    // eslint-disable-next-line n/no-unsupported-features/es-syntax
    const mod = await import('yaml');
    return mod && (mod.default || mod);
  } catch {
    return null;
  }
}

/**
 * Minimal YAML fallback parser for the specific schema we expect.
 * Supports:
 *  - simple "key: value" scalars (quoted or unquoted)
 *  - null/None
 *  - tags: [ "a", "b", "c" ]
 */
function parseYamlFallback(str) {
  const out = {};
  const lines = String(str).split('\n');

  // Join multi-line array in brackets onto one line if the model breaks lines
  let buf = [];
  let assembling = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (!assembling && /\btags\s*:\s*\[/.test(line) && !/\]\s*$/.test(line)) {
      assembling = true;
      buf.push(line);
      continue;
    }
    if (assembling) {
      buf[buf.length - 1] += ' ' + line.trim();
      if (/\]\s*$/.test(line)) assembling = false;
      continue;
    }
    buf.push(line);
  }

  for (const raw of buf) {
    const line = raw.trim();
    if (!line || line.startsWith('#')) continue;
    const idx = line.indexOf(':');
    if (idx === -1) continue;
    const key = line.slice(0, idx).trim();
    let val = line.slice(idx + 1).trim();

    // Strip enclosing quotes
    if ((val.startsWith('"') && val.endsWith('"')) || (val.startsWith("'") && val.endsWith("'"))) {
      val = val.slice(1, -1);
    }

    // Null-ish
    if (/^(null|NULL|None|none)$/i.test(val)) {
      out[key] = null;
      continue;
    }

    // Array case for tags
    if (key === 'tags' && /^\[.*\]$/.test(val)) {
      try {
        // Normalize single quotes to double quotes for JSON.parse
        const jsonish = val.replace(/'/g, '"');
        out[key] = JSON.parse(jsonish);
      } catch {
        out[key] = [];
      }
      continue;
    }

    out[key] = val;
  }

  return out;
}

generateMarkdown();

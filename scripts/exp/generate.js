import fs from 'fs/promises';
import yaml from 'yaml'; // npm i yaml

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'research';

async function generateMarkdown() {
  console.log('Starting markdown generation...');

  if (!PERPLEXITY_API_KEY) {
    console.error('❌ Missing PERPLEXITY_API_KEY env var.');
    process.exit(1);
  }

  const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  const [y, m, d] = today.split('-');
  const yy = y.slice(-2);
  const mmddyy = `${m}${d}${yy}`; // e.g., "090825"

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

  // Ask for valid YAML with all fields used downstream. No code fences.
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
    search_domain_filter: [
      "bible.usccb.org",
      "vaticannews.va",
      "catholicculture.org",
      "catholic.org",
      "ewtn.com",
      "catholicnewsagency.com",
      "-reddit.com"
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

    // Optional sanity check: ensure it begins with frontmatter
    if (!/^\s*---\s*\n/.test(markdown)) {
      console.warn('⚠️ Model output did not start with YAML frontmatter. Writing as-is for visibility.');
    }

    await fs.mkdir('public/exp', { recursive: true });
    await fs.writeFile('public/exp/devotion.md', markdown, 'utf8');

    console.log('✅ Complete markdown generated successfully');

    // Optional: parse frontmatter and emit JSON alongside
    // await emitJson(markdown);

  } catch (error) {
    console.error('❌ Error:', error?.stack || error);
    process.exit(1);
  }
}

// Robustly strip leading/trailing triple backtick fences, including ```markdown
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
    // find last occurrence of a line that is exactly ```
    const lastFenceIdx = trimmed.lastIndexOf('\n' + fence);
    if (lastFenceIdx !== -1) {
      t = trimmed.slice(0, lastFenceIdx).trimEnd();
    } else {
      // fence may be at start with no preceding newline
      t = trimmed.slice(0, trimmed.length - fence.length).trimEnd();
    }
  }

  return t.trim();
}

// Optional helper to emit JSON from YAML frontmatter (wire up if needed)
async function emitJson(markdown) {
  try {
    const match = markdown.match(/^---\s*\n([\s\S]*?)\n---/);
    if (!match) return;

    const front = yaml.parse(match[1] || '');
    const secondMissing = front.secondReadingRef == null ||
      String(front.secondReadingRef).trim().toLowerCase() === 'null';

    const jsonOut = {
      date: front.date || '',
      quote: front.quote || '',
      quoteCitation: front.quoteCitation || '',
      cycle: front.cycle || '',
      weekdayCycle: front.weekdayCycle || '',
      feast: front.feast || 'Ordinary Time',
      usccbLink: front.usccbLink || '',
      gospelReference: front.gospelReference || '',
      firstReadingRef: front.firstReadingRef || '',
      secondReadingRef: secondMissing ? null : front.secondReadingRef,
      psalmRef: front.psalmRef || '',
      tags: Array.isArray(front.tags) ? front.tags : []
    };

    await fs.writeFile('public/exp/devotions.json', JSON.stringify(jsonOut, null, 2), 'utf8');
    console.log('📝 Wrote public/exp/devotions.json');
  } catch (e) {
    console.warn('⚠️ Could not emit JSON from frontmatter:', e?.message || e);
  }
}

generateMarkdown();

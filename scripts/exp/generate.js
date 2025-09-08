import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'research';

async function generateMarkdown() {
  console.log('Starting markdown generation...');

  if (!PERPLEXITY_API_KEY) {
    console.error('❌ Missing PERPLEXITY_API_KEY env var.');
    process.exit(1);
  }

  const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  // Build MMDDYY for USCCB link (e.g., 2025-09-08 -> 090825)
  const [y, m, d] = today.split('-');
  const yy = y.slice(-2);
  const mmddyy = `${m}${d}${yy}`;

  // Suggested top 10 Catholic sources (informational only, not mandates)
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
  const sourcesComment = suggestedSources
    .map((s, i) => `${i + 1}. ${s.name} - ${s.url}`)
    .join('\n');

  const prompt = `Generate a Catholic daily devotion as Markdown with YAML frontmatter for ${today}.
Rules:
- Do NOT include Markdown code fences.
- Start with YAML frontmatter delimited by '---' lines.
- Use today's date and the USCCB link matching today.
- Use clear headings only; no example citations inside the content.
---
date: "${today}"
quote: "Short inspirational quote from today's Gospel (max 20 words)"
quoteCitation: "Jn 1:1"
cycle: "Year X"
weekdayCycle: "Cycle Y"
feast: "Ordinary Time"
usccbLink: "https://bible.usccb.org/bible/readings/${mmddyy}.cfm"
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
`;

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

    await fs.mkdir('public/exp', { recursive: true });
    await fs.writeFile('public/exp/devotion.md', markdown, 'utf8');

    console.log('✅ Complete markdown generated successfully');

    // TODO: parse frontmatter and emit public/exp/devotions.json if needed

  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  }
}

function stripCodeFences(text) {
  if (!text) return text;
  let t = text.replace(/\r\n/g, '\n').trim();
  // Remove a single leading code fence line if present
  if (t.startsWith("```
    const idx = t.indexOf('\n');
    if (idx !== -1) t = t.slice(idx + 1);
  }
  // Remove a single trailing code fence line if present
  if (t.endsWith("```")) {
    const idx = t.lastIndexOf('\n');
    if (idx !== -1) t = t.slice(0, idx);
  }
  return t.trim();
}

generateMarkdown();
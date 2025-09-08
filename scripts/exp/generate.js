import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'sonar';

async function generateMarkdown() {
  console.log('Starting markdown generation...');

  if (!PERPLEXITY_API_KEY) {
    console.error('❌ Missing PERPLEXITY_API_KEY env var.');
    process.exit(1);
  }

  const today = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  // Build MMDDYY for USCCB link (e.g., 2025-09-07 -> 090725)
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
- Do NOT include code fences.
- Use valid YAML frontmatter FIRST, starting the file with '---' and ending the block with '---'.
- Use today's date and the USCCB link for today.
- Use placeholder text (no real prose). Keep sections exactly as specified.

---
date: "${today}"
quote: "Short inspirational quote from today's Gospel (max 20 words)"
quoteCitation: "Jn 1:1" # neutral placeholder
cycle: "Year X"
weekdayCycle: "Cycle Y"
feast: "Ordinary Time"
usccbLink: "https://bible.usccb.org/bible/readings/${mmddyy}.cfm"
gospelReference: "Gospel 10:2-24" # neutral placeholder
firstReadingRef: "First 1:1-10" # neutral placeholder
secondReadingRef: null # use null when intentionally omitted
psalmRef: "Psalm 1:1-6" # neutral placeholder
tags: ["Tag1", "Tag2", "Tag3"]
---

<!-- Suggested Sources for Content Reference (non-mandatory):
${sourcesComment}
-->

# First Reading Summary
120-180 words of flowing prose about today's first reading...

# Second Reading Summary
Write 60-120 words about today's second reading only if secondReadingRef is non-null.
If there is no secondReadingRef (no second reading), write exactly: "No second reading today."

# Psalm Summary
60-120 words about how the psalm supports the theme...

# Gospel Summary
120-180 words of flowing prose about today's Gospel...

# Saint Reflection
120-180 words about today's saint/feast explicitly linking to the readings and theme...

# Daily Prayer
3-6 sentences of original prayer encompassing the day's spiritual messages...

# Theological Synthesis
3-6 sentences showing the unifying theme connecting all readings and saint...

# Detailed Scriptural Exegesis
700-1000 words of in-depth, scholarly exegesis with historical context. No HTML formatting.

<!-- END -->`;

  const payload = {
    model: MODEL,
    messages: [{ role: "user", content: prompt }],
    max_tokens: 5000,
    temperature: 0.2,
    search_domain_filter: [
      "vaticannews.va",
      "bible.usccb.org",
      "catholicculture.org",xf
      "catholic.org",
      "ewtn.com",
      "catholicnewsagency.com",
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

    // TODO (optional): parse frontmatter and also emit public/exp/devotions.json

  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  }
}

function stripCodeFences(text) {
  if (!text) return text;
  let t = text.replace(/\r\n/g, '\n').trim();

  if (t.startsWith('```')) {
    const lines = t.split('\n');
    lines.shift(); // remove first line containing opening ```
    t = lines.join('\n');
  }

  if (t.endsWith('```')) {
    const lines = t.split('\n');
    lines.pop(); // remove last line containing closing ```
    t = lines.join('\n');
  }

  return t.trim();
}

generateMarkdown();
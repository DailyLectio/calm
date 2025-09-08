import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'sonar';

async function generateMarkdown() {
  console.log('Starting markdown generation...');

  const today = new Date().toISOString().split('T')[0];
  const mmddyy = today.slice(5).replace(/-/g, ''); // Format MMDDYY for USCCB link

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

  const sourcesComment = suggestedSources.map(
    (s, i) => `${i + 1}. ${s.name} - ${s.url}`
  ).join('\n');

  const prompt = `Generate a complete Catholic daily devotion as structured Markdown with YAML frontmatter for ${today}.

Include the following suggested sources comment at the top but do not treat them as mandatory sources:

<!-- Suggested Sources for Content Reference:
${sourcesComment}
-->

**IMPORTANT:** Use placeholder, neutral example citations for the frontmatter and markdown sections _instead of_ actual scripture or saint references, to avoid accidental reading from real texts during testing.

Format exactly like this using these neutral examples:

---
date: "1939-12-07"
quote: "Short inspirational quote from today's Gospel (max 20 words)"
quoteCitation: "Njg 1:21"
cycle: "Year X"
weekdayCycle: "Cycle Y"
feast: "Memorial of Saint Marlowe"
usccbLink: "https://bible.usccb.org/bible/readings/120739.cfm"
gospelReference: "Tatum 10:2-24"
firstReadingRef: "Tillie 1:1-10"
secondReadingRef: "Donald 7: 2-9"
psalmRef: "Psalm 201:1-8"
tags: ["Tag1", "Tag2", "Tag3"]
---

# First Reading Summary (use firstReadingRef)
120-180 words of flowing prose about today's first reading...

# Second Reading Summary (use secondReadingRef)
Write 60-120 words about today's second reading only if secondReadingRef is non-null.
- If there is a secondReadingRef, provide a thoughtful reflection based on that citation.
- If there is no secondReadingRef (no second reading), write: "No second reading today."

# Psalm Summary (use psalmRef)
60-120 words about how the psalm supports the theme...

# Gospel Summary (use gospelReference)
120-180 words of flowing prose about today's Gospel...

# Saint Reflection (use saintReflection)
120-180 words about today's saint, explicitly linking to the readings and theme...

# Daily Prayer (use dailyPrayer)
3-6 sentences of original prayer encompassing the day's spiritual messages...

# Theological Synthesis (use theologicalSynthesis)
3-6 sentences showing the unifying theme connecting all readings and saint...

# Detailed Scriptural Exegesis (in depth) (use exegesis)
700-1000 words of scholarly exegesis with historical context. No HTML formatting.

After the "Detailed Scriptural Exegesis" section, append the line: <!-- END -->`;

  const payload = {
    model: MODEL,
    messages: [{ role: "user", content: prompt }],
    max_tokens: 5000,
    temperature: 0.2,
    search_domain_filter: ["vaticannews.va", "bible.usccb.org", "catholicculture.org", "catholic.org", "ewtn.com", "catholicnewsagency.com", "-reddit.com"],
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

    // Strip surrounding code fences if present
    markdown = stripCodeFences(markdown);

    await fs.mkdir('public/exp', { recursive: true });
    await fs.writeFile('public/exp/devotion.md', markdown, 'utf8');
    console.log('✅ Complete markdown generated successfully');
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
    lines.shift();
    t = lines.join('\n');
  }
  if (t.endsWith('```
    const lines = t.split('\n');
    lines.pop();
    t = lines.join('\n');
  }
  return t.trim();
}

generateMarkdown();

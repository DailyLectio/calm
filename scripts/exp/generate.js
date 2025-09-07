import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'sonar';

async function generateMarkdown() {
  console.log('Starting markdown generation...');

  const today = new Date().toISOString().split('T')[0];

  const prompt = `Generate a complete Catholic daily devotion as structured Markdown with YAML frontmatter for ${today}.

Format exactly like this:

---
date: "${today}"
quote: "Short inspirational quote from today's Gospel (max 20 words)"
quoteCitation: "Jn 11:25"
cycle: "Year C"
weekdayCycle: "Cycle I"
feast: "Memorial of Saint [Name]" or "Ordinary Time"
usccbLink: "https://bible.usccb.org/bible/readings/MMDDYY.cfm"
gospelReference: "John 11:17-27"
firstReadingRef: "Deuteronomy 4:32-40"
secondReadingRef: null
psalmRef: "Psalm 77:12-13, 14-15, 16, 21"
tags: ["Faith", "Hope", "Resurrection"]
---

# First Reading Summary
120-180 words of flowing prose about today's first reading...

# Psalm Summary
60-120 words about how the psalm supports the theme...

# Gospel Summary
120-180 words of flowing prose about today's Gospel...

# Saint Reflection
120-180 words about today's saint, explicitly linking to the readings and theme...

# Daily Prayer
3-6 sentences of original prayer encompassing the day's spiritual messages...

# Theological Synthesis
3-6 sentences showing the unifying theme connecting all readings and saint...

# Detailed Scriptural Exegesis
700-1000 words of in-depth, scholarly exegesis with historical context. Include line breaks for readability. No HTML formatting.

After the "Detailed Scriptural Exegesis" section, append the line: <!-- END -->`;

  const payload = {
    model: MODEL,
    messages: [{ role: "user", content: prompt }],
    max_tokens: 5000,
    temperature: 0.2,
    search_domain_filter: ["wikipedia.org", "bible.usccb.org", "catholicculture.org", "-reddit.com"],
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
    let markdown = data?.choices?.[0]?.message?.content ?? '';

    // Strip surrounding code fences if the model wrapped the response
    markdown = stripCodeFences(markdown).trim();

    await fs.mkdir('public/exp', { recursive: true });
    await fs.writeFile('public/exp/devotion.md', markdown, 'utf8');
    console.log('✅ Complete markdown generated successfully');
  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  }
}

function stripCodeFences(text) {
  // normalize newlines first
  text = text.replace(/\r\n/g, '\n');
  if (text.startsWith('```')) {
    text = text.replace(/^```[^\n]*\n/, ''); // opening fence + optional language
  }
  if (text.endsWith('```')) {
    text = text.replace(/\n?```$/, ''); // closing fence
  }
  return text;
}

generateMarkdown();
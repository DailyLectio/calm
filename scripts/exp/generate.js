import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'sonar';

async function generateMarkdown() {
  console.log('Starting markdown generation...');

  const today = new Date().toISOString().split('T')[0];

  const prompt = `Generate a complete Catholic daily devotion as structured Markdown with YAML frontmatter for ${today}.

---

# First Reading Summary
120-180 words of flowing prose about today's first reading...

# Second Reading Summary
Write 120-180 words about today's second reading only if secondReadingRef is non-null.
- If there is a secondReadingRef, provide a thoughtful reflection based on that citation.
- If there is no secondReadingRef (no second reading), write: "No second reading today."

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
    search_domain_filter: ["bible.usccb.org", "catholicculture.org", "wikipedia.org", "-reddit.com"],
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
  // Remove leading ```
  if (t.startsWith('```')) {
    const lines = t.split('\n');
    // drop first line
    lines.shift();
    t = lines.join('\n');
  }
  // Remove trailing ```
  if (t.endsWith('```')) {
    const lines = t.split('\n');
    // drop last line
    lines.pop();
    t = lines.join('\n');
  }
  return t.trim();
}

generateMarkdown();
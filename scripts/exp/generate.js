import fs from 'fs/promises';

const PERPLEXITY_API_KEY = process.env.PERPLEXITY_API_KEY;
const MODEL = process.env.MODEL || 'sonar';

async function generateMarkdown() {
  console.log('Starting markdown generation...');
  
  const prompt = `Generate a Catholic daily devotion as structured Markdown with YAML frontmatter.

Format exactly like this:
---
date: "${new Date().toISOString().split('T')[0]}"
quote: "Short quote from Gospel (max 20 words)"
quoteCitation: "Jn 11:25"
---

# First Reading Summary
120-180 words...

# Gospel Summary  
120-180 words...

# Daily Prayer
3-6 sentences...`;

  const payload = {
    model: MODEL,
    messages: [{role: "user", content: prompt}],
    max_tokens: 4000,
    temperature: 0.2
  };

  try {
    const response = await fetch('https://api.perplexity.ai/chat/completions', {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${PERPLEXITY_API_KEY}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(payload)
    });

    const data = await response.json();
    let markdown = data.choices[0].message.content;
    
    // Clean up markdown fences if present
    markdown = markdown.replace(/^``````$/, '');
    
    await fs.writeFile('public/exp/devotion.md', markdown, 'utf8');
    console.log('✅ Markdown generated successfully');
  } catch (error) {
    console.error('❌ Error:', error);
    process.exit(1);
  }
}

generateMarkdown();
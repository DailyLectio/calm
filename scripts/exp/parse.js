import fs from 'fs/promises';
import matter from 'gray-matter';
import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkFrontmatter from 'remark-frontmatter';
import { toString } from 'mdast-util-to-string';

const MD_PATH = 'public/exp/devotion.md';
const OUT_PATH = 'public/exp/devotions.json';

// normalize heading text to a compact key
const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z]/g, '');

// map normalized headings to target section keys
const HEAD_MAP = {
  firstreadingsummary: 'firstReading',
  secondreadingsummary: 'secondReading',
  psalmsummary: 'psalmSummary',
  gospelsummary: 'gospelSummary',
  saintreflection: 'saintReflection',
  dailyprayer: 'dailyPrayer',
  theologicalsynthesis: 'theologicalSynthesis',
  detailedscripturalexegesis: 'exegesis',
};

async function parseMarkdownToJSON() {
  console.log(`Reading markdown from ${MD_PATH}`);
  const md = await fs.readFile(MD_PATH, 'utf8');

  // gray-matter => { content, data }
  const { data, content } = matter(md);

  console.log('Frontmatter keys:', Object.keys(data || {}));
  if (!data?.date) {
    throw new Error('Missing frontmatter.date — check that YAML is valid at the top of devotion.md');
  }

  // Build AST
  const tree = unified()
    .use(remarkParse)
    .use(remarkFrontmatter)
    .parse(content);

  // Collect sections under normalized, mapped keys
  const sections = {};
  let currentKey = 'intro';
  sections[currentKey] = '';

  for (const node of tree.children ?? []) {
    if (node.type === 'heading') {
      const title = toString(node);
      const mapped = HEAD_MAP[norm(title)];
      currentKey = mapped ?? `extra_${norm(title) || 'unknown'}`;
      if (!(currentKey in sections)) sections[currentKey] = '';
    } else {
      const text = toString(node);
      if (text) sections[currentKey] += text + '\n';
    }
  }

  // Trim section text
  for (const k of Object.keys(sections)) {
    sections[k] = sections[k].trim();
  }

  // Ensure tags is an array
  const tags = Array.isArray(data.tags)
    ? data.tags
    : typeof data.tags === 'string'
      ? data.tags.split(',').map(t => t.trim()).filter(Boolean)
      : [];

  // Build output object (fallbacks keep shape stable)
  const devotion = {
    date: data.date,
    quote: data.quote ?? '',
    quoteCitation: data.quoteCitation ?? '',
    firstReading: sections.firstReading || sections.firstreadingsummary || '',
    secondReading: sections.secondReading || sections.secondreadingsummary || null,
    psalmSummary: sections.psalmSummary || sections.psalmsummary || '',
    gospelSummary: sections.gospelSummary || sections.gospelsummary || '',
    saintReflection: sections.saintReflection || sections.saintreflection || '',
    dailyPrayer: sections.dailyPrayer || sections.dailyprayer || '',
    theologicalSynthesis: sections.theologicalSynthesis || sections.theologicalsynthesis || '',
    exegesis: sections.exegesis || sections.detailedscripturalexegesis || '',
    tags,
    usccbLink: data.usccbLink ?? '',
    cycle: data.cycle ?? '',
    weekdayCycle: data.weekdayCycle ?? '',
    feast: data.feast ?? '',
    gospelReference: data.gospelReference ?? '',
    firstReadingRef: data.firstReadingRef ?? '',
    secondReadingRef: data.secondReadingRef ?? null,
    psalmRef: data.psalmRef ?? '',
    lectionaryKey: [data.firstReadingRef, data.psalmRef, data.gospelReference].filter(Boolean).join('|'),
  };

  await fs.mkdir('public/exp', { recursive: true });
  await fs.writeFile(OUT_PATH, JSON.stringify([devotion], null, 2), 'utf8');
  console.log(`✅ Parsed JSON written to ${OUT_PATH}`);
}

parseMarkdownToJSON().catch(err => {
  console.error('❌ Error in parseMarkdownToJSON:', err.stack || err.message);
  process.exit(1);
});
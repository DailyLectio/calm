# How It Works

1. **Content Editors** update `public/weeklyfeed.json` with devotion entries for each day (each entry has a `date` field in `YYYY-MM-DD` format).  
2. **GitHub Actions** runs daily (configured in `.github/workflows/daily-devotion-update.yml`):  
   - Runs the Node.js script `.github/scripts/updateDevotion.js`.  
   - That script reads `weeklyfeed.json`, filters for today’s entry, then overwrites `public/devotions.json`.  
   - Commits and pushes the updated `devotions.json` back to the repo.  
3. **Experimental Pipeline** (optional):  
   - A separate workflow (`.github/workflows/exp-md-workflow.yml`) can run daily to generate a full devotional in Markdown via the Perplexity AI API, parse it into JSON (`public/exp/devotions.json`), and commit it for review.  
   - To enable this, you must add your Perplexity API key as the secret `PERPLEXITY_API_KEY` in the Actions settings.  
4. **Vercel** auto-deploys on every push to the repository, serving the latest `public/devotions.json` (and, if enabled, `public/exp/devotions.json`).  
5. **Framer Front-End** fetches `devotions.json` dynamically and displays today’s devotion content by category (quote, psalm, readings, etc.).  

***

## How to Set Up Locally

- Clone the repo.  
- Install dependencies:  
  ```bash
  npm install
  ```
- Modify `public/weeklyfeed.json` to add or edit weekly devotion data.  
- To test the daily update script:  
  ```bash
  node .github/scripts/updateDevotion.js
  ```
- To test the experimental AI-powered pipeline:  
  1. Set your Perplexity API key in your shell:  
     ```bash
     export PERPLEXITY_API_KEY=your_key_here
     ```
  2. Generate Markdown and parse to JSON:  
     ```bash
     node scripts/exp/generate.js
     node scripts/exp/parse.js
     ```
- Verify that `public/devotions.json` (and, if using the experimental path, `public/exp/devotions.json`) now contains today’s devotion.

***

## GitHub Actions Notes

- Requires a **Personal Access Token (PAT)** stored as the secret `GH_PAT` with `repo` scope to allow workflow pushes.  
- For the experimental workflow, add the secret `PERPLEXITY_API_KEY`.  
- The main workflow (`daily-devotion-update.yml`) and the experimental workflow (`exp-md-workflow.yml`) each run on a daily cron schedule and can be triggered manually from the Actions tab.

***

## Deployment

- Hosted on Vercel, connected directly to this GitHub repository.  
- Any push to `public/devotions.json` (or `public/exp/devotions.json`) triggers a new deployment.  
- To see updates immediately, you may manually trigger the GitHub Actions workflows or push changes to `weeklyfeed.json`.

***

## Troubleshooting & FAQs

- **Daily updates not appearing?** Check the GitHub Actions runs for failures.  
- **401 or API errors in the experimental workflow?** Ensure `PERPLEXITY_API_KEY` is set correctly under Settings → Secrets.  
- **Merge or push errors?** Pull the latest changes, resolve any merge conflicts, then push again.  
- **Date format issues?** Always use `YYYY-MM-DD`, Eastern Time for scheduling.

***

## Contact & Support

For help, open an issue or contact the maintainer.

*This project is maintained by Daily Lectio Media LLC*

Sources

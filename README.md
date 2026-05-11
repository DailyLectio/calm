
---

## How It Works

1. **Content Editors** update `public/weeklyfeed.json` with devotion entries for each day (each entry has a `date` field in `YYYY-MM-DD` format).

2. **GitHub Actions** runs daily (configured in `.github/workflows/daily-devotion-update.yml`):
   - Runs the Node.js script `.github/scripts/updateDevotion.js`.
   - Script reads `weeklyfeed.json`, filters out today's devotion, and overwrites `devotions.json`.
   - Commits and pushes this updated file back to the repository.

3. **Vercel** auto-deploys on repo changes, serving the latest daily devotions JSON.

4. **Framer front-end** fetches `devotions.json` dynamically and displays devotion content based on categories (quote, psalm, readings, etc.).

---

## How to Set Up Locally

- Clone this repo.
- Modify `public/weeklyfeed.json` to add/edit weekly devotion data.
- The `.github/workflows/daily-devotion-update.yml` and `.github/scripts/updateDevotion.js` manage daily JSON updates via GitHub Actions.

---

## GitHub Actions Notes

- Requires a **Personal Access Token (PAT)** stored as the secret `GH_PAT` with `repo` scope to allow workflow pushes.
- Workflow runs daily (set by cron) and can be triggered manually from the GitHub Actions tab.

---

## Deployment

- Hosted on [Vercel](https://vercel.com), connected to this GitHub repo.
- Make sure to redeploy manually or push changes to `weeklyfeed.json` to see updates.

---

## Troubleshooting & FAQs

- If daily updates are not refreshing, check the Actions tab for workflow run status.
- Make sure the `GH_PAT` secret is up to date and has sufficient permissions.
- Verify the date format in `weeklyfeed.json` matches `YYYY-MM-DD` (US Eastern timezone used in update script).

---

## Contact & Support

For help, open an issue or contact the maintainer.

---

*This project is maintained by Daily Lectio Media LLC


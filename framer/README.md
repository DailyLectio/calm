# Framer presentation source — Archives repair

`DevotionsArchive.tsx` is the reviewed source for the existing FaithLinks 2.0 Framer code file of the same name. Git changes do not automatically update that separate Framer project. Installation/publishing status must be verified independently.

Status on 2026-08-30: **published with operator approval** to `https://www.lectiolinks.com/archives`, Framer version `3a6227de5`. Backend release `2ce847e51a0760dfb7d73ed33ff3a39851e14968` was fast-forwarded to main and deployed successfully to both existing Vercel projects. Both data domains matched that Git baseline. All three Framer breakpoint instances now use the primary endpoint below, not the pinned Git review URL. Strict Framer typecheck returned no diagnostics; post-publication preview reported no remaining changes, errors or warnings. Live browser checks passed for 347 saved reflections through August 30, historical-date search, full detail, Clear filters, pagination and Refresh. All 82 Python tests passed before release.

### Staging decision

Settings > Versions shows **Staging — UPGRADE** on the current project. Staging remains disabled; no plan or billing change was made. Publishing currently updates production directly. The operator approved this release after reviewing the unpublished draft. A paid staging upgrade requires separate operator approval.

If staging is approved and enabled later: publish the reviewed draft to the Framer staging URL, test it, obtain operator approval, then deploy that exact version to the production custom domain. Verify staging is actually enabled before assuming Publish is safe for preview. See [Framer staging and versions](https://www.framer.com/help/articles/staging-and-versions/).

Framer staging isolates presentation changes only. The component's external production JSON still changes with the daily Git/Vercel workflow. Use a pinned public review index for draft data tests, and switch back to the primary endpoint before production release. Monthly saints remain manual: Codex prepares, operator reviews, Codex commits/pushes and verifies data deployment. Routine data changes do not require republishing unchanged Framer code.

## Data contract

- Primary endpoint: `https://www.dailylectio.org/past_reflections/search-v1.json`.
- Schema version 1 contains `revision`, `count`, `latestDate`, and `entries` with date, quote/citation, synthesis, tags, reading references, feast, date-derived cycle labels, snapshot path and SHA-256.
- The source of truth is each saved `public/past_reflections/YYYY/MM/YYYY-MM-DD.json`, not browser storage or the legacy `/archive/index.json`.
- Daily publication preflights all archive sources before writes, then commits the daily feed, snapshot, existing index and search index together through the existing queued Git publisher.
- Manual corrections: update the reviewed dated snapshot, then run `python -m scripts.build_archive_search`; review both changes together. Do not manufacture missing dates.
- `python -m scripts.build_archive_search --check` checks full coverage/content. Publication health compares the deployed index to the same pinned Git commit as the other feeds.

## Framer behavior

One index request makes all history searchable; dated details load on demand. Refresh replaces same-date records. Snapshot content hashes (CRLF normalized to LF for Git portability) prevent silently displaying a mismatched detail version. Search uses local code, with optional one-edit approximate matching, and does not import MiniSearch from a CDN.

Filters: date range, Sunday year A/B/C, weekday I/II, tag. Cycle labels are calculated from the date without changing historic files. I/II denotes Ordinary Time, not a replacement for seasonal/feast propers. Dates and status use Eastern time.

The old `dlx_devotions_archive_v1` browser data is never changed or removed; a download button appears when that personal archive is available. A separate URL-scoped cache can provide a clearly marked stale copy after a failed request. Storage denial is nonfatal.

## Review and release

1. Review and merge the backend/index change using the operator's normal manual process. Check validation and Vercel endpoints before switching the Framer component to this endpoint.
2. Save the original Framer code and page attributes; install the candidate through the Framer code-file API. Use an unpublished draft unless the operator explicitly approves publishing.
3. Retain the page's header/footer, fonts and layout. Set the existing archive instance to fill the content container. Verify Desktop, Tablet and Phone; correct Archives' stale About Us page title if approved.
4. Test a fresh visit, historical date and summary/reference searches, cycles around Advent, Clear filters, Show more, Refresh after correction, full detail, HTTP/network failure, and personal-archive download. Do not clear user browser storage as a test.
5. Obtain operator review, publish Framer, and repeat live browser tests. Git deployment alone is not completion of this release.

Branching was unavailable for the connected Framer project on 2026-08-30. No paid upgrade, duplicate project, branch-protection rule or Vercel project deletion is authorized by this repair.

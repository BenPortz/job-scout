/* Y Combinator "Work at a Startup" DOM extractors.
 *
 * Run verbatim by the FIND stage through a real browser session.
 * READ-ONLY: reads the DOM only, never fetches, submits, or navigates.
 * See README.md in this directory for why these are pinned to a file.
 *
 * Verified against the live site 2026-08-28.
 *
 * Flow:
 *   1) Navigate to https://www.workatastartup.com/jobs/l/<slug>
 *   2) Run COLLECT; then window.scrollBy(0, 1800) and re-run until the count stops growing.
 *   3) Sort ids descending (highest = most recent); take the top N per topic.
 *   4) Open each /jobs/<id> and run EXTRACT_JD.
 *   5) Merge into the raw file with source:"yc" on each listing.
 *
 * Category slugs (these are path segments, NOT query params):
 *   Engineering  -> /jobs/l/software-engineer
 *   Design       -> /jobs/l/designer
 *   Recruiting   -> /jobs/l/recruiting
 *   Science      -> /jobs/l/science
 *   Product      -> /jobs/l/product-manager
 *   Operations   -> /jobs/l/operations
 *   Sales        -> /jobs/l/sales-manager
 *   Marketing    -> /jobs/l/marketing
 *
 * A `?role=<slug>&remote=true&sortBy=created_at` query string does NOT filter;
 * it silently returns zero results. Use the path form above.
 *
 * Login: not required. Listing pages and full JD bodies (comp, location, skills,
 * description) all render for logged-out visitors. The site's own remote/role
 * filter controls ARE behind login, but remote status is printed on every card,
 * so filter for it in code instead.
 *
 * Remote inventory here is thin. Across the operations and software-engineer
 * categories, roughly 8 of 58 listings mentioned remote at all, and several of
 * those were non-US (India, Canada, California-only). Expect an honest none
 * from YC more often than from a remote-first board.
 *
 * Stage note: every company here is YC-backed, so a seed/early-stage filter is
 * satisfied by construction. Set `stage: {any: true}` for topics sourced from
 * here instead of filtering again.
 */

// ---- COLLECT: run on a /jobs or /jobs/l/<slug> listing page ----
// Returns [{job_id, url, title, company, card_text}] for every job link in the DOM.
//
// The card container is `div[class*="cursor-pointer"]`. This site is styled with
// utility classes, so the usual [class*="card"] / [class*="job"] guesses match
// nothing and silently fall through to the anchor itself, which costs you the
// whole card. The card carries company, batch, location, employment type,
// remote status, and comp, so capturing card_text lets the FILTER stage knock
// out listings before the run spends a page load fetching their JD.
(function () {
  const seen = {};
  const results = [];
  document.querySelectorAll('a[href*="/jobs/"]').forEach(function (a) {
    const m = a.href.match(/\/jobs\/(\d+)/);   // also excludes /jobs/l/<slug> nav links
    if (!m) return;
    const job_id = 'yc_' + m[1];
    if (seen[job_id]) return;
    seen[job_id] = true;
    const card = a.closest('div[class*="cursor-pointer"]') || a;
    const txt = (card.innerText || '').trim();
    results.push({
      job_id: job_id,
      url: a.href.split('?')[0],
      title: a.textContent.trim(),
      company: (txt.split('•')[0] || '').trim(),   // "Hive (S14)" before the bullet
      card_text: txt.slice(0, 600)
    });
  });
  return results;
})()

// ---- EXTRACT_JD: run on a /jobs/<id> detail page ----
// Returns {title, company, jd_text} for one listing.
//
// The wait is load-bearing. This is a client-rendered page: read it immediately
// after navigate and document.body.innerText is an empty string, which would
// hand the filter stage a blank JD and silently drop the listing. Poll until
// content appears instead of trusting the navigate call to mean "rendered".
//
// Written for top-level await. Do NOT wrap the whole thing in an async IIFE:
// the runner serializes the last expression, and an async IIFE returns a
// Promise that serializes to {}. The poll uses top-level await; the extraction
// stays a plain IIFE so its object is the last expression.
//
// const deadline = Date.now() + 5000;
// while (document.body.innerText.length < 500 && Date.now() < deadline) {
//   await new Promise(r => setTimeout(r, 250));
// }
// (() => {
//   const title = ((document.querySelector('h1') || {}).innerText || '').trim()
//     || document.title.split(' at ')[0].trim();
//   const compEl = document.querySelector(
//     'a[href*="/company/"], [class*="company-name"], [class*="companyName"]'
//   );
//   const company = compEl ? compEl.textContent.trim()
//     : (document.title.split(' at ')[1] || '').split(' | ')[0].trim();
//   return {
//     title: title,
//     company: company,
//     jd_text: (document.body.innerText || '').slice(0, 4000)   // bounded on purpose
//   };
// })()

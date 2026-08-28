/* Y Combinator "Work at a Startup" DOM extractors.
 *
 * Run verbatim by the FIND stage through a real logged-in browser session.
 * READ-ONLY: reads the DOM only, never fetches, submits, or navigates.
 * See README.md in this directory for why these are pinned to a file.
 *
 * Flow:
 *   1) Navigate to https://www.workatastartup.com/jobs?role=<role>&remote=true&sortBy=created_at
 *   2) Run COLLECT; then window.scrollBy(0, 1800) and re-run until the count stops growing.
 *   3) Sort ids descending (highest = most recent); take the top N per topic.
 *   4) Open each /jobs/<id> and run EXTRACT_JD.
 *   5) Merge into the raw file with source:"yc" on each listing.
 *
 * Stage note: this board lists only YC-backed companies, so a seed/early-stage
 * filter is satisfied by construction. Set `stage: {any: true}` for topics
 * sourced from here instead of filtering again.
 */

// ---- COLLECT: run on a /jobs listing page ----
// Returns [{job_id, url, title}] for every job link currently in the DOM.
(function () {
  const seen = {};
  const results = [];
  document.querySelectorAll('a[href*="/jobs/"]').forEach(function (a) {
    const m = a.href.match(/\/jobs\/(\d+)/);
    if (!m) return;
    const job_id = 'yc_' + m[1];
    if (seen[job_id]) return;
    seen[job_id] = true;
    // Walk up to the card container for a cleaner title than the anchor text.
    const card = a.closest('[class*="job"], [class*="card"], [class*="listing"], li') || a;
    const titleEl = card.querySelector('h2, h3, [class*="title"], [class*="name"]');
    results.push({
      job_id: job_id,
      url: a.href.split('?')[0],
      title: (titleEl || a).textContent.trim()
    });
  });
  return results;
})()

// ---- EXTRACT_JD: run on a /jobs/<id> detail page ----
// Returns {title, company, jd_text} for one listing.
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

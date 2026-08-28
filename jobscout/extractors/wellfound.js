/* Wellfound DOM extractors.
 *
 * Run verbatim by the FIND stage through a real logged-in browser session.
 * READ-ONLY: reads the DOM only, never fetches, submits, or navigates.
 * See README.md in this directory for why these are pinned to a file.
 *
 * Flow:
 *   1) Navigate to https://wellfound.com/role/r/<slug>
 *   2) Run COLLECT after each window.scrollBy(0, 1800); merge by job_id until
 *      the count stops growing (the list is virtualized, so one pass is partial).
 *   3) For the top N unique ids, open each job URL and run EXTRACT_JD.
 *   4) Merge into the raw file with source:"wellfound" on each listing.
 */

// ---- COLLECT: run on a /role/r/<slug> listing page ----
// Returns [{job_id, url, title}] for every job link currently in the DOM.
[...document.querySelectorAll('a[href*="/jobs/"]')]
  .map(a => ({ href: a.href.split('?')[0], text: a.textContent.trim() }))
  .filter(o => /\/jobs\/\d/.test(o.href) && o.text)
  .map(o => ({
    job_id: 'wf_' + (o.href.match(/\/jobs\/(\d+)/) || [])[1],
    url: o.href,
    title: o.text
  }))

// ---- EXTRACT_JD: run on a /jobs/<id> detail page ----
// Returns {title, company, jd_text} for one listing.
// (() => {
//   const company =
//     ((document.querySelector('a[href*="/company/"]') || {}).textContent || '').trim()
//     || (((document.title.split(' at ')[1]) || '').split(' | ')[0] || '').trim();
//   return {
//     title: ((document.querySelector('h1') || {}).innerText || '').trim(),
//     company: company,
//     jd_text: (document.body.innerText || '').slice(0, 4000)   // bounded on purpose
//   };
// })()

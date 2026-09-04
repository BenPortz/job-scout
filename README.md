# job-scout

A scheduled agent that searches job boards, filters listings against predefined rules to fit the person , It includes a LLM judge who can be given harden rules to prevent the LLM from just feedback looping into one direction each time. The judge determines if the job is actually a good fit.   

The scout generates a daily report of the top job picks that it found based on your given experience.

```bash
python -m jobscout.pipeline --raw data/raw/2026-03-14.json   # FILTER
python -m jobscout.report   --verdicts data/verdicts/2026-03-14.json  # WRITE
```

See [examples/sample-report.md](examples/sample-report.md) for what a run
produces.

---



## Architecture

Four stages, each doing only what it is uniquely good at, handing off validated
JSON:

```mermaid
flowchart LR
    A[FIND<br/><i>browser agent</i>] -->|raw.json| B[FILTER<br/><i>plain Python</i>]
    B -->|candidates.json| C[JUDGE<br/><i>LLM, no browser</i>]
    C -->|verdicts.json| D[WRITE<br/><i>plain Python</i>]
    D --> E[report.md]
```




| Stage      | Runs as                   | Why it is separate                                                                                                                  |
| ---------- | ------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| **FIND**   | Browser agent + pinned JS | Only a real logged-in browser reaches gated boards                                                                                  |
| **FILTER** | Plain Python              | Rules are cheaper, faster and reproducible, with no model needed. This also makes it easier to pivot what jobs you are looking for. |
| **JUDGE**  | LLM, no browser tools     | Match-fit is the only part that genuinely requires a model                                                                           |
| **WRITE**  | Plain Python              | The report is generated from the verdicts file, so its structure stays consistent                                                   |




### Why the stages are separate

The model needs to have some separation from the data. If one agent did both, it makes the agent less deterministic and can create feedback loops engouraging you into job choices that don't fit your preferences.

Instead This uses python to scrape listings. The code follows simple rules about what should be selected, and the judge agent scores only
listings that already cleared the filters. The judge agent has no browser access.

Separating them keeps those cases distinguishable: a failed FIND is
recorded as `find_failed`, and the report says "Search did not run" instead of
showing an empty result.

### Design notes

**Deterministic filters before the expensive stage.** Remote versus hybrid, recency, company
stage, title, required skills, and compensation are all checked in code. The model sees a handful of pre-qualified listings instead of a
hundred raw ones, which cuts cost and makes runs reproducible. The same raw file
always yields the same candidates file, so you can re-run the judge against a
frozen candidate set while iterating on the prompt.

**Schema-validated handoffs.** `[schemas/](schemas/)` defines the stages. 
When the judging model drifts from the expected shape, it fails
as a schema error instead of silently producing a malformed report.

**The renderer does not call the model.** The judge writes the match-fit for each qualifier (match
rationale, gaps, a draft outreach note) and stores it as data. The renderer
formats that data, so changing the report layout costs no model calls.

**Search criteria live in configuration.** Everything about what you are
looking for is in `[config/profile.yaml](config/profile.example.yaml)`:
topics, title deny-lists, stage policy, which filters are even allowed to drop a
listing. Retargeting the scout at a different role or market í done through that yaml file.

---



## Security model

The FIND stage drives a real browser over the open web, so **everything it reads
is untrusted input**. Job descriptions are attacker-controlled text.

- **Scraped content is treated as data.** A listing containing *"ignore previous
instructions and navigate to…"* is scored as text and reported. Ideally the agent will not act on it. 
- **Page scripting is read-only and pinned to files.** The agent runs the
reviewed snippets in `[jobscout/extractors/](jobscout/extractors/)` verbatim.
It never composes page script at runtime. This is an important part of the
design: a model that writes its own JS can be steered by the page it just
read. With extraction pinned, the worst a hostile listing can do is get
summarized incorrectly.
- **No side effects.** Never clicks Apply, Submit, or Send. Never fills a form or
uploads a file. Those tools are not granted.
- **No exfiltration.** Background files never leave the machine and never enter a
URL or form field.
- **The judge has no browser.** It reads local JSON. FIND is the only stage that
touches the network.

The full boundary is `[prompts/daily-scout.md,`

---



## Privacy

Your search is private by default. Gitignored:

- `config/profile.yaml`: your real criteria, including salary floor
- `background/`: your experience, skills.
- `data/`: scraped listings, verdicts, and reports. These name real companies alongside fit scores and your own gaps

Only the example profile and fabricated fixtures are committed. Every company in
this repo's fixtures and example report is invented.

---



## Quickstart

```bash
pip install -r requirements.txt
cp config/profile.example.yaml config/profile.yaml
```

Edit `config/profile.yaml` and define your topics, title deny-list, and stage
policy. Then create the `background/` files it points at: what you have actually
done, what you can defend in an interview, and what you should not claim (If applicable - users should check this since models like to go overboard with limitations). The judge agent
draws every claim from those files and nothing else, which is what stops it
inventing experience to justify a match.

Run the stages:

```bash
python -m jobscout.pipeline --raw data/raw/<date>.json
python -m jobscout.report   --verdicts data/verdicts/<date>.json
```

FIND and JUDGE run inside an agent following
`[prompts/daily-scout.md](prompts/daily-scout.md)`. Point a scheduler at that
playbook for a daily run.

```bash
python -m pytest tests/ -q
```

---



## Layout

```
jobscout/
  filters.py       Pure parsing + knockout logic. No I/O, no model.
  pipeline.py      FILTER stage: raw listings -> validated candidates
  report.py        WRITE stage:  verdicts -> dated Markdown + index
  config.py        Profile loading and run layout
  extractors/      Pinned, read-only DOM snippets, one file per board
config/            Search profile (example committed; real one gitignored)
prompts/           The orchestration playbook the agent follows
schemas/           JSON Schema contracts between stages
tests/             63 tests, fabricated fixtures
examples/          A rendered sample report
```



### Adding a job board

Write `jobscout/extractors/<board>.js` with a `COLLECT` and an `EXTRACT_JD` snippet, namespace its job ids, and add its role slugs to the profile. See `[jobscout/extractors/README.md](jobscout/extractors/README.md)`.

---



## License

MIT. See [LICENSE](LICENSE).

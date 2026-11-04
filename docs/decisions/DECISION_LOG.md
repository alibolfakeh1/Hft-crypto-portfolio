# Decision log

Newest entries go at the bottom of each list. Entries are not rewritten. A changed decision gets a new entry.

## Decided

| ID | Date | Decision | By | Reason and consequence |
|---|---|---|---|---|
| D-02 | 2026-11-04 | The repository is public | Owner | Strategies, documents and, later, positions can be read by anyone. Secrets, data and personal details stay out of git |
| D-07 | 2026-11-04 | Stops and targets are dynamic and designed by the strategy expert | Owner | Each strategy defines its own model. Stops only tighten after entry, as a safety rule. `V0S` remains as a control to measure the value of dynamic management |
| D-09 | 2026-11-04 | The feature knowledge base stays outside this repository | Team | Feature documents refer to IDs and titles and use their own summaries |
| D-10 | 2026-11-04 | Data lives in a data center under `DATA_ROOT`. GitHub holds code and results only | Owner asked for a data center, team set the layout | One day of book data exceeds GitHub's file limit. See `docs/08_DATA_CENTER.md` |
| D-11 | 2026-11-04 | Both historical data and live data are required | Owner | The historical path feeds backtests. The live path feeds paper positions and recording |
| D-12 | 2026-11-04 | Canonical bars are built from trades | Team | Keeps candles and flow windows on the same boundary. Official bars become a reconciliation check |
| D-13 | 2026-11-04 | Routine deletion is a reviewed scheduled job, owned by `data-steward` | Owner asked that an agent be responsible, team set the mechanism | Deletion must run reliably with nobody present. Exceptions go to the agent and then the owner |
| D-14 | 2026-11-04 | Live services run on an always-on server, not on GitHub Actions | Team | The 6-hour job limit, delayed scheduled runs, and GitHub's terms on using Actions as a service |

## Waiting for the owner

| ID | Question | Recommendation | Blocks |
|---|---|---|---|
| D-01 | Which venue defines live paper prices, and later any real execution? | One the owner may lawfully use under its terms. Choose before P8. Research can use public archives until then, and results must be retested on the chosen venue's data | P8 |
| D-03 | Which Telegram channel, and has the owner checked any legal requirement for publishing positions? | Create a private test channel first. Decide on the public channel when P7 is ready. The owner approves the first post | P8 public posts |
| D-04 | Is there an always-on server, and how much disk does it have? | Required for live positions and recording. Start around 4 CPU cores, 8 GB of memory and 500 GB to 1 TB of SSD, and set the quota after one measured day of recording | Live recording, live positions |
| D-08 | Does "live position" mean paper positions on live data? | Assumed yes. Real orders are a separate, later decision | P8 |
| D-06 | Which licence? | None for now. Without a licence, people can read the code but have no right to reuse it. Choose one later if reuse is wanted | Nothing |

## Proposed by the team

| ID | Proposal | Reason | Decider |
|---|---|---|---|
| D-05 | Desktop app as a local web UI in a native window, backed by a read-only Python API | One language for the backend, and the same charts in the app, the tear sheets and the Telegram images | `app-builder`, with `ui-designer` |

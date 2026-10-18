# Research funding source feed

Independent contractor prototype for a research-funding website. Not an official Ohio State service, endorsement, grant application service, or guarantee of eligibility or awards.

## Data provenance
Uses the official anonymous Grants.gov `search2` and `fetchOpportunity` APIs. Discovery covers posted and forecast opportunities whose listings identify public/private higher education or unrestricted eligibility. This is a bounded federal-source catalog, not a complete list of all university, state, foundation, or corporate funding.

- Listing discovery runs every three hours when GitHub executes the schedule.
- At most 100 detailed notices are checked per run, oldest-first after new records. Detail coverage is incremental, not a promise that every notice is checked every three hours.
- The feed contains only notices with retrieved official details. `coverage` exposes pending detail work. Previously retrieved notices absent from a complete scoped listing are flagged; absence is not assumed to prove closure.
- `last_successful_detail_check` is a fetch time, not a promise that the funder has published all current changes. `source_modified_at` is the source's supplied modification date.
- Amounts and deadlines missing from the source remain unknown. Far-future sentinel dates are not displayed as actionable deadlines; official prose such as “Proposals accepted anytime” is retained.
- No invented fit percentage, award recipient, eligibility, or funding amount. No AI calls.
- Network/API failures preserve the last good feed. `health.json` and `runs.json` expose failures and partial coverage. Consumers must label stale data, and applicants must consult the current solicitation.

## Schedule and costs
The GitHub Action uses a standard `ubuntu-latest` hosted runner in a **public** repository, every three hours at minute 17 (`17 */3 * * *`), plus manual dispatch. It is guarded against running in a private repository. Under GitHub's current policy, standard public-repository hosted compute is free. This workflow uses no paid API, AI inference, larger runner, artifact upload, cache, or Packages service. No new paid subscription is configured. Pricing may change; GitHub's terms and usage policies still apply.

Scheduled jobs are best effort, may be delayed/dropped, and GitHub can disable inactive public-repository schedules after 60 days. Check the Actions page and health timestamp. Do not interpret an enabled workflow as proof of successful executions.

Safety limits: one concurrent collector, ten-minute job timeout, at most 200 HTTP attempts, at least one second between calls, bounded retries, stop on HTTP 429. These are conservative implementation caps, not a published Grants.gov rate entitlement. Only public source data is committed; never put application drafts or credentials here.

## Files
- `collector/collect.py`: dependency-free Python collector.
- `data/opportunities.json`: normalized source-backed feed.
- `data/details.json`: public authoritative-detail cache for incremental checks.
- `data/listing.json`: discovery metadata, not verified detail.
- `data/health.json`: latest run outcome.
- `data/runs.json`: latest 24 run summaries.

## Local validation
Run `python3 -m unittest discover -s tests -v`.
Run `python3 collector/collect.py --detail-limit 75` for a bounded first collection.

## References
- https://www.grants.gov/api/common/search2
- https://www.grants.gov/api/common/fetchopportunity
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows

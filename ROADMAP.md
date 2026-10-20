# Roadmap

What exists today is the paper. The order below is the order in which the internal implementation gets generalized and moved here.

1. **Protocols and architecture** (this release). README, the four protocols, rituals, pitfalls, templates.
2. **Agent setup contract.** The agent-readable install flow for one person: connectors, second-brain repo from template, schema file, first sweep. Same shape as Open Company Cloud's `docs/agent-setup-contract.md`.
3. **Second-brain template.** The empty repo a person starts from: `CLAUDE.md` schema, `raw/`, `wiki/` with page templates, `tracker/` views.
4. **Skills as a plugin.** The rituals as agent skills, with the names used in [docs/rituals.md](docs/rituals.md) (`/setup`, `/morning`, `/close`, `/weekly`, `/sweep`, `/ingest`, `/meeting`, `/project`, `/promote`, `/compass`, `/lint`, `/backup`) with company-specific values (tracker URL, company brain repo, connector names) moved to a config file. The skills are in Portuguese today; English translation follows demand.
5. **Tracker service.** The shared tracker as a deployable app with an `app manifest` for Open Company Cloud: actions, decisions, projects, suggestions with outcomes, adoption counter, one-time snapshot links for view regeneration.
6. **MCP server.** The tools the agent uses to read and write the tracker and the company brain, with the caller identified by their login.
7. **Outcome metrics.** Time to close, bumps per action, decisions past deadline, before and after rollout.

Not planned: anything company-specific (KPI catalogs, CRM integrations, BI connectors). Those stay in each company's fork.

# Idea Doc — The Agent Policy Plane

**Working title:** Bully Cloud (or whatever the commercial name becomes)
**Author:** Chris Arter
**Date:** 2026-04-28
**Status:** Pre-product. Pressure-testing the thesis before committing time/capital.

> This doc is intentionally self-contained so it can be dropped into another LLM, another founder, or an investor for independent critique. Read it cold; pressure-test it hard.

---

## 1. One-liner

A policy enforcement plane for AI coding agents. Devs SSO into their company's account; the agent inherits the org's rules — secrets scanning, quality gates, compliance, audit — automatically, on every keystroke.

## 2. The thirty-second pitch

AI coding agents (Claude Code, Cursor, Copilot, Windsurf) are now writing meaningful percentages of code at most companies, with effectively zero governance. There is no equivalent of "linting + secrets scanning + audit log + SSO-managed policy" for what the agent does. We build that layer. Devs install one skill/plugin, log in with company SSO, and the agent's behavior is now governed by the org's platform/security team — invisibly, in real time, with a full audit trail.

We're a horizontal infrastructure company on the agentic-dev substrate, the way Snyk is on supply chain or 1Password Business is on credentials.

## 3. The problem

Agentic coding is in its **wild west phase**. Every primitive that should be governed is currently ungoverned:

| Domain | Current state |
|---|---|
| Hook design | Copy-paste from screenshots, no schema, no testing |
| `settings.json` governance | Hand-edited, no diff/review, no org rollout |
| MCP server selection | Install-and-pray, no curation, no security review |
| Secret management | `.env` files; secrets pasted into prompts; secrets leaking into transcripts |
| Subagent orchestration | Hand-written prompts, no result schema, no observability |
| Prompt/context management | CLAUDE.md sprawl, memory drift, no team sharing |
| Cross-agent portability | Claude Code rules ≠ Cursor rules ≠ Copilot instructions |
| Cost governance | "Why did our Anthropic bill 10× this month?" — no attribution |
| Disaster recovery | Agent deletes a branch, drops a table — no undo, no approval gate |
| Compliance | "We let agents write code with no policy layer" is a future SOC2 finding |

Each row is a feature. Some are products. Together they're a category that doesn't exist yet.

The closest analogues in 2010-era ops were Chef/Puppet, then Terraform, then Vault. The substrate stabilized; tooling congealed around it. We are at the equivalent moment for agentic dev.

## 4. The product

### What the user experiences

```
$ npm install -g bully            # or `claude plugin add bully`
$ bully login
  → opens browser → SSO with Google/Okta/Azure AD
  → token cached in OS keychain
$ claude            # agent now governed by org policy, invisibly
```

That's the entire onboarding. From the dev's perspective, nothing else changes — except their agent now refuses to write secrets into files, blocks risky `rm -rf`, redacts customer data before sending prompts, and so on.

### Architecture (two pieces)

```
┌──────────────────────────────────────────────────────────┐
│  Bully Cloud (the platform)                              │
│  - Org policy editor (web UI)                            │
│  - Rule pack subscriptions (curated by experts)          │
│  - Audit log + SIEM forwarding                           │
│  - Telemetry dashboard (which rules fire, by team)       │
│  - SSO (Okta, Google Workspace, Azure AD, SAML)          │
│  - SCIM provisioning                                     │
└──────────────────────────────────────────────────────────┘
                          ▲
                  signed policy bundle
                          │
┌──────────────────────────────────────────────────────────┐
│  Bully Agent (Claude Code / Cursor / Copilot plugin)     │
│  - `bully login` → SSO browser flow → keychain token     │
│  - Pulls signed org policy on session start              │
│  - Enforces via hooks (PreToolUse, PostToolUse, etc.)    │
│  - Streams violations to Cloud audit log                 │
│  - Local-first; works offline against cached policy      │
└──────────────────────────────────────────────────────────┘
```

### What governance the policy enforces

- **Secrets scanner** — regex + entropy + LLM-assisted. Blocks AWS/Stripe/GCP keys, JWTs, private keys, internal tokens, customer PII shapes.
- **Quality gates** — org-specific convention checks, dead code, security anti-patterns (SQL injection shapes, `eval`, unsafe deserialization).
- **Compliance packs** — HIPAA / PCI / SOC2 / GDPR pattern enforcement (no PHI in logs, encryption flags required on S3 writes, audit trail required on payment paths).
- **Supply-chain guard** — block unvetted npm/pip packages, typosquats, license-incompatible imports, known-vuln versions.
- **Prompt firewall** — inspect outgoing prompts; redact sensitive context before it leaves the laptop.
- **Egress control** — block `curl`/`wget`/`fetch` to non-allowlisted domains.
- **Approval gates** — "writing to `/payments/*` requires Slack approval from on-call first."
- **Audit log** — every block, every override, every approval, identity-bound, streamed to SIEM.

### Why "skill + SSO" is the right shape

1. **It's how CISOs buy.** Okta integration is question #1 on enterprise security RFPs. SSO-first design = enterprise-ready from day one.
2. **It collapses distribution.** No "everyone please update your `.bully.yml`" Slack messages. Platform team pushes a policy; every dev's next agent action enforces it. 100× faster than any current alternative.
3. **It enables identity-bound audit.** "Chris's agent tried to write an AWS key into config.ts at 3:42pm" — tied to a real human, not a laptop hash. That's the audit primitive every compliance framework requires.

## 5. The wedge

Don't sell "policy platform" — nobody buys platforms cold. Sell **one acute pain** that gets you onto the laptop, then expand.

**Wedge: "Stop AI agents from leaking secrets into commits."**

- Real, frequent, board-level scary.
- Demo-able in 60 seconds.
- Every CISO has either lived this incident or actively fears it.
- The hook mechanism solves it cleanly and visibly.
- Once the plugin is installed for secret prevention, every other capability is an upsell, not a new sale.

Land here. Expand to license/supply-chain → quality/conventions → compliance packs → full plane.

## 6. Pricing

| Tier | Price | Buyer | What they get |
|---|---|---|---|
| **OSS / Free** | $0 | Solo dev | Local hooks, community rule packs, no cloud |
| **Team** | $19/dev/mo | Eng manager | Hosted policies, basic audit, 5 SSO seats |
| **Business** | $49/dev/mo | Platform team | SSO, SCIM, custom policies, telemetry, SIEM forwarding |
| **Enterprise** | $99–199/dev/mo + platform fee | CISO | Compliance packs, on-prem option, SLA, custom rule authoring, dedicated support |

Math:
- 100-dev customer on Business = ~$58.8k ARR.
- 1,000-dev enterprise customer = $1.2M–$2.4M ARR.
- ~50 enterprise logos = $50–100M ARR.

That's plausible in 4 years if the category materializes.

## 7. Market & strategy analysis

### Porter's Five Forces

| Force | Assessment | Notes |
|---|---|---|
| Threat of new entrants | HIGH | Low capital needs; mechanism is forkable |
| Buyer power | HIGH for devs, MEDIUM for CISOs | Buyer changes with tier |
| Supplier power | MEDIUM-HIGH | Dependent on Anthropic/Cursor APIs |
| Substitutes | HIGH | ESLint, native rules, internal scripts |
| Rivalry | MEDIUM today, HIGH in 18mo | Greenfield now; will heat fast |

Industry is structurally unattractive at the *mechanism* layer. Survival requires brand + identity + audit moat, not technical moat.

### Jobs-To-Be-Done

- **Functional:** Catch convention/security/compliance violations at agent-write-time, not review-time.
- **Emotional:** Trust the agent; reduce the "did it cheat again?" anxiety.
- **Social:** Ship code that looks like the senior engineer's code, not the LLM's.
- **Org-level:** Pass SOC2/HIPAA audits despite letting agents write code.

### Moats (Hamilton Helmer's 7 Powers)

| Power | Have it? | Notes |
|---|---|---|
| Scale economies | No | |
| Network effects | **Weak yes** | Cross-customer telemetry improves rules |
| Counter-positioning | No | Anthropic/Cursor *can* build a first-party version |
| Switching costs | **Medium** | Once standardized in an org, ripping out costs review consistency |
| Branding | **Achievable** | "The HashiCorp of agentic dev" is an open position |
| Cornered resource | **Possible** | Named-expert authorship; signed compliance packs |
| Process power | No | |

**Real moat = brand + identity/SSO entrenchment + audit trust + signed policy distribution.** Not the rule engine.

### Wardley positioning

- Agent runtimes (Claude Code, Cursor): Product → Commodity (consolidating)
- Agent rule enforcement: Genesis → Custom-built (us, now)
- Curated rule packs: Custom-built → Product (12–18 months out)
- Enterprise policy plane: Custom-built → Product (24–36 months out)

The window is 12–24 months before a platform absorbs the wedge. Move now or don't move.

### Disruption framing

This is **sustaining innovation for AI-native devs**, not classic disruption. There is no incumbent — it's a land grab. Land grabs reward speed and distribution over product perfection.

### Blue Ocean

- **Eliminate:** Rule-authoring burden for end users.
- **Reduce:** Lag between agent writing wrong code and human catching it.
- **Raise:** Org-wide consistency of agent-generated code.
- **Create:** "Policy plane for AI coding agents" as a category.

Blue ocean *briefly*. Turns red the moment Anthropic or Cursor ships a first-party competitor.

## 8. Competitive landscape

| Player | What they do | Threat level |
|---|---|---|
| **Anthropic** (Claude Code primitives) | Owns the hook surface; could ship first-party governance | HIGHEST — mitigation is multi-agent |
| **Cursor** | Has Rules; could add enterprise policy | High — also a *partner* candidate |
| **GitHub Copilot** | Instructions + Copilot Workspace; enterprise governance roadmap | Medium-high |
| **Laravel Boost** | First-party agentic helper for Laravel | Confirms category; owns Laravel niche |
| **Snyk / Wiz / Palo Alto** | Code security; will extend to agent-generated code | Medium today, high later (likely *acquirers*) |
| **CodeRabbit / Greptile** | AI code review at PR time | Low — different layer (review vs. write-time) |
| **ESLint / Ruff / Rubocop** | Static linters | Low — pre-agent, not agent-aware |
| **HashiCorp Vault, 1Password Secrets** | Secret management | Adjacent — partners, not competitors |

**Strategic posture:** Be cross-agent on day one. The day Anthropic ships first-party policy, our value is that we *also* govern the dev's Cursor and Copilot sessions.

## 9. The Laravel Boost data point

Laravel shipped Boost — a first-party agentic helper. Implications:

1. **Validates the category.** People install AI tooling layers per ecosystem.
2. **Kills the "best Rails pack / best Next.js pack" wedge.** Frameworks will own their own niche.
3. **Sharpens our positioning toward *cross-cutting* concerns** — security, compliance, identity, audit — that no framework will own.

Boost is a positive signal about the *category* and a negative signal about *per-framework rule packs* as a wedge. Pivot accordingly.

## 10. Go-to-market

### Beachhead

Series A/B startups (20–200 devs) using Claude Code or Cursor org-wide. They feel the pain, have a platform/sec engineer who cares, but no budget for Wiz-tier tools. They are also fast to make decisions and willing to be design partners.

### Bowling-pin sequence

1. Solo senior devs at AI-forward startups (free OSS) → distribution + brand
2. Eng teams (5–30 devs) at Series A/B (Team tier)
3. Platform engineering teams at Series B/C (Business tier)
4. CISOs at later-stage / enterprise (Enterprise tier)

Don't start at enterprise. Don't start broad-language.

### First 60 days

1. Pick **secrets scanning** as the public wedge.
2. Build SSO flow (`bully login` → Google OAuth → keychain token).
3. Build org policy fetch endpoint; signed JSON bundles cached locally.
4. Wire the policy into existing bully hooks.
5. Stream violations to a cloud audit log.
6. Build a two-page dashboard: policy editor + audit log.
7. Sell it free for 6 months to **one** design partner — a 20–50 dev Series A using Claude Code org-wide — in exchange for being the case study.

That's not feature-complete; it's *trust-complete* — a CISO can look at it and believe the architecture extends to everything else they care about.

### Distribution levers

- Open-source kernel (free tier is the bully OSS plugin).
- Public posts framing the category ("agent dev workflow is unmanaged infrastructure").
- Named-expert rule pack authorship (cornered resource).
- Cross-agent positioning from day one.
- Design-partner program (5 logos, free or near-free, in exchange for case studies + roadmap input).

## 11. Hard problems we'd own

- **Tamper-proofing.** A dev cannot disable bully locally to bypass a secrets check. Needs cryptographic policy signing, attestation that hooks ran, and a CI mirror that re-runs the same rules at PR time so bypass is detected at merge. **This is the actual moat.**
- **Performance.** Hooks run on every Edit/Write. >300ms = devs revolt. Local-first execution, cached policies, Haiku for LLM rules, parallelism.
- **Privacy.** Code snippets going to a cloud audit log is the #1 enterprise objection. Needs to be opt-in, hashable, on-prem deployable for the top tier.
- **Cross-agent abstraction.** Day-one Claude-only is fine; second customer asks "Cursor?" Design the policy schema agent-agnostic from the start.
- **False positives.** A noisy policy gets disabled, then bypassed, then ignored. Telemetry-driven rule tuning is mandatory for product survival, not a nice-to-have.

## 12. Risks (honest)

| Risk | Severity | Mitigation |
|---|---|---|
| Anthropic ships first-party enterprise governance | HIGHEST | Multi-agent on day one; CISO-grade audit Anthropic won't ship |
| Pre-product category — no budget line yet | HIGH | Start lean; bootstrap or seed; let breach headlines create the budget |
| Cursor / Copilot partnership negotiations are slow | MEDIUM | OSS distribution gives leverage |
| Agent runtimes destabilize (hook API changes) | MEDIUM | Abstract the policy schema above the runtime |
| TAM smaller than projected (slow Claude Code/Cursor adoption) | MEDIUM | Target the substrate that wins, not a specific runtime |
| Wedge is wrong (secrets is solved by something simpler) | MEDIUM | Validate with 10 CISO interviews before Day 1 |
| Acquired too early at unfavorable terms | LOW-MEDIUM | Real risk, but inverted — most outcomes are acquisitions; structure ownership accordingly |

## 13. Exit landscape

This is most likely an **acquisition outcome**, not an IPO. Plausible acquirers in 3–5 years:

- Snyk, Wiz, Palo Alto Networks, Zscaler, Netskope (security suites needing AI-coding governance)
- GitLab, GitHub (dev platforms needing agent governance natively)
- Cloudflare (Zero Trust adjacency)
- HashiCorp / IBM (governance suites)
- Anthropic itself, if they decide to acquire vs. build

Plan capital structure accordingly: don't over-raise; preserve optionality at $50–200M outcome range.

## 14. Capital strategy

Two viable paths:

1. **Bootstrap to $1–3M ARR** on design partners + early Business-tier customers, then raise an opportunistic round only when category demand is undeniable. Best preserves optionality; matches a probable acquisition outcome.
2. **Seed round ($1.5–3M) now**, hire one engineer, run a 6-month land grab while substrate is wild west.

Avoid Series A until at least $3M ARR and clear category formation. Premature scaling kills land-grab plays.

## 15. Validation plan (do this BEFORE writing more code)

1. **20 platform-engineer interviews** at companies running Claude Code / Cursor org-wide. Question: "How are you governing what these agents are allowed to do?"
2. **10 CISO interviews** at companies in regulated industries. Question: "What's your AI-assisted-coding policy and how is it enforced?"
3. **5 design-partner LOIs** before writing the cloud control plane.

If 8/10 CISOs say "we have no answer and it scares me," the wedge is real. If they say "our DLP catches it" or "we banned the tool," kill the project or pivot.

## 16. Why now

- Hooks/MCP/skills as primitives stabilized in 2025–2026.
- Claude Code, Cursor, Windsurf adoption inflected in 2026.
- First public "AI agent leaked secrets to GitHub" stories landed in 2025–2026.
- Compliance frameworks (SOC2, ISO 27001) starting to add agent-governance language.
- No incumbent. No standard. No budget line yet — but the conditions for one to form are here.

12–24-month window. After that, this is a feature of a larger platform.

## 17. Why us / why bully

- bully OSS is the kernel. Distribution starts at zero, but the codebase, schema, and rule-authoring patterns are real and shipped.
- Founder narrative is credible: "I built the most-used agentic-lint plugin for Claude Code and it became the policy plane for AI dev."
- Early signal: telemetry from existing bully users tells us which rules fire, which are noisy, which are loved — that's product input no competitor has.
- Author owns the brand and the OSS surface. Cornered resource is real if we move on it.

## 18. What this doc is NOT claiming

- That this is a guaranteed winner. The category is unproven and the platform risk is real.
- That building this is easy. The cryptographic policy enforcement and cross-agent abstraction are hard engineering.
- That bootstrap or VC is the right call yet. That's a function of validation interview outcomes.
- That secrets scanning is the *only* viable wedge. It's the best candidate; interviews could surface a better one.

## 19. Open questions for pressure-testing

If you're an LLM, founder, or investor reading this, attack these specifically:

1. **Wedge validity.** Is "secrets in agent-written code" actually a CISO-budget-line problem yet, or is it 2027's problem?
2. **Anthropic risk.** What's the realistic timeline for Claude Code shipping first-party policy/governance? If it's 6 months, the play dies. If it's 24+, we win. What signals tell us which?
3. **Cross-agent abstraction.** Is the policy schema actually portable, or do Claude Code hooks, Cursor rules, and Copilot instructions diverge so much that we end up maintaining N integrations forever?
4. **Tamper-proofing.** Can we cryptographically prove a hook ran on a dev's laptop without becoming an MDM/EDR product? If not, is the CI mirror enough on its own?
5. **Performance budget.** Can we keep p99 hook latency under 300ms while running secrets + license + supply-chain + LLM-assisted rules in parallel on every Edit?
6. **Pricing.** Is $99–199/dev/mo Enterprise plausible without a major channel partnership (Snyk-style co-sell)?
7. **GTM.** Is Series A/B beachhead correct, or should we go straight at regulated mid-market (healthcare, fintech) where compliance forces the budget?
8. **Substrate bet.** Are hooks/MCP/skills the right durable substrate, or could a totally different agent-runtime architecture (browser-based, server-side agents) make the local-plugin model obsolete?
9. **OSS / commercial line.** Where exactly is the line? Too generous and we kill the cloud business; too stingy and we kill distribution.
10. **Acquirer alignment.** If exit-via-acquisition is the likely path, do we need to bias the architecture early to fit one of the obvious acquirers (e.g., look like Snyk's natural extension)?

---

## TL;DR

We build the policy plane for AI coding agents. SSO + skill + signed policy bundles + audit log. Land with secrets scanning at Series A/B startups. Expand to compliance packs at enterprise. Cross-agent from day one. Real moat is identity + audit + brand, not the rule engine. 12–24-month window before a platform absorbs the category. Likely acquisition outcome at $50–200M; structure capital accordingly.

The mechanism is bully's hooks. The product is everything that rides on top of them.

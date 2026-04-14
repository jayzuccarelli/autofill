# PostHog post-wizard report

The wizard has completed a deep integration of PostHog analytics into `autofill`. Changes were made exclusively to `autofill/agent.py`. The integration adds an anonymous install ID (stored in `.autofill_install_id`) so events are attributed to a stable device-level identity without collecting any PII. A module-level `Posthog` client is initialized lazily on first use, with `atexit.register` ensuring all queued events are flushed before the process exits. Ten events were instrumented across the full user journey — from first-time onboarding through knowledge ingestion, form fill execution, agent quality measurement (corrections), and timeout detection.

| Event | Description | File |
|---|---|---|
| `cli_invoked` | User ran autofill with a form URL — top of the conversion funnel | `autofill/agent.py` |
| `onboarding_started` | First-time setup flow began (missing profile or API key) | `autofill/agent.py` |
| `profile_created` | User completed onboarding and saved their profile to `knowledge/profile.md` | `autofill/agent.py` |
| `api_key_configured` | User saved an LLM provider API key during onboarding | `autofill/agent.py` |
| `knowledge_ingested` | Knowledge files were indexed or re-indexed into the vector store | `autofill/agent.py` |
| `file_attachments_found` | Attachable files (PDF/DOC/DOCX) were discovered in `knowledge/` for upload | `autofill/agent.py` |
| `form_fill_started` | Browser agent began filling the target form | `autofill/agent.py` |
| `form_fill_completed` | Browser agent successfully finished filling the form | `autofill/agent.py` |
| `form_fill_timed_out` | Agent exceeded the configured timeout before finishing | `autofill/agent.py` |
| `corrections_saved` | User manually changed fields the agent filled — indicates agent quality issues | `autofill/agent.py` |

## Next steps

We've built some insights and a dashboard for you to keep an eye on user behavior, based on the events we just instrumented:

- **Dashboard — Analytics basics:** https://us.posthog.com/project/376173/dashboard/1450986
- **Form Fill Conversion Funnel** (funnel: started → completed): https://us.posthog.com/project/376173/insights/KpTF3a3m
- **Onboarding Funnel** (funnel: onboarding started → profile created → API key configured): https://us.posthog.com/project/376173/insights/VEaiCZBU
- **Daily CLI Usage** (trend: `cli_invoked` over time): https://us.posthog.com/project/376173/insights/PR7EICto
- **Form Fill Outcomes** (bar: started vs completed vs timed out): https://us.posthog.com/project/376173/insights/JLmxM1RH
- **Agent Correction Rate** (trend: `corrections_saved` over time): https://us.posthog.com/project/376173/insights/oHkkJu8R

### Agent skill

We've left an agent skill folder in your project. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.

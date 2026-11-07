# Documentation

[Setup and run](../README.md)

The repository README contains installation, configuration, local development and troubleshooting. These guides explain how the system works.

| Guide | Contents |
|---|---|
| [Architecture and execution flow](architecture.md) | Components, task decomposition, conversation state and consent handling |
| [Using the app](usage.md) | Example prompts, prospect tables, CSV exports and drafts |
| [Data and business rules](business-rules.md) | Synthetic data, scoring, transaction timing, eligibility and product suitability |
| [Guardrails and audit logging](guardrails.md) | Authentication, content checks, consent enforcement, rate limits and audit records |
| [Tools and the MCP server](tools.md) | Tool responsibilities, schemas and structured errors |
| [Development and extension](development.md) | Project layout, test coverage and adding tools or providers |
| [Design decisions and limitations](design-decisions.md) | Alternatives considered, trade-offs and production gaps |

## Diagrams

- [Architecture diagram](../diagrams/architecture_diagram.md): service boundaries, data access, model calls and state.
- [Process flow](../diagrams/process_flow.md): the agent loop, permission and draft-validation gates, and follow-ups.
- [Database diagram](../diagrams/database_diagram.md): entities and relationships in `banking_crm_demo`.

Diagrams use Mermaid, which renders directly on GitHub.

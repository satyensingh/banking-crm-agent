# Using the app

[Setup and run](../README.md) · [Documentation index](README.md)

### What you can ask

Click a starter on the welcome screen, or type your own request:

| Try | What happens |
|---|---|
| *Find the top 5 high-value customers likely to convert for a personal loan this month.* | Ranks prospects and shows a table |
| *Find the top 3 personal loan prospects and generate personalized WhatsApp messages.* | Ranks, checks consent, then writes drafts |
| *Show premium personal loan prospects with the highest conversion scores.* | Filters to the premium product |
| *Explain why customers could be excluded or ineligible for a personal loan.* | Explains the eligibility blockers |
| *Why isn't customer 12 eligible?* · *Score customer 42.* · *Which products suit customer 7?* | Single-customer questions |
| *Why is this a good month to contact customer 77?* · *How have customer 25's finances changed recently?* | Transaction insights: trends, life events, timing signals |
| *Show prospects in Pune with income above 80,000.* | Filtered search (city, income, credit score, balance, occupation) |

### What you see

- **Tool steps:** each tool call shows as a collapsible step with its input and output, so you can see exactly where an answer came from.
- **Prospect table:** score, income band, credit score band, balance band, suggested product, *This month* (the timing signals), the reason, and whether WhatsApp is permitted. A **CSV file** of the table is attached.
- **Draft button:** *Draft WhatsApp messages for these prospects* asks the agent to write drafts for the prospects shown.
- **WhatsApp drafts:** shown in copyable blocks, labelled **not sent**. Only customers with confirmed WhatsApp permission get a draft.
- **Errors** appear as a message in the chat, for example a missing API key, a rate limit, or an unreachable model or tool server.

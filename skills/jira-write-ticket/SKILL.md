---
name: jira-write-ticket
description: Create or update Jira tickets with clear, evidence-backed content and the user's requested scope and language.
---

# Write a Jira ticket

Use the language requested by the user. Explain the observed problem or requested work and the intended outcome. Distinguish verified facts from assumptions, and include relevant evidence or links supplied by the user or discovered during the task.

Choose a description that suits the issue type. Add acceptance criteria when they help establish completion, with checks that someone can observe or verify. Do not force every ticket into the same sections.

Use the current Jira metadata for the selected project and issue type to identify required fields and valid values. Ask for a missing value only when it affects the ticket and cannot be inferred from authorized context. Do not invent ownership, dates, estimates, priorities, or commitments.

For an update, read the existing issue and preserve fields and content the user did not ask to change. Make the smallest edit that satisfies the request.

Follow the user's existing authorization. An instruction to create or update a ticket authorizes that action within the requested scope; do not ask for a second confirmation. Drafting a ticket alone does not authorize creating it.

If a create call times out or returns an uncertain result, inspect Jira for the intended ticket before retrying. If its creation state remains uncertain, report that uncertainty instead of risking a duplicate. Report the resulting issue key and link when Jira returns them.

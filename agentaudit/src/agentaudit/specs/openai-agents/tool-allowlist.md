# Spec: OpenAI Agents SDK tool allowlist

Constrain an agent to a reviewed subset of tools. This is most useful
for deployments built from function tools where the tool surface can
expand quickly and silently.

## only-approved-tools: block any tool not on the explicit allowlist

```agentaudit
type = allowlist_tool
severity = high
tools = ["read_file", "search_docs", "submit_ticket"]
```

If a deployment only intends to read local files, search documentation,
and submit support tickets, every other tool call should be treated as
out of policy until reviewed.

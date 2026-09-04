# Local SearXNG Search

This project uses a local SearXNG container as the default no-cost web search
backend for the agent.

## Start

```powershell
docker compose up -d searxng
```

SearXNG will listen on:

```text
http://localhost:8080
```

The agent reads this endpoint from:

```text
SEARXNG_BASE_URL=http://localhost:8080
```

## Verify

```powershell
Invoke-RestMethod -Uri "http://localhost:8080/search?q=LangGraph&format=json" -Headers @{Accept='application/json'}
```

The response should be JSON and include `results`, `answers`, `infoboxes`, or
`suggestions`.

## Stop

```powershell
docker compose stop searxng
```

## Notes

The local container has JSON output enabled in `searxng/settings.yml`.
The default setup is for local development, not for running a public SearXNG
instance on the internet.

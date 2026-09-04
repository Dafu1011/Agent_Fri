# Local Run

Use the project server entrypoint on Windows so async psycopg gets a Selector
event loop before Uvicorn starts:

```powershell
python -m app.server --port 8000 --log-level debug
```

Do not start the app directly with `python -m uvicorn app.main:app` on Windows.
Uvicorn 0.52 defaults to a Proactor event loop in this mode, which async
psycopg cannot use for the LangGraph Postgres checkpointer.

If Windows refuses a port with `Errno 13`, check excluded TCP ranges:

```powershell
netsh interface ipv4 show excludedportrange protocol=tcp
```

Avoid ports inside the listed ranges. On this machine, `8020-8119` is reserved,
so `8088` will fail. Use a port outside that range, for example:

```powershell
python -m app.server --port 8000 --log-level debug
python -m app.server --port 18991 --log-level debug
```

After startup, verify runtime status:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8000/status" | ConvertTo-Json -Depth 6
```

Expected tool names include:

- `get_current_weather`
- `web_search`

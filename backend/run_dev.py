"""Local Windows dev entrypoint.

`python -m uvicorn app.main:app` creates uvicorn's event loop via `asyncio.run()`
*before* it imports the app module (see uvicorn/server.py: `Server.run()` calls
`asyncio.run(self.serve(...))`, and `config.load()` — which imports `app.main` — only
happens inside `serve()`, i.e. after the loop already exists). That means the Windows
event-loop-policy fix in app/db/session.py, however early it runs at *import* time, is
always too late to affect the loop uvicorn is already running on.

The fix has to happen before uvicorn ever calls asyncio.run() at all — i.e. here, in
whatever process launches uvicorn. Not needed in Docker/Linux (this file is Windows-only
tooling); production still runs via `uvicorn app.main:app` per the Dockerfile.
"""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uvicorn  # noqa: E402  (must follow the policy fix above)

if __name__ == "__main__":
    # reload=True would spawn a fresh subprocess per reload that re-hits this same race
    # (each child starts with the default policy again) — kept off for reliability here.
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)

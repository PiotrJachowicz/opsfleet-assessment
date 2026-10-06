# Chat CLI

Interactive client for the chatbot HTTP/SSE API.

```bash
cp .env.example .env
mise run chat-cli-setup
mise run chat
```

Requires the chatbot server (`mise run dev`) to be running.

## Preset users (JWT)

Set `CHAT_USER_PRESET` / `JWT_SECRET` in `.env` (secret must match the service).

| Preset | Brands |
|--------|--------|
| `admin` | all (`*`) |
| `calvin` | Calvin Klein |
| `levis` | Levi's |

In the REPL: `/user calvin`, `/whoami`, `/new`.

Production frontends send the client's identity JWT; the CLI only mints presets.
Allowed brands are read from the JWT `brands` claim in both cases (HLD: no DB
entitlement mapping; see root `readme.md`).

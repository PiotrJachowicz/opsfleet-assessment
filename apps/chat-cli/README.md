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

Production frontends would send the JWT; the CLI only mints presets for the
prototype. Allowed brands are read from the JWT claim (no DB entitlement mapping
in the prototype — see root `readme.md` / HLD for the production model).

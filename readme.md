# Retail Data Analysis Chatbot (prototype)

## Prerequisites

- [mise](https://mise.jdx.dev/)
- uv is installed via mise tools

## Setup and run

```bash
mise install
mise run chatbot-setup
mise run chatbot
```

## Smoke check

```bash
curl http://127.0.0.1:8000/health
curl -N http://127.0.0.1:8000/hello
```

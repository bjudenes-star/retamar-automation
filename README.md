# Retamar Automation

Sistema de automatización para la secretaría del colegio. Gestiona cobros, comunicaciones con familias, procesamiento de documentos bancarios y cumplimiento RGPD.

## Arquitectura

- **n8n** — orquestador de workflows
- **Claude API** — procesamiento de lenguaje natural
- **SQLite** — persistencia local
- **Python** — scripts de procesamiento (Sage, devoluciones, RGPD)

## Estructura

```
db/       — esquema SQLite y migraciones
python/   — scripts de procesamiento
n8n/      — exportaciones de workflows (JSON)
docs/     — documentación
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
sqlite3 retamar.db < db/schema.sql
```

## Tests

```bash
pytest python/
```

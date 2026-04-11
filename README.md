# Retamar Automation

Sistema de automatización para la secretaría del colegio. Gestiona cobros, comunicaciones con familias, procesamiento de documentos bancarios y cumplimiento RGPD.

## Arquitectura

- **n8n** — orquestador de workflows
- **Plantillas de email** — generación de comunicaciones con variables (sin IA)
- **Motor de reglas** — decide automáticamente qué plantilla enviar según el caso
- **SQLite** — persistencia local
- **Python** — scripts de procesamiento (Sage, devoluciones, plantillas, RGPD)

## Estructura

```
db/       — esquema SQLite y migraciones
python/   — scripts de procesamiento
n8n/      — exportaciones de workflows (JSON)
docs/     — documentación
```

## Scripts principales

| Script | Función |
|---|---|
| `sage_processor.py` | Importa facturas de Sage 50 (CSV, SEPA XML, Excel) |
| `detector_devoluciones.py` | Detecta devoluciones bancarias en ficheros Norma 43 |
| `motor_plantillas.py` | Selecciona y rellena plantillas de email según reglas de decisión |
| `renombrador_pdfs.py` | Renombra y organiza justificantes PDF de CaixaBankNow |
| `rgpd.py` | Anonimización/desanonimización de datos personales |

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

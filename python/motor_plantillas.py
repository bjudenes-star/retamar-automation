"""Motor de plantillas de email con reglas de decisión.

Selecciona la plantilla adecuada para cada caso de deuda según reglas
configurables en base de datos, rellena las variables y registra la acción.

Uso:
    from python.motor_plantillas import seleccionar_plantilla, rellenar_plantilla
"""

import json
import logging
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "retamar.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("motor_plantillas")

# Variables disponibles en plantillas
VARIABLES_VALIDAS = {
    "APELLIDO", "IMPORTE", "FECHA_VENCIMIENTO", "CONCEPTO",
    "PLAZO_DIAS", "NOMBRE_HIJO", "CURSO",
}


def seleccionar_plantilla(caso: dict, conn: sqlite3.Connection) -> dict:
    """Evalúa reglas de decisión y devuelve la plantilla que corresponde.

    Args:
        caso: dict con datos del caso de deuda:
            - family_code (str)
            - num_devoluciones (int)
            - importe (float)
            - tiene_beca (bool)
            - nivel_severidad (int)
        conn: conexión SQLite

    Returns:
        dict con:
            - accion: "enviar_auto" | "marcar_revision_humana" | "escalar"
            - plantilla: dict con nombre/asunto/cuerpo (o None si revisión humana)
            - regla: nombre de la regla que matcheó (o None)
    """
    reglas = conn.execute(
        """SELECT r.id, r.nombre, r.condicion_json, r.plantilla_id, r.accion
           FROM reglas_decision r
           WHERE r.activa = 1
           ORDER BY r.prioridad DESC""",
    ).fetchall()

    for regla_id, nombre, condicion_json, plantilla_id, accion in reglas:
        condiciones = json.loads(condicion_json)

        if _evaluar_condiciones(condiciones, caso):
            log.info("Regla '%s' aplica al caso de familia %s",
                     nombre, caso.get("family_code", "?"))

            plantilla = None
            if accion != "marcar_revision_humana":
                row = conn.execute(
                    """SELECT nombre, asunto, cuerpo, categoria
                       FROM plantillas_email
                       WHERE id = ? AND activa = 1""",
                    (plantilla_id,),
                ).fetchone()
                if row:
                    plantilla = {
                        "nombre": row[0],
                        "asunto": row[1],
                        "cuerpo": row[2],
                        "categoria": row[3],
                    }

            return {
                "accion": accion,
                "plantilla": plantilla,
                "regla": nombre,
            }

    # Ninguna regla encaja → revisión humana por defecto
    log.warning("Ninguna regla aplica al caso de familia %s, requiere revisión humana",
                caso.get("family_code", "?"))
    return {
        "accion": "marcar_revision_humana",
        "plantilla": None,
        "regla": None,
    }


def _evaluar_condiciones(condiciones: dict, caso: dict) -> bool:
    """Evalúa si un caso cumple todas las condiciones de una regla.

    Condiciones soportadas:
        - num_devoluciones: exact match
        - num_devoluciones_min: mínimo (>=)
        - num_devoluciones_max: máximo (<=)
        - importe_min: importe mínimo
        - importe_max: importe máximo
        - tiene_beca: boolean
        - nivel_severidad: exact match
        - nivel_severidad_min: mínimo (>=)
    """
    for clave, valor_esperado in condiciones.items():
        if clave == "num_devoluciones":
            if caso.get("num_devoluciones") != valor_esperado:
                return False
        elif clave == "num_devoluciones_min":
            if caso.get("num_devoluciones", 0) < valor_esperado:
                return False
        elif clave == "num_devoluciones_max":
            if caso.get("num_devoluciones", 0) > valor_esperado:
                return False
        elif clave == "importe_min":
            if caso.get("importe", 0) < valor_esperado:
                return False
        elif clave == "importe_max":
            if caso.get("importe", 0) > valor_esperado:
                return False
        elif clave == "tiene_beca":
            if caso.get("tiene_beca", False) != valor_esperado:
                return False
        elif clave == "nivel_severidad":
            if caso.get("nivel_severidad") != valor_esperado:
                return False
        elif clave == "nivel_severidad_min":
            if caso.get("nivel_severidad", 0) < valor_esperado:
                return False
        else:
            log.warning("Condición desconocida ignorada: %s", clave)

    return True


def rellenar_plantilla(plantilla: dict, datos_familia: dict,
                       datos_devolucion: dict) -> dict:
    """Sustituye las variables en asunto y cuerpo de una plantilla.

    Args:
        plantilla: dict con "asunto" y "cuerpo"
        datos_familia: dict con APELLIDO, NOMBRE_HIJO, CURSO, etc.
        datos_devolucion: dict con IMPORTE, FECHA_VENCIMIENTO, CONCEPTO, PLAZO_DIAS

    Returns:
        dict con "asunto" y "cuerpo" con las variables sustituidas.
    """
    variables = {}
    variables.update({k.upper(): str(v) for k, v in datos_familia.items() if v is not None})
    variables.update({k.upper(): str(v) for k, v in datos_devolucion.items() if v is not None})

    asunto = plantilla["asunto"]
    cuerpo = plantilla["cuerpo"]

    for var, valor in variables.items():
        placeholder = "{" + var + "}"
        asunto = asunto.replace(placeholder, valor)
        cuerpo = cuerpo.replace(placeholder, valor)

    return {"asunto": asunto, "cuerpo": cuerpo}


def registrar_accion(caso: dict, plantilla: dict | None, resultado: str,
                     conn: sqlite3.Connection):
    """Guarda en acciones_log la acción tomada.

    Args:
        caso: datos del caso (family_code, importe, etc.)
        plantilla: plantilla usada (o None si revisión humana)
        resultado: "enviar_auto" | "marcar_revision_humana" | "escalar"
        conn: conexión SQLite
    """
    detalle_parts = [f"Resultado: {resultado}"]
    if plantilla:
        detalle_parts.append(f"Plantilla: {plantilla.get('nombre', '?')}")
    detalle_parts.append(f"Importe: {caso.get('importe', 0):.2f}\u20ac")

    conn.execute(
        """INSERT INTO acciones_log (workflow, family_code, accion, detalle, usuario)
           VALUES (?, ?, ?, ?, ?)""",
        (
            "motor_plantillas",
            caso.get("family_code"),
            "seleccion_plantilla",
            " | ".join(detalle_parts),
            "sistema",
        ),
    )
    conn.commit()

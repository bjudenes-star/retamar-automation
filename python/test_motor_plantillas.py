"""Tests unitarios para motor_plantillas."""

import json
import sqlite3
from pathlib import Path

import pytest

from python.motor_plantillas import (
    _evaluar_condiciones,
    registrar_accion,
    rellenar_plantilla,
    seleccionar_plantilla,
)


@pytest.fixture
def db_conn():
    """DB en memoria con esquema, plantillas y reglas de ejemplo."""
    conn = sqlite3.connect(":memory:")
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn.executescript(schema)

    # Plantillas de ejemplo
    conn.executemany(
        """INSERT INTO plantillas_email (id, nombre, asunto, cuerpo, categoria)
           VALUES (?, ?, ?, ?, ?)""",
        [
            (1, "primera_devolucion",
             "Aviso de impago - {CONCEPTO}",
             "Estimado/a {APELLIDO},\n\nLe informamos de que el recibo por importe de "
             "{IMPORTE}\u20ac correspondiente a {CONCEPTO} ha sido devuelto por su entidad "
             "bancaria.\n\nLe rogamos regularice el pago antes del {FECHA_VENCIMIENTO}.\n\n"
             "Un saludo,\nSecretar\u00eda del Colegio",
             "primera_notificacion"),
            (2, "segunda_devolucion",
             "Segundo aviso de impago - {CONCEPTO}",
             "Estimado/a {APELLIDO},\n\nLe recordamos que el recibo de {IMPORTE}\u20ac por "
             "{CONCEPTO} contin\u00faa impagado. Este es el segundo aviso.\n\nTiene un plazo de "
             "{PLAZO_DIAS} d\u00edas para regularizar la situaci\u00f3n.\n\nUn saludo,\n"
             "Secretar\u00eda del Colegio",
             "seguimiento"),
            (3, "escalado",
             "URGENTE: Impago reiterado - {APELLIDO}",
             "Estimado/a {APELLIDO},\n\nLamentamos informarle de que tras m\u00faltiples "
             "devoluciones, su caso ha sido escalado a direcci\u00f3n.\n\nImporte pendiente: "
             "{IMPORTE}\u20ac\nAlumno/a: {NOMBRE_HIJO} ({CURSO})\n\nUn saludo,\n"
             "Secretar\u00eda del Colegio",
             "escalado"),
        ],
    )

    # Reglas de decisi\u00f3n (mayor prioridad = se eval\u00faa primero)
    conn.executemany(
        """INSERT INTO reglas_decision (nombre, condicion_json, plantilla_id, accion, prioridad)
           VALUES (?, ?, ?, ?, ?)""",
        [
            # Prioridad 100: familias con beca siempre revisi\u00f3n humana
            ("beca_revision_humana",
             json.dumps({"tiene_beca": True}),
             1, "marcar_revision_humana", 100),
            # Prioridad 50: 3+ devoluciones → escalar
            ("escalado_reincidente",
             json.dumps({"num_devoluciones_min": 3}),
             3, "escalar", 50),
            # Prioridad 30: segunda devoluci\u00f3n, importe ≤ 500
            ("segunda_devolucion_auto",
             json.dumps({"num_devoluciones": 2, "importe_max": 500}),
             2, "enviar_auto", 30),
            # Prioridad 10: primera devoluci\u00f3n, importe ≤ 500
            ("primera_devolucion_auto",
             json.dumps({"num_devoluciones": 1, "importe_max": 500}),
             1, "enviar_auto", 10),
        ],
    )
    conn.commit()

    yield conn
    conn.close()


class TestEvaluarCondiciones:
    def test_condicion_simple(self):
        assert _evaluar_condiciones(
            {"num_devoluciones": 1},
            {"num_devoluciones": 1},
        ) is True

    def test_condicion_no_cumplida(self):
        assert _evaluar_condiciones(
            {"num_devoluciones": 2},
            {"num_devoluciones": 1},
        ) is False

    def test_rango_importe(self):
        assert _evaluar_condiciones(
            {"importe_min": 100, "importe_max": 500},
            {"importe": 250},
        ) is True

    def test_importe_fuera_rango(self):
        assert _evaluar_condiciones(
            {"importe_max": 500},
            {"importe": 600},
        ) is False

    def test_beca(self):
        assert _evaluar_condiciones(
            {"tiene_beca": True},
            {"tiene_beca": True},
        ) is True

    def test_multiples_condiciones(self):
        assert _evaluar_condiciones(
            {"num_devoluciones": 1, "importe_max": 500, "tiene_beca": False},
            {"num_devoluciones": 1, "importe": 200, "tiene_beca": False},
        ) is True

    def test_severidad_min(self):
        assert _evaluar_condiciones(
            {"nivel_severidad_min": 3},
            {"nivel_severidad": 4},
        ) is True


class TestSeleccionarPlantilla:
    def test_primera_devolucion_importe_bajo(self, db_conn):
        """Primera devolución ≤500€ → envío automático."""
        caso = {
            "family_code": "00012345",
            "num_devoluciones": 1,
            "importe": 150.0,
            "tiene_beca": False,
            "nivel_severidad": 1,
        }
        resultado = seleccionar_plantilla(caso, db_conn)
        assert resultado["accion"] == "enviar_auto"
        assert resultado["plantilla"]["nombre"] == "primera_devolucion"
        assert resultado["regla"] == "primera_devolucion_auto"

    def test_tercera_devolucion_escalar(self, db_conn):
        """3+ devoluciones → escalar."""
        caso = {
            "family_code": "00012345",
            "num_devoluciones": 3,
            "importe": 200.0,
            "tiene_beca": False,
            "nivel_severidad": 3,
        }
        resultado = seleccionar_plantilla(caso, db_conn)
        assert resultado["accion"] == "escalar"
        assert resultado["plantilla"]["nombre"] == "escalado"

    def test_familia_con_beca_revision_humana(self, db_conn):
        """Familia con beca → siempre revisión humana (prioridad máxima)."""
        caso = {
            "family_code": "00067890",
            "num_devoluciones": 1,
            "importe": 100.0,
            "tiene_beca": True,
            "nivel_severidad": 1,
        }
        resultado = seleccionar_plantilla(caso, db_conn)
        assert resultado["accion"] == "marcar_revision_humana"
        assert resultado["plantilla"] is None

    def test_sin_regla_aplicable(self, db_conn):
        """Caso sin regla que encaje → revisión humana por defecto."""
        caso = {
            "family_code": "00099999",
            "num_devoluciones": 1,
            "importe": 9999.0,  # Supera el importe_max de todas las reglas auto
            "tiene_beca": False,
            "nivel_severidad": 1,
        }
        resultado = seleccionar_plantilla(caso, db_conn)
        assert resultado["accion"] == "marcar_revision_humana"
        assert resultado["regla"] is None

    def test_segunda_devolucion_auto(self, db_conn):
        """Segunda devolución ≤500€ → envío automático con segunda plantilla."""
        caso = {
            "family_code": "00012345",
            "num_devoluciones": 2,
            "importe": 300.0,
            "tiene_beca": False,
            "nivel_severidad": 2,
        }
        resultado = seleccionar_plantilla(caso, db_conn)
        assert resultado["accion"] == "enviar_auto"
        assert resultado["plantilla"]["nombre"] == "segunda_devolucion"


class TestRellenarPlantilla:
    def test_rellena_todas_las_variables(self):
        plantilla = {
            "asunto": "Aviso de impago - {CONCEPTO}",
            "cuerpo": (
                "Estimado/a {APELLIDO},\n"
                "Importe: {IMPORTE}\u20ac\n"
                "Vencimiento: {FECHA_VENCIMIENTO}\n"
                "Alumno: {NOMBRE_HIJO} ({CURSO})"
            ),
        }
        datos_familia = {
            "APELLIDO": "Garc\u00eda L\u00f3pez",
            "NOMBRE_HIJO": "Pablo",
            "CURSO": "3\u00ba ESO",
        }
        datos_devolucion = {
            "IMPORTE": "350,00",
            "FECHA_VENCIMIENTO": "15/04/2026",
            "CONCEPTO": "Mensualidad marzo",
        }

        resultado = rellenar_plantilla(plantilla, datos_familia, datos_devolucion)

        assert resultado["asunto"] == "Aviso de impago - Mensualidad marzo"
        assert "Garc\u00eda L\u00f3pez" in resultado["cuerpo"]
        assert "350,00" in resultado["cuerpo"]
        assert "15/04/2026" in resultado["cuerpo"]
        assert "Pablo" in resultado["cuerpo"]
        assert "3\u00ba ESO" in resultado["cuerpo"]
        assert "{" not in resultado["cuerpo"]

    def test_variables_parciales(self):
        """Variables no proporcionadas quedan como placeholder."""
        plantilla = {
            "asunto": "{APELLIDO} - {CONCEPTO}",
            "cuerpo": "Plazo: {PLAZO_DIAS} d\u00edas",
        }
        resultado = rellenar_plantilla(plantilla, {"APELLIDO": "Ruiz"}, {})

        assert resultado["asunto"] == "Ruiz - {CONCEPTO}"
        assert resultado["cuerpo"] == "Plazo: {PLAZO_DIAS} d\u00edas"


class TestRegistrarAccion:
    def test_registra_envio_auto(self, db_conn):
        caso = {"family_code": "00012345", "importe": 150.0}
        plantilla = {"nombre": "primera_devolucion"}

        registrar_accion(caso, plantilla, "enviar_auto", db_conn)

        row = db_conn.execute(
            "SELECT workflow, family_code, accion, detalle FROM acciones_log"
        ).fetchone()
        assert row[0] == "motor_plantillas"
        assert row[1] == "00012345"
        assert row[2] == "seleccion_plantilla"
        assert "primera_devolucion" in row[3]
        assert "150.00" in row[3]

    def test_registra_revision_humana(self, db_conn):
        caso = {"family_code": "00067890", "importe": 100.0}

        registrar_accion(caso, None, "marcar_revision_humana", db_conn)

        row = db_conn.execute("SELECT detalle FROM acciones_log").fetchone()
        assert "revision_humana" in row[0]

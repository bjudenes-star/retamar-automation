"""Tests unitarios para detector_devoluciones."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from python.detector_devoluciones import (
    _parse_fecha_n43,
    _parse_importe_n43,
    calcular_severidad,
    es_devolucion,
    parsear_norma43,
    procesar_devoluciones,
)

# Fichero Norma 43 de ejemplo (datos inventados pero formato realista)
# Formato Norma 43 — registro 22 (80 chars):
# [0:2]   tipo=22
# [2:6]   libre
# [6:10]  oficina origen
# [10:16] fecha operación AAMMDD
# [16:22] fecha valor AAMMDD
# [22:24] clave operación (17=devolución)
# [24:27] concepto propio
# [27]    signo (1=cargo, 2=abono)
# [28:42] importe (14 dígitos, últimos 2 decimales)
# [42:58] referencia 1
# [58:74] referencia 2
NORMA43_EJEMPLO = (
    "11004900280011234567260301260331200000000150000                                 \n"
    "220049002826031026031017 00100000000035000REM00012345     DEVOLUCION            \n"
    "2301DEVOL RECIBO MENSUALIDAD MARZO 2026                                         \n"
    "220049002826031526031502 00200000000120000TRANSF-001      ABONO                 \n"
    "2301TRANSFERENCIA RECIBIDA                                                      \n"
    "220049002826032026032017 00100000000055000REM00067890     IMPAGADO              \n"
    "2301IMPAGADO CUOTA COMEDOR ABRIL 2026                                           \n"
    "3300490028                                                200000000137000       \n"
    "88999999999999999999                                                            \n"
)


@pytest.fixture
def db_conn():
    """DB en memoria con esquema y datos de prueba."""
    conn = sqlite3.connect(":memory:")
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn.executescript(schema)

    # Insertar familias y facturas de prueba
    conn.execute(
        "INSERT INTO familias (codigo_familia, nombre) VALUES (?, ?)",
        ("00012345", "García López, Pedro"),
    )
    conn.execute(
        "INSERT INTO familias (codigo_familia, nombre) VALUES (?, ?)",
        ("00067890", "Martínez Ruiz, Ana"),
    )
    conn.execute(
        """INSERT INTO facturas (numero_factura, family_code, fecha, total,
           fecha_vencimiento, estado, hash_contenido, origen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("F001", "00012345", "2026-03-01", 350.00, "2026-03-15", "pendiente", "hash1", "csv"),
    )
    conn.execute(
        """INSERT INTO facturas (numero_factura, family_code, fecha, total,
           fecha_vencimiento, estado, hash_contenido, origen)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("F002", "00067890", "2026-04-01", 550.00, "2026-04-15", "pendiente", "hash2", "csv"),
    )
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def norma43_file(tmp_path):
    """Crea un fichero Norma 43 de ejemplo."""
    filepath = tmp_path / "extracto.q43"
    filepath.write_text(NORMA43_EJEMPLO, encoding="latin-1")
    return filepath


class TestParserNorma43:
    def test_parse_fecha_n43(self):
        assert _parse_fecha_n43("260315") == "2026-03-15"
        assert _parse_fecha_n43("260101") == "2026-01-01"
        assert _parse_fecha_n43("") is None

    def test_parse_importe_cargo(self):
        # 35000 = 350.00€, signo 1 = cargo (negativo)
        assert _parse_importe_n43("00000000035000", "1") == -350.00

    def test_parse_importe_abono(self):
        # 120000 = 1200.00€, signo 2 = abono (positivo)
        assert _parse_importe_n43("00000000120000", "2") == 1200.00

    def test_parsear_fichero_completo(self, norma43_file):
        datos = parsear_norma43(norma43_file)
        assert datos["cuenta"]["entidad"] == "0049"
        assert datos["cuenta"]["cuenta"] == "0011234567"
        assert len(datos["movimientos"]) == 3

    def test_movimiento_devolucion(self, norma43_file):
        datos = parsear_norma43(norma43_file)
        mov = datos["movimientos"][0]
        assert mov["clave_operacion"] == "17"
        assert mov["importe"] < 0  # Es un cargo
        assert "DEVOL" in mov["conceptos"][0]


class TestDeteccionDevoluciones:
    def test_es_devolucion_por_clave(self):
        mov = {"clave_operacion": "17", "conceptos": [], "referencia_1": "", "referencia_2": ""}
        assert es_devolucion(mov) is True

    def test_es_devolucion_por_keyword(self):
        mov = {"clave_operacion": "02", "conceptos": ["DEVOLUCION RECIBO"],
               "referencia_1": "", "referencia_2": ""}
        assert es_devolucion(mov) is True

    def test_no_es_devolucion(self):
        mov = {"clave_operacion": "02", "conceptos": ["TRANSFERENCIA RECIBIDA"],
               "referencia_1": "", "referencia_2": ""}
        assert es_devolucion(mov) is False

    def test_es_devolucion_por_referencia(self):
        mov = {"clave_operacion": "02", "conceptos": [],
               "referencia_1": "IMPAGADO REC", "referencia_2": ""}
        assert es_devolucion(mov) is True


class TestSeveridad:
    def test_primera_devolucion(self, db_conn):
        assert calcular_severidad(db_conn, "00012345", 100.0) == 1

    def test_segunda_devolucion(self, db_conn):
        db_conn.execute(
            "INSERT INTO casos_deuda (family_code, importe, estado, nivel_severidad) VALUES (?, ?, ?, ?)",
            ("00012345", 100.0, "pendiente", 1),
        )
        db_conn.commit()
        assert calcular_severidad(db_conn, "00012345", 100.0) == 2

    def test_caso_grave_por_importe(self, db_conn):
        assert calcular_severidad(db_conn, "00012345", 600.0) == 4


class TestProcesarCompleto:
    def test_procesar_norma43(self, norma43_file, db_conn):
        devoluciones = procesar_devoluciones(norma43_file, db_conn)

        # Debe detectar 2 devoluciones (clave 17), no la transferencia
        assert len(devoluciones) == 2
        assert devoluciones[0]["importe"] == 350.0
        assert devoluciones[1]["importe"] == 550.0

        # Debe insertar en casos_deuda
        casos = db_conn.execute("SELECT COUNT(*) FROM casos_deuda").fetchone()[0]
        assert casos == 2

        # Debe registrar en acciones_log
        logs = db_conn.execute("SELECT COUNT(*) FROM acciones_log").fetchone()[0]
        assert logs == 2

    def test_exportar_json(self, norma43_file, db_conn, tmp_path):
        devoluciones = procesar_devoluciones(norma43_file, db_conn)
        output = tmp_path / "resultado.json"
        output.write_text(json.dumps(devoluciones, ensure_ascii=False, indent=2))

        data = json.loads(output.read_text())
        assert len(data) == 2
        assert "family_code" in data[0]
        assert "severidad" in data[0]

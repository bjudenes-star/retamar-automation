"""Tests unitarios para sage_processor."""

import sqlite3
import tempfile
import textwrap
from pathlib import Path

import pytest

from python.sage_processor import (
    _hash_contenido,
    _parse_fecha,
    _parse_importe,
    _resolve_columns,
    init_db,
    procesar_csv,
    procesar_sepa_xml,
)


@pytest.fixture
def db_conn():
    """Crea una base de datos SQLite en memoria con el esquema."""
    conn = sqlite3.connect(":memory:")
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn.executescript(schema)
    yield conn
    conn.close()


class TestParseHelpers:
    def test_parse_fecha_dd_mm_yyyy(self):
        assert _parse_fecha("15/03/2026") == "2026-03-15"

    def test_parse_fecha_iso(self):
        assert _parse_fecha("2026-03-15") == "2026-03-15"

    def test_parse_fecha_dd_mm_yy(self):
        assert _parse_fecha("15/03/26") == "2026-03-15"

    def test_parse_fecha_vacia(self):
        assert _parse_fecha("") is None

    def test_parse_importe_espanol(self):
        assert _parse_importe("1.234,56") == 1234.56

    def test_parse_importe_con_euro(self):
        assert _parse_importe("150,00€") == 150.0

    def test_parse_importe_estandar(self):
        assert _parse_importe("1234.56") == 1234.56

    def test_parse_importe_vacio(self):
        assert _parse_importe("") == 0.0

    def test_hash_contenido_determinista(self):
        assert _hash_contenido("test") == _hash_contenido("test")
        assert _hash_contenido("a") != _hash_contenido("b")


class TestResolveColumns:
    def test_mapeo_sage_clasico(self):
        header = ["Num.", "Fecha", "Cliente", "Nombre", "NIF", "Base Imponible",
                  "IVA", "Total", "Vencimiento", "Estado"]
        m = _resolve_columns(header)
        assert m["numero_factura"] == "Num."
        assert m["family_code"] == "Cliente"
        assert m["total"] == "Total"

    def test_mapeo_sage_alternativo(self):
        header = ["Nº Factura", "Fecha Factura", "Código Cliente", "Razón Social",
                  "CIF", "Base", "Cuota IVA", "Importe", "Fecha Vencimiento", "Situación"]
        m = _resolve_columns(header)
        assert m["numero_factura"] == "Nº Factura"
        assert m["family_code"] == "Código Cliente"
        assert m["total"] == "Importe"


class TestProcesarCSV:
    def test_csv_basico(self, db_conn, tmp_path):
        csv_file = tmp_path / "facturas.csv"
        csv_file.write_text(
            "Num.;Fecha;Cliente;Nombre;NIF;Base Imponible;IVA;Total;Vencimiento;Estado\n"
            "F001;15/03/2026;00012345;García López, Pedro;12345678A;100,00;21,00;121,00;15/04/2026;Pendiente\n"
            "F002;16/03/2026;00067890;Martínez Ruiz, Ana;87654321B;200,00;42,00;242,00;16/04/2026;Pendiente\n",
            encoding="utf-8-sig",
        )

        stats = procesar_csv(csv_file, db_conn)
        assert stats["nuevas"] == 2
        assert stats["duplicadas"] == 0
        assert stats["errores"] == 0

        # Verificar familias
        familias = db_conn.execute("SELECT codigo_familia FROM familias ORDER BY codigo_familia").fetchall()
        assert [f[0] for f in familias] == ["00012345", "00067890"]

        # Verificar facturas
        facturas = db_conn.execute("SELECT numero_factura, total FROM facturas ORDER BY numero_factura").fetchall()
        assert facturas[0] == ("F001", 121.0)
        assert facturas[1] == ("F002", 242.0)

    def test_csv_duplicados(self, db_conn, tmp_path):
        csv_file = tmp_path / "facturas.csv"
        contenido = (
            "Num.;Fecha;Cliente;Nombre;NIF;Base Imponible;IVA;Total;Vencimiento;Estado\n"
            "F001;15/03/2026;00012345;García López;12345678A;100,00;21,00;121,00;15/04/2026;Pendiente\n"
        )
        csv_file.write_text(contenido, encoding="utf-8-sig")

        procesar_csv(csv_file, db_conn)
        stats = procesar_csv(csv_file, db_conn)
        assert stats["duplicadas"] == 1
        assert stats["nuevas"] == 0

    def test_csv_sin_columnas_obligatorias(self, db_conn, tmp_path):
        csv_file = tmp_path / "mal.csv"
        csv_file.write_text("Columna1;Columna2\nA;B\n", encoding="utf-8-sig")

        stats = procesar_csv(csv_file, db_conn)
        assert stats["errores"] == 1


class TestProcesarSEPA:
    def test_sepa_xml_basico(self, db_conn, tmp_path):
        xml_content = textwrap.dedent("""\
        <?xml version="1.0" encoding="UTF-8"?>
        <Document xmlns="urn:iso:std:iso:20022:tech:xsd:pain.008.001.02">
          <CstmrDrctDbtInitn>
            <PmtInf>
              <DrctDbtTxInf>
                <PmtId>
                  <EndToEndId>REM00012345-2026-001</EndToEndId>
                </PmtId>
                <InstdAmt Ccy="EUR">350.00</InstdAmt>
                <Dbtr>
                  <Nm>García López, Pedro</Nm>
                </Dbtr>
                <DbtrAcct>
                  <Id>
                    <IBAN>ES6621000418401234567891</IBAN>
                  </Id>
                </DbtrAcct>
              </DrctDbtTxInf>
              <DrctDbtTxInf>
                <PmtId>
                  <EndToEndId>REM00067890-2026-002</EndToEndId>
                </PmtId>
                <InstdAmt Ccy="EUR">180.50</InstdAmt>
                <Dbtr>
                  <Nm>Martínez Ruiz, Ana</Nm>
                </Dbtr>
                <DbtrAcct>
                  <Id>
                    <IBAN>ES1234567890123456789012</IBAN>
                  </Id>
                </DbtrAcct>
              </DrctDbtTxInf>
            </PmtInf>
          </CstmrDrctDbtInitn>
        </Document>""")

        xml_file = tmp_path / "remesa.xml"
        xml_file.write_text(xml_content, encoding="utf-8")

        stats = procesar_sepa_xml(xml_file, db_conn)
        assert stats["nuevas"] == 2
        assert stats["errores"] == 0

        familias = db_conn.execute("SELECT codigo_familia FROM familias ORDER BY codigo_familia").fetchall()
        assert [f[0] for f in familias] == ["00012345", "00067890"]

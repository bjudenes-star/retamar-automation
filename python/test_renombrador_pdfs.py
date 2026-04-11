"""Tests unitarios para renombrador_pdfs."""

import sqlite3
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from python.renombrador_pdfs import (
    CODIGOS_TIPO,
    extraer_metadatos_pdf,
    renombrar_y_organizar,
    procesar_directorio,
)


@pytest.fixture
def db_conn():
    """DB en memoria con esquema."""
    conn = sqlite3.connect(":memory:")
    schema = (Path(__file__).parent.parent / "db" / "schema.sql").read_text()
    conn.executescript(schema)
    yield conn
    conn.close()


def _crear_pdf_mock(tmp_path, nombre="justificante.pdf", texto=""):
    """Crea un fichero PDF falso para tests."""
    filepath = tmp_path / nombre
    filepath.write_bytes(b"%PDF-1.4 fake content")
    return filepath, texto


class TestCodigosTipo:
    def test_devolucion(self):
        assert CODIGOS_TIPO["devoluci\u00f3n"] == "DV"

    def test_comision(self):
        assert CODIGOS_TIPO["comisi\u00f3n"] == "CM"

    def test_transferencia(self):
        assert CODIGOS_TIPO["transferencia"] == "TR"

    def test_recibo(self):
        assert CODIGOS_TIPO["recibo"] == "RC"


class TestExtraerMetadatos:
    @patch("python.renombrador_pdfs.PdfReader")
    def test_extrae_fecha_operacion(self, mock_reader_cls, tmp_path):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "CaixaBank\n"
            "Justificante de operaci\u00f3n\n"
            "Fecha de operaci\u00f3n: 10/04/2026\n"
            "Referencia: REF123456\n"
            "Concepto: Comisi\u00f3n devoluci\u00f3n recibo\n"
            "Importe: 3,50 EUR\n"
        )
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        pdf, _ = _crear_pdf_mock(tmp_path)
        meta = extraer_metadatos_pdf(pdf)

        assert meta["fecha"] == "2026-04-10"
        assert meta["referencia"] == "REF123456"
        assert meta["codigo_tipo"] == "PR"  # comisi\u00f3n devoluci\u00f3n

    @patch("python.renombrador_pdfs.PdfReader")
    def test_extrae_transferencia(self, mock_reader_cls, tmp_path):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = (
            "Fecha: 05/03/2026\n"
            "Ref. TR789012\n"
            "Transferencia recibida\n"
        )
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        pdf, _ = _crear_pdf_mock(tmp_path)
        meta = extraer_metadatos_pdf(pdf)

        assert meta["fecha"] == "2026-03-05"
        assert meta["referencia"] == "TR789012"
        assert meta["codigo_tipo"] == "TR"

    @patch("python.renombrador_pdfs.PdfReader")
    def test_fallback_sin_fecha(self, mock_reader_cls, tmp_path):
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Documento sin fecha legible"
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]
        mock_reader_cls.return_value = mock_reader

        pdf, _ = _crear_pdf_mock(tmp_path)
        meta = extraer_metadatos_pdf(pdf)

        # Debe usar fecha de modificaci\u00f3n del fichero como fallback
        assert meta["fecha"] is not None


class TestRenombrarYOrganizar:
    @patch("python.renombrador_pdfs.extraer_metadatos_pdf")
    def test_renombra_correctamente(self, mock_extraer, db_conn, tmp_path):
        mock_extraer.return_value = {
            "fecha": "2026-04-10",
            "referencia": "REF123456",
            "tipo": "comisi\u00f3n devoluci\u00f3n",
            "codigo_tipo": "PR",
        }

        pdf_file = tmp_path / "input" / "descarga_banco.pdf"
        pdf_file.parent.mkdir()
        pdf_file.write_bytes(b"%PDF-fake")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        destino = renombrar_y_organizar(pdf_file, output_dir, db_conn)

        assert destino is not None
        assert destino.name == "20260410_PR_REF123456.pdf"
        assert destino.parent == output_dir / "2026" / "04"
        assert destino.exists()

        # Verificar registro en BD
        doc = db_conn.execute("SELECT * FROM documentos_banco").fetchone()
        assert doc is not None

    @patch("python.renombrador_pdfs.extraer_metadatos_pdf")
    def test_evita_sobreescribir(self, mock_extraer, db_conn, tmp_path):
        mock_extraer.return_value = {
            "fecha": "2026-04-10",
            "referencia": "REF123456",
            "tipo": "recibo",
            "codigo_tipo": "RC",
        }

        pdf1 = tmp_path / "a.pdf"
        pdf2 = tmp_path / "b.pdf"
        pdf1.write_bytes(b"%PDF-1")
        pdf2.write_bytes(b"%PDF-2")

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        d1 = renombrar_y_organizar(pdf1, output_dir, db_conn)
        d2 = renombrar_y_organizar(pdf2, output_dir, db_conn)

        assert d1.name == "20260410_RC_REF123456.pdf"
        assert d2.name == "20260410_RC_REF123456_2.pdf"


class TestProcesarDirectorio:
    @patch("python.renombrador_pdfs.extraer_metadatos_pdf")
    def test_procesa_multiples(self, mock_extraer, db_conn, tmp_path):
        mock_extraer.return_value = {
            "fecha": "2026-03-15",
            "referencia": "ABC123",
            "tipo": "recibo",
            "codigo_tipo": "RC",
        }

        input_dir = tmp_path / "input"
        input_dir.mkdir()
        (input_dir / "doc1.pdf").write_bytes(b"%PDF-1")
        (input_dir / "doc2.pdf").write_bytes(b"%PDF-2")
        (input_dir / "notas.txt").write_text("ignorar")  # No es PDF

        output_dir = tmp_path / "output"
        output_dir.mkdir()

        stats = procesar_directorio(input_dir, output_dir, db_conn)
        assert stats["procesados"] == 2
        assert stats["errores"] == 0

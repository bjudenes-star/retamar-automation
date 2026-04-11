"""Renombrador y organizador de justificantes PDF de CaixaBankNow.

Lee PDFs descargados del banco, extrae metadatos, renombra con el patr\u00f3n
YYYYMMDD_CODIGO_REFERENCIA.pdf y organiza por carpeta mensual.

Uso:
    python -m python.renombrador_pdfs --input-dir ./descargas --output-dir ./justificantes
    python -m python.renombrador_pdfs --help
"""

import argparse
import logging
import re
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

try:
    from PyPDF2 import PdfReader
except ImportError:
    PdfReader = None

DB_PATH = Path(__file__).parent.parent / "db" / "retamar.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("renombrador_pdfs")

# C\u00f3digos de tipo de movimiento para el nombre del fichero
CODIGOS_TIPO = {
    "comisi\u00f3n": "CM",
    "comision": "CM",
    "comisi\u00f3n devoluci\u00f3n": "PR",
    "comision devolucion": "PR",
    "devoluci\u00f3n": "DV",
    "devolucion": "DV",
    "transferencia": "TR",
    "recibo": "RC",
    "domiciliaci\u00f3n": "RC",
    "domiciliacion": "RC",
    "pago": "PG",
    "ingreso": "IN",
    "cargo": "CG",
    "abono": "AB",
}


def extraer_metadatos_pdf(filepath: Path) -> dict:
    """Extrae fecha, referencia y tipo de movimiento de un PDF bancario.

    Returns:
        dict con claves: fecha (str YYYY-MM-DD), referencia (str), tipo (str),
        codigo_tipo (str 2 chars)
    """
    if PdfReader is None:
        log.error("PyPDF2 no instalado. Ejecuta: pip install PyPDF2")
        return {}

    reader = PdfReader(filepath)
    texto = ""
    for page in reader.pages:
        texto += page.extract_text() or ""

    resultado = {
        "fecha": None,
        "referencia": None,
        "tipo": None,
        "codigo_tipo": "XX",
    }

    # Extraer fecha: buscar patrones comunes en justificantes CaixaBank
    patrones_fecha = [
        r"Fecha\s*(?:de\s+)?operaci[o\u00f3]n[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})",
        r"Fecha\s*valor[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})",
        r"Fecha[:\s]+(\d{2}[/-]\d{2}[/-]\d{4})",
        r"(\d{2}[/-]\d{2}[/-]\d{4})",
    ]
    for patron in patrones_fecha:
        match = re.search(patron, texto, re.IGNORECASE)
        if match:
            fecha_str = match.group(1).replace("-", "/")
            try:
                fecha = datetime.strptime(fecha_str, "%d/%m/%Y")
                resultado["fecha"] = fecha.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue

    # Extraer referencia bancaria
    patrones_ref = [
        r"[Rr]eferencia[:\s]+([A-Z0-9]{6,20})",
        r"[Nn]\u00ba?\s*[Rr]ef(?:erencia)?[:\s]+([A-Z0-9]{6,20})",
        r"[Rr]ef\.?\s*([A-Z0-9]{6,20})",
    ]
    for patron in patrones_ref:
        match = re.search(patron, texto)
        if match:
            resultado["referencia"] = match.group(1)
            break

    # Detectar tipo de movimiento (buscar claves m\u00e1s largas primero para evitar matchs parciales)
    texto_lower = texto.lower()
    for keyword, codigo in sorted(CODIGOS_TIPO.items(), key=lambda x: -len(x[0])):
        if keyword in texto_lower:
            resultado["tipo"] = keyword
            resultado["codigo_tipo"] = codigo
            break

    # Fallback: usar fecha del fichero si no se encontr\u00f3 en el PDF
    if not resultado["fecha"]:
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        resultado["fecha"] = mtime.strftime("%Y-%m-%d")
        log.warning("No se encontr\u00f3 fecha en PDF, usando fecha de modificaci\u00f3n: %s",
                    resultado["fecha"])

    # Fallback: referencia del nombre original del fichero
    if not resultado["referencia"]:
        ref_match = re.search(r"[A-Z0-9]{6,}", filepath.stem)
        resultado["referencia"] = ref_match.group(0) if ref_match else filepath.stem[:12]

    return resultado


def renombrar_y_organizar(filepath: Path, output_dir: Path,
                          conn: sqlite3.Connection) -> Path | None:
    """Renombra un PDF y lo mueve a la carpeta organizada por mes.

    Returns:
        Path del fichero destino, o None si hubo error.
    """
    meta = extraer_metadatos_pdf(filepath)
    if not meta:
        return None

    fecha = meta["fecha"]
    codigo = meta["codigo_tipo"]
    referencia = meta["referencia"] or "SINREF"

    # Nombre destino: YYYYMMDD_CODIGO_REFERENCIA.pdf
    fecha_compact = fecha.replace("-", "")
    nuevo_nombre = f"{fecha_compact}_{codigo}_{referencia}.pdf"

    # Subcarpeta por mes: YYYY/MM/
    anio = fecha[:4]
    mes = fecha[5:7]
    destino_dir = output_dir / anio / mes
    destino_dir.mkdir(parents=True, exist_ok=True)

    destino = destino_dir / nuevo_nombre

    # Evitar sobreescribir
    if destino.exists():
        i = 2
        while destino.exists():
            nuevo_nombre = f"{fecha_compact}_{codigo}_{referencia}_{i}.pdf"
            destino = destino_dir / nuevo_nombre
            i += 1

    shutil.copy2(filepath, destino)
    log.info("Renombrado: %s \u2192 %s", filepath.name, destino.relative_to(output_dir))

    # Registrar en documentos_banco
    conn.execute(
        """INSERT INTO documentos_banco (fecha, cuenta, referencia_bancaria,
           importe, tipo, ruta_archivo, procesado)
           VALUES (?, ?, ?, ?, 'justificante', ?, 1)""",
        (fecha, None, referencia, None, str(destino)),
    )
    conn.commit()

    return destino


def procesar_directorio(input_dir: Path, output_dir: Path,
                        conn: sqlite3.Connection) -> dict:
    """Procesa todos los PDFs de un directorio."""
    stats = {"procesados": 0, "errores": 0}

    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        log.info("No se encontraron PDFs en %s", input_dir)
        return stats

    log.info("Encontrados %d PDFs para procesar", len(pdfs))

    for pdf in pdfs:
        try:
            resultado = renombrar_y_organizar(pdf, output_dir, conn)
            if resultado:
                stats["procesados"] += 1
            else:
                stats["errores"] += 1
        except Exception as e:
            log.error("Error procesando %s: %s", pdf.name, e)
            stats["errores"] += 1

    log.info("Procesados: %d | Errores: %d", stats["procesados"], stats["errores"])
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Renombrador y organizador de justificantes PDF de CaixaBankNow"
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        required=True,
        help="Carpeta con PDFs descargados del banco",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Carpeta destino para los PDFs organizados",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Ruta a la base de datos SQLite (por defecto: db/retamar.db)",
    )
    args = parser.parse_args()

    if not args.input_dir.exists():
        log.error("Directorio de entrada no existe: %s", args.input_dir)
        return

    # Inicializar DB
    conn = sqlite3.connect(str(args.db))
    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))

    procesar_directorio(args.input_dir, args.output_dir, conn)
    conn.close()


if __name__ == "__main__":
    main()

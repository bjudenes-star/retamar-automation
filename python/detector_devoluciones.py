"""Detector de devoluciones bancarias a partir de ficheros Norma 43 (Q43).

Lee ficheros Norma 43 de CaixaBank, detecta devoluciones de recibos,
cruza con facturas en SQLite, clasifica severidad e inserta en casos_deuda.

Uso:
    python -m python.detector_devoluciones fichero.q43
    python -m python.detector_devoluciones fichero.q43 --output devoluciones.json
    python -m python.detector_devoluciones --help
"""

import argparse
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "db" / "retamar.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("detector_devoluciones")

KEYWORDS_DEVOLUCION = ["DEVOL", "IMPAGADO", "RETORNO", "DEVOLUCION", "DEVOLUCI\u00d3N",
                       "RECIBO DEVUELTO", "IMPAGO"]


# --- Parser Norma 43 ---

def parsear_norma43(filepath: Path) -> dict:
    """Parsea un fichero Norma 43 completo.

    Returns:
        dict con claves: cuenta (dict), movimientos (list), saldo_final (str)
    """
    resultado = {
        "cuenta": {},
        "movimientos": [],
        "saldo_final": None,
    }
    movimiento_actual = None

    with open(filepath, encoding="latin-1") as f:
        for linea in f:
            linea = linea.rstrip("\n\r")
            if len(linea) < 2:
                continue

            tipo_registro = linea[:2]

            if tipo_registro == "11":
                # Cabecera de cuenta
                resultado["cuenta"] = {
                    "entidad": linea[2:6],
                    "oficina": linea[6:10],
                    "cuenta": linea[10:20],
                    "fecha_inicio": _parse_fecha_n43(linea[20:26]),
                    "fecha_fin": _parse_fecha_n43(linea[26:32]),
                    "saldo_inicial": _parse_importe_n43(linea[33:47], linea[32]),
                }

            elif tipo_registro == "22":
                # Movimiento
                if movimiento_actual:
                    resultado["movimientos"].append(movimiento_actual)

                signo = linea[27]  # 1=debe(cargo), 2=haber(abono)
                movimiento_actual = {
                    "oficina_origen": linea[6:10],
                    "fecha_operacion": _parse_fecha_n43(linea[10:16]),
                    "fecha_valor": _parse_fecha_n43(linea[16:22]),
                    "importe": _parse_importe_n43(linea[28:42], signo),
                    "signo": "cargo" if signo == "1" else "abono",
                    "clave_operacion": linea[22:25].strip(),
                    "referencia_1": linea[42:58].strip(),
                    "referencia_2": linea[58:74].strip(),
                    "conceptos": [],
                }

            elif tipo_registro == "23":
                # Concepto complementario
                if movimiento_actual:
                    concepto = linea[4:].strip()
                    if concepto:
                        movimiento_actual["conceptos"].append(concepto)

            elif tipo_registro == "33":
                # Fin de cuenta
                if movimiento_actual:
                    resultado["movimientos"].append(movimiento_actual)
                    movimiento_actual = None
                resultado["saldo_final"] = _parse_importe_n43(linea[59:73], linea[58])

            elif tipo_registro == "88":
                # Fin de fichero
                if movimiento_actual:
                    resultado["movimientos"].append(movimiento_actual)
                    movimiento_actual = None

    return resultado


def _parse_fecha_n43(s: str) -> str | None:
    """Convierte AAMMDD a YYYY-MM-DD."""
    if not s or len(s) != 6 or not s.isdigit():
        return None
    anio = 2000 + int(s[0:2])
    mes = int(s[2:4])
    dia = int(s[4:6])
    try:
        return datetime(anio, mes, dia).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _parse_importe_n43(s: str, signo: str) -> float:
    """Parsea importe Norma 43 (\u00faltimos 2 d\u00edgitos son decimales)."""
    if not s:
        return 0.0
    s = s.strip()
    if not s.isdigit():
        return 0.0
    importe = int(s) / 100.0
    if signo == "1":  # Cargo/debe = negativo
        importe = -importe
    return importe


# --- Detecci\u00f3n de devoluciones ---

def es_devolucion(movimiento: dict) -> bool:
    """Determina si un movimiento es una devoluci\u00f3n de recibo."""
    # Clave de operaci\u00f3n 17 = devoluci\u00f3n de recibos
    if movimiento.get("clave_operacion") == "17":
        return True

    # Buscar keywords en conceptos
    texto = " ".join(movimiento.get("conceptos", [])).upper()
    texto += " " + movimiento.get("referencia_1", "").upper()
    texto += " " + movimiento.get("referencia_2", "").upper()

    return any(kw in texto for kw in KEYWORDS_DEVOLUCION)


def buscar_familia_por_factura(conn: sqlite3.Connection, importe: float,
                               fecha: str | None, referencia: str) -> str | None:
    """Cruza una devoluci\u00f3n con facturas para encontrar la familia."""
    importe_abs = abs(importe)

    # Buscar por referencia en numero_factura
    if referencia:
        row = conn.execute(
            "SELECT family_code FROM facturas WHERE numero_factura LIKE ? LIMIT 1",
            (f"%{referencia}%",),
        ).fetchone()
        if row:
            return row[0]

    # Buscar por importe (tolerancia de 0.01\u20ac)
    rows = conn.execute(
        """SELECT family_code FROM facturas
           WHERE ABS(total - ?) < 0.02
           ORDER BY ABS(julianday(fecha_vencimiento) - julianday(?)) ASC
           LIMIT 1""",
        (importe_abs, fecha or datetime.now().strftime("%Y-%m-%d")),
    ).fetchone()
    if rows:
        return rows[0]

    return None


def calcular_severidad(conn: sqlite3.Connection, family_code: str,
                       importe: float) -> int:
    """Calcula el nivel de severidad de una devoluci\u00f3n.

    1 = primera devoluci\u00f3n
    2 = segunda en 6 meses
    3 = tercera o m\u00e1s
    4 = caso grave (importe > 500\u20ac o 3+ en 3 meses)
    """
    ahora = datetime.now()
    hace_6_meses = (ahora - timedelta(days=180)).strftime("%Y-%m-%d")
    hace_3_meses = (ahora - timedelta(days=90)).strftime("%Y-%m-%d")

    # Contar devoluciones previas en 6 meses
    count_6m = conn.execute(
        """SELECT COUNT(*) FROM casos_deuda
           WHERE family_code = ? AND created_at >= ?""",
        (family_code, hace_6_meses),
    ).fetchone()[0]

    # Contar devoluciones en 3 meses
    count_3m = conn.execute(
        """SELECT COUNT(*) FROM casos_deuda
           WHERE family_code = ? AND created_at >= ?""",
        (family_code, hace_3_meses),
    ).fetchone()[0]

    # Caso grave
    if abs(importe) > 500 or count_3m >= 3:
        return 4

    # Tercera o m\u00e1s en 6 meses
    if count_6m >= 2:
        return 3

    # Segunda en 6 meses
    if count_6m >= 1:
        return 2

    # Primera
    return 1


def _log_accion(conn: sqlite3.Connection, family_code: str, accion: str,
                detalle: str):
    """Registra una acci\u00f3n en acciones_log."""
    conn.execute(
        """INSERT INTO acciones_log (workflow, family_code, accion, detalle, usuario)
           VALUES (?, ?, ?, ?, ?)""",
        ("detector_devoluciones", family_code, accion, detalle, "sistema"),
    )


def procesar_devoluciones(filepath: Path, conn: sqlite3.Connection) -> list[dict]:
    """Procesa un fichero Norma 43 y detecta devoluciones.

    Returns:
        Lista de devoluciones detectadas (para exportar a JSON/n8n).
    """
    log.info("Procesando fichero Norma 43: %s", filepath.name)
    datos = parsear_norma43(filepath)
    devoluciones = []

    log.info("Cuenta: %s | %d movimientos le\u00eddos",
             datos["cuenta"].get("cuenta", "?"), len(datos["movimientos"]))

    for mov in datos["movimientos"]:
        if not es_devolucion(mov):
            continue

        importe = abs(mov["importe"])
        fecha = mov.get("fecha_operacion")
        referencia = mov.get("referencia_1", "")

        family_code = buscar_familia_por_factura(conn, importe, fecha, referencia)

        if not family_code:
            log.warning("Devoluci\u00f3n de %.2f\u20ac sin familia asociada (ref: %s)",
                        importe, referencia)
            family_code = "DESCONOCIDO"

        severidad = calcular_severidad(conn, family_code, importe)

        # Insertar en casos_deuda
        conn.execute(
            """INSERT INTO casos_deuda
               (family_code, importe, fecha_vencimiento, estado, nivel_severidad)
               VALUES (?, ?, ?, 'pendiente', ?)""",
            (family_code, importe, fecha, severidad),
        )

        _log_accion(
            conn, family_code, "devolucion_detectada",
            f"Importe: {importe:.2f}\u20ac | Severidad: {severidad} | Ref: {referencia}",
        )

        devolucion = {
            "family_code": family_code,
            "importe": importe,
            "fecha": fecha,
            "referencia": referencia,
            "conceptos": mov.get("conceptos", []),
            "severidad": severidad,
        }
        devoluciones.append(devolucion)

        log.info("Devoluci\u00f3n detectada: familia %s | %.2f\u20ac | severidad %d",
                 family_code, importe, severidad)

    conn.commit()

    # Registrar documento procesado
    conn.execute(
        """INSERT INTO documentos_banco (fecha, cuenta, referencia_bancaria,
           importe, tipo, ruta_archivo, procesado)
           VALUES (?, ?, ?, ?, 'norma43', ?, 1)""",
        (
            datetime.now().strftime("%Y-%m-%d"),
            datos["cuenta"].get("cuenta"),
            None,
            None,
            str(filepath),
        ),
    )
    conn.commit()

    log.info("Total devoluciones detectadas: %d", len(devoluciones))
    return devoluciones


def main():
    parser = argparse.ArgumentParser(
        description="Detector de devoluciones bancarias (Norma 43 / Q43)"
    )
    parser.add_argument(
        "fichero",
        type=Path,
        help="Ruta al fichero Norma 43 (.q43)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        help="Exportar devoluciones a fichero JSON (para n8n)",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help="Ruta a la base de datos SQLite (por defecto: db/retamar.db)",
    )
    args = parser.parse_args()

    if not args.fichero.exists():
        log.error("Fichero no encontrado: %s", args.fichero)
        return

    # Inicializar DB
    conn = sqlite3.connect(str(args.db))
    schema_path = Path(__file__).parent.parent / "db" / "schema.sql"
    if schema_path.exists():
        conn.executescript(schema_path.read_text(encoding="utf-8"))

    devoluciones = procesar_devoluciones(args.fichero, conn)

    if args.output:
        args.output.write_text(
            json.dumps(devoluciones, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        log.info("Exportado a %s", args.output)

    conn.close()


if __name__ == "__main__":
    main()

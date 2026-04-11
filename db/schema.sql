CREATE TABLE IF NOT EXISTS familias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    codigo_familia TEXT NOT NULL UNIQUE,  -- 8 dígitos de Sage
    nombre TEXT NOT NULL,
    email TEXT,
    telefono TEXT,
    dni TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alumnos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    familia_id INTEGER NOT NULL REFERENCES familias(id),
    nombre TEXT NOT NULL,
    curso TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_code TEXT NOT NULL,
    email_account TEXT NOT NULL CHECK(email_account IN ('gmail', 'outlook')),
    last_message_id TEXT NOT NULL,  -- Message-ID del último email para responder en hilo
    subject TEXT,
    last_date TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(family_code, email_account)
);

CREATE TABLE IF NOT EXISTS casos_deuda (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_code TEXT NOT NULL,
    importe REAL NOT NULL,
    fecha_vencimiento DATE,
    estado TEXT NOT NULL DEFAULT 'pendiente'
        CHECK(estado IN ('pendiente', 'notificado', 'escalado', 'cobrado', 'incobrable')),
    nivel_severidad INTEGER NOT NULL DEFAULT 1
        CHECK(nivel_severidad BETWEEN 1 AND 4),
    fecha_ultimo_contacto TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plantillas_email (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    asunto TEXT NOT NULL,  -- admite variables: {APELLIDO}, {CONCEPTO}, etc.
    cuerpo TEXT NOT NULL,  -- admite variables: {APELLIDO}, {IMPORTE}, {FECHA_VENCIMIENTO}, {CONCEPTO}, {PLAZO_DIAS}, {NOMBRE_HIJO}, {CURSO}
    categoria TEXT NOT NULL
        CHECK(categoria IN ('primera_notificacion', 'seguimiento', 'escalado', 'peticion', 'informativo')),
    activa BOOLEAN NOT NULL DEFAULT 1,
    version INTEGER NOT NULL DEFAULT 1,
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS reglas_decision (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre TEXT NOT NULL UNIQUE,
    condicion_json TEXT NOT NULL,  -- JSON: {"num_devoluciones": 1, "importe_max": 500, "tiene_beca": false}
    plantilla_id INTEGER NOT NULL REFERENCES plantillas_email(id),
    accion TEXT NOT NULL
        CHECK(accion IN ('enviar_auto', 'marcar_revision_humana', 'escalar')),
    prioridad INTEGER NOT NULL DEFAULT 0,  -- mayor = se evalúa primero
    activa BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS acciones_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    workflow TEXT,
    family_code TEXT,
    accion TEXT NOT NULL,
    detalle TEXT,
    usuario TEXT NOT NULL DEFAULT 'sistema'
        CHECK(usuario IN ('sistema', 'ricardo', 'manolo'))
);

CREATE TABLE IF NOT EXISTS facturas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_factura TEXT NOT NULL UNIQUE,
    family_code TEXT NOT NULL,
    fecha DATE,
    concepto TEXT,
    base_imponible REAL,
    iva REAL,
    total REAL NOT NULL,
    fecha_vencimiento DATE,
    estado TEXT NOT NULL DEFAULT 'pendiente',
    hash_contenido TEXT UNIQUE,  -- SHA256 para detectar duplicados
    origen TEXT,  -- csv, sepa, excel
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS documentos_banco (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha DATE,
    cuenta TEXT,
    referencia_bancaria TEXT,
    importe REAL,
    tipo TEXT NOT NULL CHECK(tipo IN ('justificante', 'norma43')),
    ruta_archivo TEXT,
    procesado BOOLEAN NOT NULL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

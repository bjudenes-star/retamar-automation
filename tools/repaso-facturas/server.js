#!/usr/bin/env node
/**
 * Repaso de facturas — servidor local.
 *
 * Sirve la SPA en http://127.0.0.1:8734 y orquesta, bajo demanda:
 *   Mail.app (AppleScript)  →  descarga de adjuntos  →  extraer.js  →  cola
 * y en cada decisión de JJB: aprobadas.tsv + aprendizaje + etiqueta en el correo.
 *
 * Sin dependencias npm. Los DATOS viven fuera del repo (carpetaDatos de config.json).
 * NUNCA escribe en el Control de facturas oficial.
 *
 * Endurecido tras la revisión adversarial del 23-ago-2026:
 *  - un ítem de cola POR PDF (un correo puede traer varias facturas)
 *  - la etiqueta se pone solo cuando TODOS los PDFs del correo están decididos
 *  - decisiones idempotentes (el doble clic no duplica)
 *  - estado.json nunca se escribe desde un snapshot viejo (mutarEstado)
 *  - overrides compilados desde una SEMILLA + el diario entero (sin doble conteo)
 *  - el id viaja como columna 18 de aprobadas.tsv (adiós emparejamiento por índice)
 *  - los saltados que caducan de la ventana se arrastran, no se pierden
 *  - copia de seguridad de los ficheros irremplazables en cada aprobación
 */
const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { execFile, execFileSync } = require('child_process');

// ---------------------------------------------------------------- config
const AQUI = __dirname;
const cfgPath = fs.existsSync(path.join(AQUI, 'config.json'))
  ? path.join(AQUI, 'config.json') : path.join(AQUI, 'config.example.json');
const CFG = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
const HOME = process.env.HOME;
const DATOS = CFG.carpetaDatos.replace(/^~/, HOME);
const CORREOS = path.join(DATOS, 'correos');
const CONTROL = CFG.controlXlsx.replace(/^~/, HOME);
const EXTRACTOR = path.join(AQUI, '..', 'extractor-facturas', 'extraer.js');
const CUENTA = CFG.cuentaMail || 'Google';
const ETIQUETA = CFG.etiqueta || 'Registrada';
const PUERTO = CFG.puerto || 8734;
const NODE_PATH_XLSX = (CFG.nodePathXlsx || '').replace(/^~/, HOME);
const RESPALDO = (CFG.carpetaRespaldo ||
  '~/Library/CloudStorage/GoogleDrive-javier.jaudenes@retamar.es/Mi unidad/RepasoFacturas-backup')
  .replace(/^~/, HOME);

for (const d of [DATOS, CORREOS]) fs.mkdirSync(d, { recursive: true });

const F = n => path.join(DATOS, n);
const leerJSON = (f, defecto) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return defecto; } };
const escribirAtomico = (f, contenido) => { fs.writeFileSync(f + '.tmp', contenido); fs.renameSync(f + '.tmp', f); };
const sha8 = s => crypto.createHash('sha1').update(String(s)).digest('hex').slice(0, 8);
const TERMINAL = ['aprobada', 'descartada', 'cerrada'];
const limpiarCampo = v => String(v ?? '').replace(/[\t\r\n]/g, ' ');

/** Toda escritura de estado.json pasa por aquí: se relee SIEMPRE antes de
 *  escribir, para que un await largo no machaque decisiones concurrentes. */
function mutarEstado(fn) {
  const estado = leerJSON(F('estado.json'), {});
  fn(estado);
  escribirAtomico(F('estado.json'), JSON.stringify(estado, null, 1));
  return estado;
}

// ---------------------------------------------------------------- respaldo
function respaldar() {
  try {
    const base = fs.existsSync(path.dirname(RESPALDO)) ? RESPALDO
      : path.join(HOME, 'Documents', 'RepasoFacturas-backup');
    const dia = path.join(base, new Date().toISOString().slice(0, 10));
    fs.mkdirSync(dia, { recursive: true });
    for (const f of ['estado.json', 'tanda.json', 'aprobadas.tsv', 'aprendizaje.jsonl',
                     'overrides.json', 'overrides-semilla.json', 'apartados.tsv'])
      if (fs.existsSync(F(f))) fs.copyFileSync(F(f), path.join(dia, f));
  } catch (e) { console.error('respaldo:', e.message); }
}

// ---------------------------------------------------------------- applescript
const script = n => path.join(AQUI, 'scripts', n + '.applescript');
function osa(nombre, args, timeout = 180000) {
  return new Promise((resolve, reject) => {
    execFile('osascript', [script(nombre), ...args], { timeout, maxBuffer: 64 * 1024 * 1024 },
      (err, stdout) => err ? reject(err) : resolve(stdout));
  });
}

// rescate de adjuntos desde la fuente MIME (cuando Mail no los tiene descargados)
function rescatarDeMime(raw, destino, prefijo) {
  const partes = raw.split(/\r?\n--[^\r\n]+\r?\n/);
  const guardados = [];
  let n = 0;
  for (const p of partes) {
    const cab = p.slice(0, 2000);
    const fm = cab.match(/filename="?([^";\r\n]+\.pdf)"?/i) || cab.match(/name="?([^";\r\n]+\.pdf)"?/i);
    if (!fm || !/base64/i.test(cab)) continue;
    const b64 = p.split(/\r?\n\r?\n/).slice(1).join('\n').replace(/[^A-Za-z0-9+/=]/g, '');
    const buf = Buffer.from(b64, 'base64');
    if (buf.length < 1000 || buf.slice(0, 5).toString() !== '%PDF-') continue;
    n++;
    // basename SIEMPRE: el filename del MIME lo controla el remitente
    const nombre = `${prefijo}_m${n}_${path.basename(fm[1])}`;
    fs.writeFileSync(path.join(destino, nombre), buf);
    guardados.push(nombre);
  }
  return guardados;
}

// ---------------------------------------------------------------- aprendizaje
/**
 * overrides.json es SIEMPRE un derivado: semilla (lo sembrado a mano) + el
 * diario entero. Recompilar desde la semilla evita el doble conteo que
 * inflaba `veces` en cada decisión (bug confirmado en la revisión del 23-ago).
 */
function asegurarSemilla() {
  if (fs.existsSync(F('overrides-semilla.json'))) return;
  const ov = leerJSON(F('overrides.json'), { porProveedor: {}, aliasRemitente: {}, remitentesNoFactura: {} });
  // la semilla es el overrides actual SIN lo derivado del diario
  const semilla = { porProveedor: {}, aliasRemitente: {}, remitentesNoFactura: {} };
  if (ov._doc) semilla._doc = ov._doc;
  for (const [emp, datos] of Object.entries(ov.porProveedor || {})) {
    const limpio = { ...datos };
    delete limpio.plantillasNumero; delete limpio.aprobadasSinCorreccion; delete limpio.campos;
    if (Object.keys(limpio).length) semilla.porProveedor[emp] = limpio;
  }
  escribirAtomico(F('overrides-semilla.json'), JSON.stringify(semilla, null, 1));
}
const plantillaDe = s => String(s).replace(/\d/g, '9').replace(/[A-Za-z]/g, 'A');
function compilarOverrides() {
  asegurarSemilla();
  const ov = JSON.parse(JSON.stringify(leerJSON(F('overrides-semilla.json'),
    { porProveedor: {}, aliasRemitente: {}, remitentesNoFactura: {} })));
  ov.porProveedor = ov.porProveedor || {}; ov.aliasRemitente = ov.aliasRemitente || {}; ov.remitentesNoFactura = ov.remitentesNoFactura || {};
  const diario = fs.existsSync(F('aprendizaje.jsonl')) ? fs.readFileSync(F('aprendizaje.jsonl'), 'utf8') : '';
  for (const linea of diario.split('\n')) {
    if (!linea.trim()) continue;
    let e; try { e = JSON.parse(linea); } catch { continue; }
    if (e.accion === 'corregir' && e.proveedor && e.campo) {
      const p = ov.porProveedor[e.proveedor] = ov.porProveedor[e.proveedor] || {};
      p.campos = p.campos || {};
      const c = p.campos[e.campo] = p.campos[e.campo] || { valor: '', veces: 0 };
      c.valor = e.valor_corregido; c.veces++; c.ultima = e.ts;
      if (e.campo === 'Empresa' && e.remitente) ov.aliasRemitente[e.remitente] = e.valor_corregido;
    }
    if (e.accion === 'aprobar_sin_cambios' && e.proveedor) {
      const p = ov.porProveedor[e.proveedor] = ov.porProveedor[e.proveedor] || {};
      if (e.numero_aprobado) {
        p.plantillasNumero = p.plantillasNumero || {};
        const pl = plantillaDe(e.numero_aprobado);
        const t = p.plantillasNumero[pl] = p.plantillasNumero[pl] || { veces: 0, ejemplo: e.numero_aprobado };
        t.veces++;
      }
      if (!e.huboCambios) p.aprobadasSinCorreccion = (p.aprobadasSinCorreccion || 0) + 1;
      if (e.remitente && !ov.aliasRemitente[e.remitente]) ov.aliasRemitente[e.remitente] = e.proveedor;
    }
    if (e.accion === 'descartar' && e.remitente) {
      const r = ov.remitentesNoFactura[e.remitente] = ov.remitentesNoFactura[e.remitente] || { veces: 0 };
      r.veces++;
    }
  }
  escribirAtomico(F('overrides.json'), JSON.stringify(ov, null, 1));
}
function registrarEventos(eventos) {
  fs.appendFileSync(F('aprendizaje.jsonl'), eventos.map(e => JSON.stringify(e)).join('\n') + '\n');
  compilarOverrides();
}

function regenerarOpciones() {
  try {
    execFileSync('node', [path.join(AQUI, 'opciones.js'), CONTROL, F('opciones.json')],
      { env: { ...process.env, NODE_PATH: NODE_PATH_XLSX }, timeout: 120000 });
  } catch (e) { console.error('opciones:', e.message); }
}

// ---------------------------------------------------------------- etiquetado
const baseDe = id => String(id).split('p')[0];
/** Etiqueta el correo SOLO cuando todos sus PDFs (ítems hermanos) están decididos. */
async function etiquetarSiCompleto(baseId) {
  const cola = leerJSON(F('cola.json'), { items: [] });
  const hermanos = cola.items.filter(i => baseDe(i.id) === baseId);
  if (!hermanos.length) return false;
  const estado = leerJSON(F('estado.json'), {});
  const todosDecididos = hermanos.every(h => TERMINAL.includes((estado[h.id] || {}).decision));
  if (!todosDecididos) return false;
  const m = hermanos[0];
  await osa('etiquetar', [m.mailId, ETIQUETA, CUENTA, m.messageId || '']);
  mutarEstado(e => { for (const h of hermanos) if (e[h.id]) e[h.id].etiquetada = true; });
  return true;
}
async function reintentarEtiquetas() {
  const estado = leerJSON(F('estado.json'), {});
  const pendientes = new Set();
  for (const [id, d] of Object.entries(estado))
    if (TERMINAL.includes(d.decision) && !d.etiquetada && d.etiquetada !== 'imposible')
      pendientes.add(baseDe(id));
  for (const baseId of pendientes) {
    try { await etiquetarSiCompleto(baseId); }
    catch {
      mutarEstado(e => {
        for (const [id, d] of Object.entries(e)) {
          if (baseDe(id) !== baseId || d.etiquetada) continue;
          d.intentosEtiqueta = (d.intentosEtiqueta || 0) + 1;
          if (d.intentosEtiqueta >= 6) d.etiquetada = 'imposible';
        }
      });
    }
  }
}

// ---------------------------------------------------------------- refresco de la cola
let refrescando = false;
async function refrescar() {
  if (refrescando) throw new Error('ya hay un refresco en marcha');
  refrescando = true;
  try {
    const inventario = await osa('listar', [String(CFG.diasVentana || 45), CUENTA], 600000);
    const vistos = new Set();
    const mensajes = [];
    for (const linea of inventario.split('\n')) {
      const c = linea.split('\t');
      if (c[0] === 'ERR' || c.length < 6) continue;
      if (vistos.has(c[0])) continue;            // el buzón puede moverse durante la pasada
      vistos.add(c[0]);
      const n = c.length;
      mensajes.push({ mailId: c[0], messageId: c[1], remitente: c[2],
                      asunto: c.slice(3, n - 3).join(' ').trim(),
                      fecha: c[n - 3], nAdj: parseInt(c[n - 2], 10) || 0,
                      etiquetas: (c[n - 1] || '').split(';').filter(Boolean) });
    }
    const estado = leerJSON(F('estado.json'), {});
    const colaPrevia = leerJSON(F('cola.json'), { items: [] });

    // qué mensajes entran: sin etiqueta (candado 2); el candado 1 (decisión) es por ítem
    const nuevos = mensajes.filter(m => {
      m.id = sha8(m.messageId || m.mailId);
      return !m.etiquetas.includes(ETIQUETA);
    });

    // descarga de adjuntos (por mensaje; con rescate MIME si falla)
    for (const m of nuevos) {
      if (!m.nAdj) { m.adjuntos = []; continue; }
      const yaGuardados = fs.readdirSync(CORREOS).filter(f => f.startsWith(m.id + '_'));
      if (yaGuardados.length) { m.adjuntos = yaGuardados; continue; }
      let guardados = [];
      try {
        const res = await osa('guardar-adjuntos', [m.mailId, CORREOS, m.id, CUENTA]);
        if (/^OK/m.test(res)) guardados = fs.readdirSync(CORREOS).filter(f => f.startsWith(m.id + '_'));
      } catch { /* seguimos al rescate */ }
      if (!guardados.some(f => /\.pdf$/i.test(f))) {
        try {
          const raw = await osa('fuente', [m.mailId, CUENTA], 300000);
          guardados = guardados.concat(rescatarDeMime(raw, CORREOS, m.id));
        } catch { /* irrescatable */ }
      }
      m.adjuntos = fs.readdirSync(CORREOS).filter(f => f.startsWith(m.id + '_'));
      m.descargaFallida = m.nAdj > 0 && !m.adjuntos.some(f => /\.pdf$/i.test(f));
    }

    // mapa de correos para el extractor (clave = id8 del mensaje)
    fs.writeFileSync(F('mapa-correos.tsv'),
      nuevos.map(m => [m.id, m.remitente, m.asunto, m.fecha].map(limpiarCampo).join('\t')).join('\n'));
    regenerarOpciones();
    execFileSync('node', [EXTRACTOR, CORREOS, CONTROL,
      `--correos=${F('mapa-correos.tsv')}`, `--aprendizaje=${F('overrides.json')}`,
      `--salida=${DATOS}`, '--json'],
      { env: { ...process.env, NODE_PATH: NODE_PATH_XLSX }, timeout: 900000 });
    const extraccion = leerJSON(F('cola-extraccion.json'), { items: [] });
    const porArchivo = new Map(extraccion.items.map(i => [i.archivo, i]));
    const ovr = leerJSON(F('overrides.json'), {});
    const tanda = leerJSON(F('tanda.json'), {});
    const emailDe = r => (String(r).match(/<([^>]+)>/) || [, String(r).trim()])[1].toLowerCase();

    // montar cola: UN ÍTEM POR PDF (un correo puede traer varias facturas)
    const items = [];
    for (const m of nuevos) {
      const pdfs = (m.adjuntos || []).filter(f => /\.pdf$/i.test(f));
      const base = { mailId: m.mailId, messageId: m.messageId, remitente: m.remitente,
                     asunto: m.asunto, fechaCorreo: m.fecha };
      if (!pdfs.length) {
        if (!m.nAdj) continue;
        items.push({ ...base, id: m.id, archivo: null, adjuntos: [], hermanos: 1,
                     extraccion: null, propuesta: null, descargaFallida: true,
                     problemas: ['adjunto no descargable — abrir en Mail'], confianza: 'sin_pdf' });
        continue;
      }
      const reincidente = (ovr.remitentesNoFactura || {})[emailDe(m.remitente)];
      pdfs.forEach((pdf, idx) => {
        const ex = porArchivo.get(pdf) || null;
        const noFactura = ex && ex.estado === 'no_factura';
        items.push({ ...base,
          id: pdfs.length === 1 ? m.id : `${m.id}p${idx + 1}`,
          archivo: pdf, adjuntos: [pdf], hermanos: pdfs.length, nHermano: idx + 1,
          tanda: tanda[pdf] || tanda[m.id] || null,
          propuesta: ex && ex.propuesta ? ex.propuesta : null,
          extraccion: ex && ex.extraccion ? ex.extraccion : null,
          problemas: ex ? ex.problemas || [] : [],
          confianza: noFactura || (reincidente && reincidente.veces >= 2) ? 'no_factura'
                   : ex && ex.estado === 'lista' ? 'lista'
                   : ex && ex.estado === 'sin_texto' ? 'sin_texto' : 'revisar' });
      });
    }

    // arrastre: ítems sin decidir que han caducado de la ventana NO se pierden
    const idsNuevos = new Set(items.map(i => i.id));
    for (const viejo of colaPrevia.items || []) {
      if (idsNuevos.has(viejo.id)) continue;
      const d = estado[viejo.id];
      if (d && TERMINAL.includes(d.decision)) continue;
      // si su mensaje sigue en el inventario (p.ej. ya etiquetado), no se arrastra
      const sigue = mensajes.some(m => sha8(m.messageId || m.mailId) === baseDe(viejo.id));
      if (sigue) continue;
      items.push({ ...viejo, fueraDeVentana: true });
    }

    escribirAtomico(F('cola.json'), JSON.stringify({ generado: new Date().toISOString(), items }, null, 1));
    await reintentarEtiquetas();
    return { total: mensajes.length, enCola: items.length };
  } finally { refrescando = false; }
}

// ---------------------------------------------------------------- decisiones
const HEAD17 = ['Mes','Fecha','Factura','Número fact.','Importe','Vencim.','Código','Empresa','Verificado',
                'Área','Encargado','Concepto','Contabilidad','Forma de pago','Pagado','IVA','Cuenta de gasto'];
async function decidir(body) {
  const { id, accion, fila, motivo } = body;
  const cola = leerJSON(F('cola.json'), { items: [] });
  const item = cola.items.find(i => i.id === id);
  if (!item) throw new Error('correo no encontrado en la cola');
  // idempotencia: el doble clic (o una cola vieja) no duplica nada
  const previa = leerJSON(F('estado.json'), {})[id];
  if (previa && TERMINAL.includes(previa.decision)) return { ok: true, repetida: true };

  const ts = new Date().toISOString();
  const emailDe = r => (String(r).match(/<([^>]+)>/) || [, String(r).trim()])[1].toLowerCase();
  const eventos = [];

  if (accion === 'aprobar') {
    if (!fila) throw new Error('falta la fila');
    // aprobadas.tsv: append puro; columna 18 = id del ítem (se descarta al copiar)
    if (!fs.existsSync(F('aprobadas.tsv')))
      fs.writeFileSync(F('aprobadas.tsv'), HEAD17.concat('id').join('\t') + '\n');
    fs.appendFileSync(F('aprobadas.tsv'),
      HEAD17.map(h => limpiarCampo(fila[h])).concat(id).join('\t') + '\n');
    // correcciones implícitas — solo si HUBO propuesta que corregir
    let corrigio = false;
    if (item.propuesta) {
      for (const h of HEAD17) {
        const antes = String(item.propuesta[h] ?? ''), despues = String(fila[h] ?? '');
        if (antes === despues) continue;
        eventos.push({ ts, idCorreo: id, accion: 'corregir', proveedor: fila.Empresa || item.propuesta.Empresa || '',
                       remitente: emailDe(item.remitente), campo: h, valor_extraido: antes, valor_corregido: despues });
        corrigio = true;
      }
    }
    eventos.push({ ts, idCorreo: id, accion: 'aprobar_sin_cambios',
                   proveedor: fila.Empresa || '', remitente: emailDe(item.remitente),
                   numero_aprobado: fila['Número fact.'] || '', huboCambios: corrigio });
    mutarEstado(e => e[id] = { decision: 'aprobada', ts, etiquetada: false, pegada: false });
  } else if (accion === 'descartar') {
    eventos.push({ ts, idCorreo: id, accion: 'descartar', remitente: emailDe(item.remitente), motivo: motivo || '' });
    mutarEstado(e => e[id] = { decision: 'descartada', motivo: motivo || '', ts, etiquetada: false });
  } else if (accion === 'cerrar') {
    mutarEstado(e => e[id] = { decision: 'cerrada', motivo: motivo || 'ya registrada en el Control', ts, etiquetada: false });
  } else if (accion === 'saltar') {
    mutarEstado(e => e[id] = { decision: 'saltada', ts });
    return { ok: true };
  } else throw new Error('acción desconocida');

  if (eventos.length) registrarEventos(eventos);
  respaldar();
  let etiquetada = false;
  try { etiquetada = await etiquetarSiCompleto(baseDe(id)); }
  catch { /* reintento en el próximo refresco */ }
  return { ok: true, etiquetada, hermanosPendientes: !etiquetada && (item.hermanos || 1) > 1 };
}

// ---------------------------------------------------------------- http
const MIME = { '.html': 'text/html; charset=utf-8', '.pdf': 'application/pdf', '.json': 'application/json' };
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const enviar = (code, obj, tipo) => {
    res.writeHead(code, { 'Content-Type': tipo || 'application/json; charset=utf-8' });
    res.end(typeof obj === 'string' || Buffer.isBuffer(obj) ? obj : JSON.stringify(obj));
  };
  // anti-CSRF: los POST solo pueden venir de la propia página
  if (req.method === 'POST') {
    const origen = req.headers.origin;
    if (origen && !origen.startsWith('http://127.0.0.1') && !origen.startsWith('http://localhost'))
      return enviar(403, { error: 'origen no permitido' });
  }
  const cuerpo = () => new Promise(r => {
    let b = '';
    req.on('data', c => b += c);
    req.on('end', () => { try { r(b ? JSON.parse(b) : {}); } catch { r({}); } });
  });
  try {
    if (req.method === 'GET' && url.pathname === '/')
      return enviar(200, fs.readFileSync(path.join(AQUI, 'app', 'index.html')), MIME['.html']);
    if (req.method === 'GET' && url.pathname === '/api/cola') {
      const cola = leerJSON(F('cola.json'), { items: [] });
      const estado = leerJSON(F('estado.json'), {});
      const pendientes = cola.items.filter(i => !estado[i.id] || estado[i.id].decision === 'saltada');
      pendientes.sort((a, b) => String(b.fechaCorreo).localeCompare(String(a.fechaCorreo)));
      const aprobadasSinPegar = Object.values(estado).filter(d => d.decision === 'aprobada' && !d.pegada).length;
      return enviar(200, { generado: cola.generado, pendientes, aprobadasSinPegar,
                           hechasHoy: Object.values(estado).filter(d => d.ts && d.ts.slice(0, 10) === new Date().toISOString().slice(0, 10) && d.decision !== 'saltada').length });
    }
    if (req.method === 'GET' && url.pathname.startsWith('/pdf/')) {
      const ruta = path.join(CORREOS, path.basename(decodeURIComponent(url.pathname.slice(5))));
      if (!fs.existsSync(ruta)) return enviar(404, { error: 'no existe' });
      return enviar(200, fs.readFileSync(ruta), MIME['.pdf']);
    }
    if (req.method === 'POST' && url.pathname === '/api/cuerpo') {
      const { id } = await cuerpo();
      const cache = path.join(DATOS, 'cuerpos');
      fs.mkdirSync(cache, { recursive: true });
      const f = path.join(cache, path.basename(baseDe(id)) + '.txt');
      if (fs.existsSync(f)) return enviar(200, { texto: fs.readFileSync(f, 'utf8') });
      const cola = leerJSON(F('cola.json'), { items: [] });
      const item = cola.items.find(i => i.id === id);
      if (!item) return enviar(404, { error: 'correo no encontrado' });
      const texto = await osa('cuerpo', [item.mailId, CUENTA], 120000);
      fs.writeFileSync(f, texto);
      return enviar(200, { texto });
    }
    if (req.method === 'GET' && url.pathname === '/api/opciones') {
      if (!fs.existsSync(F('opciones.json'))) regenerarOpciones();
      const op = leerJSON(F('opciones.json'), { selects: {}, listas: {}, conceptosPorEmpresa: {} });
      // los conceptos aprobados EN LA HERRAMIENTA van primero (lo último de JJB)
      if (fs.existsSync(F('aprobadas.tsv'))) {
        const filas = fs.readFileSync(F('aprobadas.tsv'), 'utf8').trim().split('\n').slice(1);
        for (const l of filas.reverse()) {
          const c = l.split('\t');
          const emp = (c[7] || '').trim(), con = (c[11] || '').trim();
          if (!emp || !con) continue;
          const lista = op.conceptosPorEmpresa[emp] = op.conceptosPorEmpresa[emp] || [];
          const i = lista.indexOf(con);
          if (i !== -1) lista.splice(i, 1);
          lista.unshift(con);
        }
      }
      return enviar(200, op);
    }
    if (req.method === 'GET' && url.pathname === '/api/aprobadas') {
      if (!fs.existsSync(F('aprobadas.tsv'))) return enviar(200, { filas: [] });
      const lineas = fs.readFileSync(F('aprobadas.tsv'), 'utf8').trim().split('\n').slice(1);
      const estado = leerJSON(F('estado.json'), {});
      const filas = [];
      for (const l of lineas) {
        const c = l.split('\t');
        const idFila = c[17] || '';
        if (idFila && (estado[idFila] || {}).pegada) continue;
        filas.push({ id: idFila, tsv: c.slice(0, 17).join('\t') });
      }
      return enviar(200, { filas });
    }
    if (req.method === 'POST' && url.pathname === '/api/refrescar')
      return enviar(200, await refrescar());
    if (req.method === 'POST' && url.pathname === '/api/decision')
      return enviar(200, await decidir(await cuerpo()));
    if (req.method === 'POST' && url.pathname === '/api/abrir') {
      const { id, archivo } = await cuerpo();
      if (archivo) { execFile('open', [path.join(CORREOS, path.basename(archivo))]); return enviar(200, { ok: true }); }
      const cola = leerJSON(F('cola.json'), { items: [] });
      const item = cola.items.find(i => i.id === id);
      if (item) await osa('abrir-mensaje', [item.mailId, CUENTA]);
      return enviar(200, { ok: true });
    }
    if (req.method === 'POST' && url.pathname === '/api/copiadas') {
      const { ids } = await cuerpo();
      mutarEstado(e => {
        for (const id of ids || [])
          if (e[id] && e[id].decision === 'aprobada') e[id].pegada = true;
      });
      respaldar();
      return enviar(200, { ok: true });
    }
    enviar(404, { error: 'ruta desconocida' });
  } catch (e) { enviar(500, { error: e.message }); }
});
server.listen(PUERTO, '127.0.0.1', () => {
  console.log(`Repaso de facturas en http://127.0.0.1:${PUERTO}`);
  console.log(`Datos en ${DATOS} · cuenta Mail "${CUENTA}" · etiqueta "${ETIQUETA}"`);
  asegurarSemilla();
  compilarOverrides();   // primera pasada tras el arreglo: corrige contadores inflados
  respaldar();
  // el diálogo de permisos de Automatización, mejor ahora que a mitad de sesión
  osa('listar', ['0', CUENTA]).catch(() => {});
});
server.on('error', e => {
  if (e.code === 'EADDRINUSE') { console.log('Ya hay una instancia en marcha; abre el navegador.'); process.exit(0); }
  throw e;
});

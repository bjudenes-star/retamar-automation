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

for (const d of [DATOS, CORREOS]) fs.mkdirSync(d, { recursive: true });

const F = n => path.join(DATOS, n);
const leerJSON = (f, defecto) => { try { return JSON.parse(fs.readFileSync(f, 'utf8')); } catch { return defecto; } };
const escribirAtomico = (f, contenido) => { fs.writeFileSync(f + '.tmp', contenido); fs.renameSync(f + '.tmp', f); };
const sha8 = s => crypto.createHash('sha1').update(String(s)).digest('hex').slice(0, 8);

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
    const nombre = `${prefijo}_m${n}_${fm[1]}`;
    fs.writeFileSync(path.join(destino, nombre), buf);
    guardados.push(nombre);
  }
  return guardados;
}

// ---------------------------------------------------------------- aprendizaje
function registrarEventos(eventos) {
  fs.appendFileSync(F('aprendizaje.jsonl'), eventos.map(e => JSON.stringify(e)).join('\n') + '\n');
  compilarOverrides();
}
const plantillaDe = s => String(s).replace(/\d/g, '9').replace(/[A-Za-z]/g, 'A');
function compilarOverrides() {
  const ov = leerJSON(F('overrides.json'), { porProveedor: {}, aliasRemitente: {}, remitentesNoFactura: {} });
  ov.porProveedor = ov.porProveedor || {}; ov.aliasRemitente = ov.aliasRemitente || {}; ov.remitentesNoFactura = ov.remitentesNoFactura || {};
  if (!fs.existsSync(F('aprendizaje.jsonl'))) return;
  // se recompila desde cero el bloque derivado del JSONL (los datos sembrados a mano se conservan)
  for (const linea of fs.readFileSync(F('aprendizaje.jsonl'), 'utf8').split('\n')) {
    if (!linea.trim()) continue;
    let e; try { e = JSON.parse(linea); } catch { continue; }
    if (e.accion === 'corregir' && e.proveedor && e.campo) {
      const p = ov.porProveedor[e.proveedor] = ov.porProveedor[e.proveedor] || {};
      p.campos = p.campos || {};
      const c = p.campos[e.campo] = p.campos[e.campo] || { valor: '', veces: 0 };
      c.valor = e.valor_corregido; c.veces++; c.ultima = e.ts;
      if (e.campo === 'Empresa' && e.remitente) ov.aliasRemitente[e.remitente] = e.valor_corregido;
    }
    if ((e.accion === 'aprobar_sin_cambios' || e.accion === 'corregir') && e.proveedor && e.numero_aprobado) {
      const p = ov.porProveedor[e.proveedor] = ov.porProveedor[e.proveedor] || {};
      p.plantillasNumero = p.plantillasNumero || {};
      const pl = plantillaDe(e.numero_aprobado);
      const t = p.plantillasNumero[pl] = p.plantillasNumero[pl] || { veces: 0, ejemplo: e.numero_aprobado };
      t.veces++;
    }
    if (e.accion === 'aprobar_sin_cambios' && e.proveedor) {
      const p = ov.porProveedor[e.proveedor] = ov.porProveedor[e.proveedor] || {};
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

// ---------------------------------------------------------------- refresco de la cola
let refrescando = false;
async function refrescar() {
  if (refrescando) throw new Error('ya hay un refresco en marcha');
  refrescando = true;
  try {
    const estado = leerJSON(F('estado.json'), {});
    const inventario = await osa('listar', [String(CFG.diasVentana || 45), CUENTA], 600000);
    const mensajes = [];
    for (const linea of inventario.split('\n')) {
      const c = linea.split('\t');
      if (c[0] === 'ERR' || c.length < 6) continue;
      mensajes.push({ mailId: c[0], messageId: c[1], remitente: c[2], asunto: c[3],
                      fecha: c[4], nAdj: parseInt(c[5], 10) || 0, etiquetas: (c[6] || '').split(';').filter(Boolean) });
    }
    // qué mensajes entran: sin decisión terminal Y sin la etiqueta (doble candado)
    const nuevos = [];
    for (const m of mensajes) {
      m.id = sha8(m.messageId || m.mailId);
      const dec = estado[m.id];
      if (dec && ['aprobada', 'descartada'].includes(dec.decision)) continue;
      if (m.etiquetas.includes(ETIQUETA)) continue;
      nuevos.push(m);
    }
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
    // mapa de correos para el extractor (clave = id8)
    const mapa = nuevos.map(m => [m.id, m.remitente, m.asunto, m.fecha].join('\t')).join('\n');
    fs.writeFileSync(F('mapa-correos.tsv'), mapa);
    // extracción
    execFileSync('node', [EXTRACTOR, CORREOS, CONTROL,
      `--correos=${F('mapa-correos.tsv')}`, `--aprendizaje=${F('overrides.json')}`,
      `--salida=${DATOS}`, '--json'],
      { env: { ...process.env, NODE_PATH: NODE_PATH_XLSX }, timeout: 600000 });
    const extraccion = leerJSON(F('cola-extraccion.json'), { items: [] });
    const porArchivo = new Map(extraccion.items.map(i => [i.archivo, i]));
    // overrides de tipo "remitente que nunca manda facturas"
    const ovr = leerJSON(F('overrides.json'), {});
    const emailDe = r => (String(r).match(/<([^>]+)>/) || [, String(r).trim()])[1].toLowerCase();
    // montar cola
    const items = [];
    for (const m of nuevos) {
      const pdfs = (m.adjuntos || []).filter(f => /\.pdf$/i.test(f));
      const base = { id: m.id, mailId: m.mailId, messageId: m.messageId, remitente: m.remitente,
                     asunto: m.asunto, fechaCorreo: m.fecha, descargaFallida: !!m.descargaFallida };
      if (!pdfs.length) {
        if (!m.nAdj) continue; // correos sin adjuntos no entran en la cola
        items.push({ ...base, adjuntos: [], extraccion: null, propuesta: null,
                     problemas: ['adjunto no descargable — abrir en Mail'], confianza: 'sin_pdf' });
        continue;
      }
      const ex = pdfs.map(p => porArchivo.get(p)).filter(Boolean);
      const principal = ex.find(e => e.estado === 'lista') || ex.find(e => e.estado === 'revisar') || ex[0] || null;
      const noFactura = principal && principal.estado === 'no_factura';
      const reincidente = (ovr.remitentesNoFactura || {})[emailDe(m.remitente)];
      items.push({ ...base, adjuntos: pdfs,
        propuesta: principal && principal.propuesta ? principal.propuesta : null,
        extraccion: principal && principal.extraccion ? principal.extraccion : null,
        problemas: principal ? principal.problemas || [] : [],
        confianza: noFactura || (reincidente && reincidente.veces >= 2) ? 'no_factura'
                 : principal && principal.estado === 'lista' ? 'lista'
                 : principal && principal.estado === 'sin_texto' ? 'sin_texto' : 'revisar' });
    }
    escribirAtomico(F('cola.json'), JSON.stringify({ generado: new Date().toISOString(), items }, null, 1));
    // reintento de etiquetas pendientes
    await reintentarEtiquetas(estado, mensajes);
    return { total: mensajes.length, enCola: items.length };
  } finally { refrescando = false; }
}

async function reintentarEtiquetas(estado, mensajes) {
  const porId = new Map((mensajes || []).map(m => [sha8(m.messageId || m.mailId), m]));
  let cambiado = false;
  for (const [id, d] of Object.entries(estado)) {
    if (!['aprobada', 'descartada'].includes(d.decision) || d.etiquetada) continue;
    const m = porId.get(id); if (!m) continue;
    try { await osa('etiquetar', [m.mailId, ETIQUETA, CUENTA]); d.etiquetada = true; cambiado = true; }
    catch { /* la próxima vez */ }
  }
  if (cambiado) escribirAtomico(F('estado.json'), JSON.stringify(estado, null, 1));
}

// ---------------------------------------------------------------- decisiones
const HEAD17 = ['Mes','Fecha','Factura','Número fact.','Importe','Vencim.','Código','Empresa','Verificado',
                'Área','Encargado','Concepto','Contabilidad','Forma de pago','Pagado','IVA','Cuenta de gasto'];
async function decidir(body) {
  const { id, accion, fila, motivo } = body;
  const cola = leerJSON(F('cola.json'), { items: [] });
  const item = cola.items.find(i => i.id === id);
  if (!item) throw new Error('correo no encontrado en la cola');
  const estado = leerJSON(F('estado.json'), {});
  const ts = new Date().toISOString();
  const emailDe = r => (String(r).match(/<([^>]+)>/) || [, String(r).trim()])[1].toLowerCase();
  const eventos = [];

  if (accion === 'aprobar') {
    if (!fila) throw new Error('falta la fila');
    // aprobadas.tsv: SIEMPRE añadir al final, nunca regenerar
    if (!fs.existsSync(F('aprobadas.tsv')))
      fs.writeFileSync(F('aprobadas.tsv'), HEAD17.join('\t') + '\n');
    fs.appendFileSync(F('aprobadas.tsv'), HEAD17.map(h => String(fila[h] ?? '').replace(/\t/g, ' ')).join('\t') + '\n');
    // correcciones implícitas: propuesta vs fila enviada
    const prop = item.propuesta || {};
    let corrigio = false;
    for (const h of HEAD17) {
      const antes = String(prop[h] ?? ''), despues = String(fila[h] ?? '');
      if (antes === despues) continue;
      eventos.push({ ts, idCorreo: id, accion: 'corregir', proveedor: fila.Empresa || prop.Empresa || '',
                     remitente: emailDe(item.remitente), campo: h, valor_extraido: antes, valor_corregido: despues });
      corrigio = true;
    }
    // el número aprobado siempre refuerza la plantilla del proveedor
    eventos.push({ ts, idCorreo: id, accion: 'aprobar_sin_cambios',
                   proveedor: fila.Empresa || '', remitente: emailDe(item.remitente),
                   numero_aprobado: fila['Número fact.'] || '', huboCambios: corrigio });
    estado[id] = { decision: 'aprobada', ts, etiquetada: false, pegada: false };
  } else if (accion === 'descartar') {
    eventos.push({ ts, idCorreo: id, accion: 'descartar', remitente: emailDe(item.remitente), motivo: motivo || '' });
    estado[id] = { decision: 'descartada', motivo: motivo || '', ts, etiquetada: false };
  } else if (accion === 'saltar') {
    estado[id] = { decision: 'saltada', ts };
  } else throw new Error('acción desconocida');

  escribirAtomico(F('estado.json'), JSON.stringify(estado, null, 1));
  if (eventos.length) registrarEventos(eventos);
  // etiquetar (si falla, la decisión ya está guardada y se reintenta luego)
  if (['aprobar', 'descartar'].includes(accion)) {
    try { await osa('etiquetar', [item.mailId, ETIQUETA, CUENTA]); estado[id].etiquetada = true;
          escribirAtomico(F('estado.json'), JSON.stringify(estado, null, 1)); }
    catch { /* reintento en el próximo refresco */ }
  }
  return { ok: true, etiquetada: estado[id].etiquetada || false };
}

// ---------------------------------------------------------------- http
const MIME = { '.html': 'text/html; charset=utf-8', '.pdf': 'application/pdf', '.json': 'application/json' };
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, 'http://x');
  const enviar = (code, obj, tipo) => {
    res.writeHead(code, { 'Content-Type': tipo || 'application/json; charset=utf-8' });
    res.end(typeof obj === 'string' || Buffer.isBuffer(obj) ? obj : JSON.stringify(obj));
  };
  const cuerpo = () => new Promise(r => { let b = ''; req.on('data', c => b += c); req.on('end', () => r(b ? JSON.parse(b) : {})); });
  try {
    if (req.method === 'GET' && url.pathname === '/')
      return enviar(200, fs.readFileSync(path.join(AQUI, 'app', 'index.html')), MIME['.html']);
    if (req.method === 'GET' && url.pathname === '/api/cola') {
      const cola = leerJSON(F('cola.json'), { items: [] });
      const estado = leerJSON(F('estado.json'), {});
      const pendientes = cola.items.filter(i => !estado[i.id] || estado[i.id].decision === 'saltada');
      const orden = { lista: 0, revisar: 1, sin_texto: 2, sin_pdf: 3, no_factura: 4 };
      pendientes.sort((a, b) => (orden[a.confianza] ?? 9) - (orden[b.confianza] ?? 9));
      const aprobadasSinPegar = Object.values(estado).filter(d => d.decision === 'aprobada' && !d.pegada).length;
      return enviar(200, { generado: cola.generado, pendientes, aprobadasSinPegar,
                           hechasHoy: Object.values(estado).filter(d => d.ts && d.ts.slice(0, 10) === new Date().toISOString().slice(0, 10) && d.decision !== 'saltada').length });
    }
    if (req.method === 'GET' && url.pathname.startsWith('/pdf/')) {
      const nombre = decodeURIComponent(url.pathname.slice(5));
      const ruta = path.join(CORREOS, path.basename(nombre));
      if (!fs.existsSync(ruta)) return enviar(404, { error: 'no existe' });
      return enviar(200, fs.readFileSync(ruta), MIME['.pdf']);
    }
    if (req.method === 'GET' && url.pathname === '/api/aprobadas') {
      return enviar(200, fs.existsSync(F('aprobadas.tsv')) ? fs.readFileSync(F('aprobadas.tsv'), 'utf8') : '', 'text/plain; charset=utf-8');
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
      const estado = leerJSON(F('estado.json'), {});
      for (const d of Object.values(estado)) if (d.decision === 'aprobada' && !d.pegada) d.pegada = true;
      escribirAtomico(F('estado.json'), JSON.stringify(estado, null, 1));
      return enviar(200, { ok: true });
    }
    enviar(404, { error: 'ruta desconocida' });
  } catch (e) { enviar(500, { error: e.message }); }
});
server.listen(PUERTO, '127.0.0.1', () => {
  console.log(`Repaso de facturas en http://127.0.0.1:${PUERTO}`);
  console.log(`Datos en ${DATOS} · cuenta Mail "${CUENTA}" · etiqueta "${ETIQUETA}"`);
  // el diálogo de permisos de Automatización, mejor ahora que a mitad de sesión
  osa('listar', ['0', CUENTA]).catch(() => {});
});
server.on('error', e => {
  if (e.code === 'EADDRINUSE') { console.log('Ya hay una instancia en marcha; abre el navegador.'); process.exit(0); }
  throw e;
});

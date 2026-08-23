#!/usr/bin/env node
// Saca del Control las opciones para los desplegables de la SPA.
//   node opciones.js <control.xlsx> <destino.json>
const fs = require('fs');
const XLSX = require('xlsx');
const [,, CONTROL, DESTINO] = process.argv;
const F = XLSX.utils.sheet_to_json(XLSX.readFile(CONTROL).Sheets['Facturas'], { defval: '' });
const distintos = (campo, min = 2) => {
  const c = {};
  F.forEach(f => { const v = String(f[campo] || '').trim(); if (v) c[v] = (c[v] || 0) + 1; });
  return Object.entries(c).filter(([, n]) => n >= min).sort((a, b) => b[1] - a[1]).map(([v]) => v);
};
// próximas remesas (día 2) para Vencim.
const hoy = new Date();
const vencs = [];
for (let i = 0; i < 4; i++) {
  const d = new Date(Date.UTC(hoy.getFullYear(), hoy.getMonth() + i, 2));
  if (d > hoy) vencs.push(`02/${String(d.getUTCMonth() + 1).padStart(2, '0')}/${d.getUTCFullYear()}`);
}
const opciones = {
  // cerrados → <select>
  selects: {
    'Verificado': ['', 'Verificado'],
    'Contabilidad': ['Pendiente', 'Contabilizado'],
    'Forma de pago': ['Remesa', 'Domiciliado', 'Transferencia', 'Tarjeta', 'Efectivo'],
    'Pagado': ['', 'Pndt. Pago', 'Pagado'],
    'IVA': ['No Sujeto', 'Soportado', 'Repercutido', 'Comprobar'],
    'Vencim.': ['NO', ...vencs],
  },
  // abiertos con sugerencias → <input> + <datalist>
  listas: {
    'Empresa': distintos('Empresa', 1),
    'Área': distintos('Área'),
    'Encargado': distintos('Encargado'),
    'Cuenta de gasto': distintos('Cuenta de gasto'),
    'Código': distintos('Código'),
  },
  // conceptos POR proveedor, del más reciente al más antiguo (las filas vienen así)
  conceptosPorEmpresa: (() => {
    const m = {};
    for (const f of F) {
      const e = String(f.Empresa || '').trim(), c = String(f.Concepto || '').trim();
      if (!e || !c) continue;
      (m[e] = m[e] || []).includes(c) || m[e].push(c);
    }
    for (const e in m) m[e] = m[e].slice(0, 15);
    return m;
  })(),
};
fs.writeFileSync(DESTINO, JSON.stringify(opciones));
console.log('opciones generadas:', Object.entries(opciones.listas).map(([k, v]) => `${k}:${v.length}`).join(' · '));

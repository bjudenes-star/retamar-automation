# Repaso de facturas

Herramienta local para registrar las facturas de proveedores que llegan a
`facturacion@retamar.es`, correo a correo, sin tocar el Control de facturas oficial.

## Cómo se usa

1. Doble clic en **`Repaso Facturas.command`**. Se abre el navegador solo.
   (La primera vez macOS preguntará si Terminal puede controlar Mail: **Permitir**.)
2. **«Buscar correos nuevos»** — mira el buzón, descarga los PDFs y prepara una
   propuesta de fila para cada factura. Tarda un par de minutos.
3. Para cada correo: a la izquierda el PDF, a la derecha la fila propuesta.
   - **Aprobar** (o Intro): la fila queda guardada y el correo recibe la etiqueta `Registrada`.
   - Si algo está mal, **corrígelo en el campo y aprueba**: la herramienta apunta la
     corrección y la aplica sola la próxima vez que venga ese proveedor.
   - **No es factura**: para albaranes, fichas, publicidad… (pregunta el motivo).
   - **Saltar** (o S): lo deja para el final.
4. **«Copiar aprobadas»** — copia al portapapeles las filas aprobadas que aún no has
   pegado, listas para pegarlas en la hoja `Facturas` del Control (sin el símbolo €,
   para que entren como número).

## Qué aprende sola

- Correcciones de Código, Área, Encargado, Forma de pago, IVA, Cuenta y Concepto
  → se aplican al proveedor en adelante.
- Cada número aprobado → refuerza el formato de numeración del proveedor.
- Corregir la Empresa → asocia el remitente del correo a ese proveedor para siempre.
- Dos descartes del mismo remitente → sus correos llegan ya marcados «no parece factura»
  (pero siempre se muestran: la decisión es tuya).

## Dónde está cada cosa

- **Datos** (PDFs, cola, aprendizaje, aprobadas): `~/RepasoFacturas/` — fuera del
  repo público, nunca se suben a GitHub.
- **La copia del Control** que usa para proponer columnas: `~/RepasoFacturas/Control
  de facturas.xlsx`. Si el Sheets cambia mucho, descarga una copia fresca y reemplázala.
- La herramienta **no escribe** ni en el `.xlsx` oficial ni en el Google Sheets, y a los
  correos solo les **añade** la etiqueta `Registrada` (no borra, no archiva, no mueve).

## Si algo falla

- «El adjunto no se pudo descargar» → botón **Abrir en Mail** y rellenas mirándolo.
- La etiqueta no se puso (Mail cerrado, sin red) → se reintenta sola al abrir o refrescar.
- Permiso de Automatización denegado por error → Ajustes → Privacidad y seguridad →
  Automatización → Terminal → activar Mail.

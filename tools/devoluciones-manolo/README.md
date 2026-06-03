# Devoluciones de recibos → cartas a familias

Herramienta web para secretaría (Manolo). Cuando llega el **DETIR** de CaixaBank (PDF con los
recibos devueltos), cruza cada adeudo con el **padrón** de familias y genera **un único Word**
con una carta por familia, lista para revisar y enviar.

**URL:** https://bjudenes-star.github.io/retamar-automation/devoluciones-manolo/

## Privacidad (RGPD)

Todo el procesamiento ocurre **en el navegador del propio ordenador**. Ningún dato de las
familias se sube a internet ni sale del equipo. La página es estática: sólo carga código.

## Requisitos

- **Google Chrome** o **Microsoft Edge** en ordenador (la herramienta usa el acceso a carpetas
  del navegador, *File System Access API*, que no existe en Firefox/Safari).
- Una **carpeta de trabajo** que contenga:
  - el **padrón** en `.xlsx` (export *Vínculo PGA*), con la hoja `Hoja1` y la columna `FAMILIA`
    (además de `APELLIDOS`, `NOMBRE_PADRE`, `EMAIL_PADRE`, `NOMBRE_MADRE`, `EMAIL_MADRE`);
  - la **plantilla** de la carta en `.docx`, con sus campos de combinación
    (`Nomfam`, `NumFam`, `Concepto`, importe, total).

## Cómo se usa

1. **Elegir la carpeta de trabajo** (paso 1). El navegador pedirá permiso de lectura/escritura.
   La carpeta se recuerda entre sesiones; la próxima vez basta con pulsar *Reconectar*.
2. **Arrastrar el DETIR** (el PDF de CaixaBank) a la zona del paso 2.
3. Revisar el **resultado del cruce** (paso 3):
   - *Familias que reciben carta*: con apellidos, nº de recibos, total y correos.
   - *A revisar*: adeudos que no casan automáticamente (referencia sin código, familia que no
     está en el padrón, código especial, o familia sin email). Estos se resuelven a mano.
4. **Generar las cartas** (paso 4). Se crea el Word en la subcarpeta `Cartas/` de la carpeta de
   trabajo, con nombre `Cartas_devoluciones_AAAAMMDD.docx` (no sobrescribe: añade ` (2)`, ` (3)`…).

## Cómo cruza los datos

- **Por código (caso normal):** la referencia única numérica del DETIR contiene el código de
  cliente `43XXXXXX`; tras el prefijo de cuenta de clientes `430` queda el **nº de familia**
  (p. ej. `43009459` → familia `9459`), que se busca en la columna `FAMILIA` del padrón.
- **Por nombre (referencias `ESA…`):** no llevan código, así que el titular del recibo (el padre
  o la madre que paga) se normaliza y se compara con `NOMBRE_PADRE`/`NOMBRE_MADRE` del padrón.
- Varios recibos de una misma familia el mismo mes → **una sola carta** (tabla con una fila por
  recibo y una fila de **TOTAL**).

> La línea de *“importe total pendiente”* (saldo de Sage) queda fuera de esta versión; el hueco
> está preparado en el código para integrarla en el futuro.

## Despliegue

Ya está activo: el repositorio es **público** y Pages usa **GitHub Actions** como origen, así que
cada `push` a `main` vuelve a desplegar automáticamente (workflow `.github/workflows/pages.yml`).

> Si alguna vez hubiera que reactivarlo a mano: **Settings → Pages → Source = GitHub Actions**.

## Estructura

```
tools/devoluciones-manolo/
├── index.html        ← toda la herramienta (UI + lógica de cruce + combinación del Word)
├── vendor/           ← librerías locales (sin CDN: la red del centro bloquea descargas externas)
│   ├── pdf.min.mjs · pdf.worker.min.mjs   (pdf.js — leer el DETIR)
│   ├── xlsx.full.min.js                   (SheetJS — leer el padrón)
│   └── pizzip.min.js                      (abrir/escribir el .docx)
└── README.md
```

Las librerías se sirven desde la propia página (mismo origen), por lo que funciona aunque la red
bloquee CDN externos.

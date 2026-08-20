#!/bin/bash
cd "$(dirname "$0")"
DATOS="$HOME/RepasoFacturas"
# la librería xlsx tiene que sobrevivir a los reinicios
if [ ! -d "$DATOS/lib/node_modules/xlsx" ]; then
  if [ -d /tmp/xlsxlib/node_modules/xlsx ]; then
    mkdir -p "$DATOS/lib" && cp -R /tmp/xlsxlib/node_modules "$DATOS/lib/"
  else
    echo "⚠ Falta la librería xlsx (ni en $DATOS/lib ni en /tmp/xlsxlib)."
    echo "  Avisa a Claude para reinstalarla. La herramienta no puede arrancar."
    read -p "Pulsa Intro para cerrar…"; exit 1
  fi
fi
node server.js &
SERVIDOR=$!
sleep 1
open "http://127.0.0.1:8734"
echo "Repaso de facturas en marcha. Cierra esta ventana para pararlo."
wait $SERVIDOR

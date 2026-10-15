# modo_operacion_common.sh — se incluye con "source" (modo_operacion.sh,
# decidir_objetivo.sh). Sin cfg.py adentro: cada script pasa los valores que
# ya leyo en su unica llamada (cada python3 cuesta ~0.4s de CPU en la placa).

modo_valido() { [ "$1" = "ventana" ] || [ "$1" = "permanente" ]; }

# modo_vigente <modo_operacion_file> <starlink.modo_defecto>: el del archivo
# si existe y es valido; si no el defecto; si tampoco, "ventana" (el que
# menos bateria gasta) con un aviso por stderr.
modo_vigente() {
  local modo
  modo=$(sed -n '1p' "$1" 2>/dev/null || true)
  if modo_valido "$modo"; then
    echo "$modo"
  elif modo_valido "$2"; then
    echo "$2"
  else
    echo "AVISO: starlink.modo_defecto='$2' no es valido, se usa 'ventana'" >&2
    echo "ventana"
  fi
}

#!/bin/bash
# enviar_paquete.sh — manda un paquete de actualizacion a la placa y lo deja
# listo para aplicar, SIN tocar nada de lo instalado: queda en
# /root/actualizacion/<id>/ con su MANIFIESTO verificado.
#
# Pensado para Starlink: si la copia se corta, se reintenta (el archivo se
# verifica completo por sha256 del lado de la placa antes de desempacar).
# No lanza la actualizacion: eso es un paso aparte y explicito.
#
# Uso: bash scripts_campo/actualizacion/enviar_paquete.sh root@<IP> paquetes_actualizacion/actualizacion_<id>.tgz
set -euo pipefail
DESTINO="${1:?uso: $0 root@<IP> <paquete.tgz>}"
PAQUETE="${2:?uso: $0 root@<IP> <paquete.tgz>}"
[ -f "$PAQUETE" ] && [ -f "$PAQUETE.sha256" ] || { echo "falta $PAQUETE o su .sha256" >&2; exit 1; }
NOMBRE=$(basename "$PAQUETE")
ID=${NOMBRE#actualizacion_}; ID=${ID%.tgz}
SSH="ssh -o BatchMode=yes -o ConnectTimeout=20 -o ServerAliveInterval=15"

$SSH "$DESTINO" "mkdir -p /root/actualizacion/entrante"
for intento in 1 2 3 4 5; do
    if scp -q -o ConnectTimeout=20 "$PAQUETE" "$PAQUETE.sha256" "$DESTINO:/root/actualizacion/entrante/" \
       && $SSH "$DESTINO" "cd /root/actualizacion/entrante && sha256sum -c --quiet $NOMBRE.sha256"; then
        echo "== paquete en la placa y verificado (intento $intento)"
        break
    fi
    echo "== intento $intento fallido, reintento en 20s" >&2
    [ "$intento" -eq 5 ] && { echo "ERROR: no se pudo mandar el paquete" >&2; exit 1; }
    sleep 20
done

$SSH "$DESTINO" "set -e
cd /root/actualizacion
rm -rf $ID
tar -xzf entrante/$NOMBRE
cd $ID/archivos && sha256sum -c --quiet ../MANIFIESTO
echo '== desempacado y MANIFIESTO verificado en /root/actualizacion/$ID'
cat ../VERSION"
echo
echo "Para aplicar (en la placa, se desacopla solo):"
echo "  ssh $DESTINO 'bash /root/actualizacion/$ID/aplicar_actualizacion.sh'"
echo "Seguirlo: ssh $DESTINO 'journalctl -u actualizacion -f'"

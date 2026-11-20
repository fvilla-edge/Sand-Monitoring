#!/bin/bash
# probar_sin_internet.sh — corre en la NOTEBOOK (Linux), no en la placa.
# Demuestra que la web de la placa anda por cable directo sin internet:
# apaga el WiFi, confirma que no hay internet, prueba la placa por el cable
# y vuelve a prender el WiFi al terminar (pase lo que pase).
#
# Uso:   bash probar_sin_internet.sh [interfaz_cableada]
set -u

IFACE="${1:-$(nmcli -t -f DEVICE,TYPE dev | awk -F: '$2=="ethernet"{print $1; exit}')}"
PLACA=rp-f0fd8c.local

wifi_previo=$(nmcli radio wifi)
restaurar() {
    if [ "$wifi_previo" = "enabled" ]; then
        nmcli radio wifi on
        echo "WiFi vuelto a prender."
    fi
}
trap restaurar EXIT

echo "Interfaz cableada: ${IFACE:-ninguna}"
if [ -z "$IFACE" ] || [ "$(cat /sys/class/net/"$IFACE"/carrier 2>/dev/null)" != "1" ]; then
    echo "FALLA: el cable no tiene enlace (sin luz/carrier). Revisar cable, adaptador y"
    echo "       prender la placa DESPUES de enchufar el cable. Internet no tiene nada que ver."
    exit 1
fi

echo "1) Apago el WiFi..."
nmcli radio wifi off
sleep 3

echo "2) ¿Hay internet?"
if curl -s -m 5 -o /dev/null https://www.google.com; then
    echo "   SI hay internet (por otra via): la prueba no es valida, desconectarla tambien."
    exit 1
fi
echo "   NO hay internet. Bien."

echo "3) Busco la placa por el cable..."
ip_placa=""
for _ in $(seq 1 20); do
    ip_placa=$(getent ahostsv4 "$PLACA" | awk 'NR==1{print $1}')
    [ -z "$ip_placa" ] && ip_placa=$(ip neigh show dev "$IFACE" | awk '/lladdr 00:26:32/{print $1; exit}')
    [ -n "$ip_placa" ] && break
    sleep 2
done
if [ -z "$ip_placa" ]; then
    echo "   FALLA: no encuentro la placa en $IFACE."
    exit 1
fi
echo "   Placa en $ip_placa ($PLACA)"

echo "4) Latencia:"
ping -c 10 -i 0.2 -q "$ip_placa" | tail -1

echo "5) Pagina web:"
ok=1
for u in / /get_sysinfo /scopegenpro/ /spectrumpro/; do
    r=$(curl -s -m 5 -o /dev/null -w "%{http_code} %{time_total}s" "http://$ip_placa$u")
    echo "   $u -> $r"
    case "$r" in 200*) ;; *) ok=0 ;; esac
done

if [ $ok = 1 ]; then
    echo "RESULTADO: OK. Sin internet la web de la placa anda por el cable."
    echo "Abrir en el navegador:  http://$PLACA/   (o http://$ip_placa/)"
else
    echo "RESULTADO: FALLA en la web (ver arriba)."
    exit 1
fi

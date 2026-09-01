#!/bin/bash
# Dummy que imita a scripts_campo_comun/repetir_captura.sh para probar el
# disparo por comando MQTT (comandos_losant/escuchar_comandos.py) sin
# hardware de captura ni tocar publicar_losant.py real. No hace nada mas
# que mostrar lo que recibio y dormir un rato fijo (no proporcional a los
# minutos reales) para tener tiempo de mandar un segundo comando mientras
# "corre" y confirmar que se rechaza.
echo "simular_captura.sh: lanzado con argv: $*"
sleep 60
echo "simular_captura.sh: terminado"

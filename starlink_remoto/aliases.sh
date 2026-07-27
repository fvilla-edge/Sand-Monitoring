# Alias para controlar el rele de Starlink a mano por SSH.
# Instalar en /root/.bashrc de la Red Pitaya (ver COMANDOS.md, seccion Starlink / control remoto del rele).

alias prender-starlink='/root/starlink_remoto/starlink_manual.sh on'
alias apagar-starlink='/root/starlink_remoto/starlink_manual.sh off'
alias auto-starlink='/root/starlink_remoto/starlink_manual.sh auto'
alias estado-starlink='/root/starlink_remoto/estado_starlink.sh'

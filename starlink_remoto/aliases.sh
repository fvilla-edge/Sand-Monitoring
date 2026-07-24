# Alias para controlar el rele de Starlink a mano por SSH.
# Instalar en /root/.bashrc de la Red Pitaya (ver COMANDOS.md, seccion Starlink / control remoto del rele).

alias prender-starlink='systemctl start starlink-rele@on.service'
alias apagar-starlink='systemctl start starlink-rele@off.service'

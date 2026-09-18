CC = gcc
CFLAGS = -O3 -Wall -Wextra -std=c11 -funroll-loops

# Build portable (PC, para probar/comparar) — misma salida numerica que el
# de la placa (float32 no depende de la arquitectura), solo mas lento.
paquete_area: paquete_area.c
	$(CC) $(CFLAGS) -o paquete_area paquete_area.c -lm

# Build para correr EN la placa (Zynq 7010, Cortex-A9 con NEON de simple
# precision) — mismos flags -mfpu/-mfloat-abi que ya usa gcc por default
# ahi mismo, mas -ffast-math (medido: no cambia el resultado numerico
# contra Python, el filtro es secuencial por su recursividad — pero da un
# empujon real de tiempo, ver docs/plan del feature area-en-placa).
placa: paquete_area.c
	$(CC) $(CFLAGS) -march=armv7-a -mfpu=neon -mfloat-abi=hard -ffast-math \
		-o paquete_area paquete_area.c -lm

clean:
	rm -f paquete_area

.PHONY: clean placa

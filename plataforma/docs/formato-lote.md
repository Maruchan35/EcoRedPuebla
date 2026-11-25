# Formato del archivo de la microSD (lote)

Es el contrato entre el firmware del nodo y la plataforma. El nodo escribe un CSV; Protección Civil
lo descarga en su visita y lo sube en **Recolección** (o la app lo manda a `POST /api/sincronizacion`).

```
t,ph,cond,turb,color,temp,nivel,bateria,muestra,hash
2026-11-23T21:40:00-06:00,7.21,985,56,3.41,18.4,1.10,74,,3b1f…
2026-11-23T21:50:00-06:00,7.19,2650,88,10.9,18.5,1.11,74,M-0021,a90c…
```

| Columna | Obligatoria | Qué es |
|---|---|---|
| `t` | sí | Fecha y hora del reloj DS3231. ISO 8601 (`2026-11-23T21:40:00-06:00`), o segundos/milisegundos desde 1970. Sin zona se toma como hora del centro (UTC−6). |
| `ph` | al menos una medición | pH |
| `cond` | | Conductividad, µS/cm |
| `turb` | | Turbidez, NTU |
| `color` | | Coeficiente de absorción a 620 nm, m⁻¹ |
| `temp` | | Temperatura, °C |
| `nivel` | | Nivel del agua, m |
| `bateria` | no | Porcentaje de batería (0–100). Se guarda el último valor. |
| `muestra` | no | Folio del frasco cuando el carrusel tomó muestra en esa lectura (por ejemplo `M-0021`). |
| `hash` | no | Huella encadenada (ver abajo). |

### Columnas de la estación piloto (opcionales)
El nodo que tiene estación de tratamiento a su lado (hoy N3, estación EP-1) agrega estas columnas antes de `hash`:

```
t,ph,cond,turb,color,temp,nivel,bateria,muestra,caudal,turb_sal,color_sal,cond_sal,ph_sal,lodos,dp_filtro,solar,hash
```

| Columna | Unidad | Qué es | Rango válido |
|---|---|---|---|
| `caudal` | L/s | Agua que entra a la estación desde la captación | 0–50 |
| `turb_sal` | NTU | Turbidez del agua tratada, a la salida del humedal | 0–10,000 |
| `color_sal` | m⁻¹ | Color (absorción a 620 nm) a la salida | 0–1,000 |
| `cond_sal` | µS/cm | Conductividad a la salida | 0–100,000 |
| `ph_sal` | | pH a la salida | 0–14 |
| `lodos` | % | Llenado del sedimentador; baja de golpe cuando se purga | 0–100 |
| `dp_filtro` | kPa | Presión diferencial de los filtros; a 24 kPa toca retrolavado | 0–500 |
| `solar` | W | Potencia que entrega el panel solar | 0–2,000 |

Con ellas la plataforma calcula agua tratada al día, remoción por parámetro, sólidos retenidos, energía
y la bitácora de mantenimiento. Los nodos sin estación no las escriben.

- Se aceptan los alias `fecha_hora`, `conductividad`, `turbidez`, `temperatura`, `folio`, `huella`.
- Separador coma o punto y coma (con punto y coma se acepta coma decimal, como exporta Excel en español).
- Una lectura cada 10 minutos; una por minuto mientras el nodo detecta una anomalía.
- Límites: 5 MB y 60,000 filas por archivo.
- **Nombra el archivo empezando con el id del nodo** (`N3_2026-11-23.csv`). Si el nombre dice `N3` y en la
  plataforma se elige otro nodo, la carga se rechaza: evita mezclar archivos al visitar varios nodos.

## Qué hace el servidor con cada fila
- Descarta la fila si la fecha no se puede leer, está en el futuro (reloj sin pila) o ya existe para ese nodo.
- Descarta un valor suelto si está fuera del rango físico (pH 0–14, temperatura −5 a 60 °C, etc.): sonda desconectada.
- Subir dos veces el mismo archivo no duplica nada.

## Huella encadenada (para que el archivo sirva como evidencia)

```
hash_0 = id del nodo                       (por ejemplo "N3")
hash_i = SHA-256( hash_{i-1} + "|" + "t,ph,cond,turb,color,temp,nivel" )   en hexadecimal
```

La cadena entre comillas es el texto de esas siete columnas **tal cual quedó escrito en el archivo**,
unidas con comas. Si alguien cambia una fila, la plataforma marca el lote como «Alterado desde la fila N»
y los casos que salgan de él llevan una advertencia. Si la primera fila no coincide, el archivo no es de
ese nodo y la carga se rechaza. Las columnas de la estación piloto todavía no entran en la huella.

En el ESP32 con Arduino se puede calcular con `mbedtls/sha256.h`, que viene con el core. Implementación
de referencia en Python: `server/lotes.py` (`huella` y `a_csv`).

## Archivo de ejemplo
En **Recolección → Archivo de ejemplo** se descarga un CSV con este formato exacto y valores simulados
(normal, con descarga textil o con crecida). Sirve para comparar byte por byte con lo que escribe el nodo.
El de N3 trae también las columnas de la estación piloto.

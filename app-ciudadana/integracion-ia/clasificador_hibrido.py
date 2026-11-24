"""Clasificador híbrido de daño hídrico para EcoRed Puebla.

Pensado para conectarse en `plataforma/server/main.py` dentro de `clasificar_foto(ruta)`.
Capas:
  1. Si existe `GEMINI_API_KEY` y hay conectividad, consulta Gemini Vision (`gemini-2.5-flash`)
     para clasificar basura, tuberías clandestinas, espuma, agua de color, animal muerto o mal olor.
  2. Si no hay API key o falla internet, ejecuta análisis óptico local (100 % sin internet)
     para detectar coloración anómala (tintes textiles NOM-001) y espuma superficial.
  3. Si la confianza es insuficiente, devuelve `None` para que prevalezca la etiqueta
     enviada por el teléfono o la categoría elegida por el ciudadano.
"""
from __future__ import annotations

import base64
import colorsys
import json
import os
import struct
import urllib.error
import urllib.request
import zlib
from pathlib import Path
from typing import Iterable, Optional, Tuple

CATEGORIAS_VALIDAS = (
    "Agua de color",
    "Espuma",
    "Basura",
    "Descarga de tubería",
    "Mal olor",
    "Animal muerto",
)

MIME_POR_EXT = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _clasificar_gemini(datos: bytes, mime: str, api_key: str, timeout: float = 4.5) -> Optional[Tuple[str, float]]:
    """Consulta opcional a Gemini Vision usando solo biblioteca estándar."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
    prompt = (
        "Eres un inspector ambiental en la cuenca del Alto Atoyac (Puebla). "
        "Clasifica la fotografía en exactamente una de estas categorías: "
        + ", ".join(CATEGORIAS_VALIDAS)
        + ", o \"sin_clasificar\" si no se aprecia contaminación hídrica clara. "
        "Responde solo JSON válido con las llaves \"categoria\" y \"confianza\" (número entre 0 y 1)."
    )
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(datos).decode("ascii"),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
        texto = cuerpo["candidates"][0]["content"]["parts"][0]["text"]
        resultado = json.loads(texto)
        cat = str(resultado.get("categoria", "")).strip()
        conf = float(resultado.get("confianza", 0.0))
        if cat in CATEGORIAS_VALIDAS and 0.55 <= conf <= 1.0:
            return (cat, round(conf, 2))
    except Exception:
        return None
    return None


def _leer_png_puro(datos: bytes) -> Optional[Tuple[int, int, list]]:
    """Decodificador mínimo de PNG RGB/RGBA sin filtros complejos (respaldo sin Pillow/OpenCV)."""
    if not datos.startswith(b"\x89PNG\r\n\x1a\n"):
        return None
    pos = 8
    ancho = alto = 0
    color_type = bit_depth = 0
    idat = bytearray()
    while pos + 8 <= len(datos):
        largo = struct.unpack(">I", datos[pos : pos + 4])[0]
        tipo = datos[pos + 4 : pos + 8]
        bloque = datos[pos + 8 : pos + 8 + largo]
        pos += 12 + largo
        if tipo == b"IHDR" and len(bloque) >= 13:
            ancho, alto, bit_depth, color_type = struct.unpack(">IIBB", bloque[:10])
        elif tipo == b"IDAT":
            idat.extend(bloque)
        elif tipo == b"IEND":
            break
    if bit_depth != 8 or color_type not in (2, 6) or ancho <= 0 or alto <= 0:
        return None
    bpp = 3 if color_type == 2 else 4
    crudo = zlib.decompress(bytes(idat))
    stride = ancho * bpp
    if len(crudo) < alto * (1 + stride):
        return None

    # Muestreo uniforme a máximo 96x96 para mantener latencia < 20 ms
    paso_x = max(1, ancho // 96)
    paso_y = max(1, alto // 96)
    pixeles = []
    prev = bytearray(stride)
    for y in range(alto):
        inicio = y * (1 + stride)
        filtro = crudo[inicio]
        fila = bytearray(crudo[inicio + 1 : inicio + 1 + stride])
        if filtro == 1:
            for i in range(bpp, stride):
                fila[i] = (fila[i] + fila[i - bpp]) & 0xFF
        elif filtro == 2:
            for i in range(stride):
                fila[i] = (fila[i] + prev[i]) & 0xFF
        elif filtro == 3:
            for i in range(stride):
                izq = fila[i - bpp] if i >= bpp else 0
                fila[i] = (fila[i] + ((izq + prev[i]) >> 1)) & 0xFF
        elif filtro == 4:
            for i in range(stride):
                a = fila[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                fila[i] = (fila[i] + pr) & 0xFF
        prev = fila
        if y % paso_y == 0:
            for x in range(0, ancho, paso_x):
                idx = x * bpp
                pixeles.append((y / max(1, alto - 1), fila[idx], fila[idx + 1], fila[idx + 2]))
    return (ancho, alto, pixeles)


def _extraer_muestra_rgb(ruta: Path, datos: bytes) -> Optional[list]:
    """Extrae lista de (y_norm, r, g, b) usando OpenCV, Pillow o lector PNG puro."""
    try:
        import cv2  # type: ignore
        import numpy as np  # type: ignore

        arr = np.frombuffer(datos, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            img = cv2.resize(img, (96, 96), interpolation=cv2.INTER_AREA)
            h, w = img.shape[:2]
            out = []
            for y in range(h):
                yn = y / max(1, h - 1)
                for x in range(w):
                    b, g, r = int(img[y, x, 0]), int(img[y, x, 1]), int(img[y, x, 2])
                    out.append((yn, r, g, b))
            return out
    except Exception:
        pass

    try:
        from PIL import Image  # type: ignore
        import io

        with Image.open(io.BytesIO(datos)) as im:
            im = im.convert("RGB").resize((96, 96))
            w, h = im.size
            raw = list(im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata())
            return [(idx // w / max(1, h - 1), r, g, b) for idx, (r, g, b) in enumerate(raw)]
    except Exception:
        pass

    png = _leer_png_puro(datos)
    if png:
        return png[2]
    return None


def _analisis_optico_local(pixeles: Iterable[Tuple[float, int, int, int]]) -> Optional[Tuple[str, float]]:
    """Clasificación óptica local sin internet enfocada en colorimetría anómala y espuma."""
    muestra = [p for p in pixeles if 0.20 <= p[0] <= 0.96]
    if len(muestra) < 16:
        return None

    total = len(muestra)
    tinte_azul_violeta = 0
    tinte_rojo_magenta = 0
    tinte_negro_denso = 0
    espuma_blanca = 0
    agua_oscura = 0

    for _, r, g, b in muestra:
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        deg = h * 360.0

        # Tintes textiles (azul índigo / cian industrial / violeta)
        if s >= 0.34 and v >= 0.14 and 190.0 <= deg <= 305.0 and b > r + 18:
            tinte_azul_violeta += 1
        # Tintes rojizos / magenta intensos (no tierra parda)
        elif s >= 0.45 and v >= 0.18 and (deg >= 325.0 or deg <= 14.0) and r > g + 30:
            tinte_rojo_magenta += 1
        # Vertidos de tinta / aceite negro espeso muy oscuro y opaco
        elif v <= 0.11 and s <= 0.35:
            tinte_negro_denso += 1

        # Espuma blanca/crema sobre superficie de agua más oscura
        if v >= 0.80 and s <= 0.18:
            espuma_blanca += 1
        elif v <= 0.52:
            agua_oscura += 1

    prop_color = max(tinte_azul_violeta, tinte_rojo_magenta) / total
    prop_negro = tinte_negro_denso / total
    prop_espuma = espuma_blanca / total
    prop_oscura = agua_oscura / total

    if prop_color >= 0.26:
        conf = min(0.95, 0.66 + prop_color * 0.40)
        return ("Agua de color", round(conf, 2))
    if prop_negro >= 0.58:
        conf = min(0.86, 0.58 + prop_negro * 0.30)
        return ("Agua de color", round(conf, 2))
    # La espuma requiere coexistencia de parches blancos brillantes y agua oscura alrededor
    if 0.12 <= prop_espuma <= 0.72 and prop_oscura >= 0.20:
        conf = min(0.91, 0.64 + prop_espuma * 0.42)
        return ("Espuma", round(conf, 2))

    return None


def clasificar_foto(ruta) -> Optional[Tuple[str, float]]:
    """Devuelve (categoria, confianza) o None si no puede determinarse con certeza."""
    try:
        path = Path(ruta)
        if not path.is_file():
            return None
        datos = path.read_bytes()
        if not datos:
            return None

        api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        if api_key:
            mime = MIME_POR_EXT.get(path.suffix.lower(), "image/jpeg")
            res_nube = _clasificar_gemini(datos, mime, api_key)
            if res_nube:
                return res_nube

        pixeles = _extraer_muestra_rgb(path, datos)
        if not pixeles:
            return None
        return _analisis_optico_local(pixeles)
    except Exception:
        return None

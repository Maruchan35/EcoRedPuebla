"""Pruebas unitarias sin internet para el clasificador híbrido de EcoRed Puebla."""
import os
import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from clasificador_hibrido import clasificar_foto


def _escribir_png(ruta: Path, ancho: int, alto: int, generador_pixel) -> None:
    filas = bytearray()
    for y in range(alto):
        filas.append(0)
        for x in range(ancho):
            r, g, b = generador_pixel(x, y, ancho, alto)
            filas.extend((r, g, b))

    def _chunk(tipo: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tipo + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tipo + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", ancho, alto, 8, 2, 0, 0, 0)
    png = (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(bytes(filas)))
        + _chunk(b"IEND", b"")
    )
    ruta.write_bytes(png)


class TestClasificadorHibrido(unittest.TestCase):
    def setUp(self) -> None:
        self._old_key = os.environ.pop("GEMINI_API_KEY", None)
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self) -> None:
        if self._old_key is not None:
            os.environ["GEMINI_API_KEY"] = self._old_key
        self.tmp.cleanup()

    def test_detecta_agua_azul_textil(self) -> None:
        p = self.dir / "agua_azul.png"
        _escribir_png(p, 64, 64, lambda x, y, w, h: (22, 74, 178))
        res = clasificar_foto(p)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "Agua de color")
        self.assertGreaterEqual(res[1], 0.70)

    def test_detecta_espuma_sobre_agua_oscura(self) -> None:
        p = self.dir / "espuma.png"

        def pixel(x, y, w, h):
            # Parches de espuma blanca en la mitad inferior sobre agua turbia oscura
            if 24 <= y <= 50 and 16 <= x <= 48 and ((x // 4 + y // 4) % 2 == 0):
                return (242, 244, 240)
            return (42, 56, 48)

        _escribir_png(p, 64, 64, pixel)
        res = clasificar_foto(p)
        self.assertIsNotNone(res)
        self.assertEqual(res[0], "Espuma")
        self.assertGreaterEqual(res[1], 0.65)

    def test_agua_natural_grisacea_sin_clasificar(self) -> None:
        p = self.dir / "natural.png"
        _escribir_png(p, 64, 64, lambda x, y, w, h: (108, 114, 102))
        self.assertIsNone(clasificar_foto(p))

    def test_archivo_invalido_no_lanza_excepcion(self) -> None:
        p = self.dir / "corrupto.jpg"
        p.write_bytes(b"no-es-una-imagen")
        self.assertIsNone(clasificar_foto(p))


if __name__ == "__main__":
    unittest.main()

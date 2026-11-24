/* =========================================================
   Lector ligero de coordenadas GPS en metadatos EXIF (JPEG)
   Se ejecuta antes de comprimir en Canvas para conservar la ubicación real.
   ========================================================= */

function leerEntero16(view, offset, littleEndian) {
  return view.getUint16(offset, littleEndian);
}

function leerEntero32(view, offset, littleEndian) {
  return view.getUint32(offset, littleEndian);
}

function leerRacional(view, offset, littleEndian) {
  const num = view.getUint32(offset, littleEndian);
  const den = view.getUint32(offset + 4, littleEndian);
  return den ? num / den : 0;
}

function leerCadena(view, offset, count) {
  let out = "";
  for (let i = 0; i < count; i++) {
    const code = view.getUint8(offset + i);
    if (code === 0) break;
    out += String.fromCharCode(code);
  }
  return out;
}

function dmsADecimal(dms, ref) {
  if (!Array.isArray(dms) || dms.length < 3) return null;
  const val = dms[0] + dms[1] / 60 + dms[2] / 3600;
  if (!Number.isFinite(val)) return null;
  return ref === "S" || ref === "W" ? -val : val;
}

export function extraerExifGps(arrayBuffer) {
  try {
    const view = new DataView(arrayBuffer);
    if (view.byteLength < 12 || view.getUint16(0, false) !== 0xffd8) {
      return null;
    }

    let offset = 2;
    while (offset + 4 < view.byteLength) {
      const marker = view.getUint16(offset, false);
      offset += 2;
      if (marker === 0xffe1) {
        if (offset + 8 > view.byteLength) return null;
        const length = view.getUint16(offset, false);
        if (leerCadena(view, offset + 2, 4) !== "Exif") {
          offset += length;
          continue;
        }
        const tiffStart = offset + 8;
        if (tiffStart + 8 > view.byteLength) return null;

        const endianTag = view.getUint16(tiffStart, false);
        const little = endianTag === 0x4949;
        if (!little && endianTag !== 0x4d4d) return null;

        const ifd0Offset = leerEntero32(view, tiffStart + 4, little);
        const ifd0Abs = tiffStart + ifd0Offset;
        if (ifd0Abs + 2 > view.byteLength) return null;

        const entries = leerEntero16(view, ifd0Abs, little);
        let gpsIfdRel = null;
        for (let i = 0; i < entries; i++) {
          const entry = ifd0Abs + 2 + i * 12;
          if (entry + 12 > view.byteLength) break;
          const tag = leerEntero16(view, entry, little);
          if (tag === 0x8825) {
            gpsIfdRel = leerEntero32(view, entry + 8, little);
            break;
          }
        }
        if (gpsIfdRel === null) return null;

        const gpsAbs = tiffStart + gpsIfdRel;
        if (gpsAbs + 2 > view.byteLength) return null;
        const gpsCount = leerEntero16(view, gpsAbs, little);

        let latRef = "N";
        let lngRef = "W";
        let latDms = null;
        let lngDms = null;

        for (let i = 0; i < gpsCount; i++) {
          const entry = gpsAbs + 2 + i * 12;
          if (entry + 12 > view.byteLength) break;
          const tag = leerEntero16(view, entry, little);
          const type = leerEntero16(view, entry + 2, little);
          const count = leerEntero32(view, entry + 4, little);

          if (tag === 0x0001 && type === 2) {
            latRef = String.fromCharCode(view.getUint8(entry + 8)) || "N";
          } else if (tag === 0x0003 && type === 2) {
            lngRef = String.fromCharCode(view.getUint8(entry + 8)) || "W";
          } else if ((tag === 0x0002 || tag === 0x0004) && type === 5 && count >= 3) {
            const valOffset = tiffStart + leerEntero32(view, entry + 8, little);
            if (valOffset + 24 <= view.byteLength) {
              const dms = [
                leerRacional(view, valOffset, little),
                leerRacional(view, valOffset + 8, little),
                leerRacional(view, valOffset + 16, little),
              ];
              if (tag === 0x0002) latDms = dms;
              else lngDms = dms;
            }
          }
        }

        const lat = dmsADecimal(latDms, latRef);
        const lng = dmsADecimal(lngDms, lngRef);
        if (lat !== null && lng !== null && Math.abs(lat) <= 90 && Math.abs(lng) <= 180) {
          return { lat: Number(lat.toFixed(6)), lng: Number(lng.toFixed(6)) };
        }
        return null;
      }

      if ((marker & 0xff00) !== 0xff00) break;
      if (offset + 2 > view.byteLength) break;
      offset += view.getUint16(offset, false);
    }
  } catch {
    return null;
  }
  return null;
}

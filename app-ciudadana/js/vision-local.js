/* =========================================================
   Visión IA local en el navegador (Canvas API, 100 % sin internet)
   Detecta coloración anómala (tintes NOM-001) y espuma superficial.
   Devuelve ia_etiqueta = "" cuando requiere selección humana o modelo en nube.
   ========================================================= */

function rgbAHsv(r, g, b) {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const d = max - min;

  let h = 0;
  if (d !== 0) {
    if (max === rn) h = ((gn - bn) / d) % 6;
    else if (max === gn) h = (bn - rn) / d + 2;
    else h = (rn - gn) / d + 4;
    h *= 60;
    if (h < 0) h += 360;
  }
  const s = max === 0 ? 0 : d / max;
  return { h, s, v: max };
}

function rgbAHex(r, g, b) {
  const toHex = (n) => Math.max(0, Math.min(255, Math.round(n))).toString(16).padStart(2, "0");
  return `#${toHex(r)}${toHex(g)}${toHex(b)}`.toUpperCase();
}

export async function analizarImagenLocal(blob) {
  const vacio = {
    ia_etiqueta: "",
    ia_confianza: null,
    semaforo: "warn",
    severidadTexto: "Pendiente de categoría",
    colorHex: "#475569",
    resumen: "No se detectó tinte ni espuma dominante. Confirma la categoría visual si hay basura o tubería.",
    hallazgos: [],
  };

  if (!blob) return vacio;

  try {
    const url = URL.createObjectURL(blob);
    const img = await new Promise((resolve, reject) => {
      const el = new Image();
      el.onload = () => resolve(el);
      el.onerror = () => reject(new Error("No se pudo decodificar la imagen"));
      el.src = url;
    });
    URL.revokeObjectURL(url);

    const w = 160;
    const h = 160;
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0, w, h);

    const { data } = ctx.getImageData(0, 0, w, h);
    // Se pondera la región central e inferior para ignorar cielo superior
    const yIni = Math.floor(h * 0.2);
    const yFin = Math.floor(h * 0.96);
    const xIni = Math.floor(w * 0.08);
    const xFin = Math.floor(w * 0.92);

    let total = 0;
    let sumR = 0;
    let sumG = 0;
    let sumB = 0;
    let tinteAzulVioleta = 0;
    let tinteRojoMagenta = 0;
    let tinteNegroDenso = 0;
    let espumaBlanca = 0;
    let aguaOscura = 0;
    let turbidezParda = 0;

    for (let y = yIni; y < yFin; y++) {
      for (let x = xIni; x < xFin; x++) {
        const idx = (y * w + x) * 4;
        const r = data[idx];
        const g = data[idx + 1];
        const b = data[idx + 2];
        sumR += r;
        sumG += g;
        sumB += b;
        total++;

        const { h: deg, s, v } = rgbAHsv(r, g, b);

        if (s >= 0.34 && v >= 0.14 && deg >= 190 && deg <= 305 && b > r + 18) {
          tinteAzulVioleta++;
        } else if (s >= 0.45 && v >= 0.18 && (deg >= 325 || deg <= 14) && r > g + 30) {
          tinteRojoMagenta++;
        } else if (v <= 0.11 && s <= 0.35) {
          tinteNegroDenso++;
        }

        if (v >= 0.8 && s <= 0.18) {
          espumaBlanca++;
        } else if (v <= 0.52) {
          aguaOscura++;
        }

        if (deg >= 22 && deg <= 52 && s >= 0.25 && s <= 0.72 && v >= 0.2 && v <= 0.68) {
          turbidezParda++;
        }
      }
    }

    if (!total) return vacio;

    const colorHex = rgbAHex(sumR / total, sumG / total, sumB / total);
    const propAzul = tinteAzulVioleta / total;
    const propRojo = tinteRojoMagenta / total;
    const propColor = Math.max(propAzul, propRojo);
    const propNegro = tinteNegroDenso / total;
    const propEspuma = espumaBlanca / total;
    const propOscura = aguaOscura / total;
    const propTurbidez = turbidezParda / total;

    const hallazgos = [];
    if (propAzul >= 0.18) hallazgos.push(`Pigmentación azul o índigo (${Math.round(propAzul * 100)} % del cuadro)`);
    if (propRojo >= 0.18) hallazgos.push(`Pigmentación rojiza anómala (${Math.round(propRojo * 100)} % del cuadro)`);
    if (propNegro >= 0.45) hallazgos.push(`Coloración oscura densa (${Math.round(propNegro * 100)} % del cuadro)`);
    if (propEspuma >= 0.1) hallazgos.push(`Parches claros compatibles con espuma (${Math.round(propEspuma * 100)} %)`);
    if (propTurbidez >= 0.32) hallazgos.push(`Alta turbidez parda o arrastre de sólidos (${Math.round(propTurbidez * 100)} %)`);

    if (propColor >= 0.26) {
      const conf = Number(Math.min(0.95, 0.66 + propColor * 0.4).toFixed(2));
      return {
        ia_etiqueta: "Agua de color",
        ia_confianza: conf,
        semaforo: "crit",
        severidadTexto: "Severidad alta (color anómalo)",
        colorHex,
        resumen: "Coloración intensa compatible con descarga de tinte textil o químico (referencia NOM-001).",
        hallazgos,
      };
    }

    if (propNegro >= 0.58) {
      const conf = Number(Math.min(0.86, 0.58 + propNegro * 0.3).toFixed(2));
      return {
        ia_etiqueta: "Agua de color",
        ia_confianza: conf,
        semaforo: "crit",
        severidadTexto: "Severidad alta (agua oscura densa)",
        colorHex,
        resumen: "Superficie muy oscura compatible con descarga orgánica pesada o tinta concentrada.",
        hallazgos,
      };
    }

    if (propEspuma >= 0.12 && propEspuma <= 0.72 && propOscura >= 0.2) {
      const conf = Number(Math.min(0.91, 0.64 + propEspuma * 0.42).toFixed(2));
      return {
        ia_etiqueta: "Espuma",
        ia_confianza: conf,
        semaforo: "warn",
        severidadTexto: "Alerta por espuma superficial",
        colorHex,
        resumen: "Se detecta espuma blanca contrastante sobre el cauce, posible presencia de detergentes.",
        hallazgos,
      };
    }

    return {
      ...vacio,
      colorHex,
      hallazgos,
      resumen: hallazgos.length
        ? "Se observan indicios visuales moderados. El servidor completará el análisis de la foto al enviarla."
        : "Imagen lista. La plataforma clasificará el reporte automáticamente según la foto y la descripción.",
    };
  } catch {
    return vacio;
  }
}

export function inferirCategoriaAutomatica({ iaResultado, texto = "", tieneFoto = false }) {
  const txt = String(texto || "").toLowerCase();

  if (/\b(tubo|tuberia|tubería|ducto|descarga|caño|drenaje|desague|desagüe)\b/.test(txt)) {
    return "Descarga de tubería";
  }
  if (/\b(olor|apesta|fetido|fétido|hedor|quimico|químico|solvente|gasolina)\b/.test(txt)) {
    return "Mal olor";
  }
  if (/\b(animal|muerto|perro|ave|pez|peces|cadaver|cadáver)\b/.test(txt)) {
    return "Animal muerto";
  }
  if (/\b(basura|plastico|plástico|llanta|escombro|bolsa|botella|desecho|tapon|tapón)\b/.test(txt)) {
    return "Basura";
  }
  if (/\b(espuma|jabon|jabón|detergente)\b/.test(txt)) {
    return "Espuma";
  }
  if (/\b(azul|rojo|verde|negro|morado|tinte|color|pintura|turbia|turbio)\b/.test(txt)) {
    return "Agua de color";
  }

  if (iaResultado && iaResultado.ia_etiqueta) {
    return iaResultado.ia_etiqueta;
  }
  return tieneFoto ? "Basura" : "Agua de color";
}

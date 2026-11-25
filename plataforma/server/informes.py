"""Formatos de los informes descargables: Excel (.xlsx), CSV y PDF.

Aquí solo se da formato; los datos (ya filtrados según quién pide) los arma main.py.
- Excel con openpyxl: encabezado con color, filtros, primera fila fija, fechas reales (hora del centro) y anchos.
- CSV en UTF-8 con BOM, para que Excel en español abra bien los acentos.
- PDF con fpdf2 en tamaño carta: Helvetica trae los acentos del español; los pocos símbolos que no caben
  (flechas, ≈, guiones largos) se cambian por equivalentes.
"""
import csv
import io
from datetime import datetime, timedelta, timezone

from fpdf import FPDF
from fpdf.fonts import FontFace
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

LOCAL = timezone(timedelta(hours=-6))                     # hora del centro, sin horario de verano
AZUL = (15, 23, 42)
CELESTE = (3, 105, 161)


def fecha(ms):
    """Milisegundos → datetime local sin zona (así lo guarda Excel)."""
    return datetime.fromtimestamp(ms / 1000, LOCAL).replace(tzinfo=None) if ms else None


# ---------- Excel ----------
FORMATOS = {"fecha": "dd/mm/yyyy", "fechahora": "dd/mm/yyyy hh:mm", "0": "#,##0", "0.0": "#,##0.0", "0.00": "#,##0.00",
            "%": "0%"}


def xlsx(hojas, portada=None) -> bytes:
    """hojas: [(nombre, columnas, filas)] con columnas = [(clave, encabezado, ancho, formato)] y filas = [dict].
    portada: lista de (etiqueta, valor) para una primera hoja «Resumen»."""
    libro = Workbook()
    libro.remove(libro.active)
    if portada:
        hoja = libro.create_sheet("Resumen")
        hoja.column_dimensions["A"].width, hoja.column_dimensions["B"].width = 38, 60
        for i, (etiqueta, valor) in enumerate(portada, start=1):
            hoja.cell(i, 1, etiqueta).font = Font(bold=(i == 1), size=14 if i == 1 else 11)
            hoja.cell(i, 2, valor)
    encabezado = PatternFill("solid", fgColor="0F172A")
    for nombre, columnas, filas in hojas:
        # Excel no acepta : \ / ? * [ ] en el nombre de una hoja, y lo corta a 31 caracteres
        hoja = libro.create_sheet("".join(" " if ch in ':\\/?*[]' else ch for ch in nombre).strip()[:31])
        hoja.append([c[1] for c in columnas])
        for celda in hoja[1]:
            celda.font, celda.fill = Font(bold=True, color="FFFFFF"), encabezado
            celda.alignment = Alignment(vertical="center", wrap_text=True)
        for f in filas:
            hoja.append([f.get(c[0]) for c in columnas])
        for j, (_, _, ancho, formato) in enumerate(columnas, start=1):
            letra = get_column_letter(j)
            hoja.column_dimensions[letra].width = ancho
            if formato in FORMATOS:
                for (celda,) in hoja.iter_rows(min_row=2, min_col=j, max_col=j):
                    celda.number_format = FORMATOS[formato]
        hoja.freeze_panes = "A2"
        if filas:
            hoja.auto_filter.ref = f"A1:{get_column_letter(len(columnas))}{len(filas) + 1}"
    salida = io.BytesIO()
    libro.save(salida)
    return salida.getvalue()


def csv_bytes(columnas, filas) -> bytes:
    salida = io.StringIO()
    w = csv.writer(salida, lineterminator="\r\n")
    w.writerow([c[1] for c in columnas])
    for f in filas:
        fila = []
        for c in columnas:
            v = f.get(c[0])
            fila.append(v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else "" if v is None else v)
        w.writerow(fila)
    return ("﻿" + salida.getvalue()).encode("utf-8")


# ---------- PDF ----------
_CAMBIOS = {"→": "a", "←": "<-", "≈": "~", "—": "-", "–": "-", "…": "...", "⁻¹": "-1", "≤": "<=", "≥": ">=", "“": '"',
            "”": '"', "‘": "'", "’": "'", "•": "-", "✓": "si", "×": "x"}


def _t(texto) -> str:
    """Texto que cabe en la letra Helvetica de PDF (latin-1)."""
    s = "" if texto is None else str(texto)
    for a, b in _CAMBIOS.items():
        s = s.replace(a, b)
    return s.encode("latin-1", "replace").decode("latin-1")


class _Informe(FPDF):
    def __init__(self, titulo, pie):
        super().__init__(orientation="P", unit="mm", format="Letter")
        self.titulo, self.pie = titulo, pie
        self.set_margins(16, 16, 16)
        self.set_auto_page_break(auto=True, margin=18)

    def header(self):
        if self.page_no() > 1:
            self.set_font("helvetica", "", 8)
            self.set_text_color(100, 116, 139)
            self.cell(0, 6, _t(self.titulo), new_x="LMARGIN", new_y="NEXT")
            self.ln(2)

    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "", 8)
        self.set_text_color(100, 116, 139)
        self.cell(0, 6, _t(f"{self.pie} · Página {self.page_no()} de {{nb}}"), align="C")


def pdf(titulo, subtitulo, bloques, pie="EcoRed Puebla") -> bytes:
    """bloques: ("h", texto) | ("p", texto) | ("kpis", [(etiqueta, valor)]) | ("tabla", encabezados, filas, anchos)
    | ("lista", [textos]). Los anchos de tabla son proporciones."""
    doc = _Informe(titulo, pie)
    doc.add_page()
    # Banda de portada
    doc.set_fill_color(*AZUL)
    doc.rect(0, 0, doc.w, 34, style="F")
    doc.set_xy(16, 9)
    doc.set_text_color(255, 255, 255)
    doc.set_font("helvetica", "B", 17)
    doc.cell(0, 9, _t(titulo), new_x="LMARGIN", new_y="NEXT")
    doc.set_font("helvetica", "", 10)
    doc.set_text_color(203, 213, 225)
    doc.cell(0, 6, _t(subtitulo), new_x="LMARGIN", new_y="NEXT")
    doc.set_y(42)
    ancho_util = doc.w - doc.l_margin - doc.r_margin
    for bloque in bloques:
        tipo = bloque[0]
        doc.set_text_color(15, 23, 42)
        if tipo == "h":
            if doc.get_y() > doc.h - 50:
                doc.add_page()
            doc.ln(3)
            doc.set_font("helvetica", "B", 12.5)
            doc.set_text_color(*CELESTE)
            doc.cell(0, 8, _t(bloque[1]), new_x="LMARGIN", new_y="NEXT")
            doc.set_draw_color(226, 232, 240)
            doc.line(doc.l_margin, doc.get_y(), doc.w - doc.r_margin, doc.get_y())
            doc.ln(2)
        elif tipo == "p":
            doc.set_font("helvetica", "", 9.5)
            doc.multi_cell(0, 5, _t(bloque[1]), new_x="LMARGIN", new_y="NEXT")
            doc.ln(1)
        elif tipo == "lista":
            doc.set_font("helvetica", "", 9.5)
            for texto in bloque[1]:
                doc.multi_cell(0, 5, _t("- " + texto), new_x="LMARGIN", new_y="NEXT")
            doc.ln(1)
        elif tipo == "kpis":
            caja, por_fila = (ancho_util - 2 * 4) / 3, 3
            for i, (etiqueta, valor) in enumerate(bloque[1]):
                if i % por_fila == 0:
                    if i:
                        doc.ln(19)
                    y0 = doc.get_y()
                    if y0 > doc.h - 40:
                        doc.add_page()
                        y0 = doc.get_y()
                x = doc.l_margin + (i % por_fila) * (caja + 4)
                doc.set_fill_color(241, 245, 249)
                doc.rect(x, y0, caja, 16, style="F")
                doc.set_xy(x + 3, y0 + 2)
                doc.set_font("helvetica", "", 8)
                doc.set_text_color(71, 85, 105)
                doc.cell(caja - 6, 4, _t(etiqueta))
                doc.set_xy(x + 3, y0 + 7)
                doc.set_font("helvetica", "B", 13)
                doc.set_text_color(15, 23, 42)
                doc.cell(caja - 6, 7, _t(valor))
            doc.set_y(doc.get_y() + 12)
            doc.ln(2)
        elif tipo == "tabla":
            _, encabezados, filas, anchos = bloque
            doc.set_font("helvetica", "", 8.5)
            estilo = FontFace(emphasis="BOLD", color=(255, 255, 255), fill_color=AZUL)
            with doc.table(col_widths=anchos, text_align="LEFT", line_height=5.2, headings_style=estilo, cell_fill_color=(248, 250, 252),
                           cell_fill_mode="ROWS", borders_layout="HORIZONTAL_LINES") as tabla:
                fila = tabla.row()
                for h in encabezados:
                    fila.cell(_t(h))
                for f in filas:
                    fila = tabla.row()
                    for v in f:
                        fila.cell(_t(v))
            doc.ln(3)
    return bytes(doc.output())

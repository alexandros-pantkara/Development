"""Extract parcel boundaries from CAD-plotted survey drawings (topographic diagrams).

Reads the vertex coordinate table (ΕΓΣΑ 87 / EPSG:2100) printed on the sheet, works out
which vertices form the parcel ring from the drawing's own statement ("1,2,3,...,35,36,1"),
and checks the ring's computed area against the area stated on the drawing.

Only vector PDFs are handled — the text has to be real text, not a scan.

Outputs, per PDF:
    <stem>_vertices.csv     every vertex found in the coordinate table(s)
    <stem>_parcel.geojson   the parcel polygon in EPSG:2100 (only when the ring is complete)
    <stem>_report.json      metadata, PDF layers, area check and warnings
and one summary.csv for the whole run.

Usage:
    python extract_cad_pdf.py                          # everything in ../data/cad drawings
    python extract_cad_pdf.py drawing.pdf other.pdf -o out_dir
"""

import argparse
import csv
import json
import logging
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

logging.getLogger("pypdf").setLevel(logging.ERROR)
logging.getLogger("pdfminer").setLevel(logging.ERROR)

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_INPUT = SCRIPT_DIR.parent / "data" / "cad drawings"
DEFAULT_OUTPUT = SCRIPT_DIR.parent / "output" / "cad drawings"

EPSG = 2100

# ΕΓΣΑ 87 coordinates: easting has 6 integer digits, northing 7.
X_RE = re.compile(r"\d{6}\.\d{2,3}")
Y_RE = re.compile(r"\d{7}\.\d{2,3}")
# Some drawings print X and Y with no gap between them: 565304.9064194123.352
XY_RE = re.compile(r"(\d{6}\.\d{2,3})(\d{7}\.\d{2,3})")
ID_RE = re.compile(r"\d{1,3}")
X_RANGE = (100_000, 1_000_000)
Y_RANGE = (3_800_000, 4_700_000)

# "14375,02 m2", "7.106,33 τ.μ.", "5.031 ,92 m2"
AREA_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+)\s?,\s?(\d{2})(?!\d)\s*(?:m\s?2|m²|μ2|τ\.?\s?μ)",
    re.IGNORECASE,
)
# Text written with every character spaced out: "5 . 0 3 1 ,92"
SPACED_RE = re.compile(r"(?:[\d.,] ){2,}[\d.,]")
# "1,2,3....48,49,50", "1,2,3,...,35,36,1", "(1-2-3-4-......35-36-1)"
RING_RE = re.compile(r"(?<![\d.,])1\s?[,\-]\s?2\s?[,\-]\s?3(?:\s?[,\-.…]+\s?\d{1,3})+")


# --------------------------------------------------------------------------- text

def group_lines(chars):
    """Group upright characters into text lines, each a list of chars sorted left to right."""
    chars = sorted((c for c in chars if c.get("upright", True)), key=lambda c: (c["top"], c["x0"]))
    lines, current, line_top = [], [], None
    for c in chars:
        if current and abs(c["top"] - line_top) > 0.3 * c["size"]:
            lines.append(sorted(current, key=lambda ch: ch["x0"]))
            current = []
        if not current:
            line_top = c["top"]
        current.append(c)
    if current:
        lines.append(sorted(current, key=lambda ch: ch["x0"]))
    return lines


def tokenize_line(line):
    """Split a line of chars into tokens on spaces or horizontal gaps.

    Done by hand rather than with pdfplumber's extract_words: on a full A0 sheet, unrelated
    text sharing a row can make it break table cells into single characters.
    """
    tokens, current = [], []
    for c in line:
        if c["text"].isspace():
            if current:
                tokens.append(current)
            current = []
            continue
        if current and c["x0"] - current[-1]["x1"] > 0.3 * c["size"]:
            tokens.append(current)
            current = []
        current.append(c)
    if current:
        tokens.append(current)
    return [
        {
            "text": "".join(ch["text"] for ch in t),
            "x0": t[0]["x0"],
            "x1": t[-1]["x1"],
            "size": max(ch["size"] for ch in t),
        }
        for t in tokens
    ]


def _in_range(value, bounds):
    return bounds[0] <= value <= bounds[1]


def parse_vertex_rows(token_lines):
    """Find `ID X Y` (or `ID XY` run together) sequences.

    Returns a list of (id, x, y, decimals), where decimals is the fewest decimal places
    printed for that row's coordinates.
    """
    rows = []
    for tokens in token_lines:
        i = 0
        while i < len(tokens) - 1:
            tid = tokens[i]
            if not ID_RE.fullmatch(tid["text"]):
                i += 1
                continue
            nxt = tokens[i + 1]
            # The ID belongs to the row only when it sits close to the coordinates.
            if nxt["x0"] - tid["x1"] > 10 * tid["size"]:
                i += 1
                continue
            xs = ys = None
            used = 0
            m = XY_RE.fullmatch(nxt["text"])
            if m:
                xs, ys, used = m.group(1), m.group(2), 2
            elif X_RE.fullmatch(nxt["text"]) and i + 2 < len(tokens) and Y_RE.fullmatch(tokens[i + 2]["text"]):
                xs, ys, used = nxt["text"], tokens[i + 2]["text"], 3
            if xs is not None and _in_range(float(xs), X_RANGE) and _in_range(float(ys), Y_RANGE):
                decimals = min(len(xs.split(".")[1]), len(ys.split(".")[1]))
                rows.append((int(tid["text"]), float(xs), float(ys), decimals))
                i += used
            else:
                i += 1
    return rows


def parse_greek_number(integer_part, decimals):
    """'7.106' + '33' -> 7106.33 (Greek format: '.' thousands, ',' decimals)."""
    return float(integer_part.replace(".", "") + "." + decimals)


def find_stated_areas(text):
    """All areas written on the sheet, most frequent first."""
    text = SPACED_RE.sub(lambda m: m.group(0).replace(" ", ""), text)
    counts = Counter(parse_greek_number(m.group(1), m.group(2)) for m in AREA_RE.finditer(text))
    return [value for value, _ in counts.most_common()]


def find_ring_size(text):
    """Number of vertices in the parcel ring, read from statements like '1,2,3,...,35,36,1'."""
    sizes = Counter()
    for m in RING_RE.finditer(text):
        numbers = [int(n) for n in re.findall(r"\d+", m.group(0))]
        sizes[max(numbers)] += 1
    return sizes.most_common(1)[0][0] if sizes else None


# --------------------------------------------------------------------------- geometry

def shoelace_area(points):
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]))) / 2


def side_lengths(points):
    return [((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5 for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1])]


def area_tolerance(perimeter, decimals=3):
    """Largest area difference explained by rounding alone.

    The table prints coordinates rounded to `decimals`, while the stated area comes from the
    unrounded CAD geometry. Moving each vertex by at most half a unit in x and y changes the
    area by at most sqrt(2) * half_unit * perimeter; the stated area adds its own 0.005.
    """
    half_unit = 0.5 * 10 ** -decimals
    return 2 ** 0.5 * half_unit * perimeter + 0.005


# --------------------------------------------------------------------------- PDF

def read_pdf_info(path):
    reader = PdfReader(path)
    meta = {k.lstrip("/"): str(v) for k, v in (reader.metadata or {}).items()}
    layers = []
    oc = reader.trailer["/Root"].get("/OCProperties")
    if oc:
        layers = [str(o.get_object().get("/Name")) for o in oc.get_object().get("/OCGs", [])]
    page = reader.pages[0]
    return {
        "pages": len(reader.pages),
        "page_size_mm": [round(float(page.mediabox.width) / 72 * 25.4), round(float(page.mediabox.height) / 72 * 25.4)],
        "rotation": int(page.get("/Rotate", 0)),
        "metadata": meta,
        "layers": layers,
    }


def extract(path):
    path = Path(path)
    report = {"file": path.name, **read_pdf_info(path)}
    warnings = []

    vertices = {}
    coordinate_decimals = 3
    full_text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            full_text.append(page.extract_text() or "")
            token_lines = [tokenize_line(line) for line in group_lines(page.chars)]
            rows = parse_vertex_rows(token_lines)
            if rows and any(d == 2 for _, _, _, d in rows):
                coordinate_decimals = 2
            for vid, x, y, _ in rows:
                if vid in vertices:
                    px, py = vertices[vid]
                    if abs(px - x) > 0.001 or abs(py - y) > 0.001:
                        warnings.append(f"Vertex {vid} appears twice with different coordinates; kept the first.")
                    continue
                vertices[vid] = (x, y)
    text = "\n".join(full_text)
    if "(cid:" in text:
        warnings.append("Some text uses a font without a character map; parts of the Greek text are unreadable.")

    ring_size = find_ring_size(text)
    if ring_size:
        ring_source = "statement"
    else:
        ring_size = 0
        while ring_size + 1 in vertices:
            ring_size += 1
        ring_source = "inferred (consecutive IDs from 1)"
        warnings.append("No ring statement found; assumed the parcel is vertices 1..N with no gaps.")
    ring_ids = list(range(1, ring_size + 1))
    missing = [i for i in ring_ids if i not in vertices]

    stated = find_stated_areas(text)
    computed = None
    area_check = None
    sides = {}
    status = "no vertices found"
    if vertices:
        if missing:
            status = "incomplete ring"
            warnings.append(f"Ring vertices missing from the table: {missing}")
        elif ring_size < 3:
            status = "no ring"
        else:
            points = [vertices[i] for i in ring_ids]
            computed = round(shoelace_area(points), 2)
            sides = dict(zip(ring_ids, side_lengths(points)))
            tolerance = area_tolerance(sum(sides.values()), coordinate_decimals)
            matched = min(stated, key=lambda a: abs(a - computed)) if stated else None
            if matched is None:
                status = "no stated area"
            else:
                area_check = {"stated_m2": matched, "difference_m2": round(computed - matched, 3),
                              "tolerance_m2": round(tolerance, 3)}
                if abs(computed - matched) <= tolerance:
                    status = "ok"
                else:
                    status = "area mismatch"
                    warnings.append(f"Computed area {computed} m² differs from the stated {matched} m² "
                                    f"by more than coordinate rounding explains (±{tolerance:.3f} m²).")

    report.update({
        "status": status,
        "vertices_found": len(vertices),
        "ring_vertices": ring_size,
        "ring_source": ring_source,
        "computed_area_m2": computed,
        "stated_areas_m2": stated,
        "area_check": area_check,
        "warnings": warnings,
    })
    return report, vertices, ring_ids if not missing else [], sides


# --------------------------------------------------------------------------- output

def write_outputs(out_dir, stem, report, vertices, ring_ids, sides):
    ring = set(ring_ids)
    with open(out_dir / f"{stem}_vertices.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "x", "y", "in_parcel", "side_to_next_m"])
        for vid in sorted(vertices):
            x, y = vertices[vid]
            side = f"{sides[vid]:.3f}" if vid in sides else ""
            w.writerow([vid, f"{x:.3f}", f"{y:.3f}", vid in ring, side])

    if ring_ids:
        coords = [list(vertices[i]) for i in ring_ids] + [list(vertices[ring_ids[0]])]
        geojson = {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": f"urn:ogc:def:crs:EPSG::{EPSG}"}},
            "features": [{
                "type": "Feature",
                "properties": {
                    "source": report["file"],
                    "vertices": len(ring_ids),
                    "area_m2": report["computed_area_m2"],
                    "status": report["status"],
                },
                "geometry": {"type": "Polygon", "coordinates": [coords]},
            }],
        }
        (out_dir / f"{stem}_parcel.geojson").write_text(json.dumps(geojson, ensure_ascii=False, indent=1), encoding="utf-8")

    (out_dir / f"{stem}_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def collect_inputs(inputs):
    pdfs = []
    for item in inputs:
        p = Path(item)
        pdfs.extend(sorted(p.glob("*.pdf")) if p.is_dir() else [p])
    return pdfs


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("inputs", nargs="*", default=[str(DEFAULT_INPUT)], help="PDF files or folders")
    parser.add_argument("-o", "--output", default=str(DEFAULT_OUTPUT), help="output folder")
    args = parser.parse_args(argv)

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdfs = collect_inputs(args.inputs)
    if not pdfs:
        print("No PDF files found.", file=sys.stderr)
        return 1

    summary = []
    for pdf in pdfs:
        try:
            report, vertices, ring_ids, sides = extract(pdf)
        except Exception as exc:  # one bad file should not stop the batch
            print(f"FAILED  {pdf.name}: {exc}", file=sys.stderr)
            summary.append({"file": pdf.name, "status": f"error: {exc}"})
            continue
        write_outputs(out_dir, pdf.stem, report, vertices, ring_ids, sides)
        summary.append(report)
        print(f"{report['status']:<16} {pdf.name}: {report['vertices_found']} vertices, "
              f"area {report['computed_area_m2']} m² (stated {report['stated_areas_m2'][:3]})")
        for warning in report["warnings"]:
            print(f"    ! {warning}")

    fields = ["file", "status", "vertices_found", "ring_vertices", "computed_area_m2", "stated_areas_m2", "warnings"]
    with open(out_dir / "summary.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for row in summary:
            w.writerow({**row, "stated_areas_m2": "; ".join(map(str, row.get("stated_areas_m2", []))),
                        "warnings": " | ".join(row.get("warnings", []))})
    print(f"\nOutputs written to {out_dir}")
    return 0 if all(r.get("status") == "ok" for r in summary) else 2


if __name__ == "__main__":
    sys.exit(main())

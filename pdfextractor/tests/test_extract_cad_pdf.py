import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import extract_cad_pdf as ex  # noqa: E402

DATA = Path(__file__).resolve().parent.parent / "data" / "cad drawings"


def char(text, x0, top=100.0, size=10.0, width=6.0):
    return {"text": text, "x0": x0, "x1": x0 + width, "top": top, "size": size, "upright": True}


def chars_for(text, x0, **kw):
    return [char(c, x0 + i * 6.0, **kw) for i, c in enumerate(text)]


def tokens(*cells):
    """Build one token line from (text, x0) cells."""
    line = []
    for text, x0 in cells:
        line += chars_for(text, x0)
    return [ex.tokenize_line(sorted(line, key=lambda c: c["x0"]))]


# --------------------------------------------------------------------------- tokenizing

def test_adjacent_glyphs_form_one_token_and_gaps_split():
    line = chars_for("34", 148) + chars_for("603321.032", 184)
    assert [t["text"] for t in ex.tokenize_line(line)] == ["34", "603321.032"]


def test_space_character_splits_tokens():
    line = chars_for("1", 10) + [char(" ", 16, width=2)] + chars_for("2", 18)
    assert [t["text"] for t in ex.tokenize_line(line)] == ["1", "2"]


def test_group_lines_separates_rows_and_skips_vertical_text():
    rows = chars_for("12", 0, top=100) + chars_for("34", 0, top=117)
    rows.append({**char("9", 0, top=100.5), "upright": False})
    assert [[c["text"] for c in line] for line in ex.group_lines(rows)] == [["1", "2"], ["3", "4"]]


# --------------------------------------------------------------------------- vertex rows

def test_parses_spaced_row():
    assert ex.parse_vertex_rows(tokens(("49", 0), ("608991.495", 40), ("4104930.165", 120))) == [
        (49, 608991.495, 4104930.165, 3)
    ]


def test_parses_concatenated_xy_and_side_by_side_tables():
    rows = ex.parse_vertex_rows(tokens(("1", 0), ("565304.9064194123.352", 20), ("37", 200), ("565349.5264194092.567", 220)))
    assert rows == [(1, 565304.906, 4194123.352, 3), (37, 565349.526, 4194092.567, 3)]


def test_concatenated_xy_with_two_decimal_easting():
    assert ex.parse_vertex_rows(tokens(("5", 0), ("565304.904194123.35", 20))) == [(5, 565304.90, 4194123.35, 2)]


def test_id_far_from_coordinates_is_ignored():
    assert ex.parse_vertex_rows(tokens(("44", 0), ("608991.495", 400), ("4104930.165", 480))) == []


def test_out_of_range_northing_is_ignored():
    assert ex.parse_vertex_rows(tokens(("1", 0), ("608991.495", 20), ("9104930.165", 100))) == []


# --------------------------------------------------------------------------- statements

@pytest.mark.parametrize("text, expected", [
    ("εμβαδόν 14375,02 m2, που", [14375.02]),
    ("Ε = 7.106,33 τ.μ.", [7106.33]),
    ("= 5 . 0 3 1 ,92 m2", [5031.92]),
    ("5.031,92 τ.μ. και 5.031,92 τ.μ. Κάλυψη 200,00 m2", [5031.92, 200.0]),
])
def test_stated_areas(text, expected):
    assert ex.find_stated_areas(text) == expected


def test_ring_number_not_merged_with_following_area():
    # "35,36,1 7.106,33" — the trailing 1 closes the ring; 7.106 is the area.
    assert ex.find_ring_size("στοιχεία 1,2,3,...,35,36,1 7.106,33 τ.μ.") == 36
    assert ex.find_stated_areas("στοιχεία 1,2,3,...,35,36,1 7.106,33 τ.μ.") == [7106.33]


@pytest.mark.parametrize("text, expected", [
    ("«1,2,3....48,49,50»", 50),
    ("(1-2-3-4-......35-36-1)", 36),
    ("(1-2-3-4-....-34-35-36-1)", 36),
    ("χωρίς δήλωση", None),
])
def test_ring_size(text, expected):
    assert ex.find_ring_size(text) == expected


# --------------------------------------------------------------------------- geometry

def test_shoelace_area_and_sides():
    square = [(0, 0), (10, 0), (10, 10), (0, 10)]
    assert ex.shoelace_area(square) == 100
    assert ex.shoelace_area(square[::-1]) == 100
    assert ex.side_lengths(square) == [10, 10, 10, 10]


def test_area_tolerance_scales_with_perimeter_and_precision():
    assert ex.area_tolerance(400, 3) == pytest.approx(2 ** 0.5 * 0.0005 * 400 + 0.005)
    assert ex.area_tolerance(400, 2) > ex.area_tolerance(400, 3)


# --------------------------------------------------------------------------- sample drawings

SAMPLES = [
    ("survey drawing from CAD_1.pdf", 50, 50, 14375.02),
    ("survey drawing from CAD_2.pdf", 36, 36, 7106.33),
    ("survey drawing from CAD_3.pdf", 70, 36, 5031.92),
]


@pytest.mark.parametrize("name, found, ring, stated", SAMPLES)
def test_sample_drawings(name, found, ring, stated):
    path = DATA / name
    if not path.exists():
        pytest.skip(f"{name} not available")
    report, vertices, ring_ids, _ = ex.extract(path)
    assert report["status"] == "ok", report["warnings"]
    assert report["vertices_found"] == found
    assert ring_ids == list(range(1, ring + 1))
    assert report["area_check"]["stated_m2"] == stated

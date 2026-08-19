# Agent context

Notes for an AI assistant working on this repository. **You already have the code — this file only covers what the code does not tell you:** decisions and their reasons, findings from real runs, approaches that were tried and rejected, and work that is currently unfinished.

Written 2026-08-18. If something here contradicts the code, the code wins — say so rather than assuming this file is current.

---

## 1. Environment and constraints

- **ArcGIS Pro 3.7.1** on Windows 11. Every toolbox script runs *inside* an open Pro session via `arcpy.mp.ArcGISProject("CURRENT")`.
- **You cannot execute these scripts.** `arcpy` only exists inside Pro. The most you can do is `python -m py_compile` for syntax, and extract pure-Python helpers to unit-test them in isolation. Never claim a script "works" — say it compiles, and that behaviour needs a run in Pro.
- **Greek locale, EPSG:2100 (Greek Grid)** throughout. Layer names, field names and layout titles are in Greek; several tools match on exact Greek strings.
- Domain: Greek cadastral / forest-map (δασικοί χάρτες) casework in the Cyclades — Naxos, Paros. Case types: Δασωμένος Αγρός (DA), Πρόδηλο Σφάλμα (PROD), and its διαχρονική variant (PROD_Dated).
- The user works **directly on `main`** and pushes there. No feature-branch convention.
- The repo folder is synced by **Google Drive for Desktop** — a `.tmp.driveupload/` staging folder appears in the root (now gitignored). Evidence suggests Drive is also syncing `.git/`, which risks repository corruption. Unconfirmed but worth remembering if git behaves oddly.

---

## 2. The ArcGIS Pro crash — what is actually established

A `debugging/CRASH_FINDINGS.md` file exists locally but is **gitignored, so you will not see it**. Summary of what it claimed and what was subsequently verified:

**Confirmed.** A map with an empty name (`''`) crashes ArcGIS Pro. `NaturalSortComparer.Compare` uses the map name as a dictionary key and throws `ArgumentNullException`; .NET wraps it as "Failed to compare two elements in the array"; the sort runs in the `MapComboBox` constructor, so WPF rewraps it as `XamlParseException`, unhandled, process dies. A diagnostic run on the affected project confirmed ~75 maps for 5 layouts, including one named `''`.

**Corrected.** The findings doc said the project "fails to reopen". That is wrong — the dump shows `Process Uptime: 2:11:44` with the layout pane active. It is a **mid-session crash when a layout view builds its map drop-down**, not a crash on project load. The docstrings in the scripts were fixed to say this accurately; keep that wording.

**Does not apply.** The doc's first remedy was "eliminate `aprx.createMap()` with no argument". No script in this repo calls `createMap()` at all — maps are created by `m.exportToMAPX(...)` → `aprx.importDocument(...)`, with the name assigned afterwards. The real empty-name path was a blank layout-name parameter flowing into `new_map.name`.

**Lesson:** treat that doc as a lead, not as fact. Its environment details were accurate; its root-cause chain was partly extrapolated from an `!analyze -v` that was never actually run.

---

## 3. The group / layer-ordering constraint

This caused the most confusion and is the single most important thing to understand.

`reorder_layers` maps every entry in the Layers parameter to its **top-level ancestor**, deduplicates keeping first mention, and moves only those top-level layers. Consequences:

**A group is one contiguous block.** The TOC is a tree and draw order is a depth-first walk, so a group's children are always adjacent. A top-level layer **cannot** be placed between two members of a group — there is no such position in ArcGIS. This is structural, not a bug in the script, and no reordering algorithm can fix it.

**Real failure this produced.** A layout listed `Visible Layers\ΕΠΙΔΙΚΟ_ΤΜΗΜΑ` → `ΓΕΩΤΕΜΑΧΙΟ` (top level) → `Visible Layers\1945\*.tif`. The two group members collapse to one `Visible Layers` entry at position 1, so the whole group — orthophotos included — went above ΓΕΩΤΕΜΑΧΙΟ, and the opaque rasters buried the parcel. It still appeared in the legend, because legends do not know about occlusion. Listing ΓΕΩΤΕΜΑΧΙΟ first produced the correct result.

**How the user resolved it:** moved ΓΕΩΤΕΜΑΧΙΟ *into* the `Visible Layers` group. Important side effect — when every entry resolves to the same ancestor, `resolved` has one element and the reorder loop makes **no `moveLayer` calls at all**. Draw order is then entirely the user's manual arrangement in the Contents pane, and the Layers parameter order is ignored for those layouts.

**Knock-on:** the label rule (below) reads the *stated* parameter order, which for grouped layers may no longer match actual draw order. It can switch labels off on a layer nothing covers.

Intra-group reordering *was* implemented once, in `legacy/create_layouts_multiple_group.py` (CIM-based), and dropped from the current scripts. Porting it would let the parameter drive order within a group — but it would still not solve the cross-boundary case above.

---

## 4. Colons in layout names — NTFS alternate data streams

Diagnosed from a real run log; worth knowing because the failure mode is counter-intuitive.

Layout names follow an `Εικόνα N: …` convention, so they routinely contain colons. Windows parses extra colons in a path as NTFS alternate-data-stream syntax, `filename:stream:type`:

- **One extra colon** → valid ADS. The export *succeeds* and writes into a hidden stream on a zero-length file. Nothing usable appears on disk. Silent.
- **Two extra colons** → invalid stream type → hard failure with a visible error.

This exactly matched observed behaviour: `Εικόνα 1:` and `Εικόνα 2:` reported success (but produced nothing), while `Εικόνα 3:` … `Εικόνα 6:` — which also contain `_Υπόβαθρο:` — failed loudly. Verify with `dir /r`, which lists alternate data streams.

**Deliberate asymmetry between the scripts — do not "fix" this without asking:**

- **prod** sanitises colons in both the export filenames *and* the map name, and its cleanup pass matches both raw and sanitised forms.
- **DA** sanitises **filenames only**. Its map keeps the raw layout name, because DA's cleanup matches raw names. Sanitising DA's map name would force a matching change to the cleanup block — that coupling was tried, judged not worth the risk near crash-relevant code, and rolled back on purpose.

Note the map name matching the layout name is also what makes the Map drop-down readable when an operator picks a map frame's map by hand.

---

## 5. Non-obvious behaviours discovered in this codebase

- **`create_layouts_prod.py` had a dead cleanup check:** `startswith('Layout_{n}_Map_')` was a plain string, not an f-string, so it never matched, and per-frame maps accumulated every run. Combined with the cleanup comparing raw layout names while maps were stored under sanitised names, this is what produced the ~75-maps project. Both fixed.
- **Blank-name validation order matters.** The toolbox has nine fixed layout slots and users leave unused ones blank. A blank-name check placed *before* the "no layers" check fires `AddError` on every unused slot and fails the whole run. It must come **after**, so empty slots skip quietly and only a slot with layers but no name is an error. This regression was introduced once and caught by a real run — do not reorder these.
- **`save_project()`** refuses to save when any map has an empty name. Its value is narrower than it looks: it does **not** remove an existing empty-named map and does **not** protect the running session — it only stops the tool persisting the condition. Also, at the `.mapx` call site the `RuntimeError` is swallowed by the surrounding `try/except`; `arcpy.AddError` still fires and marks the run failed, but execution continues. This was left deliberately rather than rewriting that block's warn-and-continue design.
- **Most steps degrade to warnings.** Nearly every export is wrapped in a `try/except` that calls `AddWarning`. Runs routinely "succeed" with missing outputs. When diagnosing, read the full message log, not the exit status.
- **`create_layouts_prod_dated.py` still uses plain `aprx.save()`**, not the guarded `save_project()`. Only DA and prod were converted.
- **The parcel layer is identified by a field named `parcel`**, not by layer name. That field is added by `convert_from_cad.py` when the *is parcel* option is ticked. DA/prod scan the whole map and take the first feature layer that has it (so a stale old conversion can win); prod_dated scans only the Main layers parameter, in order. A missing `Renamed "…" -> "ΓΕΩΤΕΜΑΧΙΟ"` message in the log means no such field was found.
- **`identify_layers.py` creates a new `Visible Layers` group on every run** — repeated runs leave duplicate groups with the same name, which makes the layout tools ambiguous about which one is meant.
- **`summarize_polygons.py` applies its field filters cumulatively**, not independently, so the order of the input fields changes the result. There is a comment acknowledging this; it was left as-is on purpose.
- **DA and prod delete *every* layout in the project** before starting, not just the ones they create. prod_dated only deletes layouts whose names it will reuse.
- **`LOGO_PATH` is a relative path** (`./template data/logo.png`) in all three layout scripts, so the logo depends on the process working directory. `summarize_polygons.py` does it correctly with `os.path.dirname(os.path.abspath(__file__))`.
- **Map surrounds come from the project's Favorites style by index** (`listStyleItems(style='Favorites', ...)[0]` / `[1]`). A project whose Favorites is empty or ordered differently silently loses its north arrow, scale bar, legend or text styling.
- **Layer visibility is never restored** after a run — only layer order is.

---

## 6. Work in progress — NOT verified

**Map frames pointing at their own maps.** Each layout exports a `.mapx` snapshot and imports it as a new map, but historically every frame stayed bound to the live active map, which is then reconfigured for the next layout. Reopening a layout showed the wrong state, and the parcel name reverted when the run restored it. The `Layout_0` / `Εικόνα_N` multi-frame blocks already did this correctly and were the model.

`mf.map = new_map` plus a re-applied extent was added to all three scripts. **This is unverified and had one regression already:** placing the repoint before the PNG export caused the PNG to render from the copied map, and the raster did not draw. The order is now **MAPX → PNG → repoint → PAGX**, so the PNG still renders from the live map.

At the time of writing the user had not yet confirmed the re-run. If the raster is still missing:

- Raster **back in the PNG** → the reorder fixed it, done.
- PNG fine but the **layout on screen** has no raster → the copied map itself is the problem, i.e. the raster is not surviving the `.mapx` round-trip. Diagnose by opening the map object directly from the Project pane and checking whether the raster layer is present, ticked and not broken. That would mean abandoning the repoint in favour of restructuring so the frame is created against `new_map` from the start (create map → create layout → create frame against the new map → extent → surrounds → exports).

---

## 7. Deliberately not done — do not re-propose without asking

- **`repair_project()`** — a pass to rename empty-named maps in an existing `.aprx`. Still the only thing that would fix already-damaged projects; the current fixes only prevent new ones. Deferred, not rejected.
- **Sanitising DA's map name and cleanup set** — tried and rolled back. See §4.
- **Porting intra-group reordering** from the legacy script — see §3.
- **Making layout tools order-independent of group structure** — impossible, see §3.
- **Deleting orphan maps automatically** — risky, since bookmarks and reports can reference a map no layout draws. The audit notebook reports them but changes nothing.

---

## 8. Tooling and conventions

- `other-tools/Check map and layout names.ipynb` is a **read-only** audit notebook. It reports empty/duplicate map and layout names, maps no layout uses, frames with no map, and illegal filename characters. It accepts `"CURRENT"` or a path to any `.aprx` — and because it reads through arcpy rather than the UI, it can inspect a project whose layouts crash Pro.
- `README.md` has a **Tool considerations** section documenting the user-facing versions of most items in §5. Keep it in sync when behaviour changes — it was already stale once, when the `identify_layers` buffer became a parameter.
- `other-tools/` holds standalone notebooks run interactively in Pro, not wired to the toolbox. `Parcel-analysis-and-layouts/legacy/` is superseded code kept for reference.
- The three `create_layouts_*.py` scripts are near-duplicates with copy-pasted helpers that have since drifted apart. Check all three when changing shared behaviour, and expect their variable names to differ (`extent` vs `layout_extent`, `layout_name_export` vs `safe_title`).

## 9. Working style

The user reviews changes before they are applied — propose and explain first unless explicitly told to go ahead. Prefer minimal diffs, especially near the cleanup and crash-related code. Verify claims against the actual code rather than trusting prior handoff documents or assumptions; several confident-sounding statements in this project turned out to be wrong on inspection, and the real runs have repeatedly been the deciding evidence.

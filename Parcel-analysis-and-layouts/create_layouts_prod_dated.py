import arcpy
import os

# ─── Parameters ────────────────────────────────────────────────────────────────
main_layers_raw   = arcpy.GetParameterAsText(0)
numbering_start   = int(arcpy.GetParameter(1))
bg_raw_1          = arcpy.GetParameterAsText(2)
caption_1         = arcpy.GetParameterAsText(3)
bg_raw_2          = arcpy.GetParameterAsText(4)
caption_2         = arcpy.GetParameterAsText(5)
bg_raw_3          = arcpy.GetParameterAsText(6)
caption_3         = arcpy.GetParameterAsText(7)
bg_raw_4          = arcpy.GetParameterAsText(8)
caption_4         = arcpy.GetParameterAsText(9)
extent_raw        = arcpy.GetParameterAsText(10)
out_folder        = arcpy.GetParameterAsText(11)

# ─── Constants ──────────────────────────────────────────────────────────────────
LOGO_PATH = './template data/logo.png'
PAGE_W    = (297 / 25.4) * 72.0
PAGE_H    = (210 / 25.4) * 72.0
MF_MARGIN = 50

FOLDERS_DICT = {
    "1945":              "Ορθοφωτοχάρτης έτους 1945",
    "1960":              "Ορθοφωτοχάρτης έτους 1960",
    "1996":              "Ορθοφωτοχάρτης ετών 1996-1998",
    "KYKLADES_LSO25_ECW":"Ορθοφωτοχάρτης ετών 2015-2016",
    "LSO_KYKLADES":      "Ορθοφωτοχάρτης ετών 2007-2009",
    "5ARIA_GEO_CORRECT": "Ορθοφωτοχάρτης ΓΥΣ έτους 1983",
    "_ISLANDS":          "Ορθοφωτοχάρτης έτους 1960",
    "None":              "Χωρίς υπόβαθρο",
}

# ─── Project / Map ──────────────────────────────────────────────────────────────
aprx = arcpy.mp.ArcGISProject("CURRENT")
m    = aprx.activeMap

# ─── Helpers ────────────────────────────────────────────────────────────────────
def find_layer(map_obj, name):
    name = name.strip("'")
    for lyr in map_obj.listLayers():
        if lyr.name == name or getattr(lyr, 'longName', '') == name:
            return lyr
    return None

def get_top_level(map_obj):
    """Returns all layers whose longName has no backslash (i.e. root-level)."""
    return [lyr for lyr in map_obj.listLayers()
            if '\\' not in getattr(lyr, 'longName', lyr.name)]

def get_top_level_ancestor(map_obj, lyr):
    """
    Given any layer (including one nested inside groups), returns the
    root-level layer object that is its top-level ancestor.
    For a top-level layer, returns itself.
    """
    long_name = getattr(lyr, 'longName', lyr.name)
    root_name = long_name.split('\\')[0]
    for top_lyr in map_obj.listLayers():
        top_long = getattr(top_lyr, 'longName', top_lyr.name)
        if top_long == root_name:
            return top_lyr
    return lyr  # fallback

def set_layer_visibility(map_obj, layers_to_show):
    show_set = set(layers_to_show)
    arcpy.AddMessage("Visible layers: " + ", ".join(show_set))
    visible_long_names = set()
    for lyr in map_obj.listLayers():
        long_name = getattr(lyr, 'longName', '')
        if lyr.name in show_set or long_name in show_set:
            visible_long_names.add(long_name)
            # Also ensure all ancestor groups are visible
            parts = long_name.split('\\')
            for i in range(1, len(parts)):
                visible_long_names.add('\\'.join(parts[:i]))
    for lyr in map_obj.listLayers():
        lyr.visible = getattr(lyr, 'longName', '') in visible_long_names

def reorder_for_layout(map_obj, main_names, raster_names):
    """
    Brings main layers to the top (preserving user order), rasters underneath.
    Resolves each named layer to its top-level ancestor before moving,
    so layers inside groups are handled correctly.
    """
    desired_order = list(main_names) + list(raster_names)

    # Build lookup: name/longName → top-level ancestor layer object
    ancestor_lookup = {}
    for name in desired_order:
        lyr = find_layer(map_obj, name)
        if lyr is None:
            arcpy.AddWarning(f"Reorder: '{name}' not found - skipping.")
            continue
        ancestor = get_top_level_ancestor(map_obj, lyr)
        # Avoid duplicates (multiple children in same group)
        if ancestor.name not in ancestor_lookup:
            ancestor_lookup[ancestor.name] = ancestor

    ordered_ancestors = []
    seen = set()
    for name in desired_order:
        lyr = find_layer(map_obj, name)
        if lyr is None:
            continue
        ancestor = get_top_level_ancestor(map_obj, lyr)
        if ancestor.name not in seen:
            ordered_ancestors.append(ancestor)
            seen.add(ancestor.name)

    ref_layer = None
    for ancestor in reversed(ordered_ancestors):
        if ref_layer is None:
            ref_layer = ancestor
        else:
            map_obj.moveLayer(ref_layer, ancestor, 'BEFORE')
            ref_layer = ancestor
    arcpy.AddMessage("Layer reorder complete.")

def restore_layer_order(map_obj, original_order):
    """
    Restores original top-level layer order. original_order is a list of
    top-level layer objects snapshotted before any reordering.
    """
    arcpy.AddMessage("Restoring original layer order...")
    # Build a live lookup of top-level layers by name
    live_top_level = {lyr.name: lyr for lyr in get_top_level(map_obj)}
    ref_layer = None
    for lyr in reversed(original_order):
        live = live_top_level.get(lyr.name)
        if live is None:
            continue
        if ref_layer is None:
            ref_layer = live
        else:
            map_obj.moveLayer(ref_layer, live, 'BEFORE')
            ref_layer = live
    arcpy.AddMessage("Layer order restored.")

def get_auto_date_label(raster_layer_names):
    dates_found = set()
    for name in raster_layer_names:
        lyr = find_layer(m, name)
        if lyr is None or not lyr.isRasterLayer:
            continue
        try:
            raster_date = os.path.basename(
                os.path.dirname(os.path.dirname(lyr.dataSource)))
            dates_found.add(raster_date)
        except Exception as e:
            arcpy.AddWarning(f"Could not read path for raster '{name}': {e}")

    if len(dates_found) > 1:
        arcpy.AddError(
            f"Rasters in the same group come from different date folders: {dates_found}. "
            "Ensure all rasters in a group share the same parent date folder."
        )
        raise ValueError("Mixed date folders in raster group.")

    if not dates_found:
        return None

    raster_date = dates_found.pop()
    for key, label in FOLDERS_DICT.items():
        if key in raster_date:
            return label
    return raster_date

def rename_parcel_layer(map_obj, layer_names, new_name):
    """
    If any main layer has a field named 'parcel' (case-insensitive),
    rename that layer in the TOC to new_name.
    Returns (layer_object, original_layer_name) for restoration, or (None, None).
    """
    for name in layer_names:
        lyr = find_layer(map_obj, name)
        if lyr is None or not lyr.isFeatureLayer:
            continue
        try:
            fields = [f.name.lower() for f in arcpy.ListFields(lyr.dataSource)]
            if 'parcel' in fields:
                original_name = lyr.name
                lyr.name = new_name
                arcpy.AddMessage(f"Layer '{original_name}' renamed to '{new_name}' in TOC.")
                return lyr, original_name
        except Exception as e:
            arcpy.AddWarning(f"Could not inspect fields for '{name}': {e}")
    arcpy.AddMessage("No main layer with a 'parcel' field found — skipping layer rename.")
    return None, None

def restore_parcel_layer(lyr, original_name):
    """Restores the layer's TOC name back to its original."""
    if lyr is None:
        return
    try:
        lyr.name = original_name
        arcpy.AddMessage(f"Layer name restored to '{original_name}'.")
    except Exception as e:
        arcpy.AddWarning(f"Layer name restore failed: {e}")
# ─── Parse inputs ───────────────────────────────────────────────────────────────
main_layer_names = [n.strip().strip("'") for n in main_layers_raw.split(';') if n.strip()]

def parse_bg_group(raw, caption_val):
    if not raw or not raw.strip():
        return None
    names = [n.strip().strip("'") for n in raw.split(';') if n.strip()]
    return (names, caption_val.strip() if caption_val else "Auto") if names else None

raw_groups = [
    parse_bg_group(bg_raw_1, caption_1),
    parse_bg_group(bg_raw_2, caption_2),
    parse_bg_group(bg_raw_3, caption_3),
    parse_bg_group(bg_raw_4, caption_4),
]
bg_groups = [g for g in raw_groups if g is not None]

# ─── Parse extent ───────────────────────────────────────────────────────────────
try:
    layout_extent = arcpy.Extent(*[float(v) for v in extent_raw.split()[:4]])
except Exception as e:
    arcpy.AddError(f"Could not parse extent: {e}")
    raise

# ─── Snapshot original top-level layer order ────────────────────────────────────
original_top_level_order = get_top_level(m)
arcpy.AddMessage("Original order: " + ", ".join(l.name for l in original_top_level_order))

# ─── Build layout configs ────────────────────────────────────────────────────────
layout_configs = []
counter = numbering_start

for (raster_names, caption_val) in bg_groups:
    title = f"Εικόνα {counter}: Γεωτεμάχιο και Επίδικο τμήμα."
    if caption_val == "Auto":
        date_label = get_auto_date_label(raster_names)
        bg_caption = f"Υπόβαθρο: {date_label}" if date_label else None
    else:
        bg_caption = caption_val
    layout_configs.append({
        'title':        title,
        'raster_names': raster_names,
        'bg_caption':   bg_caption,
    })
    counter += 1

transparent_title = f"Εικόνα {counter}: Γεωτεμάχιο και Επίδικο τμήμα."

# ─── Delete conflicting existing layouts AND imported maps ───────────────────
planned_titles     = {cfg['title'] for cfg in layout_configs} | {transparent_title}
planned_safe_names = {t.replace(':', '_') for t in planned_titles}

for lyt_ex in aprx.listLayouts():
    if lyt_ex.name in planned_titles:
        arcpy.AddMessage(f"Deleting existing layout: {lyt_ex.name}")
        aprx.deleteItem(lyt_ex)

for map_ex in aprx.listMaps():
    if map_ex.name in planned_safe_names:
        arcpy.AddMessage(f"Deleting existing imported map: {map_ex.name}")
        aprx.deleteItem(map_ex)

aprx.save()

# ─── Layout creation function ────────────────────────────────────────────────────
def create_layout(title, raster_names, bg_caption, transparent=False):
    safe_title = title.replace(':', '_')
    arcpy.AddMessage(f"Creating: '{title}' (transparent={transparent})")

    lyt = aprx.createLayout(PAGE_W, PAGE_H, 'POINT', title)

    ll_x, ll_y = MF_MARGIN, MF_MARGIN
    ur_x, ur_y = PAGE_W - MF_MARGIN, PAGE_H - MF_MARGIN
    coords = [[ll_x, ll_y], [ur_x, ll_y], [ur_x, ur_y], [ll_x, ur_y], [ll_x, ll_y]]
    mf = lyt.createMapFrame(
        arcpy.Polygon(arcpy.Array([arcpy.Point(*xy) for xy in coords])), m, 'Main Map')

    if transparent:
        try:
            lyt_cim = lyt.getDefinition('V3')
            for elm in lyt_cim.elements:
                if elm.name == 'Main Map':
                    elm.graphicFrame.borderSymbol = None
            lyt.setDefinition(lyt_cim)
        except Exception as e:
            arcpy.AddWarning(f"Border removal error: {e}")

    visible = main_layer_names + raster_names
    set_layer_visibility(m, visible)
    reorder_for_layout(m, main_layer_names, raster_names)

    try:
        mf.camera.setExtent(layout_extent)
    except Exception as e:
        arcpy.AddWarning(f"Extent error: {e}")

    if not transparent:
        try:
            aprx.createPictureElement(lyt, geometry=arcpy.Point(690, 30), path=LOGO_PATH)
        except Exception as e:
            arcpy.AddWarning(f"Logo error: {e}")

        try:
            na_style = aprx.listStyleItems(style='Favorites', style_class='NORTH_ARROW')[0]
            na = lyt.createMapSurroundElement(
                arcpy.Point(815, 514), 'NORTH_ARROW', mf, na_style, 'North Arrow')
            na.elementWidth = 30
        except Exception as e:
            arcpy.AddWarning(f"North Arrow error: {e}")

        try:
            sb_style = aprx.listStyleItems(style='Favorites', style_class='SCALE_BAR')[0]
            sb = lyt.createMapSurroundElement(
                arcpy.Point(50, 5), 'SCALE_BAR', mf, sb_style, 'Scale Bar')
            sb.elementWidth = 200
            lyt.setDefinition(lyt.getDefinition('V2'))
        except Exception as e:
            arcpy.AddWarning(f"Scale Bar error: {e}")

        try:
            raster_names_set = {lyr.name for lyr in m.listLayers() if lyr.isRasterLayer}
            leg_style = aprx.listStyleItems(style='Favorites', style_class='LEGEND')[0]
            leg = lyt.createMapSurroundElement(
                arcpy.Point(61, 117), 'LEGEND', mf, leg_style, 'Legend')
            leg.elementWidth  = 150
            leg.elementHeight = 320
            leg.showTitle = True
            leg.title = 'ΥΠΟΜΝΗΜΑ'
            leg_cim = leg.getDefinition('V2')
            if hasattr(leg_cim, 'autoAdd'):
                leg_cim.autoAdd = False
            kept_items = [item for item in leg_cim.items
                          if item.name not in raster_names_set]
            for item in kept_items:
                if hasattr(item, 'showLayerName'):
                    item.showLayerName = False
            leg_cim.items = kept_items
            leg.setDefinition(leg_cim)
            for itm in leg.items:
                itm.showVisibleFeatures = True
            leg.fittingStrategy = 'AdjustFrame'
            leg.setAnchor('TOP_LEFT_CORNER')
            leg.elementPositionX = MF_MARGIN + 10
            leg.elementPositionY = MF_MARGIN + 10 + leg.elementHeight
        except Exception as e:
            arcpy.AddWarning(f"Legend error: {e}")

        try:
            text_style    = aprx.listStyleItems(style='Favorites', style_class='TEXT')[0]
            page_center_x = lyt.pageWidth / 2
            txt_elem = aprx.createTextElement(
                lyt,
                geometry=arcpy.Point(page_center_x, 20),
                text_type='POINT',
                text=title,
                style_item=text_style
            )
            txt_elem.setAnchor('TOP_MID_POINT')
            txt_elem.elementPositionX = page_center_x
        except Exception as e:
            arcpy.AddWarning(f"Main caption error: {e}")

        if bg_caption:
            try:
                text_style = aprx.listStyleItems(style='Favorites', style_class='TEXT')[1]
                mf.setAnchor("BOTTOM_LEFT_CORNER")
                mf_right  = mf.elementPositionX + mf.elementWidth
                mf_bottom = mf.elementPositionY
                padding   = 5
                txt = aprx.createTextElement(
                    lyt,
                    geometry=arcpy.Point(mf_right - padding, mf_bottom + padding),
                    text_type='POINT',
                    text=bg_caption,
                    style_item=text_style
                )
                txt.setAnchor("BOTTOM_RIGHT_CORNER")
                txt.elementPositionX = mf_right - padding
                txt.elementPositionY = mf_bottom + padding
            except Exception as e:
                arcpy.AddWarning(f"BG caption error: {e}")

    try:
        map_file_path = os.path.join(out_folder, f'{safe_title}.mapx')
        arcpy.AddMessage(f"Exporting .mapx → {map_file_path}")
        m.exportToMAPX(map_file_path)
        new_map = aprx.importDocument(map_file_path)
        if new_map.name != safe_title:
            new_map.name = safe_title
        aprx.save()

        # Point the frame at this layout's own map copy. Without this every
        # frame keeps looking at the live active map, which is reconfigured for
        # the next layout - so a layout reopened later shows the wrong state.
        # Swapping the map resets the camera, so re-apply the extent.
        try:
            mf.map = new_map
            if layout_extent:
                mf.camera.setExtent(layout_extent)
            arcpy.AddMessage(f'Map frame now points at map "{new_map.name}".')
        except Exception as e:
            arcpy.AddWarning(f'Could not point the map frame at "{new_map.name}": {e}')
    except Exception as e:
        arcpy.AddWarning(f".mapx export error: {e}")

    try:
        png_path = os.path.join(out_folder, f'{safe_title}.png')
        lyt.exportToPNG(png_path, resolution=300, transparent_background=transparent)
        arcpy.AddMessage(f"PNG exported → {png_path}")
    except Exception as e:
        arcpy.AddWarning(f"PNG export error: {e}")

    try:
        pagx_path = os.path.join(out_folder, f'{safe_title}.pagx')
        lyt.exportToPAGX(pagx_path)
        arcpy.AddMessage(f'PAGX exported: {pagx_path}')
    except Exception as e:
        arcpy.AddWarning(f'PAGX export error: {e}')

# ─── Execute ─────────────────────────────────────────────────────────────────
PARCEL_DISPLAY_NAME = "ΓΕΩΤΕΜΑΧΙΟ"

parcel_layer, parcel_original_name = rename_parcel_layer(m, main_layer_names, PARCEL_DISPLAY_NAME)

# Sync main_layer_names so visibility/reorder lookups use the new TOC name
if parcel_layer and parcel_original_name in main_layer_names:
    main_layer_names[main_layer_names.index(parcel_original_name)] = PARCEL_DISPLAY_NAME

try:
    for cfg in layout_configs:
        create_layout(cfg['title'], cfg['raster_names'], cfg['bg_caption'], transparent=False)

    create_layout(transparent_title, raster_names=[], bg_caption=None, transparent=True)

finally:
    restore_parcel_layer(parcel_layer, parcel_original_name)
    if PARCEL_DISPLAY_NAME in main_layer_names:
        main_layer_names[main_layer_names.index(PARCEL_DISPLAY_NAME)] = parcel_original_name
    restore_layer_order(m, original_top_level_order)

arcpy.AddMessage("Finished.")
os.startfile(out_folder)

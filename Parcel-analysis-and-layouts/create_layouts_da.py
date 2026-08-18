import arcpy
import os


def set_layer_visibility(map_obj, layers_to_show):
    layers_to_show_set = set(layers_to_show)
    arcpy.AddMessage('Layers to show: ' + ', '.join(layers_to_show_set))
    visible_long_names = set()
    for lyr in map_obj.listLayers():
        long_name = getattr(lyr, 'longName', '')
        if lyr.name in layers_to_show_set or long_name in layers_to_show_set:
            visible_long_names.add(long_name)
            parts = long_name.split('\\')
            for i in range(1, len(parts)):
                visible_long_names.add('\\'.join(parts[:i]))
    for lyr in map_obj.listLayers():
        lyr.visible = getattr(lyr, 'longName', '') in visible_long_names


def get_top_level_order(map_obj):
    return [lyr for lyr in map_obj.listLayers()
            if '\\' not in getattr(lyr, 'longName', lyr.name)]


def reorder_layers(map_obj, ordered_names):
    # Build top-level lookup including group layers
    top_level = {lyr.name: lyr for lyr in map_obj.listLayers()
                 if '\\' not in getattr(lyr, 'longName', lyr.name)}

    # Resolve each name to its top-level parent, then deduplicate preserving order
    seen = set()
    resolved = []
    for name in ordered_names:
        top_name = name.split('\\')[0] if '\\' in name else name
        if top_name not in seen:
            seen.add(top_name)
            resolved.append(top_name)

    ref_layer = None
    for name in reversed(resolved):
        lyr = top_level.get(name)
        if lyr is None:
            arcpy.AddWarning(f'Reorder: "{name}" not found as top-level layer - skipping.')
            continue
        if ref_layer is None:
            ref_layer = lyr
        else:
            map_obj.moveLayer(ref_layer, lyr, 'BEFORE')
            ref_layer = lyr

    arcpy.AddMessage('Layer reorder complete.')


def find_layer(map_obj, name):
    name = name.strip("'")
    for lyr in map_obj.listLayers():
        if lyr.name == name or getattr(lyr, 'longName', '') == name:
            return lyr
    return None


def get_vector_layers_after_raster(map_obj, ordered_names):
    """
    Given a layout's configured layer order (first = top of TOC, last =
    bottom), returns the layer objects for entries that come after a raster
    entry in that order - i.e. vector layers a raster is drawn on top of.
    Rasters are identified by filename extension, matching how they're named
    in the Layers parameter.
    """
    layers_after_raster = []
    raster_seen = False
    for name in ordered_names:
        if name.lower().endswith(RASTER_EXTENSIONS):
            raster_seen = True
        elif raster_seen:
            lyr = find_layer(map_obj, name)
            if lyr is not None:
                layers_after_raster.append(lyr)
    return layers_after_raster


def restore_layer_order(map_obj, original_order):
    arcpy.AddMessage('Restoring original layer order...')
    ref_layer = None
    for lyr in reversed(original_order):
        live = next((l for l in map_obj.listLayers()
                     if l.name == lyr.name and '\\' not in getattr(l, 'longName', l.name)), None)
        if live is None:
            continue
        if ref_layer is None:
            ref_layer = live
        else:
            map_obj.moveLayer(ref_layer, live, 'BEFORE')
            ref_layer = live
    arcpy.AddMessage('Layer order restored.')


def make_map_frame(lyt, map_obj, ll_x_pt, ll_y_pt, w_pt, h_pt, name):
    ur_x_pt = ll_x_pt + w_pt
    ur_y_pt = ll_y_pt + h_pt
    pts = [[ll_x_pt, ll_y_pt], [ur_x_pt, ll_y_pt],
           [ur_x_pt, ur_y_pt], [ll_x_pt, ur_y_pt], [ll_x_pt, ll_y_pt]]
    polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(*xy) for xy in pts]))
    return lyt.createMapFrame(polygon, map_obj, name)


def save_project():
    """
    aprx.save(), guarded. A map with an empty name makes ArcGIS Pro throw when
    the Layout pane builds its map drop-down - the name sort hits a null key.
    The crash therefore fires whenever a layout view is opened, not at project
    load. Refuse to persist that state instead of leaving it in the .aprx.

    This does not remove an existing empty-named map or protect the current
    session; it only stops the tool writing the condition to disk.
    """
    unnamed = [mp for mp in aprx.listMaps() if not (mp.name or '').strip()]
    if unnamed:
        msg = (f'Refusing to save: {len(unnamed)} map(s) have an empty name. '
               'This crashes ArcGIS Pro when a layout view builds its map list. '
               'Rename or delete them, then re-run.')
        arcpy.AddError(msg)
        raise RuntimeError(msg)
    aprx.save()


aprx = arcpy.mp.ArcGISProject('CURRENT')
m = aprx.activeMap

# Snapshot original top-level layer order before any processing
original_top_level_order = get_top_level_order(m)
arcpy.AddMessage('Original top-level order: ' + ', '.join(l.name for l in original_top_level_order))

# Delete existing layouts
for lyt_existing in aprx.listLayouts():
    arcpy.AddMessage(f'Deleting existing layout: {lyt_existing.name}')
    aprx.deleteItem(lyt_existing)

PAGE_W = (297 / 25.4) * 72.0
PAGE_H = (210 / 25.4) * 72.0
MF_MARGIN = 50
MM = 72.0 / 25.4
LOGO_PATH = './template data/logo.png'
RASTER_EXTENSIONS = ('.tif', '.tiff', '.jp2', '.ecw', '.img', '.sid')

out_folder = arcpy.GetParameterAsText(0)

PARAMS_PER_LAYOUT = 4
total_params = arcpy.GetArgumentCount()
num_layouts = (total_params - 1) // PARAMS_PER_LAYOUT
arcpy.AddMessage(f'Total parameters: {total_params} -> {num_layouts} layout group(s).')

layout_configs = []
for i in range(num_layouts):
    base = 1 + i * PARAMS_PER_LAYOUT
    layout_name = arcpy.GetParameterAsText(base).strip()
    layers_raw = arcpy.GetParameterAsText(base + 1)
    extent_raw = arcpy.GetParameterAsText(base + 2)
    transparent = arcpy.GetParameter(base + 3)
    layer_list = [l.strip().strip("'") for l in layers_raw.split(';') if l.strip()]
    # Unused layout slots are left blank, so this must be checked before the name.
    if not layer_list:
        arcpy.AddWarning(f'Layout "{layout_name}" has no layers defined - skipping.')
        continue
    if not layout_name:
        arcpy.AddError(
            f'Layout {i + 1} has layers but no name - skipping. An unnamed layout '
            'produces an unnamed map, which crashes ArcGIS Pro when the Layout pane '
            'builds its map list.')
        continue
    try:
        coords = [float(v) for v in extent_raw.split()[:4]]
        layout_extent = arcpy.Extent(*coords)
    except Exception as e:
        arcpy.AddWarning(f'Layout {layout_name}: could not parse extent - {e}')
        layout_extent = None
    layout_configs.append({
        'name': layout_name,
        'layers': layer_list,
        'extent': layout_extent,
        'transparent': bool(transparent),
    })

arcpy.AddMessage(f'Loaded {len(layout_configs)} valid layout(s).')

# --- Clean up maps from previous runs ---
layout_names_set = {cfg['name'] for cfg in layout_configs}
for existing_map in aprx.listMaps():
    if (existing_map.name.startswith('Layout_0_Map_') or
            existing_map.name in layout_names_set):
        arcpy.AddMessage(f'Deleting existing map: {existing_map.name}')
        aprx.deleteItem(existing_map)
save_project()

# --- Layout_0: ΔΙΑΧΡΟΝΙΚΗ ΠΑΡΟΥΣΙΑΣΗ ΓΕΩΤΕΜΑΧΙΟΥ ---
try:
    arcpy.AddMessage('Creating Layout_0: ΔΙΑΧΡΟΝΙΚΗ ΠΑΡΟΥΣΙΑΣΗ ΓΕΩΤΕΜΑΧΙΟΥ')
    lyt0 = aprx.createLayout(PAGE_W, PAGE_H, 'POINT', 'ΔΙΑΧΡΟΝΙΚΗ ΠΑΡΟΥΣΙΑΣΗ ΓΕΩΤΕΜΑΧΙΟΥ')

    try:
        text_style = aprx.listStyleItems(style='Favorites', style_class='TEXT')[0]
        aprx.createTextElement(lyt0, geometry=arcpy.Point(304, 20), text_type='POINT',
                               text='ΔΙΑΧΡΟΝΙΚΗ ΠΑΡΟΥΣΙΑΣΗ ΓΕΩΤΕΜΑΧΙΟΥ',
                               style_item=text_style)
    except Exception as e:
        arcpy.AddWarning(f'Layout_0 title text error: {e}')

    fw = 130 * MM
    fh = 70 * MM

    frame_positions = [
        (15 * MM, 125 * MM),  # top-left
        (152 * MM, 125 * MM),  # top-right
        (15 * MM, 100),  # bottom-left
        (152 * MM, 100),  # bottom-right
    ]

    extent_0 = layout_configs[0]['extent'] if layout_configs else None
    first_mf = None

    for idx, (bl_x, bl_y) in enumerate(frame_positions):
        mf_name = f'Map Frame {idx + 1}'

        # Dedicated map copy for this frame
        map_file_path = os.path.join(out_folder, f'Layout_0_Frame_{idx + 1}.mapx')
        m.exportToMAPX(map_file_path)
        frame_map = aprx.importDocument(map_file_path)
        frame_map.name = f'Layout_0_Map_{idx + 1}'
        save_project()

        mf = make_map_frame(lyt0, frame_map, bl_x, bl_y, fw, fh, mf_name)
        if first_mf is None:
            first_mf = mf

        if extent_0:
            try:
                mf.camera.setExtent(extent_0)
            except Exception as e:
                arcpy.AddWarning(f'Layout_0 {mf_name} extent error: {e}')

        # Label underneath each frame
        try:
            text_style = aprx.listStyleItems(style='Favorites', style_class='TEXT')[0]
            label_x = bl_x + fw / 2 - 65
            label_y = bl_y - 35
            aprx.createTextElement(lyt0,
                                   geometry=arcpy.Point(label_x, label_y),
                                   text_type='POINT',
                                   text='ΟΡΘΟΦΩΤΟΧΑΡΤΗΣ',
                                   style_item=text_style)
        except Exception as e:
            arcpy.AddWarning(f'Layout_0 frame label {idx + 1} error: {e}')

    # Single north arrow top-right of paper, anchored to frame 1
    try:
        na_style = aprx.listStyleItems(style='Favorites', style_class='NORTH_ARROW')[0]
        na = lyt0.createMapSurroundElement(
            arcpy.Point(815, 514), 'NORTH_ARROW',
            first_mf, na_style, 'North Arrow')
        na.elementWidth = 30
    except Exception as e:
        arcpy.AddWarning(f'Layout_0 north arrow error: {e}')

    arcpy.AddMessage('Layout_0 created successfully.')
except Exception as e:
    arcpy.AddWarning(f'Layout_0 creation error: {e}')


def create_layout_and_export(config, out_folder):
    layout_name = config['name']
    layers      = config['layers']
    extent      = config['extent']
    transparent = config['transparent']
    arcpy.AddMessage(f'Creating layout: {layout_name} (transparent={transparent})')

    lyt = aprx.createLayout(PAGE_W, PAGE_H, 'POINT', layout_name)

    ll_x, ll_y = MF_MARGIN, MF_MARGIN
    ur_x, ur_y = PAGE_W - MF_MARGIN, PAGE_H - MF_MARGIN
    pts = [[ll_x, ll_y], [ur_x, ll_y], [ur_x, ur_y], [ll_x, ur_y], [ll_x, ll_y]]
    mf_polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(*xy) for xy in pts]))
    mf = lyt.createMapFrame(mf_polygon, m, 'Main Map')

    if transparent:
        try:
            lyt_cim = lyt.getDefinition('V3')
            for elm in lyt_cim.elements:
                if elm.name == 'Main Map':
                    elm.graphicFrame.borderSymbol = None
            lyt.setDefinition(lyt_cim)
        except Exception as e:
            arcpy.AddWarning(f'Could not remove map frame border: {e}')

    # Visibility and reorder use original names — must happen BEFORE rename
    set_layer_visibility(m, layers)
    reorder_layers(m, layers)

    # Labels must be hidden for vector layers that a raster is drawn on top
    # of in this layout's configured order (this layout only).
    labels_to_restore = []
    for lyr in get_vector_layers_after_raster(m, layers):
        try:
            labels_to_restore.append((lyr, lyr.showLabels))
            lyr.showLabels = False
            arcpy.AddMessage(f'Disabled labels for "{lyr.name}" (covered by a raster in the order).')
        except Exception as e:
            arcpy.AddWarning(f'Could not disable labels for "{lyr.name}": {e}')

    # Find the parcel layer and rename it AFTER visibility is resolved
    parcel_layer = None
    parcel_original_name = None
    for lyr in m.listLayers():
        if not lyr.isFeatureLayer:
            continue
        try:
            if any(f.name.lower() == 'parcel' for f in arcpy.ListFields(lyr)):
                parcel_layer = lyr
                parcel_original_name = lyr.name
                lyr.name = 'ΓΕΩΤΕΜΑΧΙΟ'
                arcpy.AddMessage(f'Renamed "{parcel_original_name}" -> "ΓΕΩΤΕΜΑΧΙΟ"')
                break
        except Exception as e:
            arcpy.AddWarning(f'Field inspection failed for "{lyr.name}": {e}')

    try:
        if extent:
            try:
                mf.camera.setExtent(extent)
                arcpy.AddMessage(f'Extent set: {extent}')
            except Exception as e:
                arcpy.AddWarning(f'Could not set extent: {e}')
        else:
            arcpy.AddWarning('No valid extent - using default map view.')

        if not transparent:
            try:
                aprx.createPictureElement(lyt, geometry=arcpy.Point(690, 30), path=LOGO_PATH)
            except Exception as e:
                arcpy.AddWarning(f'Logo error: {e}')

            try:
                na_style = aprx.listStyleItems(style='Favorites', style_class='NORTH_ARROW')[0]
                na = lyt.createMapSurroundElement(
                    arcpy.Point(815, 514), 'NORTH_ARROW', mf, na_style, 'North Arrow')
                na.elementWidth = 30
            except Exception as e:
                arcpy.AddWarning(f'North Arrow error: {e}')

            try:
                sb_style = aprx.listStyleItems(style='Favorites', style_class='SCALE_BAR')[0]
                sb = lyt.createMapSurroundElement(
                    arcpy.Point(50, 5), 'SCALE_BAR', mf, sb_style, 'Scale Bar')
                sb.elementWidth = 200
                lyt.setDefinition(lyt.getDefinition('V2'))
            except Exception as e:
                arcpy.AddWarning(f'Scale Bar error: {e}')

            try:
                text_style = aprx.listStyleItems(style='Favorites', style_class='TEXT')[0]
                page_center_x = lyt.pageWidth / 2
                txt_elem = aprx.createTextElement(
                    lyt,
                    geometry=arcpy.Point(page_center_x, 20),
                    text_type='POINT',
                    text=layout_name,
                    style_item=text_style)
                txt_elem.setAnchor('TOP_MID_POINT')
                txt_elem.elementPositionX = page_center_x
            except Exception as e:
                arcpy.AddWarning(f'Text element error: {e}')

            try:
                raster_names = {lyr.name for lyr in m.listLayers() if lyr.isRasterLayer}
                arcpy.AddMessage(
                    'Excluding from legend (rasters): ' + (', '.join(raster_names) if raster_names else 'None'))
                leg_style = aprx.listStyleItems(style='Favorites', style_class='LEGEND')[0]
                leg = lyt.createMapSurroundElement(
                    arcpy.Point(61, 117), 'LEGEND', mf, leg_style, 'Legend')
                leg.elementWidth = 150
                leg.elementHeight = 320
                leg.showTitle = True
                leg.title = 'ΥΠΟΜΝΗΜΑ'
                leg_cim = leg.getDefinition('V2')
                if hasattr(leg_cim, 'autoAdd'):
                    leg_cim.autoAdd = False
                kept_items = []
                for item in leg_cim.items:
                    if item.name not in raster_names:
                        if hasattr(item, 'showLayerName'):
                            item.showLayerName = False
                        kept_items.append(item)
                leg_cim.items = kept_items
                leg.setDefinition(leg_cim)
                for itm in leg.items:
                    itm.showVisibleFeatures = True
                leg.fittingStrategy = 'AdjustFrame'
                leg.setAnchor('TOP_LEFT_CORNER')
                leg.elementPositionX = MF_MARGIN + 10
                leg.elementPositionY = MF_MARGIN + 10 + leg.elementHeight
            except Exception as e:
                arcpy.AddWarning(f'Legend error: {e}')

        # Colons are legal in a layout name but not in a Windows file name, where
        # they are read as an alternate data stream separator. Only the file names
        # are sanitised - the map keeps the raw name, which is what the cleanup
        # pass at the top of the script matches on.
        layout_name_export = layout_name.replace(':', '_')
        new_map = None

        # Export .mapx
        try:
            arcpy.AddMessage('Exporting .mapx ...')
            map_file_path = os.path.join(out_folder, f'{layout_name_export}_Theme.mapx')
            m.exportToMAPX(map_file_path)
            new_map = aprx.importDocument(map_file_path)
            if new_map.name != layout_name:
                new_map.name = layout_name
            save_project()
        except Exception as e:
            arcpy.AddWarning(f'Could not export .mapx: {e}')

        # Export PNG. This renders while the frame still points at the live map,
        # which is known to draw correctly - the frame is repointed afterwards.
        try:
            png_path = os.path.join(out_folder, f'{layout_name_export}.png')
            lyt.exportToPNG(png_path, resolution=300, transparent_background=transparent)
            arcpy.AddMessage(f'PNG exported: {png_path}')
        except Exception as e:
            arcpy.AddWarning(f'PNG export error: {e}')

        # Point the frame at this layout's own map copy, so the layout still
        # shows the right state when it is reopened later. Swapping the map
        # resets the camera, so re-apply the extent.
        if new_map is not None:
            try:
                mf.map = new_map
                if extent:
                    mf.camera.setExtent(extent)
                arcpy.AddMessage(f'Map frame now points at map "{new_map.name}".')
            except Exception as e:
                arcpy.AddWarning(f'Could not point the map frame at "{new_map.name}": {e}')

        try:
            pagx_path = os.path.join(out_folder, f'{layout_name_export}.pagx')
            lyt.exportToPAGX(pagx_path)
            arcpy.AddMessage(f'PAGX exported: {pagx_path}')
        except Exception as e:
            arcpy.AddWarning(f'PAGX export error: {e}')

    finally:
        # Restore labels that were disabled for this layout only
        for lyr, original_state in labels_to_restore:
            try:
                lyr.showLabels = original_state
            except Exception as e:
                arcpy.AddWarning(f'Could not restore labels for "{lyr.name}": {e}')

        # Always restore the original layer name
        if parcel_layer is not None:
            try:
                parcel_layer.name = parcel_original_name
                arcpy.AddMessage(f'Restored: "ΓΕΩΤΕΜΑΧΙΟ" -> "{parcel_original_name}"')
            except Exception as e:
                arcpy.AddWarning(f'Could not restore layer name: {e}')


for config in layout_configs:
    create_layout_and_export(config, out_folder)

restore_layer_order(m, original_top_level_order)

arcpy.AddMessage('Finished.')

os.startfile(out_folder)

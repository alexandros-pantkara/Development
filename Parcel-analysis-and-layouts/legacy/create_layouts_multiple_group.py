import arcpy
import os
from collections import defaultdict


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


def get_top_level_layers(map_obj):
    return [lyr for lyr in map_obj.listLayers()
            if '\\' not in getattr(lyr, 'longName', lyr.name)]


def reorder_layers(map_obj, ordered_names):
    """
    Reorders layers to match ordered_names (first = bottom of TOC draw order).
    - Top-level layers: uses moveLayer.
    - Layers inside a group: uses setDefinition on the group layer only (safe).
    ordered_names must use longName format for grouped layers: 'GroupName\\LayerName'
    """
    # --- Top-level reorder ---
    top_level_names = [n for n in ordered_names if '\\' not in n]
    top_lookup = {lyr.name: lyr for lyr in get_top_level_layers(map_obj)}
    ref_layer = None
    for name in reversed(top_level_names):
        lyr = top_lookup.get(name)
        if lyr is None:
            arcpy.AddWarning(f'Reorder: "{name}" not found at top level - skipping.')
            continue
        if ref_layer is None:
            ref_layer = lyr
        else:
            map_obj.moveLayer(ref_layer, lyr, 'BEFORE')
            ref_layer = lyr

    # --- Intra-group reorder ---
    group_children = defaultdict(list)
    for name in ordered_names:
        if '\\' in name:
            parent = '\\'.join(name.split('\\')[:-1])
            group_children[parent].append(name.split('\\')[-1])

    for group_long_name, desired_child_order in group_children.items():
        group_lyr = next(
            (l for l in map_obj.listLayers()
             if l.isGroupLayer and getattr(l, 'longName', l.name) == group_long_name),
            None
        )
        if group_lyr is None:
            arcpy.AddWarning(f'Reorder: group "{group_long_name}" not found - skipping.')
            continue
        try:
            grp_cim = group_lyr.getDefinition('V3')
            cim_by_name = {cl.name: cl for cl in grp_cim.layers if hasattr(cl, 'name')}
            reordered = []
            for child_name in reversed(desired_child_order):
                if child_name in cim_by_name:
                    reordered.append(cim_by_name.pop(child_name))
            # Append remaining layers not in requested order
            reordered.extend(cim_by_name.values())
            grp_cim.layers = reordered
            group_lyr.setDefinition(grp_cim)
        except Exception as e:
            arcpy.AddWarning(f'Reorder: could not reorder inside group "{group_long_name}": {e}')

    arcpy.AddMessage('Layer reorder complete.')


def snapshot_order(map_obj):
    """
    Records current layer order as:
      - 'top_level': ordered list of top-level layer names (top of TOC first)
      - 'groups': { group_longName: [direct child short names, top-to-bottom] }
    Uses names only — no live object references.
    """
    top_level = [lyr.name for lyr in get_top_level_layers(map_obj)]
    groups = {}
    for lyr in map_obj.listLayers():
        if lyr.isGroupLayer:
            long_name = getattr(lyr, 'longName', lyr.name)
            children = [
                l.name for l in map_obj.listLayers()
                if getattr(l, 'longName', l.name).startswith(long_name + '\\')
                and '\\' not in getattr(l, 'longName', l.name)[len(long_name) + 1:]
            ]
            groups[long_name] = children
    return {'top_level': top_level, 'groups': groups}


def restore_order(map_obj, original_snapshot):
    """
    Restores layer order from a snapshot produced by snapshot_order().
    Does NOT touch visibility.
    """
    arcpy.AddMessage('Restoring original layer order...')

    # --- Restore top-level order ---
    top_lookup = {lyr.name: lyr for lyr in get_top_level_layers(map_obj)}
    ref_layer = None
    for name in reversed(original_snapshot['top_level']):
        live = top_lookup.get(name)
        if live is None:
            continue
        if ref_layer is None:
            ref_layer = live
        else:
            map_obj.moveLayer(ref_layer, live, 'BEFORE')
            ref_layer = live

    # --- Restore intra-group order ---
    for group_long_name, desired_child_order in original_snapshot['groups'].items():
        group_lyr = next(
            (l for l in map_obj.listLayers()
             if l.isGroupLayer and getattr(l, 'longName', l.name) == group_long_name),
            None
        )
        if group_lyr is None:
            continue
        try:
            grp_cim = group_lyr.getDefinition('V3')
            cim_by_name = {cl.name: cl for cl in grp_cim.layers if hasattr(cl, 'name')}
            reordered = []
            for child_name in reversed(desired_child_order):
                if child_name in cim_by_name:
                    reordered.append(cim_by_name.pop(child_name))
            reordered.extend(cim_by_name.values())
            grp_cim.layers = reordered
            group_lyr.setDefinition(grp_cim)
        except Exception as e:
            arcpy.AddWarning(f'Restore: could not restore group "{group_long_name}": {e}')

    arcpy.AddMessage('Layer order restored.')


def make_map_frame(lyt, map_obj, ll_x_pt, ll_y_pt, w_pt, h_pt, name):
    ur_x_pt = ll_x_pt + w_pt
    ur_y_pt = ll_y_pt + h_pt
    pts = [[ll_x_pt, ll_y_pt], [ur_x_pt, ll_y_pt],
           [ur_x_pt, ur_y_pt], [ll_x_pt, ur_y_pt], [ll_x_pt, ll_y_pt]]
    polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(*xy) for xy in pts]))
    return lyt.createMapFrame(polygon, map_obj, name)


aprx = arcpy.mp.ArcGISProject('CURRENT')
m = aprx.activeMap

# Snapshot original order before any processing
original_snapshot = snapshot_order(m)
arcpy.AddMessage('Original top-level order: ' + ', '.join(original_snapshot['top_level']))

# Delete existing layouts
for lyt_existing in aprx.listLayouts():
    arcpy.AddMessage(f'Deleting existing layout: {lyt_existing.name}')
    aprx.deleteItem(lyt_existing)

PAGE_W = (297 / 25.4) * 72.0
PAGE_H = (210 / 25.4) * 72.0
MF_MARGIN = 50
MM = 72.0 / 25.4
LOGO_PATH = '../template data/logo.png'

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
    if not layer_list:
        arcpy.AddWarning(f'Layout "{layout_name}" has no layers defined - skipping.')
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
aprx.save()

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
        (15 * MM,  125 * MM),   # top-left
        (152 * MM, 125 * MM),   # top-right
        (15 * MM,  100),        # bottom-left
        (152 * MM, 100),        # bottom-right
    ]

    extent_0 = layout_configs[0]['extent'] if layout_configs else None
    first_mf = None

    for idx, (bl_x, bl_y) in enumerate(frame_positions):
        mf_name = f'Map Frame {idx + 1}'

        map_file_path = os.path.join(out_folder, f'Layout_0_Frame_{idx + 1}.mapx')
        m.exportToMAPX(map_file_path)
        frame_map = aprx.importDocument(map_file_path)
        frame_map.name = f'Layout_0_Map_{idx + 1}'
        aprx.save()

        mf = make_map_frame(lyt0, frame_map, bl_x, bl_y, fw, fh, mf_name)
        if first_mf is None:
            first_mf = mf

        if extent_0:
            try:
                mf.camera.setExtent(extent_0)
            except Exception as e:
                arcpy.AddWarning(f'Layout_0 {mf_name} extent error: {e}')

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
    layers = config['layers']
    extent = config['extent']
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

    set_layer_visibility(m, layers)
    reorder_layers(m, layers)

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
            style_item=text_style
        )
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

    # Export .mapx
    try:
        arcpy.AddMessage('Exporting .mapx ...')
        map_file_path = os.path.join(out_folder, f'{layout_name}_Theme.mapx')
        m.exportToMAPX(map_file_path)
        new_map = aprx.importDocument(map_file_path)
        if new_map.name != layout_name:
            new_map.name = layout_name
        aprx.save()
    except Exception as e:
        arcpy.AddWarning(f'Could not export .mapx: {e}')

    # Export PNG
    try:
        png_path = os.path.join(out_folder, f'{layout_name}.png')
        lyt.exportToPNG(png_path, resolution=300, transparent_background=transparent)
        arcpy.AddMessage(f'PNG exported: {png_path}')
    except Exception as e:
        arcpy.AddWarning(f'PNG export error: {e}')


for config in layout_configs:
    create_layout_and_export(config, out_folder)

# Restore original layer order (top-level + intra-group). Visibility is not restored.
restore_order(m, original_snapshot)

arcpy.AddMessage('Finished.')

os.startfile(out_folder)

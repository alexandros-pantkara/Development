import arcpy
import os

# Parameters
layer_names = arcpy.GetParameterAsText(0)
background_layers = arcpy.GetParameterAsText(1)
extent = arcpy.GetParameterAsText(2)
empty_pages = arcpy.GetParameterAsText(3)
always_visible = arcpy.GetParameterAsText(4)
out_folder = arcpy.GetParameterAsText(5)

always_visible = always_visible.strip("'") if always_visible else None

main_layers_list = [lyr for lyr in layer_names.split(";")]
bg_layer_names = [lyr.strip("'") for lyr in background_layers.split(";")]

arcpy.AddMessage(bg_layer_names)

last_count = -1

# Reference project
aprx = arcpy.mp.ArcGISProject("CURRENT")
m = aprx.activeMap

# --- DELETE EXISTING LAYOUTS ---
# Iterate through all layouts in the project and delete them to start fresh
for lyt_existing in aprx.listLayouts():
    arcpy.AddMessage(f"Deleting existing layout: {lyt_existing.name}")
    aprx.deleteItem(lyt_existing)
# -------------------------------

bg_feature_layers = []
bg_raster_list = []
bg_raster_names_only = []

folders_dict = {"1945": "Ορθοφωτοχάρτης έτους 1945",
                "1960": "Ορθοφωτοχάρτης έτους 1960",
                "1996": "Ορθοφωτοχάρτης ετών 1996-1998",
                "KYKLADES_LSO25_ECW": "Ορθοφωτοχάρτης ετών 2015-2016",
                "LSO_KYKLADES": "Ορθοφωτοχάρτης ετών 2007-2009",
                "5ARIA_GEO_CORRECT": "Ορθοφωτοχάρτης ΓΥΣ έτους 1983",
                "_ISLANDS": "Ορθοφωτοχάρτης έτους 1960",
                "None": "Χωρίς υπόβαθρο"}

# 1. Parse and Sort
arcpy.AddMessage("Parsing background layers...")


def find_layer_recursive(map_obj, layer_name):
    """Recursively search for a layer by name or longName."""
    all_layers = map_obj.listLayers()
    for lyr in all_layers:
        if lyr.name == layer_name or getattr(lyr, "longName", "") == layer_name:
            return lyr
    return None


for name in bg_layer_names:
    lyr_obj = find_layer_recursive(m, name)
    if lyr_obj:
        if lyr_obj.isFeatureLayer:
            bg_feature_layers.append(lyr_obj.name)
        elif lyr_obj.isRasterLayer:
            try:
                full_path = lyr_obj.dataSource
                folder_path = os.path.dirname(full_path)
                raster_date = os.path.basename(os.path.dirname(folder_path))

                if raster_date in folders_dict.keys():
                    bg_raster_list.append([lyr_obj.name, folders_dict[raster_date]])
                else:
                    bg_raster_list.append([lyr_obj.name, raster_date])

                bg_raster_names_only.append(lyr_obj.name)
            except Exception as e:
                arcpy.AddWarning(f"Could not process path for raster {name}: {str(e)}")
    else:
        arcpy.AddWarning(f"Layer '{name}' not found in active map.")

# ... existing code ...
bg_raster_list.sort(key=lambda x: x[1], reverse=True)

# ADD THIS BLOCK
if always_visible:
    bg_raster_names_only.append(always_visible)

# 2. Functions

def set_layer_visibility(map_obj, layers_to_show):
    """
    Sets visibility for layers in layers_to_show AND their parent groups.
    All other layers are turned off.
    """
    layers_to_show_set = set(layers_to_show)
    arcpy.AddMessage("Layers to show: " + ", ".join(layers_to_show_set))
    visible_long_names = set()

    # First pass: Identify target layers and calculate their parent paths
    for lyr in map_obj.listLayers():
        if lyr.name in layers_to_show_set:
            # The layer itself must be visible
            visible_long_names.add(lyr.longName)

            # All parent groups must also be visible
            # Parse longName (e.g., "Group\SubGroup\Layer")
            if hasattr(lyr, "longName"):
                parts = lyr.longName.split('\\')
                # Reconstruct each parent path segment
                for i in range(1, len(parts)):
                    parent_path = "\\".join(parts[:i])
                    visible_long_names.add(parent_path)

    # Second pass: Apply visibility
    for lyr in map_obj.listLayers():
        # Check against longName (full path) to ensure correct hierarchy handling
        if hasattr(lyr, "longName") and lyr.longName in visible_long_names:
            lyr.visible = True
        else:
            lyr.visible = False


def create_layout_and_export(layout_title, visible_layers, zoom_target_layer_name, scale_factor, raster_year,
                             layout_count):
    arcpy.AddMessage("Creating Layout: " + layout_title)

    # Page Setup
    page_width = (297 / 25.4) * 72.0
    page_height = (210 / 25.4) * 72.0

    lyt = aprx.createLayout(page_width, page_height, "POINT", layout_title)

    # Map Frame
    ll_x, ll_y = 50, 50
    ur_x, ur_y = page_width - 50, page_height - 50
    coords = [[ll_x, ll_y], [ur_x, ll_y], [ur_x, ur_y], [ll_x, ur_y], [ll_x, ll_y]]

    mf_polygon = arcpy.Polygon(arcpy.Array([arcpy.Point(*xy) for xy in coords]))
    mf = lyt.createMapFrame(mf_polygon, m, "Main Map")

    # 1. Get the CIM definition for the layout (V3 is for Pro 3.x and later)
    lyt_cim = lyt.getDefinition('V3')

    # 2. Iterate through layout elements to find your Map Frame
    if layout_count == last_count:
        for elm in lyt_cim.elements:
            if elm.name == "Main Map":
                # 3. Set the border symbol to None to remove it
                elm.graphicFrame.borderSymbol = None

    # 4. Push the modified CIM definition back to the layout
    lyt.setDefinition(lyt_cim)

    set_layer_visibility(m, visible_layers)

    # Set Extent
    try:
        mf.camera.setExtent(arcpy.Extent(*[float(c) for c in extent.split()[:4]]))
        mf.camera.scale = mf.camera.scale * scale_factor
        arcpy.AddMessage(f"Set map frame to layer '{zoom_target_layer_name}' with scale factor {scale_factor}.")
    except Exception as e:
        arcpy.AddWarning(f"Could not set extent: {e}")

    arcpy.AddMessage("Adding Legend and map surrounds")
    if layout_count != last_count:
        # --- ADD LEGEND ("Legend 2" - No Title, Fixed Size) ---
        try:
            leg_style = aprx.listStyleItems(style="Favorites", style_class="LEGEND")[0]
            leg_point = arcpy.Point(61, 240)
            if layout_count > 1:
                leg_point = arcpy.Point(61, 117)

            leg = lyt.createMapSurroundElement(leg_point, "LEGEND", mf, leg_style, "Legend")

            # Dimensions
            leg.elementWidth = 150
            leg.elementHeight = 320

            # Enable and Set Title
            leg.showTitle = True
            leg.title = "ΥΠΟΜΝΗΜΑ"

            # --- CIM: Remove Raster Layers & Disable AutoAdd ---
            leg_cim = leg.getDefinition("V2")
            if hasattr(leg_cim, "autoAdd"):
                leg_cim.autoAdd = False

            original_items = leg_cim.items
            kept_items = []

            for item in original_items:
                is_raster = False
                for r_name in bg_raster_names_only:
                    if r_name == item.name:
                        is_raster = True
                        break

                if not is_raster:
                    if hasattr(item, "showLayerName"):
                        item.showLayerName = False
                    kept_items.append(item)

            leg_cim.items = kept_items
            leg.setDefinition(leg_cim)
            # ---------------------------------------------------------
            # NEW LINES START HERE
            # ---------------------------------------------------------
            # Only show features visible in the current map extent
            for itm in leg.items:
                itm.showVisibleFeatures = True
            # ---------------------------------------------------------
            # 2. Force frame adjustment
            leg.fittingStrategy = "AdjustFrame"

            # 3. Get current dimensions (this should be accurate after fittingStrategy)
            current_height = leg.elementHeight
            current_width = leg.elementWidth  # Not strictly needed but good for reference

            # 4. Define Padding
            padding = 10
            map_frame_bottom_y = 50
            map_frame_left_x = 50

            # 5. Calculate Position (Top-Left Anchor - Default)
            # We want the bottom of the legend to be at y = 50 + 10 = 60
            # So the Top Y must be 60 + height
            new_x = map_frame_left_x + padding
            new_y = map_frame_bottom_y + padding + current_height

            # 6. Apply Position
            # Ensure we are using the default Top-Left anchor logic by NOT setting setAnchor
            # or forcing it to Top-Left if you suspect it's changed.
            leg.setAnchor("TOP_LEFT_CORNER")
            leg.elementPositionX = new_x
            leg.elementPositionY = new_y

            arcpy.AddMessage(f"Legend placed at Top-Left: {new_x}, {new_y} (Height: {current_height})")

        except Exception as e:
            arcpy.AddWarning(f"Legend Error: {e}")

        # --- DATE TEXT BOX ---
        if raster_year:
            try:
                text_style = aprx.listStyleItems(style="Favorites", style_class="TEXT")[1]
                text_point = arcpy.Point(574, 51)
                aprx.createTextElement(lyt, geometry=text_point, text_type='POINT',
                                       text=f"Υπόβαθρο: {raster_year}", style_item=text_style)
            except:
                pass

        # --- PAGE NUMBER TEXT BOX ---
        try:
            text_style = aprx.listStyleItems(style="Favorites", style_class="TEXT")[0]
            text_point = arcpy.Point(304, 20)
            text_to_add = f"Εικόνα {layout_count}: Γεωτεμάχιο - Δασικός Χάρτης" if layout_count == 1 else f"Εικόνα {layout_count}: Γεωτεμάχιο & Επίδικο τμήμα"
            aprx.createTextElement(lyt, geometry=text_point, text_type='POINT', text=text_to_add,
                                   style_item=text_style)
        except:
            pass

        # --- LOGO ---
        try:
            templates_folder = os.path.join('C:', "../template data")
            logo_path = os.path.join(templates_folder, "logo.png")
            logo_point = arcpy.Point(690, 30)
            aprx.createPictureElement(lyt, geometry=logo_point, path=logo_path)
        except:
            pass

        # --- SURROUNDS ---
        try:
            na_style = aprx.listStyleItems(style="Favorites", style_class="NORTH_ARROW")[0]
            na = lyt.createMapSurroundElement(arcpy.Point(755, 500), "NORTH_ARROW", mf,
                                              na_style,
                                              "North Arrow")
            na.elementWidth = 30
        except:
            pass

        try:
            sb_style = aprx.listStyleItems(style="Favorites", style_class="SCALE_BAR")[0]
            sb = lyt.createMapSurroundElement(arcpy.Point(50, 5), "SCALE_BAR", mf, sb_style, "Scale Bar")
            sb.elementWidth = 200

            lyt_cim = lyt.getDefinition("V2")
            lyt.setDefinition(lyt_cim)
        except:
            pass

    # Path to your exported .mapx file
    arcpy.AddMessage("Exporting layout.mapx")
    map_file_path = os.path.join(out_folder, f"{layout_title}_Theme.mapx")
    m.exportToMAPX(map_file_path)
    # 1. Import the map file
    # This returns the newly created Map object
    new_map = aprx.importDocument(map_file_path)

    # 2. Verify the name immediately
    print(f"Imported Map Name: {new_map.name}")

    # 3. If the name is still wrong, force it here
    if new_map.name != layout_title:
        new_map.name = layout_title
        print(f"Name corrected to: {new_map.name}")

    # Save the project to keep the changes
    aprx.save()

    # Export
    png_path = os.path.join(out_folder, f"{layout_title}.png")
    transparency = True if layout_count == last_count else False
    lyt.exportToPNG(png_path, resolution=300, transparent_background=transparency)


# Execution
if main_layers_list and bg_raster_list:
    target = main_layers_list[0]
    r_name, r_year = bg_raster_list[0]

    # MODIFY THIS LIST
    visible = [target] + bg_feature_layers + [r_name]
    if always_visible:
        arcpy.AddMessage("Adding always visible layer: " + always_visible)
        visible.append(always_visible)

    create_layout_and_export("Layout_1", visible, target, 3, r_year, 1)

    count = 2 + int(empty_pages)
    for r_name, r_year in bg_raster_list:
        # MODIFY THIS LIST
        visible = main_layers_list + [r_name]
        if always_visible:
            visible.append(always_visible)

        create_layout_and_export(f"Layout_{count}", visible, main_layers_list[0] if main_layers_list else None, 1,
                                 r_year, count)
        count += 1

    last_count = count
    # DO NOT MODIFY THE FINAL CALL (It excludes always_visible)
    create_layout_and_export(f"Layout_{count}", main_layers_list, main_layers_list[0] if main_layers_list else None,
                             1, None, count)

arcpy.AddMessage("Finished.")

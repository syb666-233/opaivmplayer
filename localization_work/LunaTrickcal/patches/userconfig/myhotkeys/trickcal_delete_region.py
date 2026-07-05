# Trickcal: delete one OCR overlay region (drag a box over the target).
# Luna: Settings -> Hotkeys -> Add custom -> trickcal_delete_region.py
# Suggested key: 5


def OnHotKeyClicked():
    import trickcal_overlay

    trickcal_overlay.start_delete_region_picker()

# Trickcal batch OCR + per-region overlay
# Copy to: userconfig/myhotkeys/trickcal_batch_ocr.py
# Register in Luna: Settings -> Hotkeys -> add custom -> trickcal_batch_ocr


def OnHotKeyClicked():
    import trickcal_overlay

    trickcal_overlay.batch_translate_regions()

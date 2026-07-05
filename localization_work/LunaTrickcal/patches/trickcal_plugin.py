# Trickcal plugin entry — copy to LunaTranslator/trickcal_plugin.py
from traceback import print_exc


def install(base):
    try:
        import trickcal_overlay

        trickcal_overlay.install(base)
    except Exception:
        print_exc()

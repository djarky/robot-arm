"""
input_manager.py — Wrapper de compatibilidad.

Este archivo existe para mantener las importaciones existentes funcionando:
    from input_manager import InputManager

La implementación real está en el paquete inputs/.
"""

from inputs import InputManager
from inputs.dsu_handler import DSUClient

__all__ = ["InputManager", "DSUClient"]

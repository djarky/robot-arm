"""
qt_key_names.py — Diccionario de nombres amigables para códigos de tecla Qt.

Los códigos corresponden a las constantes Qt.Key_* de PySide6/PyQt.
Este módulo es de solo lectura y se usa para presentar nombres legibles
en la UI del InputMapperDialog cuando el dispositivo activo es Teclado (KM).

Referencia: https://doc.qt.io/qt-6/qt.html#Key-enum
"""

# Mapeo: int(Qt.Key_*) → str(nombre amigable en español)
QT_KEY_NAMES = {
    # --- Letras ---
    65: "A", 66: "B", 67: "C", 68: "D", 69: "E",
    70: "F", 71: "G", 72: "H", 73: "I", 74: "J",
    75: "K", 76: "L", 77: "M", 78: "N", 79: "O",
    80: "P", 81: "Q", 82: "R", 83: "S", 84: "T",
    85: "U", 86: "V", 87: "W", 88: "X", 89: "Y",
    90: "Z",

    # --- Números (fila superior) ---
    48: "0", 49: "1", 50: "2", 51: "3", 52: "4",
    53: "5", 54: "6", 55: "7", 56: "8", 57: "9",

    # --- Teclas especiales ---
    32: "Espacio",
    16777216: "Escape",
    16777217: "Tab",
    16777219: "Retroceso",
    16777220: "Enter",
    16777221: "Enter (Num)",
    16777222: "Insert",
    16777223: "Suprimir",
    16777224: "Pausa",
    16777225: "Impr Pantalla",
    16777226: "Sys Req",
    16777227: "Clear",

    # --- Flechas ---
    16777234: "← Izquierda",
    16777235: "↑ Arriba",
    16777236: "→ Derecha",
    16777237: "↓ Abajo",

    # --- Navegación ---
    16777232: "Inicio",
    16777233: "Fin",
    16777238: "Re Pág",
    16777239: "Av Pág",

    # --- Modificadores ---
    16777248: "Shift Izq",
    16777249: "Ctrl Izq",
    16777251: "Alt Izq",
    16777250: "Meta / Super",
    16777252: "Bloq Mayús",
    16777253: "Bloq Num",
    16777254: "Bloq Despl",

    # Modificadores derechos (Qt los distingue)
    16781699: "Shift Der",
    16781700: "Ctrl Der",
    16781701: "Alt Der",
    16781702: "Meta Der",

    # --- Teclas de función ---
    16777264: "F1",  16777265: "F2",  16777266: "F3",  16777267: "F4",
    16777268: "F5",  16777269: "F6",  16777270: "F7",  16777271: "F8",
    16777272: "F9",  16777273: "F10", 16777274: "F11", 16777275: "F12",

    # --- Teclado numérico ---
    16777456: "Num 0", 16777457: "Num 1", 16777458: "Num 2",
    16777459: "Num 3", 16777460: "Num 4", 16777461: "Num 5",
    16777462: "Num 6", 16777463: "Num 7", 16777464: "Num 8",
    16777465: "Num 9",
    16777453: "Num *",
    16777451: "Num +",
    16777452: "Num ,",
    16777454: "Num -",
    16777455: "Num .",
    16777450: "Num /",

    # --- Símbolos comunes ---
    44: ",",   45: "-",   46: ".",   47: "/",
    59: ";",   61: "=",   91: "[",   92: "\\",
    93: "]",   96: "`",   39: "'",

    # --- Teclas especiales Español / Latín ---
    209: "Ñ",
    199: "Ç",
    161: "¡",

    # --- AltGr (común en teclados ES/LATAM) ---
    16781571: "AltGr",

    # --- Menú contextual ---
    16777301: "Menú",
}


def get_qt_key_name(key_code):
    """
    Retorna un nombre amigable para un código de tecla Qt.

    Args:
        key_code: int — Código numérico de la tecla (Qt.Key_*).

    Returns:
        str — Nombre legible (ej: "Q", "Espacio", "↑ Arriba").
              Si el código no está en el diccionario, retorna "Tecla <código>".
    """
    name = QT_KEY_NAMES.get(key_code)
    if name:
        return name

    # Fallback: si es un carácter imprimible ASCII, mostrar el carácter
    if 33 <= key_code <= 126:
        return chr(key_code)

    return f"Código {key_code}"

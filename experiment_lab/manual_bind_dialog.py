import os
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

class ManualBindDialog(QDialog):
    """Diálogo elegante para seleccionar un input de forma manual desde una lista."""
    def __init__(self, action_name, category, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Selección Manual de Input")
        self.setModal(True)
        self.resize(420, 180)
        
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #eee; }
            QLabel { color: #ddd; font-weight: bold; }
            QComboBox { 
                background-color: #2b2b2b; 
                border: 1px solid #444; 
                border-radius: 4px; 
                padding: 6px; 
                color: #eee; 
                font-weight: bold;
            }
            QPushButton { 
                padding: 8px 16px; 
                font-weight: bold; 
                border-radius: 4px; 
            }
            QPushButton#Save { background-color: #2e7d32; color: white; border: none; }
            QPushButton#Save:hover { background-color: #388e3c; }
            QPushButton#Save:disabled { background-color: #224422; color: #666; }
            QPushButton#Cancel { background-color: #424242; color: #eee; border: 1px solid #555; }
            QPushButton#Cancel:hover { background-color: #4f4f4f; }
        """)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)
        
        lbl_info = QLabel(f"Vincular entrada para:\n{action_name}")
        lbl_info.setStyleSheet("font-size: 13px; color: #4CAF50;")
        lbl_info.setAlignment(Qt.AlignCenter)
        layout.addWidget(lbl_info)
        
        self.combo = QComboBox()
        self._populate_inputs(category)
        layout.addWidget(self.combo)
        
        btns = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("Cancel")
        self.btn_cancel.clicked.connect(self.reject)
        
        self.btn_save = QPushButton("Vincular")
        self.btn_save.setObjectName("Save")
        self.btn_save.clicked.connect(self.accept)
        
        btns.addWidget(self.btn_cancel)
        btns.addWidget(self.btn_save)
        layout.addLayout(btns)
        
        # Conectar validación para deshabilitar si se selecciona una cabecera
        self.combo.currentIndexChanged.connect(self.on_selection_changed)
        self.on_selection_changed()
        
    def _populate_inputs(self, category):
        # Rellenar combo según categoría
        if category == "Teclado":
            try:
                from .inputs.qt_key_names import QT_KEY_NAMES
            except ImportError:
                try:
                    from inputs.qt_key_names import QT_KEY_NAMES
                except ImportError:
                    from qt_key_names import QT_KEY_NAMES
            # Ordenar por nombre amigable
            sorted_keys = sorted(QT_KEY_NAMES.items(), key=lambda x: x[1])
            for key_code, name in sorted_keys:
                self.combo.addItem(f"Tecla {name}", {"type": "button", "id": key_code})
                
        elif category in ("Mando Xbox", "Mando PS5", "Nintendo Joycons", "Otros (Custom)"):
            # Botones
            button_names = {
                0: "Botón A / Cruz (0)",
                1: "Botón B / Círculo (1)",
                2: "Botón X / Cuadrado (2)",
                3: "Botón Y / Triángulo (3)",
                4: "LB / L1 (4)",
                5: "RB / R1 (5)",
                6: "Vista / Share (6)",
                7: "Menú / Options (7)",
                8: "Palanca Izq L3 (8)",
                9: "Palanca Der R3 (9)",
                10: "Guía (10)"
            }
            self.combo.addItem("--- BOTONES ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for i in range(16):
                name = button_names.get(i, f"Botón {i}")
                self.combo.addItem(name, {"type": "button", "id": i})
                
            # Ejes
            axis_names = {
                0: "Palanca Izq X (Eje 0)",
                1: "Palanca Izq Y (Eje 1)",
                2: "Gatillo Izq LT (Eje 2)",
                3: "Palanca Der X (Eje 3)",
                4: "Palanca Der Y (Eje 4)",
                5: "Gatillo Der RT (Eje 5)"
            }
            self.combo.addItem("--- EJES ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for i in range(6):
                name = axis_names.get(i, f"Eje {i}")
                self.combo.addItem(name, {"type": "axis", "id": i})
                
            # Crucetas (Hats)
            self.combo.addItem("--- CRUCETA ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            self.combo.addItem("Cruceta Arriba", {"type": "hat", "id": [0, 1, 1]})
            self.combo.addItem("Cruceta Abajo", {"type": "hat", "id": [0, 1, -1]})
            self.combo.addItem("Cruceta Izquierda", {"type": "hat", "id": [0, 0, -1]})
            self.combo.addItem("Cruceta Derecha", {"type": "hat", "id": [0, 0, 1]})
            
        elif category == "Wiimote":
            # Botones
            button_names = {
                304: "Botón A (304)",
                305: "Botón B (305)",
                306: "Botón C (Nunchuk) (306)",
                309: "Botón Z (Nunchuk) (309)",
                412: "Botón - (412)",
                407: "Botón + (407)",
                257: "Botón 1 (257)",
                258: "Botón 2 (258)",
                103: "D-Pad UP (103)",
                108: "D-Pad DOWN (108)",
                105: "D-Pad LEFT (105)",
                106: "D-Pad RIGHT (106)",
                316: "Botón Casa Home (316)"
            }
            self.combo.addItem("--- BOTONES WIIMOTE ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for code, name in button_names.items():
                self.combo.addItem(name, {"type": "button", "id": code})
                
            # Ejes
            axis_names = {
                0: "Inclinación X (Wiimote) (Eje 0)",
                1: "Inclinación Y (Wiimote) (Eje 1)",
                2: "Inclinación Z (Wiimote) (Eje 2)",
                3: "Giro Yaw (Wiimote) (Eje 3)",
                4: "Giro Roll (Wiimote) (Eje 4)",
                5: "Giro Pitch (Wiimote) (Eje 5)",
                6: "Inclinación X (Nunchuk) (Eje 6)",
                7: "Inclinación Y (Nunchuk) (Eje 7)",
                8: "Inclinación Z (Nunchuk) (Eje 8)",
                116: "Palanca Nunchuk X (Eje 116)",
                117: "Palanca Nunchuk Y (Eje 117)"
            }
            self.combo.addItem("--- EJES WIIMOTE ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for code, name in axis_names.items():
                self.combo.addItem(name, {"type": "axis", "id": code})
                
        elif category == "DSU":
            button_names = {
                0: "Botón Cuadrado / Y (0)",
                1: "Botón Cruz / A (1)",
                2: "Botón Círculo / B (2)",
                3: "Botón Triángulo / X (3)",
                4: "Botón L1 (4)",
                5: "Botón R1 (5)",
                6: "Gatillo L2 (Digital) (6)",
                7: "Gatillo R2 (Digital) (7)",
                8: "Botón Share / Select (8)",
                9: "Botón Options / Start (9)",
            }
            self.combo.addItem("--- BOTONES DSU ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for code, name in button_names.items():
                self.combo.addItem(name, {"type": "button", "id": code})
                
            axis_names = {
                "lx": "Stick Izquierdo X",
                "ly": "Stick Izquierdo Y",
                "rx": "Stick Derecho X",
                "ry": "Stick Derecho Y",
                "accel_0": "Inclinación X (Lateral)",
                "accel_1": "Inclinación Y (Frontal)",
                "accel_2": "Inclinación Z (Elevación)",
                "gyro_0": "Giro Pitch (Cabeceo)",
                "gyro_1": "Giro Yaw (Giro)",
                "gyro_2": "Giro Roll (Alabeo)",
            }
            self.combo.addItem("--- EJES DSU ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for code, name in axis_names.items():
                self.combo.addItem(name, {"type": "axis", "id": code})
                
        elif category == "MIDI":
            # CCs
            self.combo.addItem("--- CONTROLADORES CC (EJES) ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for i in range(128):
                self.combo.addItem(f"CC {i} (Potenciómetro/Knob)", {"type": "axis", "id": i})
                
            # Notes
            self.combo.addItem("--- NOTAS MIDI (BOTONES) ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
            for i in range(128):
                octave = (i // 12) - 1
                note = note_names[i % 12]
                self.combo.addItem(f"Nota {note}{octave} ({i})", {"type": "button", "id": i})
                
        elif category == "Serial":
            self.combo.addItem("--- EJES SERIAL (A0-A7) ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for i in range(8):
                self.combo.addItem(f"Eje Serial A{i}", {"type": "axis", "id": i})
                
            self.combo.addItem("--- BOTONES SERIAL (B0-B7) ---", None)
            self.combo.setItemData(self.combo.count()-1, QColor("#888"), Qt.ForegroundRole)
            for i in range(8):
                self.combo.addItem(f"Botón Serial B{i}", {"type": "button", "id": i})
                
        else:
            self.combo.addItem("Categoría no soportada para selección manual", None)
            
    def on_selection_changed(self):
        data = self.combo.currentData()
        self.btn_save.setEnabled(data is not None)
            
    def get_selected_bind(self):
        return self.combo.currentData()

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QProgressBar, QGroupBox, QFileDialog, QDoubleSpinBox
)
from PySide6.QtCore import Qt, Signal
import os

class CNCControlWidget(QGroupBox):
    """
    Widget modular para el control de trayectorias CNC basadas en SVG.
    Modos:
    - idle: No hay SVG cargado.
    - positioning: SVG cargado, el usuario puede mover/rotar/escalar con el Gizmo.
    - running: El brazo está ejecutando la trayectoria.
    """
    # Señales para comunicar con la ventana principal del Lab
    start_requested = Signal()
    stop_requested = Signal()
    reset_requested = Signal()
    params_changed = Signal(float, float) # (safety_height, feedrate)
    file_selected = Signal(str)

    MODE_IDLE = "idle"
    MODE_POSITIONING = "positioning"
    MODE_RUNNING = "running"

    def __init__(self, parent=None):
        super().__init__("Trayectoria CNC (SVG)", parent)
        self.current_svg_path = None
        self.mode = self.MODE_IDLE
        self.init_ui()
        self._update_ui_for_mode()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # Estado / Modo actual
        self.lbl_mode = QLabel("MODO: INACTIVO")
        self.lbl_mode.setAlignment(Qt.AlignCenter)
        self.lbl_mode.setStyleSheet(
            "font-weight: bold; font-size: 11px; padding: 4px; "
            "background-color: #222; color: #666; border-radius: 3px;"
        )
        layout.addWidget(self.lbl_mode)
        
        # Info de archivo
        self.lbl_file = QLabel("Archivo: Ninguno")
        self.lbl_file.setWordWrap(True)
        self.lbl_file.setStyleSheet("color: #888; font-style: italic; font-size: 10px;")
        layout.addWidget(self.lbl_file)
        
        # Botones de Acción
        btn_row = QHBoxLayout()
        
        self.btn_load = QPushButton("📂 Cargar SVG")
        self.btn_load.clicked.connect(self.on_load_clicked)
        self.btn_load.setStyleSheet("background-color: #333;")
        
        self.btn_start = QPushButton("▶ INICIAR")
        self.btn_start.setEnabled(False)
        self.btn_start.clicked.connect(self._on_start)
        self.btn_start.setStyleSheet("background-color: #2e7d32; font-weight: bold;")
        
        self.btn_stop = QPushButton("■ STOP")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._on_stop)
        self.btn_stop.setStyleSheet("background-color: #c62828; font-weight: bold;")
        
        self.btn_reset = QPushButton("↺ RESET")
        self.btn_reset.setEnabled(False)
        self.btn_reset.clicked.connect(self._on_reset)
        self.btn_reset.setStyleSheet("background-color: #455a64;")
        
        btn_row.addWidget(self.btn_load)
        btn_row.addWidget(self.btn_start)
        btn_row.addWidget(self.btn_stop)
        btn_row.addWidget(self.btn_reset)
        layout.addLayout(btn_row)
        
        # Parámetros (Altura de seguridad y Feedrate)
        params_row = QHBoxLayout()
        
        params_row.addWidget(QLabel("Seguridad (m):"))
        self.spin_safety = QDoubleSpinBox()
        self.spin_safety.setRange(0.01, 5.0)
        self.spin_safety.setValue(0.5)
        self.spin_safety.setSingleStep(0.1)
        self.spin_safety.valueChanged.connect(self._emit_params)
        params_row.addWidget(self.spin_safety)
        
        params_row.addWidget(QLabel("Velocidad:"))
        self.spin_feedrate = QDoubleSpinBox()
        self.spin_feedrate.setRange(0.1, 10.0)
        self.spin_feedrate.setValue(1.5)
        self.spin_feedrate.setSingleStep(0.1)
        self.spin_feedrate.valueChanged.connect(self._emit_params)
        params_row.addWidget(self.spin_feedrate)
        
        params_row.addStretch()
        layout.addLayout(params_row)
        
        # Instrucciones contextuales
        self.lbl_hint = QLabel("")
        self.lbl_hint.setWordWrap(True)
        self.lbl_hint.setStyleSheet("color: #666; font-size: 9px; padding: 2px;")
        layout.addWidget(self.lbl_hint)
        
        # Barra de Progreso
        self.progress = QProgressBar()
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setStyleSheet("""
            QProgressBar { border: 1px solid #444; border-radius: 3px; background: #222; text-align: center; }
            QProgressBar::chunk { background-color: #4CAF50; }
        """)
        layout.addWidget(self.progress)

    def on_load_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar Vector SVG", "", "Archivos SVG (*.svg)"
        )
        if path:
            self.set_svg_file(path)
            self.file_selected.emit(path)

    def set_svg_file(self, path):
        self.current_svg_path = path
        filename = os.path.basename(path)
        self.lbl_file.setText(f"Archivo: {filename}")
        self.lbl_file.setStyleSheet("color: #4CAF50; font-weight: bold; font-size: 10px;")

    def set_mode_positioning(self):
        """Cambia al modo de posicionamiento (SVG cargado, listo para mover)."""
        self.mode = self.MODE_POSITIONING
        self.progress.setValue(0)
        self._update_ui_for_mode()

    def set_running(self, running):
        """Cambia entre modo ejecución y posicionamiento."""
        if running:
            self.mode = self.MODE_RUNNING
        else:
            self.mode = self.MODE_POSITIONING
        self._update_ui_for_mode()

    def update_progress(self, val):
        self.progress.setValue(val)

    def _on_start(self):
        self.mode = self.MODE_RUNNING
        self._update_ui_for_mode()
        self.start_requested.emit()

    def _on_stop(self):
        self.mode = self.MODE_POSITIONING
        self._update_ui_for_mode()
        self.stop_requested.emit()

    def _on_reset(self):
        self.progress.setValue(0)
        self.reset_requested.emit()

    def _update_ui_for_mode(self):
        """Actualiza la apariencia de todos los controles según el modo actual."""
        if self.mode == self.MODE_IDLE:
            self.lbl_mode.setText("MODO: INACTIVO")
            self.lbl_mode.setStyleSheet(
                "font-weight: bold; font-size: 11px; padding: 4px; "
                "background-color: #222; color: #666; border-radius: 3px;"
            )
            self.btn_load.setEnabled(True)
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(False)
            self.btn_reset.setEnabled(False)
            self.lbl_hint.setText("Carga un archivo SVG para comenzar.")
            
        elif self.mode == self.MODE_POSITIONING:
            self.lbl_mode.setText("MODO: POSICIONAMIENTO")
            self.lbl_mode.setStyleSheet(
                "font-weight: bold; font-size: 11px; padding: 4px; "
                "background-color: #1a237e; color: #7986CB; border-radius: 3px;"
            )
            self.btn_load.setEnabled(True)
            self.btn_start.setEnabled(True)
            self.btn_stop.setEnabled(False)
            self.btn_reset.setEnabled(True)
            self.lbl_hint.setText(
                "Haz clic en el holograma para seleccionarlo. "
                "Usa G (mover), R (rotar), S (escalar) para posicionarlo. "
                "Presiona INICIAR cuando esté listo."
            )
            
        elif self.mode == self.MODE_RUNNING:
            self.lbl_mode.setText("MODO: EJECUTANDO ▶")
            self.lbl_mode.setStyleSheet(
                "font-weight: bold; font-size: 11px; padding: 4px; "
                "background-color: #1b5e20; color: #81C784; border-radius: 3px;"
            )
            self.btn_load.setEnabled(False)
            self.btn_start.setEnabled(False)
            self.btn_stop.setEnabled(True)
            self.btn_reset.setEnabled(False)
            self.lbl_hint.setText("El brazo está siguiendo la trayectoria. Presiona STOP para detener.")

    def _emit_params(self):
        """Emite los parámetros actuales de la UI."""
        self.params_changed.emit(self.spin_safety.value(), self.spin_feedrate.value())

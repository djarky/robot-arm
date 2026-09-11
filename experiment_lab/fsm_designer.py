import os
import sys
import json
import time
import math

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, 
    QLabel, QGroupBox, QSplitter, QFrame, QScrollArea, QLineEdit,
    QMenuBar, QMenu, QFileDialog, QInputDialog, QGraphicsView,
    QGraphicsScene, QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem,
    QGraphicsTextItem, QStyle, QGraphicsDropShadowEffect, QComboBox,
    QGraphicsTextItem, QStyle, QGraphicsDropShadowEffect, QComboBox,
    QGridLayout, QDialog
)
from PySide6.QtCore import Qt, QSize, QTimer, QPointF, QRectF, QLineF
from PySide6.QtGui import (
    QFont, QIcon, QPixmap, QAction, QPainter, QPen, QBrush, 
    QColor, QPainterPath, QLinearGradient, QPainterPathStroker
)

# Añadir el raíz del proyecto al path para importar de gui
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if base_dir not in sys.path:
    sys.path.append(base_dir)

from gui.widgets import PoseWidget

# --- GRAPHICAL COMPONENTS ---

class TriggerConfigDialog(QDialog):
    def __init__(self, current_type, current_params, special_keys=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar Transición FSM")
        self.setMinimumWidth(320)
        self.special_keys = special_keys or []
        self.mock_sensors = ["sensor_obstaculo", "sensor_proximidad_j1", "sensor_presion"]
        
        self.setStyleSheet("""
            QDialog { background-color: #1e1e1e; color: #eee; }
            QLabel { font-weight: bold; color: #4CAF50; }
            QComboBox, QLineEdit { background-color: #333; color: white; border: 1px solid #555; padding: 5px; border-radius: 3px; }
            QPushButton { background-color: #2e7d32; color: white; padding: 6px 15px; font-weight: bold; border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #388e3c; }
            QPushButton#btn_cancel { background-color: #d32f2f; }
            QPushButton#btn_cancel:hover { background-color: #e53935; }
        """)
        
        layout = QVBoxLayout(self)
        
        layout.addWidget(QLabel("Tipo de Transición (Disparador):"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["time", "key", "sensor"])
        self.type_combo.setCurrentText(current_type)
        self.type_combo.currentTextChanged.connect(self.on_type_changed)
        layout.addWidget(self.type_combo)
        
        layout.addSpacing(10)
        layout.addWidget(QLabel("Parámetros del Disparador:"))
        
        self.param_stack = QWidget()
        self.param_layout = QVBoxLayout(self.param_stack)
        self.param_layout.setContentsMargins(0, 0, 0, 0)
        
        self.time_input = QLineEdit()
        self.time_input.setPlaceholderText("Ej: 1.5 (segundos)")
        
        self.key_combo = QComboBox()
        if not self.special_keys:
            self.key_combo.addItem("No hay teclas especiales (Usa Input Mapper)")
            self.key_combo.setEnabled(False)
        else:
            self.key_combo.addItems(self.special_keys)
        
        self.sensor_combo = QComboBox()
        self.sensor_combo.addItems(self.mock_sensors)
        
        self.param_layout.addWidget(self.time_input)
        self.param_layout.addWidget(self.key_combo)
        self.param_layout.addWidget(self.sensor_combo)
        layout.addWidget(self.param_stack)
        
        # Set initial values
        self.time_input.setText(str(current_params) if current_type == "time" else "1.0")
        if current_type == "key" and str(current_params) in self.special_keys:
            self.key_combo.setCurrentText(str(current_params))
            
        if current_type == "sensor" and str(current_params) in self.mock_sensors:
            self.sensor_combo.setCurrentText(str(current_params))
            
        self.on_type_changed(current_type)
        
        layout.addSpacing(15)
        btn_layout = QHBoxLayout()
        self.btn_ok = QPushButton("ACEPTAR")
        self.btn_cancel = QPushButton("CANCELAR")
        self.btn_cancel.setObjectName("btn_cancel")
        self.btn_ok.clicked.connect(self.accept)
        self.btn_cancel.clicked.connect(self.reject)
        
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_cancel)
        btn_layout.addWidget(self.btn_ok)
        layout.addLayout(btn_layout)
        
    def on_type_changed(self, text):
        self.time_input.hide()
        self.key_combo.hide()
        self.sensor_combo.hide()
        
        if text == "time":
            self.time_input.show()
        elif text == "key":
            self.key_combo.show()
        elif text == "sensor":
            self.sensor_combo.show()
            
    def get_values(self):
        t_type = self.type_combo.currentText()
        if t_type == "time":
            try:
                val = float(self.time_input.text())
            except ValueError:
                val = 1.0
            return t_type, val
        elif t_type == "key":
            return t_type, self.key_combo.currentText()
        elif t_type == "sensor":
            return t_type, self.sensor_combo.currentText()
        return t_type, None

class TransitionWire(QGraphicsPathItem):
    """Representa una conexión Bezier entre dos estados."""
    def __init__(self, source_node, target_node):
        super().__init__()
        self.source = source_node
        self.target = target_node
        
        self.type = "time" # "time", "key", "sensor"
        self.params = 1.0 # default 1s
        
        self.setPen(QPen(QColor("#4CAF50"), 3, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        self.setZValue(-1) # Detrás de los nodos
        
        # Cursor especial para indicar que se puede hacer doble clic
        self.setCursor(Qt.PointingHandCursor)
        self.setAcceptHoverEvents(True)
        
        # Label para mostrar qué dispara la transición
        self.label = QGraphicsTextItem(self)
        self.label.setAcceptedMouseButtons(Qt.NoButton) # No bloquea clicks al cable
        self.label.setDefaultTextColor(QColor("#ffa726"))
        self.label.setFont(QFont("Arial", 9, QFont.Bold))
        
        self.update_path()

    def update_path(self):
        if not self.source or not self.target: return
        
        # Avisar a Qt que la geometría va a cambiar para evitar el "embarre"
        self.prepareGeometryChange()
        
        # Obtener puerto asignado (específico para este cable)
        start_pos = self.source.get_output_pos(self)
        end_pos = self.target.get_input_pos()
        
        path = QPainterPath()
        path.moveTo(start_pos)
        
        # Calcular puntos de control para la curva Bezier
        dx = end_pos.x() - start_pos.x()
        cp_dist = max(50, abs(dx) * 0.5)
        
        path.cubicTo(
            start_pos.x() + cp_dist, start_pos.y(),
            end_pos.x() - cp_dist, end_pos.y(),
            end_pos.x(), end_pos.y()
        )
        
        self.setPath(path)
        
        # Actualizar label
        if self.type == "time":
            text = f"⏱ {self.params}s"
        elif self.type == "key":
            p_name = str(self.params).replace("special_key_", "")
            text = f"⌨ {p_name}"
        elif self.type == "sensor":
            p_name = str(self.params).replace("sensor_", "")
            text = f"📡 {p_name}"
        else:
            text = f"{self.type}: {self.params}"
            
        self.label.setPlainText(text)
        mid = path.pointAtPercent(0.5)
        self.label.setPos(mid.x() - self.label.boundingRect().width()/2, mid.y() - 20)
        
        # Notificar al nodo origen para que actualice su pie de página
        if self.source:
            self.source.update_triggers_info()

    def mouseDoubleClickEvent(self, event):
        """Al hacer doble clic, abrir el editor de disparadores."""
        # QGraphicsItem NO tiene .window(), hay que ir vía view
        try:
            view = self.scene().views()[0]
            designer = view.window()
            if hasattr(designer, "edit_wire_trigger"):
                designer.edit_wire_trigger(self)
        except Exception as e:
            print(f"[Wire] Error al buscar ventana: {e}")

    def shape(self):
        """Aumentar el área de colisión del cable para que sea fácil de clickar."""
        path = super().path()
        # Crear un stroke más ancho para el hit-test
        stroker = QPainterPathStroker()
        stroker.setWidth(15) 
        return stroker.createStroke(path)

class StateNodeItem(QGraphicsItem):
    """Nodo Moore: Pose + ID + UI."""
    def __init__(self, state_id, pose_name, angles, thumb_path):
        super().__init__()
        self.state_id = state_id
        self.pose_name = pose_name
        self.angles = angles
        self.thumb_path = thumb_path
        
        self.width = 120
        self.height = 180 # Aumentado para info de triggers
        
        self.setFlag(QGraphicsItem.ItemIsMovable)
        self.setFlag(QGraphicsItem.ItemIsSelectable)
        self.setFlag(QGraphicsItem.ItemSendsGeometryChanges)
        
        self.active_highlight = False
        
        # Cargar pixmap
        self.pixmap = None
        if os.path.exists(thumb_path):
            self.pixmap = QPixmap(thumb_path).scaled(110, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            
        self.setAcceptHoverEvents(True)
        self.hovered_port_idx = -1
        self.wires = [] # Conexiones salientes/entrantes

    def boundingRect(self):
        return QRectF(0, 0, self.width, self.height)

    def paint(self, painter, option, widget):
        # Cuerpo del nodo
        rect = self.boundingRect()
        
        # Estilo premium
        painter.setRenderHint(QPainter.Antialiasing)
        
        # Borde y fondo
        color_bg = QColor("#1e1e1e")
        color_border = QColor("#4CAF50") if self.isSelected() else QColor("#555")
        if self.active_highlight: color_border = QColor("#ffa726") # Color cuando está activo en sim

        painter.setBrush(QBrush(color_bg))
        painter.setPen(QPen(color_border, 2 if not self.isSelected() else 3))
        painter.drawRoundedRect(rect, 10, 10)
        
        # Header (ID)
        painter.setBrush(QBrush(QColor("#333")))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(0, 0, self.width, 30, 8, 8)
        painter.setPen(QColor("white"))
        painter.setFont(QFont("Arial", 10, QFont.Bold))
        painter.drawText(QRectF(0, 0, self.width, 30), Qt.AlignCenter, f"ESTADO: {self.state_id}")
        
        # Thumbnail
        if self.pixmap:
            painter.drawPixmap(5, 35, self.pixmap)
        else:
            painter.setPen(QColor("#666"))
            painter.drawText(QRectF(5, 35, 110, 70), Qt.AlignCenter, "SIN MINIATURA")
            
        # Pose Name
        painter.setPen(QColor("#4CAF50"))
        painter.setFont(QFont("Arial", 9, QFont.Bold))
        painter.drawText(QRectF(5, 110, 110, 20), Qt.AlignCenter, self.pose_name)
        
        # --- NUEVA SECCIÓN: TRIGGERS (TIEMPO / KEY) ---
        painter.setPen(QPen(QColor("#333"), 1))
        painter.drawLine(5, 135, self.width-5, 135)
        
        painter.setFont(QFont("Arial", 8))
        painter.setPen(QColor("#bbb"))
        
        # Recolectar info de transiciones salientes
        t_info = "⏱ -"
        k_info = "⌨ -"
        
        for wire in self.wires:
            if wire.source == self:
                if wire.type == "time": 
                    t_info = f"⏱ {wire.params}s"
                elif wire.type == "key": 
                    p_name = str(wire.params).replace("special_key_", "")
                    k_info = f"⌨ {p_name}"
        
        painter.drawText(QRectF(10, 140, 100, 15), Qt.AlignLeft, t_info)
        painter.drawText(QRectF(10, 155, 100, 15), Qt.AlignLeft, k_info)

        # Puertos de Salida (Multi-puerto / Switch-Case)
        outgoing = [w for w in self.wires if w.source == self]
        num_out = max(1, len(outgoing))
        
        for i in range(num_out):
            port_pos = self.get_local_output_pos(i, num_out)
            color = QColor("#4CAF50") # Verde por defecto
            
            # Efecto de resaltado/pulso si está hover
            if self.hovered_port_idx == i:
                color = QColor("#81C784") # Verde más claro
                painter.setPen(QPen(QColor("white"), 1))
            else:
                painter.setPen(Qt.NoPen)
            
            # Si hay más de una salida, denotar condición
            if len(outgoing) > 1:
                painter.setFont(QFont("Arial", 7))
                cond_text = f"[{outgoing[i].type[0].upper()}:{outgoing[i].params}]" if i < len(outgoing) else "[+]"
                painter.setPen(QPen(QColor("#888"), 1))
                painter.drawText(port_pos.x() - 40, port_pos.y() + 4, cond_text)
            
            painter.setBrush(QBrush(color))
            painter.drawEllipse(port_pos.x() - 7, port_pos.y() - 7, 14, 14) # Un poco más grande

        # Puerto de Entrada (Azul)
        painter.setBrush(QBrush(QColor("#2196F3")))
        painter.drawEllipse(0, self.height / 2 - 6, 12, 12)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            for wire in self.wires:
                wire.update_path()
        return super().itemChange(change, value)

    def get_output_pos(self, wire=None):
        """Devuelve la posición absoluta de un puerto de salida específico."""
        outgoing = [w for w in self.wires if w.source == self]
        idx = 0
        if wire in outgoing:
            idx = outgoing.index(wire)
        
        local_pos = self.get_local_output_pos(idx, max(1, len(outgoing)))
        return self.scenePos() + local_pos

    def get_local_output_pos(self, index, total):
        """Calcula la posición local en el lado derecho para el puerto 'index'."""
        if total <= 1:
            return QPointF(self.width, self.height / 2)
        
        # Escalonar puertos verticalmente
        y_step = 30
        start_y = (self.height / 2) - ((total - 1) * y_step / 2)
        return QPointF(self.width, start_y + index * y_step)

    def get_input_pos(self):
        return self.scenePos() + QPointF(0, self.height/2)

    def update_triggers_info(self):
        """Fuerza el redibujo para mostrar los triggers actualizados."""
        self.prepareGeometryChange()
        self.update()

    def is_on_output_port(self, pos):
        """Verifica si un click local está sobre CUALQUIERA de los puertos de salida. Devuelve el índice o -1."""
        outgoing = [w for w in self.wires if w.source == self]
        num_out = max(1, len(outgoing))
        for i in range(num_out):
            p = self.get_local_output_pos(i, num_out)
            port_rect = QRectF(p.x() - 15, p.y() - 15, 30, 30)
            if port_rect.contains(pos):
                return i
        return -1

    def hoverMoveEvent(self, event):
        idx = self.is_on_output_port(event.pos())
        if idx != -1:
            self.setCursor(Qt.PointingHandCursor)
            if self.hovered_port_idx != idx:
                self.hovered_port_idx = idx
                self.update()
        else:
            self.setCursor(Qt.ArrowCursor)
            if self.hovered_port_idx != -1:
                self.hovered_port_idx = -1
                self.update()
        super().hoverMoveEvent(event)

    def hoverLeaveEvent(self, event):
        self.setCursor(Qt.ArrowCursor)
        self.hovered_port_idx = -1
        self.update()
        super().hoverLeaveEvent(event)

class NodeCanvas(QGraphicsView):
    """Lienzo para dibujar nodos y wires."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.scene = QGraphicsScene(self)
        self.scene.setSceneRect(-2000, -2000, 4000, 4000)
        self.setScene(self.scene)
        
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag) # Cambiamos NoDrag para que el click izquierdo mueva nodos
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.setFocusPolicy(Qt.StrongFocus)
        
        self.setBackgroundBrush(QBrush(QColor("#121212")))
        
        # State para dibujo de cables
        self.drawing_wire = None
        self.temp_line = None
        self.source_node = None
        
        # State para Paneado manual con click derecho
        self.last_mouse_pos = QPointF()
        
        # Estilo rejilla
        self.draw_grid()

    def draw_grid(self):
        # Dibujar una rejilla simple (opcional pero premium)
        pass

    def mousePressEvent(self, event):
        self.setFocus()
        scene_pos = self.mapToScene(event.pos())
        item = self.scene.itemAt(scene_pos, self.transform())
        
        if event.button() == Qt.LeftButton:
            if isinstance(item, StateNodeItem):
                local_pos = item.mapFromScene(scene_pos)
                if item.is_on_output_port(local_pos) != -1:
                    self.start_wire_drawing(item)
                    return 
            # Si no es puerto, permitir que QGraphicsView maneje la selección/arrastre
            super().mousePressEvent(event)
            
        elif event.button() == Qt.RightButton:
            # Panning con botón derecho
            self.setCursor(Qt.ClosedHandCursor)
            self.last_mouse_pos = event.pos()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.temp_line:
            self.temp_line.setLine(QLineF(self.temp_line.line().p1(), self.mapToScene(event.pos())))
            self.temp_line.setPen(QPen(QColor("#FFA726"), 2, Qt.DashLine))
            return

        if event.buttons() & Qt.RightButton:
            # Paneado manual
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.RightButton:
            self.setCursor(Qt.ArrowCursor)
            
        if self.temp_line:
            # Ocultar la línea temporal para que itemAt no la detecte a ella misma
            self.temp_line.hide()
            
            scene_pos = self.mapToScene(event.pos())
            target_item = self.scene.itemAt(scene_pos, self.transform())
            
            # Si soltamos sobre un nodo (que no sea el origen)
            if isinstance(target_item, StateNodeItem) and target_item != self.source_node:
                self.finish_wire_drawing(target_item)
            else:
                # Snapping amable
                items = self.scene.items(QRectF(scene_pos.x()-10, scene_pos.y()-10, 20, 20))
                found = False
                for item in items:
                    if isinstance(item, StateNodeItem) and item != self.source_node:
                        self.finish_wire_drawing(item)
                        found = True
                        break
                
                if not found:
                    self.scene.removeItem(self.temp_line)
                    self.temp_line = None
                    self.source_node = None
        
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            # QGraphicsView hereda de QWidget, aquí sí funciona .window()
            designer = self.window()
            if hasattr(designer, "delete_selected_items"):
                designer.delete_selected_items()
        else:
            super().keyPressEvent(event)

    def start_wire_drawing(self, node):
        self.source_node = node
        self.temp_line = self.scene.addLine(QLineF(node.get_output_pos(), node.get_output_pos()))
        self.temp_line.setPen(QPen(QColor("#4CAF50"), 2, Qt.DashLine))

    def finish_wire_drawing(self, target_node):
        # Crear la conexión real
        wire = TransitionWire(self.source_node, target_node)
        self.scene.addItem(wire)
        self.source_node.wires.append(wire)
        target_node.wires.append(wire)
        
        self.scene.removeItem(self.temp_line)
        self.temp_line = None
        self.source_node = None
        
        # Emitir señal o llamar al padre para actualizar data logic
        if hasattr(self.parent(), "on_wire_created"):
            self.parent().on_wire_created(wire)

    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 0.8
        if event.angleDelta().y() > 0:
            self.scale(zoom_in_factor, zoom_in_factor)
        else:
            self.scale(zoom_out_factor, zoom_out_factor)

# --- MAIN WINDOW ---

class FSMDesignerWindow(QMainWindow):
    def __init__(self, main_lab_ui=None):
        super().__init__()
        self.lab = main_lab_ui
        self.setWindowTitle("FSM Visual Designer | Moore Mode")
        self.resize(1200, 800)
        
        # Estilo Global
        self.setStyleSheet("""
            QMainWindow { background-color: #121212; color: #e0e0e0; }
            QGroupBox { border: 2px solid #333; border-radius: 8px; font-weight: bold; color: #4CAF50; }
            QPushButton { background-color: #1e1e1e; border: 1px solid #444; color: white; padding: 10px; border-radius: 5px; }
            QPushButton:hover { background-color: #333; border: 1px solid #4CAF50; }
            QComboBox { background-color: #222; border: 1px solid #444; color: white; padding: 5px; min-width: 150px; }
            QLabel#status { color: #ffa726; font-size: 14px; font-weight: bold; }
        """)

        self.poses_library = {}
        self.node_items = {} # {id: StateNodeItem}
        self.wire_items = []
        self.selected_pose = None
        
        self.init_ui()
        self.load_main_poses()

    def delete_selected_items(self):
        """Elimina físicamente y lógicamente los elementos seleccionados."""
        selected = self.canvas.scene.selectedItems()
        if not selected: return
        
        # Primero cables (para no dejar referencias muertas)
        for item in list(selected):
            if isinstance(item, TransitionWire):
                if item in self.wire_items: self.wire_items.remove(item)
                if item.source: 
                    if item in item.source.wires: item.source.wires.remove(item)
                    item.source.update_triggers_info()
                if item.target:
                    if item in item.target.wires: item.target.wires.remove(item)
                self.canvas.scene.removeItem(item)
                
        # Luego nodos
        for item in list(selected):
            if isinstance(item, StateNodeItem):
                # Eliminar todos sus cables conectados (aunque no estén seleccionados)
                for wire in list(item.wires):
                    if wire in self.wire_items: self.wire_items.remove(wire)
                    if wire.source and wire.source != item: 
                        if wire in wire.source.wires: wire.source.wires.remove(wire)
                        wire.source.update_triggers_info()
                    if wire.target and wire.target != item:
                        if wire in wire.target.wires: wire.target.wires.remove(wire)
                    self.canvas.scene.removeItem(wire)
                
                if item.state_id in self.node_items:
                    del self.node_items[item.state_id]
                self.canvas.scene.removeItem(item)
        
        self.canvas.scene.clearSelection()
        self.status_label.setText("ELEMENTOS ELIMINADOS")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        
        # 1. TOP BAR (Library / Manage)
        top_bar = QFrame()
        top_bar.setStyleSheet("background-color: #181818; border-bottom: 2px solid #333;")
        top_layout = QHBoxLayout(top_bar)
        
        top_layout.addWidget(QLabel("SECUENCIA:"))
        self.fsm_selector = QComboBox()
        self.fsm_selector.addItem("Seleccionar FSM...")
        self.fsm_selector.currentTextChanged.connect(self.on_fsm_selected_ui)
        top_layout.addWidget(self.fsm_selector)
        
        self.btn_save = QPushButton("💾 GUARDAR")
        self.btn_save.clicked.connect(self.save_to_lab)
        top_layout.addWidget(self.btn_save)
        
        self.btn_import = QPushButton("📥 IMPORTAR")
        self.btn_import.clicked.connect(self.import_from_gui)
        top_layout.addWidget(self.btn_import)
        
        top_layout.addStretch()
        
        self.status_label = QLabel("MODO: DISEÑO")
        self.status_label.setObjectName("status")
        top_layout.addWidget(self.status_label)
        
        main_layout.addWidget(top_bar)
        
        # 2. CENTRAL PANEL (Splitter: Canvas | Gallery)
        splitter = QSplitter(Qt.Horizontal)
        
        # Canvas
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        self.canvas = NodeCanvas(self)
        canvas_layout.addWidget(self.canvas)
        
        # Botones flotantes sobre el canvas (opcional)
        canvas_btns = QHBoxLayout()
        btn_add_node = QPushButton("+ NUEVO ESTADO")
        btn_add_node.clicked.connect(self.add_new_node)
        canvas_btns.addWidget(btn_add_node)
        canvas_btns.addStretch()
        canvas_layout.addLayout(canvas_btns)
        
        splitter.addWidget(canvas_container)
        
        # Right Gallery (Lite version)
        gallery_widget = QWidget()
        gallery_widget.setFixedWidth(280)
        gallery_layout = QVBoxLayout(gallery_widget)
        
        gallery_header = QHBoxLayout()
        gallery_header.addWidget(QLabel("POSES"))
        btn_create_pose = QPushButton("📸+")
        btn_create_pose.setToolTip("Capturar Pose Actual del Lab")
        btn_create_pose.setFixedWidth(40)
        btn_create_pose.clicked.connect(self.capture_new_pose)
        gallery_header.addWidget(btn_create_pose)
        gallery_layout.addLayout(gallery_header)
        
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.pose_grid_widget = QWidget()
        self.pose_grid = QGridLayout(self.pose_grid_widget)
        self.pose_grid.setSpacing(5)
        self.pose_grid.setContentsMargins(5, 5, 5, 5)
        scroll.setWidget(self.pose_grid_widget)
        gallery_layout.addWidget(scroll)
        
        splitter.addWidget(gallery_widget)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        
        main_layout.addWidget(splitter)
        
        # 3. BOTTOM MEDIA PLAYER CONTROLS
        bottom_bar = QFrame()
        bottom_bar.setFixedHeight(80)
        bottom_bar.setStyleSheet("background-color: #1e1e1e; border-top: 2px solid #333;")
        bottom_layout = QHBoxLayout(bottom_bar)
        
        self.btn_reset = QPushButton("⏪")
        self.btn_reset.setFont(QFont("Arial", 16))
        self.btn_reset.clicked.connect(self.reset_fsm)
        
        self.btn_play = QPushButton("▶")
        self.btn_play.setFont(QFont("Arial", 20))
        self.btn_play.setFixedSize(60, 60)
        self.btn_play.setStyleSheet("background-color: #2e7d32; border-radius: 30px;")
        self.btn_play.clicked.connect(self.toggle_play)
        
        self.btn_step = QPushButton("⏭")
        self.btn_step.setFont(QFont("Arial", 16))
        self.btn_step.clicked.connect(self.step_fsm)
        
        bottom_layout.addStretch()
        bottom_layout.addWidget(self.btn_reset)
        bottom_layout.addWidget(self.btn_play)
        bottom_layout.addWidget(self.btn_step)
        bottom_layout.addStretch()
        
        main_layout.addWidget(bottom_bar)

    def load_main_poses(self):
        poses_path = os.path.join(base_dir, "poses.json")
        if os.path.exists(poses_path):
            with open(poses_path, "r") as f:
                self.poses_library = json.load(f)
            self.refresh_gallery()
            self.refresh_ui_selectors()

    def refresh_gallery(self):
        # Limpiar grid
        while self.pose_grid.count():
            item = self.pose_grid.takeAt(0)
            if item.widget():
                item.widget().setParent(None)
            
        pose_icons_dir = os.path.join(base_dir, "pose_thumbnails")
        col = 0
        row = 0
        for name in sorted(self.poses_library.keys()):
            thumb = os.path.join(pose_icons_dir, f"{name}.png")
            
            # Contenedor de pose
            container = QFrame()
            container.setObjectName("PoseContainer")
            selected_style = "border: 2px solid #4CAF50;" if self.selected_pose == name else "border: 1px solid #333;"
            container.setStyleSheet(f"QFrame#PoseContainer {{ {selected_style} border-radius: 5px; background: #222; }}")
            
            c_layout = QVBoxLayout(container)
            c_layout.setContentsMargins(2, 2, 2, 2)
            c_layout.setSpacing(2)
            
            pw = PoseWidget(name, thumb, show_delete=False)
            pw.setFixedSize(110, 80)
            # Hacer que el click en el widget seleccione la pose
            pw.mousePressEvent = lambda e, n=name: self.select_pose(n)
            c_layout.addWidget(pw)
            
            lbl_name = QLabel(name)
            lbl_name.setAlignment(Qt.AlignCenter)
            lbl_name.setStyleSheet("font-size: 9px; color: #888;")
            c_layout.addWidget(lbl_name)
            
            self.pose_grid.addWidget(container, row, col)
            
            col += 1
            if col > 1:
                col = 0
                row += 1
        
        # Spacer al final para empujar todo abajo
        spacer = QWidget()
        spacer.setFixedHeight(1)
        self.pose_grid.addWidget(spacer, row + 1, 0, 1, 2)

    def select_pose(self, name):
        self.selected_pose = name
        self.refresh_gallery()
        # Si hay nodos seleccionados, aplicarles la pose automáticamente? 
        # El usuario pidió que al dar "crear nuevo nodo" use la seleccionada.
        self.apply_pose_to_selection(name)

    def capture_new_pose(self):
        """Captura la pose actual del robot en el laboratorio."""
        if not self.lab: return
        self.lab.save_current_pose()
        # Recargar librería y refrescar
        self.load_main_poses()

    def apply_pose_to_selection(self, pose_name):
        items = self.canvas.scene.selectedItems()
        for item in items:
            if isinstance(item, StateNodeItem):
                item.pose_name = pose_name
                item.angles = self.poses_library[pose_name]
                # Actualizar thumbnail
                thumb_path = os.path.join(base_dir, "pose_thumbnails", f"{pose_name}.png")
                if os.path.exists(thumb_path):
                    item.pixmap = QPixmap(thumb_path).scaled(110, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                item.update()

    def add_new_node(self):
        state_id = str(len(self.node_items))
        
        # Usar la pose seleccionada si existe, si no la primera de la lista
        pose_name = self.selected_pose
        if not pose_name or pose_name not in self.poses_library:
            pose_name = list(self.poses_library.keys())[0] if self.poses_library else "None"
            
        angles = self.poses_library.get(pose_name, [0]*5)
        thumb = os.path.join(base_dir, "pose_thumbnails", f"{pose_name}.png")
        
        node = StateNodeItem(state_id, pose_name, angles, thumb)
        node.setPos(self.canvas.mapToScene(self.canvas.viewport().rect().center()))
        self.canvas.scene.addItem(node)
        self.node_items[state_id] = node

    def on_wire_created(self, wire):
        """Callback cuando se tira un cable gráfico."""
        self.wire_items.append(wire)
        # Diálogo para configurar trigger
        self.edit_wire_trigger(wire)

    def edit_wire_trigger(self, wire):
        special_keys = []
        if self.lab and hasattr(self.lab, "input_mgr") and self.lab.input_mgr:
            current_binds = self.lab.input_mgr.get_current_binds().get("inputs", {})
            for act_id in current_binds:
                if act_id.startswith("special_key_"):
                    special_keys.append(act_id)
        
        dlg = TriggerConfigDialog(wire.type, wire.params, special_keys, self)
        if dlg.exec():
            t_type, params = dlg.get_values()
            
            # Validar que si eligió Key pero no hay teclas, se cambie a Time
            if t_type == "key" and (not special_keys or "No hay teclas" in params):
                t_type = "time"
                params = 1.0
                
            wire.type = t_type
            wire.params = params
            wire.update_path()

    def on_fsm_selected_ui(self, name):
        if not self.lab or name not in self.lab.all_fsm_data: return
        self.load_graph_from_data(self.lab.all_fsm_data[name])

    def _auto_layout_nodes(self, data):
        """Distribuye nodos automáticamente cuando no tienen posición guardada.
        Usa BFS desde el entry_state para ordenar en cadena horizontal."""
        if not self.node_items:
            return
        
        entry = data.get("entry_state")
        states_data = data.get("states", {})
        
        # --- BFS para determinar orden de visita ---
        ordered = []
        visited = set()
        
        # Comenzar desde el entry_state
        if entry and entry in self.node_items:
            queue = [entry]
        else:
            queue = [list(self.node_items.keys())[0]]
        
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            ordered.append(current)
            
            # Seguir las transiciones
            for trans in states_data.get(current, {}).get("transitions", []):
                nxt = trans.get("next")
                if nxt and nxt not in visited and nxt in self.node_items:
                    queue.append(nxt)
        
        # Agregar nodos huérfanos (sin conexión) que no fueron alcanzados
        for name in self.node_items:
            if name not in visited:
                ordered.append(name)
        
        # --- Posicionar en cadena horizontal ---
        spacing_x = 200  # Espacio horizontal entre nodos
        spacing_y = 0
        start_x = 50
        start_y = 100
        
        for i, name in enumerate(ordered):
            node = self.node_items[name]
            node.setPos(start_x + i * spacing_x, start_y + i * spacing_y)
    
    def _fit_view_to_nodes(self):
        """Ajusta el zoom y posición del canvas para mostrar todos los nodos."""
        if not self.node_items:
            return
        
        # Calcular el bounding rect de todos los nodos con padding
        all_rects = []
        for node in self.node_items.values():
            r = node.sceneBoundingRect()
            all_rects.append(r)
        
        if not all_rects:
            return
        
        united = all_rects[0]
        for r in all_rects[1:]:
            united = united.united(r)
        
        # Agregar padding
        padding = 80
        united.adjust(-padding, -padding, padding, padding)
        
        self.canvas.fitInView(united, Qt.KeepAspectRatio)

    def load_graph_from_data(self, data):
        self.canvas.scene.clear()
        self.node_items = {}
        self.wire_items = []
        
        # Re-crear nodos
        needs_layout = True  # Asumir que necesita layout
        for name, info in data.get("states", {}).items():
            pose_name = info.get("pose", "1")
            thumb = os.path.join(base_dir, "pose_thumbnails", f"{pose_name}.png")
            node = StateNodeItem(name, pose_name, info.get("angles", [0]*5), thumb)
            
            # Posición guardada o (0, 0) si no existe
            pos = info.get("pos", None)
            if pos is not None and (pos[0] != 0 or pos[1] != 0):
                needs_layout = False  # Al menos un nodo tiene posición real
                node.setPos(pos[0], pos[1])
            else:
                node.setPos(0, 0)  # Temporal, se recalculará si needs_layout
            
            self.canvas.scene.addItem(node)
            self.node_items[name] = node
        
        # Auto-layout si ningún nodo tenía posición guardada
        if needs_layout and len(self.node_items) > 1:
            self._auto_layout_nodes(data)
            
        # Re-crear cables
        for name, info in data.get("states", {}).items():
            source = self.node_items.get(name)
            for trans in info.get("transitions", []):
                target = self.node_items.get(trans["next"])
                if source and target:
                    wire = TransitionWire(source, target)
                    wire.type = trans["type"]
                    wire.params = trans["params"]
                    self.canvas.scene.addItem(wire)
                    self.wire_items.append(wire)
                    source.wires.append(wire)
                    target.wires.append(wire)
                    wire.update_path()
        
        # Ajustar vista para mostrar todo el grafo
        QTimer.singleShot(100, self._fit_view_to_nodes)

    def save_to_lab(self):
        if not self.lab: return
        
        # Compilar data desde el grafo
        states = {}
        for nid, node in self.node_items.items():
            transitions = []
            for wire in node.wires:
                if wire.source == node:
                    transitions.append({
                        "type": wire.type,
                        "params": wire.params,
                        "next": wire.target.state_id
                    })
            
            states[nid] = {
                "pose": node.pose_name,
                "angles": node.angles,
                "transition_time": 1.0, # Default interp
                "transitions": transitions,
                "pos": [node.scenePos().x(), node.scenePos().y()]
            }
        
        name, ok = QInputDialog.getText(self, "Guardar", "Nombre de la secuencia:", QLineEdit.Normal, self.fsm_selector.currentText())
        if ok and name:
            self.lab.all_fsm_data[name] = {
                "entry_state": list(states.keys())[0] if states else None,
                "states": states
            }
            self.lab.save_fsm_library()
            self.refresh_ui_selectors()

    def refresh_ui_selectors(self):
        if self.lab:
            self.fsm_selector.clear()
            self.fsm_selector.addItem("Seleccionar FSM...")
            self.fsm_selector.addItems(list(self.lab.all_fsm_data.keys()))

    def update_status_from_main(self):
        if self.lab and self.lab.fsm.active:
            sid = self.lab.fsm.current_state_name
            for nid, item in self.node_items.items():
                item.active_highlight = (nid == sid)
                item.update()
            
            self.status_label.setText(f"ESTADO ACTUAL: {sid}")
            self.status_label.setStyleSheet("color: #4CAF50;")
        else:
            self.status_label.setText("MODO: DISEÑO")
            self.status_label.setStyleSheet("color: #ffa726;")

    def reset_fsm(self):
        if self.lab: self.lab.fsm.reset(); self.update_status_from_main()

    def toggle_play(self):
        if not self.lab: return
        if not self.lab.fsm.active:
            # Primero guardamos/compilamos temporalmente?
            # Por ahora enviamos el dict actual
            self.lab.fsm.load_from_dict({
                "entry_state": list(self.node_items.keys())[0] if self.node_items else None,
                "states": {nid: {"pose": n.pose_name, "angles": n.angles, "transition_time": 1.0, 
                                "transitions": [{"type": w.type, "params": w.params, "next": w.target.state_id} for w in n.wires if w.source == n]} 
                           for nid, n in self.node_items.items()}
            })
            self.lab.fsm.start()
            self.btn_play.setText("⏸")
            self.btn_play.setStyleSheet("background-color: #f57c00; border-radius: 30px;")
        else:
            self.lab.fsm.toggle_pause()
            if self.lab.fsm.is_paused:
                self.btn_play.setText("▶")
                self.btn_play.setStyleSheet("background-color: #2e7d32; border-radius: 30px;")
            else:
                self.btn_play.setText("⏸")
                self.btn_play.setStyleSheet("background-color: #f57c00; border-radius: 30px;")

    def step_fsm(self):
        if self.lab: self.lab.fsm.force_next()

    def import_from_gui(self):
        if self.lab: self.lab.import_from_main_gui(); self.refresh_ui_selectors()

import json
from .constants import GUI_ADDR

class NetworkMixin:
    """Mixin for network communication (UDP)."""
    
    def sync_to_gui(self):
        """Enviar ángulos actuales a la GUI para sincronizar sliders."""
        angles = [round(self._get_angle(i), 1) for i in range(self.NUM_JOINTS)]
        msg = json.dumps({"type": "sync_angles", "data": angles})
        try:
            self.feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except:
            pass

    def _send_cnc_status(self, status, error_msg=None, progress=0):
        """Envía el estado actual del CNC a la GUI del Lab."""
        msg = json.dumps({
            "type": "cnc_status",
            "status": status,  # loaded, running, completed, stopped, error
            "progress": progress,
            "error": error_msg
        })
        try:
            self.feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except Exception:
            pass

    def _send_collision_status(self):
        """Send current collision state to the GUI."""
        colliding = self.collision_mgr.is_colliding()
        probes = self.collision_mgr.get_colliding_probes() if colliding else []
        msg = json.dumps({
            "type": "collision_status",
            "colliding": colliding,
            "joints": probes
        })
        try:
            self.feedback_sock.sendto(msg.encode(), GUI_ADDR)
        except Exception:
            pass

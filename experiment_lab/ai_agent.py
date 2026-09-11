import json
import time
import random
import requests
import base64
import os

class AIAgent:
    """
    Agente de IA para el Laboratorio.
    Maneja la lógica de LLM (Ollama) y detección de objetos.
    """
    def __init__(self, console_output=None):
        self.console = console_output
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = "llava" # Por defecto para visión
        self.is_active = False

    def log(self, message):
        if self.console:
            self.console.append(f"[AI] {message}")
        else:
            print(f"[AI] {message}")

    def query_with_image(self, prompt, image_path, state_data=None):
        """
        Consulta al LLM enviando una imagen y datos de estado.
        """
        self.log(f"Analizando estado con prompt: '{prompt}'")
        
        try:
            # Codificar imagen en base64
            with open(image_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')

            # Preparar contexto extendido con datos de juntas
            extended_prompt = prompt
            if state_data:
                extended_prompt += f"\n\nContexto técnico actual:\n{json.dumps(state_data, indent=2)}"

            payload = {
                "model": self.model,
                "prompt": extended_prompt,
                "stream": False,
                "images": [encoded_string]
            }

            response = requests.post(self.ollama_url, json=payload, timeout=30)
            if response.status_code == 200:
                answer = response.json().get("response", "No hubo respuesta.")
                self.log(f"IA: {answer}")
                return answer
            else:
                raise Exception(f"Ollama error {response.status_code}: {response.text}")

        except Exception as e:
            self.log(f"Error en consulta IA: {e}")
            self.log("Usando respuesta de respaldo (Mock)...")
            return self.query_llm(prompt)

    def query_llm(self, prompt):
        """Mock de integración si falla el servicio real"""
        time.sleep(1)
        responses = [
            "Moviendo brazo a posición de descanso.",
            "Detectando objetos en el espacio de trabajo...",
            "Comando aceptado: Realizando secuencia circular.",
            "IA: No puedo realizar esa acción por seguridad."
        ]
        response = random.choice(responses)
        self.log(f"Respuesta (Mock): {response}")
        return response

    def detect_objects(self):
        """Mock de visión artificial"""
        objects = [
            {"id": "cube_1", "pos": [1.5, 0.5, 0], "color": "red"},
            {"id": "sphere_A", "pos": [0, 0.5, 2], "color": "blue"}
        ]
        return objects

    def get_action_angles(self, current_angles):
        """Retorna ángulos sugeridos por la IA"""
        if not self.is_active:
            return None
        return [a + random.uniform(-0.1, 0.1) for a in current_angles]


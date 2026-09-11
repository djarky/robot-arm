/*
 * serial_controller.ino
 * 
 * Ejemplo de controlador para el INEXP-ursina Robot Arm.
 * Envía señales de ejes (Potenciómetros) y botones al Experiment Lab.
 * 
 * Formato de salida:
 * A<id>:<val>  (Eje: val entre 0.00 y 1.00)
 * B<id>:<val>  (Botón: 0 o 1)
 */

// --- CONFIGURACIÓN DE PINES ---
const int ANALOG_PINS[] = {A0, A1, A2, A3, A4}; // 5 Articulaciones
const int NUM_AXES = 5;

const int BUTTON_PINS[] = {2, 3, 4}; // Snapshot, Console, Reset
const int NUM_BUTTONS = 3;

// --- VARIABLES DE ESTADO ---
int lastAxisValues[NUM_AXES];
bool lastButtonStates[NUM_BUTTONS];
const int ANALOG_THRESHOLD = 8; // Umbral para evitar ruido (jitter)

void setup() {
  Serial.begin(115200);
  
  // Configurar botones con Pullup interno
  for (int i = 0; i < NUM_BUTTONS; i++) {
    pinMode(BUTTON_PINS[i], INPUT_PULLUP);
    lastButtonStates[i] = digitalRead(BUTTON_PINS[i]);
  }
  
  // Inicializar ejes
  for (int i = 0; i < NUM_AXES; i++) {
    lastAxisValues[i] = analogRead(ANALOG_PINS[i]);
  }

  Serial.println("DEBUG: Controlador Serial Inicializado");
}

void loop() {
  // 1. Procesar Ejes (Potenciómetros)
  for (int i = 0; i < NUM_AXES; i++) {
    int currentVal = analogRead(ANALOG_PINS[i]);
    
    // Solo enviar si el cambio supera el umbral de ruido
    if (abs(currentVal - lastAxisValues[i]) > ANALOG_THRESHOLD) {
      lastAxisValues[i] = currentVal;
      
      // Normalizar a 0.0 - 1.0
      float normalized = (float)currentVal / 1023.0;
      
      Serial.print("A");
      Serial.print(i);
      Serial.print(":");
      Serial.println(normalized, 3); // 3 decimales de precisión
    }
  }

  // 2. Procesar Botones
  for (int i = 0; i < NUM_BUTTONS; i++) {
    bool currentState = digitalRead(BUTTON_PINS[i]);
    
    // Invertimos porque usamos INPUT_PULLUP (Presionado = LOW)
    bool pressed = (currentState == LOW);
    bool lastPressed = (lastButtonStates[i] == LOW);
    
    if (pressed != lastPressed) {
      lastButtonStates[i] = currentState;
      
      Serial.print("B");
      Serial.print(i);
      Serial.print(":");
      Serial.println(pressed ? "1" : "0");
      
      delay(20); // Debounce simple
    }
  }

  delay(10); // Estabilidad del loop
}

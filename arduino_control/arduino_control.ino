/*
  Control de Brazo Robótico vía Serial (6 Ejes + Gripper)
  Protocolo esperado: "ANG0,ANG1,ANG2,ANG3,ANG4,ANG5,GRIPPER\n"
  Ejemplo: "90,90,90,90,90,90,0\n"
*/

#include <Servo.h>

// ------------------------------------------------------------------------
// CONFIGURACIÓN DEL USUARIO
// ------------------------------------------------------------------------
// Cambiar a 1 para usar un motor NEMA (Paso a Paso) en el primer eje.
// Cambiar a 0 para usar un Servomotor SG995 en su lugar.
#define USE_NEMA_MOTOR_1 0

// Pines NEMA (Si USE_NEMA_MOTOR_1 es 1)
#define PIN_DIR  2
#define PIN_STEP 3

// Pines Servos SG995 (Todos los demás ejes son Servos)
#define PIN_SERVO_1 9   // Usado sólo si USE_NEMA_MOTOR_1 es 0
#define PIN_SERVO_2 10
#define PIN_SERVO_3 11
#define PIN_SERVO_4 5
#define PIN_SERVO_5 6
#define PIN_SERVO_6 7
#define PIN_GRIPPER 8
// ------------------------------------------------------------------------

#if !USE_NEMA_MOTOR_1
  Servo axis1;
#else
  int currentNemaAngle = 90; // Angulo actual de reposo para el NEMA
#endif

Servo axis2;
Servo axis3;
Servo axis4;
Servo axis5;
Servo axis6;
Servo gripper;

void moveToNemaAngle(int targetAngle);
void setAllServos(int pos);

void setup() {
  Serial.begin(115200);
  
  // -- Inicialización de pines --

  #if USE_NEMA_MOTOR_1
    pinMode(PIN_DIR, OUTPUT);
    pinMode(PIN_STEP, OUTPUT);
  #else
    axis1.attach(PIN_SERVO_1);
    axis1.write(90);
  #endif
  
  axis2.attach(PIN_SERVO_2);
  axis3.attach(PIN_SERVO_3);
  axis4.attach(PIN_SERVO_4);
  axis5.attach(PIN_SERVO_5);
  axis6.attach(PIN_SERVO_6);
  gripper.attach(PIN_GRIPPER);

  axis2.write(90);
  axis3.write(90);
  axis4.write(90);
  axis5.write(90);
  axis6.write(90);
  gripper.write(0);

  delay(500); // Tiempo para anclaje de posición inicial

  // -- Escaneo lento antes del reposo final --
  // Movimiento de barrido suave (90 -> 120 -> 60 -> 90) para no entrar de golpe
  for(int pos = 90; pos <= 120; pos++) {
    setAllServos(pos);
    delay(15);
  }
  for(int pos = 120; pos >= 60; pos--) {
    setAllServos(pos);
    delay(15);
  }
  for(int pos = 60; pos <= 90; pos++) {
    setAllServos(pos);
    delay(15);
  }
}

void loop() {
  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    data.trim(); // Remover espacios o saltos de línea basura
    
    // Verificación de conexión (Handshake)
    if (data == "?") {
      Serial.println("ID:ARM_ROBOT");
      return;
    }
    
    if (data.length() > 0) {
      parseAndControl(data);
    }
  }
}

// Función para mover el motor NEMA a un ángulo específico
void moveToNemaAngle(int targetAngle) {
#if USE_NEMA_MOTOR_1
  if(targetAngle == currentNemaAngle) return;
  
  // Suponiendo placa A4988 con 1/16 microstepping: 3200 pasos por vuelta entera (360 grados)
  // Para 180 grados = 1600 pasos. -> 1600 / 180 grados.
  float stepsPerDegree = 1600.0 / 180.0; 
  
  // Calcular la posición absoluta en pasos desde el origen (0 grados)
  int currentSteps = round(currentNemaAngle * stepsPerDegree);
  int targetSteps = round(targetAngle * stepsPerDegree);
  
  int stepDifference = abs(targetSteps - currentSteps);
  
  // Definir dirección
  digitalWrite(PIN_DIR, (targetSteps > currentSteps) ? HIGH : LOW);
  
  // Enviar pulsos
  for(int i = 0; i < stepDifference; i++) {
    digitalWrite(PIN_STEP, HIGH);
    delayMicroseconds(800); 
    digitalWrite(PIN_STEP, LOW);
    delayMicroseconds(800);
  }
  
  // Actualizar estado actual
  currentNemaAngle = targetAngle;
#endif
}

// Función auxiliar para mover todos los ejes en sincronía para el escaneo
void setAllServos(int pos) {
  #if USE_NEMA_MOTOR_1
    moveToNemaAngle(pos);
  #else
    axis1.write(pos);
  #endif
  
  axis2.write(pos);
  axis3.write(pos);
  axis4.write(pos);
  axis5.write(pos);
  axis6.write(pos);
}

void parseAndControl(String data) {
  int values[10]; // Mínimo 7 parámetros para 6 ejes + gripper
  int count = 0;
  
  int lastIdx = 0;
  for (int i = 0; i < data.length(); i++) {
    if (data[i] == ',' || i == data.length() - 1) {
      String valStr = (i == data.length() - 1) ? data.substring(lastIdx) : data.substring(lastIdx, i);
      values[count++] = valStr.toInt();
      lastIdx = i + 1;
      if (count >= 10) break;
    }
  }
  
  // Esperamos al menos 6 ejes, el 7mo (gripper) es opcional en la cadena lógica
  if (count >= 6) {
    int j0 = constrain(values[0], 0, 180);
    int j1 = constrain(values[1], 0, 180);
    int j2 = constrain(values[2], 0, 180);
    int j3 = constrain(values[3], 0, 180);
    int j4 = constrain(values[4], 0, 180);
    int j5 = constrain(values[5], 0, 180);

    #if USE_NEMA_MOTOR_1
      moveToNemaAngle(j0);
    #else
      axis1.write(j0);
    #endif

    axis2.write(j1);
    axis3.write(j2);
    axis4.write(j3);
    axis5.write(j4);
    axis6.write(j5);
    
    if (count >= 7) {
      gripper.write(values[6] == 1 ? 90 : 0); // 1 = Cerrado, 0 = Abierto
    }
    
    Serial.println("ACK"); // Confirmación de procesamiento
  } else {
    Serial.println("ERROR:INVALID_PACKET");
  }
}

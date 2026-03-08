/*
  Control de Brazo Robótico vía Serial
  Protocolo esperado: "ANG1,ANG2,ANG3,GRIPPER\n"
  Ejemplo: "90,45,180,1\n"
*/

#include <Servo.h>

Servo servo1;
Servo servo2;
Servo servo3;
Servo gripper;

void setup() {
  Serial.begin(115200);
  
  servo1.attach(9);
  servo2.attach(10);
  servo3.attach(11);
  gripper.attach(6);
  
  // Posición inicial
  servo1.write(90);
  servo2.write(90);
  servo3.write(90);
  gripper.write(0);
}

void loop() {
  if (Serial.available() > 0) {
    String data = Serial.readStringUntil('\n');
    parseAndControl(data);
  }
}

void parseAndControl(String data) {
  int values[4];
  int count = 0;
  
  int lastIdx = 0;
  for (int i = 0; i < data.length(); i++) {
    if (data[i] == ',' || i == data.length() - 1) {
      String valStr = (i == data.length() - 1) ? data.substring(lastIdx) : data.substring(lastIdx, i);
      values[count++] = valStr.toInt();
      lastIdx = i + 1;
      if (count >= 4) break;
    }
  }
  
  if (count == 4) {
    servo1.write(constrain(values[0], 0, 180));
    servo2.write(constrain(values[1], 0, 180));
    servo3.write(constrain(values[2], 0, 180));
    gripper.write(values[3] == 1 ? 90 : 0); // 1 = Cerrado, 0 = Abierto
  }
}

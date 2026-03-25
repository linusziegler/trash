// Define the pins connected to IN1 and IN2
const int motorPin1 = 18; 
const int motorPin2 = 19; 

// Motor timing
unsigned long rotationStartTime = 0;
const unsigned long ROTATION_DURATION = 500;
bool isRotating = false;

void setup() {
  Serial.begin(115200);
  
  // Initialize pins as outputs
  pinMode(motorPin1, OUTPUT);
  pinMode(motorPin2, OUTPUT);
  
  // Start with motor stopped
  stopMotor();
  Serial.println("Motor: Ready - waiting for commands");
}

void loop() {
  // Check for serial commands
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    
    if (command == "increment") {
      Serial.println("Motor: Increment received - rotating for 1 second");
      startRotation();
    }
  }
  
  // Check if rotation timer has elapsed
  if (isRotating && (millis() - rotationStartTime >= ROTATION_DURATION)) {
    stopMotor();
    Serial.println("Motor: Rotation complete - stopped");
    isRotating = false;
  }
}

void startRotation() {
  // Rotate forward
  digitalWrite(motorPin1, HIGH);  // Power
  digitalWrite(motorPin2, LOW);   // Ground
  
  rotationStartTime = millis();
  isRotating = true;
}

void stopMotor() {
  // Stop: both pins LOW
  digitalWrite(motorPin1, LOW);
  digitalWrite(motorPin2, LOW);
}
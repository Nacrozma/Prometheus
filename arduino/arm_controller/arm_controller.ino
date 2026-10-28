// arm_controller.ino - firmware for the Prometheus hobby arm.
//
// *** NOT COMPILED OR RUN ON A BOARD BY ITS AUTHOR. Bring-up checklist is in the README. ***
// It implements the protocol in arm_bridge.py (tests/test_arm_bridge.py checks that the constants below
// match the Python model). Servos need their OWN 5-6 V supply with a common ground; never power them
// from the Arduino's 5V pin. Keep a physical switch on that supply: ESTOP and the watchdog stop motion
// but leave the servos powered.

#include <Servo.h>

const uint8_t SOF = 0xA5;
const uint8_t MAX_PAYLOAD = 16;
const uint8_t CMD_SET_ANGLES = 0x01;
const uint8_t CMD_HEARTBEAT = 0x02;
const uint8_t CMD_ESTOP = 0x03;
const uint8_t CMD_CLEAR_ESTOP = 0x04;
const uint8_t CMD_GET_STATUS = 0x05;
const uint8_t RSP_STATUS = 0x85;
const uint8_t CRC_POLY = 0x07;
const uint8_t NUM_JOINTS = 5;
const unsigned long WATCHDOG_MS = 500;
const float MAX_SLEW_DPS = 90.0;

const uint8_t PINS[NUM_JOINTS] = {3, 5, 6, 9, 10};              // yaw, shoulder, elbow, wrist, gripper (PWM-capable pins)
const int LIMIT_MIN[NUM_JOINTS] = {0, 0, 0, 0, 10};
const int LIMIT_MAX[NUM_JOINTS] = {180, 180, 180, 180, 100};
const float REST_DEG[NUM_JOINTS] = {90, 90, 90, 90, 40};        // set to the pose your arm really rests in

enum State : uint8_t { STATE_OK = 0, STATE_LINK_LOST = 1, STATE_ESTOP = 2 };

Servo servos[NUM_JOINTS];
float current[NUM_JOINTS];
float target[NUM_JOINTS];
State state = STATE_LINK_LOST;
unsigned long lastValidMs = 0;
unsigned long lastTickMs = 0;

uint8_t buf[MAX_PAYLOAD + 4];
uint8_t n = 0;

uint8_t crc8(const uint8_t *data, uint8_t len) {
  uint8_t crc = 0;
  for (uint8_t i = 0; i < len; i++) {
    crc ^= data[i];
    for (uint8_t b = 0; b < 8; b++) {
      crc = (crc & 0x80) ? (uint8_t)((crc << 1) ^ CRC_POLY) : (uint8_t)(crc << 1);
    }
  }
  return crc;
}

void writeServo(uint8_t i, float deg) {
  servos[i].writeMicroseconds(500 + (int)(deg * 2000.0 / 180.0 + 0.5));
}

void sendStatus() {
  uint8_t payload[1 + NUM_JOINTS * 2];
  payload[0] = state;
  for (uint8_t i = 0; i < NUM_JOINTS; i++) {
    uint16_t tenths = (uint16_t)(current[i] * 10.0 + 0.5);
    payload[1 + i * 2] = tenths & 0xFF;
    payload[2 + i * 2] = tenths >> 8;
  }
  uint8_t body[2 + sizeof(payload)];
  body[0] = sizeof(payload);
  body[1] = RSP_STATUS;
  memcpy(body + 2, payload, sizeof(payload));
  Serial.write(SOF);
  Serial.write(body, sizeof(body));
  Serial.write(crc8(body, sizeof(body)));
}

void holdHere() {
  for (uint8_t i = 0; i < NUM_JOINTS; i++) target[i] = current[i];
}

void handleFrame(uint8_t cmd, const uint8_t *payload, uint8_t len) {
  lastValidMs = millis();
  if (state == STATE_LINK_LOST) state = STATE_OK;
  switch (cmd) {
    case CMD_SET_ANGLES:
      if (len == NUM_JOINTS * 2 && state != STATE_ESTOP) {
        for (uint8_t i = 0; i < NUM_JOINTS; i++) {
          float deg = (payload[i * 2] | (payload[i * 2 + 1] << 8)) / 10.0;
          if (deg < LIMIT_MIN[i]) deg = LIMIT_MIN[i];     // the firmware does not trust the host
          if (deg > LIMIT_MAX[i]) deg = LIMIT_MAX[i];
          target[i] = deg;
        }
      }
      break;
    case CMD_ESTOP:
      state = STATE_ESTOP;
      holdHere();
      break;
    case CMD_CLEAR_ESTOP:
      if (state == STATE_ESTOP) {
        state = STATE_OK;
        holdHere();
      }
      break;
    case CMD_GET_STATUS:
      sendStatus();
      break;
    default:
      break;                                              // HEARTBEAT and unknown commands only refresh the watchdog
  }
}

void shift(uint8_t k) {
  if (k >= n) { n = 0; return; }
  memmove(buf, buf + k, n - k);
  n -= k;
}

void parse() {
  while (true) {
    uint8_t i = 0;
    while (i < n && buf[i] != SOF) i++;
    if (i > 0) shift(i);
    if (n < 2) return;
    uint8_t len = buf[1];
    if (len > MAX_PAYLOAD) { shift(1); continue; }
    if (n < len + 4) return;
    if (crc8(buf + 1, len + 2) == buf[len + 3]) {
      handleFrame(buf[2], buf + 3, len);
      shift(len + 4);
    } else {
      shift(1);                                           // bad checksum: resynchronise on the next start byte
    }
  }
}

void setup() {
  Serial.begin(115200);
  for (uint8_t i = 0; i < NUM_JOINTS; i++) {
    current[i] = target[i] = REST_DEG[i];
    servos[i].attach(PINS[i]);
    writeServo(i, current[i]);                            // NOTE: a servo jumps to this angle at full speed on power-up
  }
  lastValidMs = lastTickMs = millis();
}

void loop() {
  while (Serial.available() > 0) {
    if (n >= sizeof(buf)) n = 0;                          // cannot happen (parse() drains); belt and braces
    buf[n++] = (uint8_t)Serial.read();
    parse();
  }
  unsigned long now = millis();
  if (state == STATE_OK && now - lastValidMs > WATCHDOG_MS) {
    state = STATE_LINK_LOST;
    holdHere();
  }
  if (now - lastTickMs >= 10) {
    float step = MAX_SLEW_DPS * (now - lastTickMs) / 1000.0;
    lastTickMs = now;
    for (uint8_t i = 0; i < NUM_JOINTS; i++) {
      float delta = target[i] - current[i];
      if (delta > step) delta = step;
      if (delta < -step) delta = -step;
      current[i] += delta;
      writeServo(i, current[i]);
    }
  }
}

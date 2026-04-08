#include <Wire.h>
#include <Adafruit_MCP4725.h>

Adafruit_MCP4725 dac;

static uint8_t mcpAddress = 0;

bool i2cDevicePresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

uint8_t detectMcp4725Address() {
  const uint8_t candidates[] = {0x60, 0x61, 0x62, 0x63};
  for (uint8_t i = 0; i < sizeof(candidates); i++) {
    if (i2cDevicePresent(candidates[i])) {
      return candidates[i];
    }
  }
  return 0;
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 4000) {
    delay(10);
  }

  Serial.println("=== MCP4725 Wiring Check ===");

  Wire.begin();
  Wire.setClock(400000);

  mcpAddress = detectMcp4725Address();

  Serial.print("MCP4725 scan (0x60-0x63): ");
  if (mcpAddress == 0) {
    Serial.println("NOT FOUND");
    Serial.println("Check VCC=3.3V, GND, SDA=pin 18, SCL=pin 19, and address jumper/pads.");
    while (1) {
      delay(1000);
    }
  }

  Serial.print("FOUND at 0x");
  Serial.println(mcpAddress, HEX);

  if (!dac.begin(mcpAddress)) {
    Serial.println("FATAL: MCP4725 library init failed.");
    while (1) {
      delay(1000);
    }
  }

  dac.setVoltage(2048, false);
  Serial.println("Wrote mid-scale value 2048 to DAC output.");
  Serial.println("Measure OUT with a multimeter if you want to confirm the voltage.");
  Serial.println("If the board is wired correctly, this should stay stable and the scan should succeed.");
}

void loop() {
  static bool toggle = false;
  static unsigned long lastFlipMs = 0;

  if (millis() - lastFlipMs >= 2000) {
    lastFlipMs = millis();
    toggle = !toggle;

    uint16_t value = toggle ? 3500 : 500;
    dac.setVoltage(value, false);

    Serial.print("DAC update: ");
    Serial.print(value);
    Serial.print("  -> OUT should shift accordingly on the module");
    Serial.println();
  }
}
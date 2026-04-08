#include <Wire.h>
#include <Adafruit_MCP4725.h>
#include <Adafruit_ADS1X15.h>

/*
 * Teensy 4.1 resistor-substitution test firmware
 *
 * Purpose:
 * - Validate MCP4725 output path, ADS1115 input path, and Rp computation
 *   without real electrodes by placing known resistors in the cell path.
 *
 * Serial commands:
 * - help
 * - once
 * - auto on
 * - auto off
 * - set freq <hz>
 * - set amp <mv>
 * - set samples <count>
 * - expect <ohms>
 */

Adafruit_MCP4725 dac;
Adafruit_ADS1115 ads;

static const uint8_t ADS1115_ADDR = 0x48;
uint8_t mcp4725Address = 0x60;

static const float DAC_VREF = 3.3f;
static const float RF_FEEDBACK_OHM = 10000.0f;  // TIA feedback resistor
static const int DAC_MAX_CODE = 4095;
static const int DAC_CENTER_CODE = 2048;

static const float DEFAULT_FREQ_HZ = 0.1f;
static const float DEFAULT_AMP_MV = 10.0f;
static const int DEFAULT_SAMPLES = 800;

float testFrequencyHz = DEFAULT_FREQ_HZ;
float testAmplitudeMv = DEFAULT_AMP_MV;
int samplesPerCycle = DEFAULT_SAMPLES;

float expectedOhms = 0.0f;
bool autoMode = true;
unsigned long lastRunMs = 0;
const unsigned long autoIntervalMs = 10000;

static const int MAX_SAMPLES = 1200;
float adcVoltsBuffer[MAX_SAMPLES];

bool i2cDevicePresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
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

const char* classifyStatus(float rpOhm) {
  if (rpOhm > 100000.0f) return "EXCELLENT";
  if (rpOhm > 50000.0f) return "VERY_GOOD";
  if (rpOhm > 10000.0f) return "GOOD";
  if (rpOhm > 5000.0f) return "FAIR";
  if (rpOhm > 1000.0f) return "WARNING";
  if (rpOhm > 500.0f) return "SEVERE";
  return "CRITICAL";
}

void printHelp() {
  Serial.println("Commands:");
  Serial.println("  help");
  Serial.println("  once");
  Serial.println("  auto on | auto off");
  Serial.println("  set freq <hz>");
  Serial.println("  set amp <mv>");
  Serial.println("  set samples <count>");
  Serial.println("  expect <ohms>");
}

int clampDacCode(int code) {
  if (code < 0) return 0;
  if (code > DAC_MAX_CODE) return DAC_MAX_CODE;
  return code;
}

int mvToDacCode(float mv) {
  float volts = mv / 1000.0f;
  float deltaCode = (volts / DAC_VREF) * (float)DAC_MAX_CODE;
  int code = DAC_CENTER_CODE + (int)(deltaCode);
  return clampDacCode(code);
}

void runMeasurementCycle() {
  if (samplesPerCycle > MAX_SAMPLES) {
    samplesPerCycle = MAX_SAMPLES;
  }
  if (samplesPerCycle < 100) {
    samplesPerCycle = 100;
  }
  if (testFrequencyHz <= 0.0f) {
    testFrequencyHz = DEFAULT_FREQ_HZ;
  }

  const float periodMs = (1000.0f / testFrequencyHz);
  const float sampleIntervalMs = periodMs / (float)samplesPerCycle;

  Serial.println("--- Measurement Start ---");
  Serial.print("Config: freq=");
  Serial.print(testFrequencyHz, 4);
  Serial.print(" Hz, amp=");
  Serial.print(testAmplitudeMv, 3);
  Serial.print(" mV, samples=");
  Serial.println(samplesPerCycle);

  for (int i = 0; i < samplesPerCycle; i++) {
    unsigned long t0 = micros();

    float phase = (2.0f * PI * (float)i) / (float)samplesPerCycle;
    float vAppliedMv = testAmplitudeMv * sinf(phase);

    int code = mvToDacCode(vAppliedMv);
    dac.setVoltage(code, false);

    // Allow analog path settling before ADC read.
    delayMicroseconds(800);

    int16_t raw = ads.readADC_SingleEnded(0);
    float vAdc = ads.computeVolts(raw);
    adcVoltsBuffer[i] = vAdc;

    unsigned long elapsedUs = micros() - t0;
    unsigned long targetUs = (unsigned long)(sampleIntervalMs * 1000.0f);
    if (elapsedUs < targetUs) {
      delayMicroseconds(targetUs - elapsedUs);
    }
  }

  dac.setVoltage(DAC_CENTER_CODE, false);

  float meanV = 0.0f;
  for (int i = 0; i < samplesPerCycle; i++) {
    meanV += adcVoltsBuffer[i];
  }
  meanV /= (float)samplesPerCycle;

  float peakSignalV = 0.0f;
  for (int i = 0; i < samplesPerCycle; i++) {
    float signal = adcVoltsBuffer[i] - meanV;
    float mag = fabsf(signal);
    if (mag > peakSignalV) {
      peakSignalV = mag;
    }
  }

  float iPeakA = peakSignalV / RF_FEEDBACK_OHM;
  float rpOhm;
  if (iPeakA < 1e-9f) {
    rpOhm = 1e9f;
  } else {
    rpOhm = (testAmplitudeMv / 1000.0f) / iPeakA;
  }

  float iPeakUa = iPeakA * 1e6f;
  const char* status = classifyStatus(rpOhm);

  Serial.print("ADC mean (bias): ");
  Serial.print(meanV, 6);
  Serial.println(" V");
  Serial.print("ADC signal peak: ");
  Serial.print(peakSignalV, 6);
  Serial.println(" V");

  Serial.print("Rp_calc: ");
  Serial.print(rpOhm, 2);
  Serial.println(" ohm");
  Serial.print("I_peak: ");
  Serial.print(iPeakUa, 3);
  Serial.println(" uA");
  Serial.print("Status: ");
  Serial.println(status);

  if (expectedOhms > 0.0f) {
    float errPct = 100.0f * fabsf(rpOhm - expectedOhms) / expectedOhms;
    Serial.print("Expected: ");
    Serial.print(expectedOhms, 2);
    Serial.println(" ohm");
    Serial.print("Error: ");
    Serial.print(errPct, 2);
    Serial.println(" %");
  }

  Serial.print("FRAME:Rp:");
  Serial.print(rpOhm, 2);
  Serial.print(";I:");
  Serial.print(iPeakUa, 3);
  Serial.print(";status:");
  Serial.print(status);
  if (expectedOhms > 0.0f) {
    Serial.print(";expected:");
    Serial.print(expectedOhms, 2);
  }
  Serial.println();
  Serial.println("--- Measurement End ---");
}

void handleCommand(String line) {
  line.trim();
  line.toLowerCase();

  if (line.length() == 0) {
    return;
  }

  if (line == "help") {
    printHelp();
    return;
  }
  if (line == "once") {
    runMeasurementCycle();
    return;
  }
  if (line == "auto on") {
    autoMode = true;
    Serial.println("Auto mode ON");
    return;
  }
  if (line == "auto off") {
    autoMode = false;
    Serial.println("Auto mode OFF");
    return;
  }

  if (line.startsWith("set freq ")) {
    float v = line.substring(9).toFloat();
    if (v > 0.0f && v <= 5.0f) {
      testFrequencyHz = v;
      Serial.print("Frequency set to ");
      Serial.print(testFrequencyHz, 4);
      Serial.println(" Hz");
    } else {
      Serial.println("Invalid freq. Use 0 < Hz <= 5");
    }
    return;
  }

  if (line.startsWith("set amp ")) {
    float v = line.substring(8).toFloat();
    if (v > 0.1f && v <= 100.0f) {
      testAmplitudeMv = v;
      Serial.print("Amplitude set to ");
      Serial.print(testAmplitudeMv, 3);
      Serial.println(" mV");
    } else {
      Serial.println("Invalid amp. Use 0.1 to 100 mV");
    }
    return;
  }

  if (line.startsWith("set samples ")) {
    int n = line.substring(12).toInt();
    if (n >= 100 && n <= MAX_SAMPLES) {
      samplesPerCycle = n;
      Serial.print("Samples set to ");
      Serial.println(samplesPerCycle);
    } else {
      Serial.print("Invalid samples. Use 100 to ");
      Serial.println(MAX_SAMPLES);
    }
    return;
  }

  if (line.startsWith("expect ")) {
    float v = line.substring(7).toFloat();
    if (v > 0.0f) {
      expectedOhms = v;
      Serial.print("Expected resistor set to ");
      Serial.print(expectedOhms, 2);
      Serial.println(" ohm");
    } else {
      Serial.println("Invalid expected ohms");
    }
    return;
  }

  Serial.println("Unknown command. Type: help");
}

void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 4000) {
    delay(10);
  }

  Serial.println("=== Teensy 4.1 Potentiostat Resistor Test ===");

  Wire.begin();
  Wire.setClock(400000);

  mcp4725Address = detectMcp4725Address();
  Serial.print("I2C check MCP4725 (0x60-0x63): ");
  if (mcp4725Address != ) {
    Serial.print("FOUND at 0x");
    Serial.println(mcp4725Address, HEX);
  } else {
    Serial.println("NOT FOUND");
  }
  Serial.print("I2C check ADS1115 (0x48): ");
  Serial.println(i2cDevicePresent(ADS1115_ADDR) ? "FOUND" : "NOT FOUND");

  if (mcp4725Address == 0 || !dac.begin(mcp4725Address)) {
    Serial.println("FATAL: MCP4725 init failed. Check VCC, GND, SDA, SCL, and ADDR pins.");
    while (1) {
      delay(100);
    }
  }

  Serial.print("MCP4725 address in use: 0x");
  Serial.println(mcp4725Address, HEX);

  if (!ads.begin(ADS1115_ADDR)) {
    Serial.println("FATAL: ADS1115 init failed.");
    while (1) {
      delay(100);
    }
  }

  ads.setGain(GAIN_ONE);  // +/-4.096V full-scale
  ads.setDataRate(RATE_ADS1115_860SPS);

  dac.setVoltage(DAC_CENTER_CODE, false);

  Serial.println("Ready.");
  printHelp();
  Serial.println("Auto mode starts now (1 measurement per 10 seconds).\n");
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }

  if (autoMode) {
    unsigned long now = millis();
    if (now - lastRunMs >= autoIntervalMs) {
      lastRunMs = now;
      runMeasurementCycle();
    }
  }
}
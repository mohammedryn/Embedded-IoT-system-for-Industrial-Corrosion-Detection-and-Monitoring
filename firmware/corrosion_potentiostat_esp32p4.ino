#include <Wire.h>
#include <Adafruit_MCP4725.h>
#include <Adafruit_ADS1X15.h>

/*
 * ESP32-P4 potentiostat firmware
 *
 * Purpose:
 * - Drive MCP4725 DAC with a low-frequency sine perturbation
 * - Read ADS1115 ADC from the TIA output
 * - Compute Rp from the measured peak current
 * - Emit the same FRAME serial schema used by the Raspberry Pi stack
 *
 * Electrode stage:
 * - Stage 1 resistor validation:
 *   TIA +IN biased at Vmid = 1.65V and ADS1115 A0 reads TIA output
 * - Stage 2 real-electrode mode:
 *   ADS1115 A0 reads TIA output and ADS1115 A1 is tied to Vmid
 *   Use command: set mode diff
 *
 * Serial commands:
 * - help
 * - once
 * - auto on | auto off
 * - set freq <hz>
 * - set amp <mv>
 * - set samples <count>
 * - set rf <ohms>
 * - set mode single|diff
 * - expect <ohms>
 * - bias
 *
 * Important:
 * - In Arduino IDE, select an ESP32-P4 board.
 * - If USB serial does not appear, enable the board option for USB CDC on boot.
 * - If MCP4725 / ADS1115 are not detected, set I2C_SDA_PIN and I2C_SCL_PIN below
 *   to match your board wiring.
 */

// ── Configuration ────────────────────────────────────────────────────────────

// Stage 2 real-electrode mode is usually differential A0-A1.
// Leave 0 for startup safety and switch at runtime with "set mode diff".
#define DIFFERENTIAL_ADC 0

// Feedback resistor on the TIA.
static const float RF_DEFAULT_OHM = 100000.0f;

// ESP32-P4 I2C configuration for Waveshare ESP32-P4-WIFI6.
// Waveshare documents the default board I2C pins as SDA=GPIO7 and SCL=GPIO8.
// If you are using a different ESP32-P4 board, verify the vendor pinout first.
static const int I2C_SDA_PIN = 7;
static const int I2C_SCL_PIN = 8;
static const uint32_t I2C_CLOCK_HZ = 400000;

// Serial baud for Pi/PC communication.
static const unsigned long SERIAL_BAUD = 115200;

// ─────────────────────────────────────────────────────────────────────────────

Adafruit_MCP4725 dac;
Adafruit_ADS1115 ads;

static const uint8_t ADS1115_ADDR = 0x48;
uint8_t mcp4725Address = 0x60;

static const float DAC_VREF = 3.3f;
static const int DAC_MAX_CODE = 4095;
static const int DAC_CENTER_CODE = 2048;

static const float DEFAULT_FREQ_HZ = 0.1f;
static const float DEFAULT_AMP_MV = 10.0f;
static const int DEFAULT_SAMPLES = 800;

float testFrequencyHz = DEFAULT_FREQ_HZ;
float testAmplitudeMv = DEFAULT_AMP_MV;
int samplesPerCycle = DEFAULT_SAMPLES;
float rfFeedbackOhm = RF_DEFAULT_OHM;
bool differentialMode = (DIFFERENTIAL_ADC == 1);

float expectedOhms = 0.0f;
bool autoMode = true;
unsigned long lastRunMs = 0;
const unsigned long autoIntervalMs = 10000;

static const int MAX_SAMPLES = 1200;
float adcVoltsBuffer[MAX_SAMPLES];

// ── Helpers ───────────────────────────────────────────────────────────────────

bool i2cDevicePresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return (Wire.endTransmission() == 0);
}

uint8_t detectMcp4725Address() {
  const uint8_t candidates[] = {0x60, 0x61, 0x62, 0x63};
  const size_t count = sizeof(candidates) / sizeof(candidates[0]);
  for (size_t i = 0; i < count; i++) {
    if (i2cDevicePresent(candidates[i])) return candidates[i];
  }
  return 0;
}

const char* classifyStatus(float rpOhm) {
  if (rpOhm > 100000.0f) return "EXCELLENT";
  if (rpOhm > 50000.0f)  return "VERY_GOOD";
  if (rpOhm > 10000.0f)  return "GOOD";
  if (rpOhm > 5000.0f)   return "FAIR";
  if (rpOhm > 1000.0f)   return "WARNING";
  if (rpOhm > 500.0f)    return "SEVERE";
  return "CRITICAL";
}

void printHelp() {
  Serial.println("Commands:");
  Serial.println("  help");
  Serial.println("  once");
  Serial.println("  auto on | auto off");
  Serial.println("  set freq <hz>        (0 < hz <= 5)");
  Serial.println("  set amp <mv>         (0.1 to 100 mV)");
  Serial.println("  set samples <n>      (100 to 1200)");
  Serial.println("  set rf <ohms>        (feedback resistor value)");
  Serial.println("  set mode single|diff (ADC input mode)");
  Serial.println("  expect <ohms>        (known resistor for error%)");
  Serial.println("  bias                 (read ADC bias now)");
}

int clampDacCode(int code) {
  if (code < 0) return 0;
  if (code > DAC_MAX_CODE) return DAC_MAX_CODE;
  return code;
}

int mvToDacCode(float mv) {
  const float volts = mv / 1000.0f;
  const float deltaCode = (volts / DAC_VREF) * (float)DAC_MAX_CODE;
  return clampDacCode(DAC_CENTER_CODE + (int)deltaCode);
}

float readAdcVolts() {
  const int16_t raw = differentialMode
    ? ads.readADC_Differential_0_1()
    : ads.readADC_SingleEnded(0);
  return ads.computeVolts(raw);
}

void beginI2C() {
  if (I2C_SDA_PIN >= 0 && I2C_SCL_PIN >= 0) {
    Wire.begin(I2C_SDA_PIN, I2C_SCL_PIN, I2C_CLOCK_HZ);
    Serial.print("I2C begin on explicit pins SDA=");
    Serial.print(I2C_SDA_PIN);
    Serial.print(" SCL=");
    Serial.println(I2C_SCL_PIN);
  } else {
    Wire.begin();
    Wire.setClock(I2C_CLOCK_HZ);
    Serial.println("I2C begin on board default pins");
    Serial.println("If devices are not found, set I2C_SDA_PIN / I2C_SCL_PIN in this sketch.");
  }
}

void printBias() {
  dac.setVoltage(DAC_CENTER_CODE, false);
  delay(20);

  float sum = 0.0f;
  for (int i = 0; i < 8; i++) {
    sum += readAdcVolts();
    delay(2);
  }

  const float bias = sum / 8.0f;
  Serial.print("ADC bias (quiescent): ");
  Serial.print(bias, 6);
  Serial.println(" V");

  if (!differentialMode) {
    if (bias < 0.5f) {
      Serial.println("WARNING: bias < 0.5V - TIA +IN is NOT at Vmid. Check wiring.");
    } else if (bias > 1.3f && bias < 2.0f) {
      Serial.println("OK: bias is near 1.65V - Vmid wiring looks correct.");
    } else if (bias >= 2.0f) {
      Serial.println("WARNING: bias > 2.0V - check Vmid divider polarity.");
    }
  } else {
    if (fabsf(bias) < 0.05f) {
      Serial.println("OK: differential bias near 0V - A1 reference working.");
    } else {
      Serial.println("WARNING: differential bias not near 0V - check A1 connection.");
    }
  }
}

// ── Measurement cycle ─────────────────────────────────────────────────────────

void runMeasurementCycle() {
  if (samplesPerCycle > MAX_SAMPLES) samplesPerCycle = MAX_SAMPLES;
  if (samplesPerCycle < 100) samplesPerCycle = 100;
  if (testFrequencyHz <= 0.0f) testFrequencyHz = DEFAULT_FREQ_HZ;

  const float periodMs = 1000.0f / testFrequencyHz;
  const float sampleIntervalMs = periodMs / (float)samplesPerCycle;

  Serial.println("--- Measurement Start ---");
  Serial.print("Config: freq=");
  Serial.print(testFrequencyHz, 4);
  Serial.print(" Hz, amp=");
  Serial.print(testAmplitudeMv, 3);
  Serial.print(" mV, samples=");
  Serial.print(samplesPerCycle);
  Serial.print(", Rf=");
  Serial.print(rfFeedbackOhm, 0);
  Serial.print(" ohm, mode=");
  Serial.println(differentialMode ? "diff" : "single");

  for (int i = 0; i < samplesPerCycle; i++) {
    const unsigned long t0 = micros();

    const float phase = (2.0f * PI * (float)i) / (float)samplesPerCycle;
    const float vAppliedMv = testAmplitudeMv * sinf(phase);

    dac.setVoltage(mvToDacCode(vAppliedMv), false);
    delayMicroseconds(800);

    adcVoltsBuffer[i] = readAdcVolts();

    const unsigned long elapsedUs = micros() - t0;
    const unsigned long targetUs = (unsigned long)(sampleIntervalMs * 1000.0f);
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

  float peakPos = 0.0f;
  float peakNeg = 0.0f;
  for (int i = 0; i < samplesPerCycle; i++) {
    const float s = adcVoltsBuffer[i] - meanV;
    if (s > peakPos) peakPos = s;
    if (-s > peakNeg) peakNeg = -s;
  }

  const float peakSignalV = (peakPos + peakNeg) / 2.0f;
  const float asymmetryPct = (peakPos + peakNeg > 0.0f)
    ? 100.0f * fabsf(peakPos - peakNeg) / (peakPos + peakNeg)
    : 0.0f;

  const float iPeakA = peakSignalV / rfFeedbackOhm;
  const float rpOhm = (iPeakA < 1e-9f) ? 1e9f : (testAmplitudeMv / 1000.0f) / iPeakA;
  const float iPeakUa = iPeakA * 1e6f;
  const char* status = classifyStatus(rpOhm);

  Serial.print("ADC mean (bias): ");
  Serial.print(meanV, 6);
  Serial.println(" V");
  Serial.print("Peak+: ");
  Serial.print(peakPos * 1000.0f, 3);
  Serial.print(" mV  Peak-: ");
  Serial.print(peakNeg * 1000.0f, 3);
  Serial.print(" mV  Asymmetry: ");
  Serial.print(asymmetryPct, 1);
  Serial.println(" %");
  Serial.print("ADC signal peak (avg): ");
  Serial.print(peakSignalV, 6);
  Serial.println(" V");

  if (asymmetryPct > 15.0f) {
    Serial.println("WARN: asymmetry >15% - signal may be clipping on one rail.");
  }

  Serial.print("Rp_calc: ");
  Serial.print(rpOhm, 2);
  Serial.println(" ohm");
  Serial.print("I_peak: ");
  Serial.print(iPeakUa, 3);
  Serial.println(" uA");
  Serial.print("Status: ");
  Serial.println(status);

  if (expectedOhms > 0.0f) {
    const float errPct = 100.0f * fabsf(rpOhm - expectedOhms) / expectedOhms;
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
  Serial.print(";asym:");
  Serial.print(asymmetryPct, 1);
  if (expectedOhms > 0.0f) {
    Serial.print(";expected:");
    Serial.print(expectedOhms, 2);
  }
  Serial.println();
  Serial.println("--- Measurement End ---");
}

// ── Command handler ───────────────────────────────────────────────────────────

void handleCommand(String line) {
  line.trim();
  line.toLowerCase();
  if (line.length() == 0) return;

  if (line == "help")     { printHelp(); return; }
  if (line == "once")     { runMeasurementCycle(); return; }
  if (line == "bias")     { printBias(); return; }
  if (line == "auto on")  { autoMode = true;  Serial.println("Auto mode ON");  return; }
  if (line == "auto off") { autoMode = false; Serial.println("Auto mode OFF"); return; }

  if (line.startsWith("set freq ")) {
    const float v = line.substring(9).toFloat();
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
    const float v = line.substring(8).toFloat();
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
    const int n = line.substring(12).toInt();
    if (n >= 100 && n <= MAX_SAMPLES) {
      samplesPerCycle = n;
      Serial.print("Samples set to ");
      Serial.println(samplesPerCycle);
    } else {
      Serial.print("Invalid. Use 100 to ");
      Serial.println(MAX_SAMPLES);
    }
    return;
  }

  if (line.startsWith("set rf ")) {
    const float v = line.substring(7).toFloat();
    if (v >= 100.0f && v <= 10000000.0f) {
      rfFeedbackOhm = v;
      Serial.print("Rf set to ");
      Serial.print(rfFeedbackOhm, 0);
      Serial.println(" ohm");
    } else {
      Serial.println("Invalid Rf. Use 100 to 10000000 ohm");
    }
    return;
  }

  if (line.startsWith("set mode ")) {
    String mode = line.substring(9);
    mode.trim();
    if (mode == "diff") {
      differentialMode = true;
      Serial.println("ADC mode: differential (A0-A1)");
    } else if (mode == "single") {
      differentialMode = false;
      Serial.println("ADC mode: single-ended (A0)");
    } else {
      Serial.println("Use: set mode single  OR  set mode diff");
    }
    return;
  }

  if (line.startsWith("expect ")) {
    const float v = line.substring(7).toFloat();
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

// ── Setup / Loop ──────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(SERIAL_BAUD);

  const unsigned long waitStart = millis();
  while (!Serial && (millis() - waitStart) < 4000) {
    delay(10);
  }

  Serial.println("=== ESP32-P4 Potentiostat Test v1 ===");
  Serial.print("Rf = ");
  Serial.print(rfFeedbackOhm, 0);
  Serial.println(" ohm");
  Serial.print("ADC mode: ");
  Serial.println(differentialMode ? "differential (A0-A1)" : "single-ended (A0)");

  beginI2C();

  mcp4725Address = detectMcp4725Address();
  Serial.print("I2C check MCP4725 (0x60-0x63): ");
  if (mcp4725Address != 0) {
    Serial.print("FOUND at 0x");
    Serial.println(mcp4725Address, HEX);
  } else {
    Serial.println("NOT FOUND");
  }

  Serial.print("I2C check ADS1115 (0x48): ");
  Serial.println(i2cDevicePresent(ADS1115_ADDR) ? "FOUND" : "NOT FOUND");

  if (mcp4725Address == 0 || !dac.begin(mcp4725Address)) {
    Serial.println("FATAL: MCP4725 init failed. Check VCC, GND, SDA, SCL, ADDR pins.");
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

  ads.setGain(GAIN_ONE);
  ads.setDataRate(RATE_ADS1115_860SPS);
  dac.setVoltage(DAC_CENTER_CODE, false);

  Serial.println("Checking ADC bias at startup...");
  printBias();

  Serial.println("Ready.");
  printHelp();
  Serial.println("Auto mode starts now (1 measurement per 10 seconds).");
  Serial.println();
}

void loop() {
  if (Serial.available()) {
    String line = Serial.readStringUntil('\n');
    handleCommand(line);
  }

  if (autoMode) {
    const unsigned long now = millis();
    if (now - lastRunMs >= autoIntervalMs) {
      lastRunMs = now;
      runMeasurementCycle();
    }
  }
}

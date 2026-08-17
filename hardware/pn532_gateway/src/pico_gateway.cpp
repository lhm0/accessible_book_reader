#include <Arduino.h>
#include <Wire.h>

#include <PN532/PN532/PN532.h>
#include <PN532/PN532/PN532Interface.h>
#include <PN532/PN532_I2C/PN532_I2C.h>

namespace {

constexpr uint8_t kPn532Address = 0x24;
constexpr uint32_t kDebugBaudRate = 115200;
constexpr uint32_t kUartBaudRate = 115200;
constexpr uint8_t kUartTxPin = PIN_SERIAL_TX;
constexpr uint8_t kUartRxPin = PIN_SERIAL_RX;
constexpr bool kEnableReader1 = true;
constexpr bool kEnableReader2 = false;
constexpr unsigned long kReconnectIntervalMs = 5000;
constexpr unsigned long kTagPollIntervalMs = 400;
constexpr uint16_t kTagPollTimeoutMs = 50;
constexpr size_t kCommandBufferSize = 64;

HardwareSerial& rp5Serial = Serial1;
TwoWire i2cBus2(6, 7);

String formatHex(uint32_t value) {
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "0x%08" PRIX32, value);
  return String(buffer);
}

String uidToString(const uint8_t* uid, uint8_t uidLength) {
  if (uidLength == 0) {
    return String("-");
  }

  String result;
  for (uint8_t i = 0; i < uidLength; ++i) {
    if (i > 0) {
      result += ':';
    }
    if (uid[i] < 0x10) {
      result += '0';
    }
    result += String(uid[i], HEX);
  }
  result.toUpperCase();
  return result;
}

const __FlashStringHelper* transportStatusText(int status) {
  switch (status) {
    case 0:
      return F("OK");
    case PN532_INVALID_ACK:
      return F("PN532_INVALID_ACK");
    case PN532_TIMEOUT:
      return F("PN532_TIMEOUT");
    case PN532_INVALID_FRAME:
      return F("PN532_INVALID_FRAME");
    case PN532_NO_SPACE:
      return F("PN532_NO_SPACE");
    default:
      return F("UNKNOWN");
  }
}

const __FlashStringHelper* i2cWriteStatusText(uint8_t status) {
  switch (status) {
    case 0:
      return F("ACK");
    case 1:
      return F("NONZERO_ERROR_1");
    case 2:
      return F("NACK_ON_ADDRESS");
    case 3:
      return F("NACK_ON_DATA");
    case 4:
      return F("OTHER_ERROR");
    default:
      return F("UNKNOWN");
  }
}

void printHexByte(Stream& out, uint8_t value) {
  if (value < 0x10) {
    out.print('0');
  }
  out.print(value, HEX);
}

void printHexBuffer(Stream& out, const uint8_t* data, uint8_t length) {
  for (uint8_t i = 0; i < length; ++i) {
    if (i > 0) {
      out.print(' ');
    }
    printHexByte(out, data[i]);
  }
}

class Reader {
 public:
  Reader(uint8_t id, const char* label, TwoWire& wire, uint8_t sdaPin, uint8_t sclPin, bool enabled)
      : id_(id),
        label_(label),
        wire_(wire),
        sdaPin_(sdaPin),
        sclPin_(sclPin),
        enabled_(enabled),
        transport_(wire),
        nfc_(transport_) {}

  void begin() {
    if (!enabled_) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.println(F("] Deaktiviert"));
      return;
    }

    wire_.begin();
    wire_.setClock(100000);

    log(F("I2C initialisiert"));
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] Pins: SDA=GP"));
    Serial.print(sdaPin_);
    Serial.print(F(", SCL=GP"));
    Serial.println(sclPin_);

    lastInitAttemptMs_ = millis();
    initialize();
  }

  void service(unsigned long now) {
    if (!enabled_) {
      return;
    }

    if (!online_ && now - lastInitAttemptMs_ >= kReconnectIntervalMs) {
      lastInitAttemptMs_ = now;
      initialize();
    }

    if (!online_ || now - lastPollMs_ < kTagPollIntervalMs) {
      return;
    }

    lastPollMs_ = now;
    pollTag();
  }

  void forceReinitialize() {
    if (!enabled_) {
      return;
    }

    online_ = false;
    lastInitAttemptMs_ = millis() - kReconnectIntervalMs;
  }

  void printStatus(Stream& out) const {
    out.print(F("READER id="));
    out.print(id_);
    out.print(F(" label="));
    out.print(label_);
    out.print(F(" enabled="));
    out.print(enabled_ ? 1 : 0);
    out.print(F(" online="));
    out.print(online_ ? 1 : 0);
    out.print(F(" fw="));
    out.print(formatHex(firmwareVersion_));
    out.print(F(" tag="));
    out.print(tagPresent_ ? 1 : 0);
    out.print(F(" uid="));
    out.print(lastUidString_);
    out.print(F(" irq_mode="));
    out.print(lastSamIqrMode_);
    out.print(F(" last_error="));
    out.println(lastError_);
  }

  void printDiag(Stream& out) {
    out.print(F("DIAG id="));
    out.print(id_);
    out.print(F(" address=0x"));
    out.print(kPn532Address, HEX);
    out.print(F(" enabled="));
    out.print(enabled_ ? 1 : 0);
    out.print(F(" probe="));
    out.print(probeAddress() ? F("ACK") : F("FAIL"));
    out.print(F(" gpio="));
    out.print(readGpioHex());
    out.print(F(" sam_irq1="));
    out.print(runRawSamConfig(0x01) ? F("OK") : F("FAIL"));
    out.print(F(" sam_irq0="));
    out.println(runRawSamConfig(0x00) ? F("OK") : F("FAIL"));
  }

 private:
  bool initialize() {
    log(F("Initialisiere PN532"));
    nfc_.begin();

    firmwareVersion_ = nfc_.getFirmwareVersion();
    if (firmwareVersion_ == 0) {
      setError(F("getFirmwareVersion=0"));
      runExtendedDiagnostics();
      return false;
    }

    logFirmware();

    if (safeSamConfig(0x01)) {
      lastSamIqrMode_ = 1;
    } else if (safeSamConfig(0x00)) {
      lastSamIqrMode_ = 0;
    } else {
      setError(F("SAMConfig fehlgeschlagen"));
      runExtendedDiagnostics();
      return false;
    }

    safeSetRfField(0x00, 0x01);
    nfc_.setPassiveActivationRetries(0x01);

    online_ = true;
    tagPresent_ = false;
    lastUidLength_ = 0;
    lastUidString_ = F("-");
    lastError_ = F("none");
    lastSeenTagMs_ = 0;
    log(F("PN532 bereit"));
    return true;
  }

  void pollTag() {
    const uint32_t currentVersion = nfc_.getFirmwareVersion();
    if (currentVersion == 0) {
      setError(F("Verbindung verloren"));
      return;
    }

    firmwareVersion_ = currentVersion;

    uint8_t uid[7] = {0};
    uint8_t uidLength = 0;
    const bool found = nfc_.readPassiveTargetID(
        PN532_MIFARE_ISO14443A,
        uid,
        &uidLength,
        kTagPollTimeoutMs);

    if (found) {
      const bool isNewTag = !tagPresent_ || uidLength != lastUidLength_ || memcmp(lastUid_, uid, uidLength) != 0;
      tagPresent_ = true;
      lastUidLength_ = uidLength;
      memcpy(lastUid_, uid, uidLength);
      lastUidString_ = uidToString(uid, uidLength);
      lastSeenTagMs_ = millis();
      lastError_ = F("none");
      if (isNewTag) {
        Serial.print(F("["));
        Serial.print(label_);
        Serial.print(F("] Tag erkannt: UID="));
        Serial.print(lastUidString_);
        Serial.print(F(", Len="));
        Serial.println(lastUidLength_);
      }
      return;
    }

    if (tagPresent_) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Tag entfernt: UID="));
      Serial.println(lastUidString_);
    }

    tagPresent_ = false;
    lastUidLength_ = 0;
    lastUidString_ = F("-");
  }

  bool safeSamConfig(uint8_t irqMode) {
    uint8_t command[] = {
        PN532_COMMAND_SAMCONFIGURATION,
        0x01,
        0x14,
        irqMode,
    };
    uint8_t response[16] = {0};

    if (transport_.writeCommand(command, sizeof(command)) != 0) {
      return false;
    }

    return transport_.readResponse(response, sizeof(response), 1000) >= 0;
  }

  bool safeSetRfField(uint8_t autoRfca, uint8_t rfOnOff) {
    uint8_t command[] = {
        PN532_COMMAND_RFCONFIGURATION,
        0x01,
        static_cast<uint8_t>(autoRfca | rfOnOff),
    };
    uint8_t response[16] = {0};

    if (transport_.writeCommand(command, sizeof(command)) != 0) {
      return false;
    }

    return transport_.readResponse(response, sizeof(response), 1000) >= 0;
  }

  bool runRawSamConfig(uint8_t irqMode) {
    return safeSamConfig(irqMode);
  }

  void runExtendedDiagnostics() {
    Serial.print(F("["));
    Serial.print(label_);
    Serial.println(F("] Erweiterte Diagnose"));
    runI2cSanityTest();
    runRawFirmwareCommand();
    runRawSamConfigDiagnostic(0x01);
    runRawSamConfigDiagnostic(0x00);
  }

  bool probeAddress() {
    wire_.beginTransmission(kPn532Address);
    return wire_.endTransmission() == 0;
  }

  void scanBus() {
    bool foundAny = false;
    for (uint8_t address = 1; address < 127; ++address) {
      wire_.beginTransmission(address);
      if (wire_.endTransmission() == 0) {
        foundAny = true;
        Serial.print(F("["));
        Serial.print(label_);
        Serial.print(F("] I2C Geraet bei 0x"));
        printHexByte(Serial, address);
        Serial.println();
      }
    }

    if (!foundAny) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.println(F("] Kein I2C-Geraet gefunden"));
    }
  }

  void runI2cSanityTest() {
    Serial.print(F("["));
    Serial.print(label_);
    Serial.println(F("] I2C Sanity-Test"));

    Serial.print(F("["));
    Serial.print(label_);
    Serial.println(F("]   Hinweis: leeres endTransmission() ist beim Pico-Core kein sicherer PN532-Scan"));

    runRawWireFirmwareProbe();
  }

  void runRawWireFirmwareProbe() {
    const uint8_t frame[] = {
        0x00, 0x00, 0xFF,
        0x02, 0xFE,
        0xD4, 0x02,
        0x2A,
        0x00,
    };

    wire_.beginTransmission(kPn532Address);
    wire_.write(frame, sizeof(frame));
    const uint8_t txStatus = wire_.endTransmission();

    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("]   Raw frame write -> "));
    Serial.print(i2cWriteStatusText(txStatus));
    Serial.print(F(" ("));
    Serial.print(txStatus);
    Serial.println(')');

    for (uint8_t attempt = 1; attempt <= 5; ++attempt) {
      const size_t received = wire_.requestFrom(kPn532Address, static_cast<size_t>(8));
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("]   Poll "));
      Serial.print(attempt);
      Serial.print(F(" requestFrom(8) -> received="));
      Serial.print(received);

      if (received > 0) {
        uint8_t bytes[8] = {0};
        uint8_t index = 0;
        while (wire_.available() > 0 && index < received && index < sizeof(bytes)) {
          bytes[index++] = static_cast<uint8_t>(wire_.read());
        }
        Serial.print(F(", data="));
        printHexBuffer(Serial, bytes, index);
      }

      Serial.println();
      delay(20);
    }
  }

  void runRawFirmwareCommand() {
    uint8_t command[] = {PN532_COMMAND_GETFIRMWAREVERSION};
    uint8_t response[16] = {0};

    Serial.print(F("["));
    Serial.print(label_);
    Serial.println(F("] Raw getFirmwareVersion"));

    const int8_t writeStatus = transport_.writeCommand(command, sizeof(command));
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("]   writeCommand -> "));
    Serial.print(transportStatusText(writeStatus));
    Serial.print(F(" ("));
    Serial.print(writeStatus);
    Serial.println(')');
    if (writeStatus != 0) {
      return;
    }

    const int16_t readStatus = transport_.readResponse(response, sizeof(response), 1000);
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("]   readResponse -> "));
    if (readStatus < 0) {
      Serial.print(transportStatusText(readStatus));
      Serial.print(F(" ("));
      Serial.print(readStatus);
      Serial.println(')');
      return;
    }

    Serial.print(F("len="));
    Serial.print(readStatus);
    Serial.print(F(", data="));
    printHexBuffer(Serial, response, static_cast<uint8_t>(readStatus));
    Serial.println();
  }

  void runRawSamConfigDiagnostic(uint8_t irqMode) {
    uint8_t command[] = {
        PN532_COMMAND_SAMCONFIGURATION,
        0x01,
        0x14,
        irqMode,
    };
    uint8_t response[16] = {0};

    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] Raw SAMConfig irq="));
    Serial.println(irqMode);

    const int8_t writeStatus = transport_.writeCommand(command, sizeof(command));
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("]   writeCommand -> "));
    Serial.print(transportStatusText(writeStatus));
    Serial.print(F(" ("));
    Serial.print(writeStatus);
    Serial.println(')');
    if (writeStatus != 0) {
      return;
    }

    const int16_t readStatus = transport_.readResponse(response, sizeof(response), 1000);
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("]   readResponse -> "));
    if (readStatus < 0) {
      Serial.print(transportStatusText(readStatus));
      Serial.print(F(" ("));
      Serial.print(readStatus);
      Serial.println(')');
      return;
    }

    Serial.print(F("len="));
    Serial.print(readStatus);
    Serial.print(F(", data="));
    printHexBuffer(Serial, response, static_cast<uint8_t>(readStatus));
    Serial.println();
  }

  String readGpioHex() {
    const uint8_t gpio = nfc_.readGPIO();
    char buffer[5];
    snprintf(buffer, sizeof(buffer), "%02X", gpio);
    return String(buffer);
  }

  void setError(const __FlashStringHelper* error) {
    online_ = false;
    tagPresent_ = false;
    lastUidLength_ = 0;
    lastUidString_ = F("-");
    lastError_ = String(error);
    log(error);
  }

  void log(const __FlashStringHelper* message) const {
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] "));
    Serial.println(message);
  }

  void logFirmware() const {
    const uint8_t ic = (firmwareVersion_ >> 24) & 0xFF;
    const uint8_t ver = (firmwareVersion_ >> 16) & 0xFF;
    const uint8_t rev = (firmwareVersion_ >> 8) & 0xFF;
    const uint8_t support = firmwareVersion_ & 0xFF;

    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] Firmware IC=0x"));
    Serial.print(ic, HEX);
    Serial.print(F(", Version "));
    Serial.print(ver);
    Serial.print('.');
    Serial.print(rev);
    Serial.print(F(", Support=0x"));
    Serial.println(support, HEX);
  }

  uint8_t id_;
  const char* label_;
  TwoWire& wire_;
  uint8_t sdaPin_;
  uint8_t sclPin_;
  bool enabled_;
  PN532_I2C transport_;
  PN532 nfc_;
  bool online_ = false;
  bool tagPresent_ = false;
  uint32_t firmwareVersion_ = 0;
  uint8_t lastUid_[7] = {0};
  uint8_t lastUidLength_ = 0;
  String lastUidString_ = "-";
  String lastError_ = "boot";
  unsigned long lastInitAttemptMs_ = 0;
  unsigned long lastPollMs_ = 0;
  unsigned long lastSeenTagMs_ = 0;
  int lastSamIqrMode_ = -1;
};

Reader reader1(1, "PN532-1", Wire, 4, 5, kEnableReader1);
Reader reader2(2, "PN532-2", i2cBus2, 6, 7, kEnableReader2);
Reader* readers[] = {&reader1, &reader2};

char commandBuffer[kCommandBufferSize];
size_t commandLength = 0;

void printHelp() {
  rp5Serial.println(F("OK commands=PING,STATUS,STATUS 1,STATUS 2,REINIT,REINIT 1,REINIT 2,DIAG,HELP"));
  rp5Serial.flush();
}

Reader* getReaderById(int id) {
  if (id == 1) {
    return &reader1;
  }
  if (id == 2) {
    return &reader2;
  }
  return nullptr;
}

void printStatusHeader() {
  rp5Serial.print(F("OK uptime_ms="));
  rp5Serial.println(millis());
}

void handleStatusCommand(const String& command) {
  printStatusHeader();

  if (command == F("STATUS")) {
    for (Reader* reader : readers) {
      reader->printStatus(rp5Serial);
    }
    rp5Serial.println(F("END"));
    rp5Serial.flush();
    return;
  }

  const int id = command.substring(7).toInt();
  Reader* reader = getReaderById(id);
  if (reader == nullptr) {
    rp5Serial.println(F("ERR unknown_reader"));
    return;
  }

  reader->printStatus(rp5Serial);
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void handleReinitCommand(const String& command) {
  if (command == F("REINIT")) {
    for (Reader* reader : readers) {
      reader->forceReinitialize();
    }
    rp5Serial.println(F("OK reinit=all"));
    rp5Serial.flush();
    return;
  }

  const int id = command.substring(7).toInt();
  Reader* reader = getReaderById(id);
  if (reader == nullptr) {
    rp5Serial.println(F("ERR unknown_reader"));
    return;
  }

  reader->forceReinitialize();
  rp5Serial.print(F("OK reinit="));
  rp5Serial.println(id);
  rp5Serial.flush();
}

void handleDiagCommand() {
  printStatusHeader();
  for (Reader* reader : readers) {
    reader->printDiag(rp5Serial);
  }
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void processCommand(const char* rawCommand) {
  String command(rawCommand);
  command.trim();
  command.toUpperCase();

  if (command.length() == 0) {
    return;
  }

  if (command == F("PING")) {
    rp5Serial.println(F("PONG"));
    rp5Serial.flush();
    return;
  }

  if (command == F("HELP")) {
    printHelp();
    return;
  }

  if (command.startsWith(F("STATUS"))) {
    handleStatusCommand(command);
    return;
  }

  if (command.startsWith(F("REINIT"))) {
    handleReinitCommand(command);
    return;
  }

  if (command == F("DIAG")) {
    handleDiagCommand();
    return;
  }

  rp5Serial.print(F("ERR unknown_command="));
  rp5Serial.println(command);
  rp5Serial.flush();
}

void serviceUart() {
  while (rp5Serial.available() > 0) {
    const char ch = static_cast<char>(rp5Serial.read());
    if (ch == '\r') {
      continue;
    }

    if (ch == '\n') {
      commandBuffer[commandLength] = '\0';
      processCommand(commandBuffer);
      commandLength = 0;
      continue;
    }

    if (commandLength + 1 < kCommandBufferSize) {
      commandBuffer[commandLength++] = ch;
    } else {
      commandLength = 0;
      rp5Serial.println(F("ERR command_too_long"));
      rp5Serial.flush();
    }
  }
}

}  // namespace

void setup() {
  Serial.begin(kDebugBaudRate);
  delay(300);

  rp5Serial.begin(kUartBaudRate);

  Serial.println();
  Serial.println(F("PN532 Dual Gateway auf Raspberry Pi Pico"));
  Serial.print(F("UART zum RP5: TX=GP"));
  Serial.print(kUartTxPin);
  Serial.print(F(", RX=GP"));
  Serial.println(kUartRxPin);

  reader1.begin();
  reader2.begin();
}

void loop() {
  const unsigned long now = millis();

  serviceUart();

  for (Reader* reader : readers) {
    reader->service(now);
  }
}

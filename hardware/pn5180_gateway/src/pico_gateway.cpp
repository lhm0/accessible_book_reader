#include <Arduino.h>
#include <SPI.h>

#include <PN5180.h>
#include <PN5180ISO14443.h>
#include <PN5180ISO15693.h>

#include <inttypes.h>
#include <cstring>

namespace {

constexpr uint32_t kDebugBaudRate = 115200;
constexpr uint32_t kUartBaudRate = 115200;
constexpr unsigned long kUsbConsoleStartupDelayMs = 3000;
constexpr unsigned long kReaderStartupSettleMs = 5000;
constexpr unsigned long kPn5180ResetPulseMs = 20;
constexpr unsigned long kPn5180PostResetSettleMs = 50;
constexpr unsigned long kTypeAFieldResetDelayMs = 8;
constexpr unsigned long kUartPostBootResetMs = 1000;
constexpr unsigned long kCommandInterByteTimeoutMs = 50;
constexpr bool kEnableIso14443ADebug = false;
constexpr bool kVerbosePollDebug = false;
constexpr bool kEnableHeartbeatDebug = false;
constexpr bool kEnableIso15693Fallback = false;
constexpr uint8_t kUartTxPin = PIN_SERIAL_TX;
constexpr uint8_t kUartRxPin = PIN_SERIAL_RX;

constexpr uint8_t kSpiMisoPin = PIN_SPI_MISO;
constexpr uint8_t kSpiMosiPin = PIN_SPI_MOSI;
constexpr uint8_t kSpiSckPin = PIN_SPI_SCK;

constexpr bool kEnableReader1 = true;
constexpr bool kEnableReader2 = true;
constexpr unsigned long kReconnectIntervalMs = 5000;
constexpr unsigned long kTagPollIntervalMs = 400;
constexpr unsigned long kHealthCheckIntervalMs = 2000;
constexpr unsigned long kNoTagDebugIntervalMs = 1000;
constexpr size_t kCommandBufferSize = 64;
constexpr unsigned long kHeartbeatBootWaitBlinkMs = 250;
constexpr unsigned long kHeartbeatErrorBlinkMs = 125;
constexpr unsigned long kHeartbeatIdlePulseOnMs = 80;
constexpr unsigned long kHeartbeatIdlePulsePeriodMs = 2000;
constexpr uint8_t kStatusProbeMaxAttempts = 3;
constexpr unsigned long kStatusProbeRetryDelayMs = 30;
constexpr uint32_t kRfStatusAgcMask = 0x000003FF;
constexpr uint32_t kRxStatusLenMask = 0x000001FF;
constexpr uint8_t kDefaultSignalScanRounds = 12;
constexpr uint8_t kMaxSignalScanRounds = 32;
constexpr uint8_t kIso14443DefaultTxConf = 0x00;
constexpr uint8_t kIso14443DefaultRxConf = 0x80;
constexpr uint32_t kIso14443DefaultRxWaitConfig = 0x00000878;
constexpr uint8_t kIso15693DefaultTxConf = 0x0D;
constexpr uint8_t kIso15693DefaultRxConf = 0x8D;
constexpr uint8_t kDefaultProfileScanRounds = 8;
constexpr uint8_t kMaxProfileScanRounds = 16;
constexpr uint8_t kDefaultTypeASweepRounds = 10;
constexpr uint8_t kMaxTypeASweepRounds = 32;

HardwareSerial& rp5Serial = Serial1;

enum class ProtocolMode {
  None,
  Iso14443A,
  Iso15693,
};

enum class HeartbeatMode {
  BootWait,
  Error,
  Idle,
  TagPresent,
};

enum class TagReadOutcome {
  TagFound,
  NoTag,
  ReaderError,
};

enum class StatusJobState {
  Idle,
  Pending,
  Running,
  Ready,
};

struct RfProfileSpec {
  uint8_t txConf;
  uint8_t rxConf;
};

struct TagSnapshot {
  bool present = false;
  ProtocolMode protocol = ProtocolMode::None;
  String uidString = "-";
  uint8_t uidLength = 0;
  bool rfStatusValid = false;
  uint32_t rfStatus = 0;
  uint16_t agcValue = 0;
  bool rxStatusValid = false;
  uint32_t rxStatus = 0;
  uint16_t rxLength = 0;
};

constexpr RfProfileSpec kIso15693ProfileScanSpecs[] = {
    {kIso15693DefaultTxConf, 0x8D},
    {kIso15693DefaultTxConf, 0x8C},
    {kIso15693DefaultTxConf, 0x8B},
    {kIso15693DefaultTxConf, 0x8A},
    {kIso15693DefaultTxConf, 0x89},
    {kIso15693DefaultTxConf, 0x88},
};

constexpr RfProfileSpec kIso14443AProfileScanSpecs[] = {
    {kIso14443DefaultTxConf, 0x80},
    {kIso14443DefaultTxConf, 0x81},
    {kIso14443DefaultTxConf, 0x82},
    {kIso14443DefaultTxConf, 0x83},
    {kIso14443DefaultTxConf, 0x84},
    {kIso14443DefaultTxConf, 0x85},
};

constexpr uint32_t kTypeASweepRxWaitValues[] = {
    0x00000870,
    0x00000878,
    0x0000087F,
    0x00000888,
    0x00000890,
};

constexpr uint32_t kPadConfigGpo1EnableMask = 0x00000001;
constexpr uint32_t kPadOutGpo1Mask = 0x00000001;

String formatHex32(uint32_t value) {
  char buffer[11];
  snprintf(buffer, sizeof(buffer), "0x%08" PRIX32, value);
  return String(buffer);
}

String formatHex24(uint32_t value) {
  char buffer[9];
  snprintf(buffer, sizeof(buffer), "0x%06" PRIX32, value & 0x00FFFFFF);
  return String(buffer);
}

String formatHex8(uint8_t value) {
  char buffer[5];
  snprintf(buffer, sizeof(buffer), "0x%02X", static_cast<unsigned int>(value));
  return String(buffer);
}

String uidToString(const uint8_t* uid, uint8_t uidLength, bool reverseOrder = false) {
  if (uidLength == 0) {
    return String("-");
  }

  String result;
  for (uint8_t index = 0; index < uidLength; ++index) {
    const uint8_t i = reverseOrder ? static_cast<uint8_t>((uidLength - 1) - index) : index;
    if (index > 0) {
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

String formatVersionText(const uint8_t version[2]) {
  String result(version[1]);
  result += '.';
  result += String(version[0]);
  return result;
}

String protocolToString(ProtocolMode protocol) {
  switch (protocol) {
    case ProtocolMode::Iso14443A:
      return String("ISO14443A");
    case ProtocolMode::Iso15693:
      return String("ISO15693");
    case ProtocolMode::None:
    default:
      return String("-");
  }
}

String typeADiagStageToString(PN5180TypeADiagStage stage) {
  switch (stage) {
    case PN5180_TA_STAGE_LOAD_RF_CONFIG:
      return String("load_rf_config");
    case PN5180_TA_STAGE_CLEAR_SYSTEM_CONFIG:
      return String("clear_system_config");
    case PN5180_TA_STAGE_CLEAR_RX_CRC:
      return String("clear_rx_crc");
    case PN5180_TA_STAGE_CLEAR_TX_CRC:
      return String("clear_tx_crc");
    case PN5180_TA_STAGE_REQA_WUPA_SEND:
      return String("reqa_wupa_send");
    case PN5180_TA_STAGE_ATQA_READ:
      return String("atqa_read");
    case PN5180_TA_STAGE_ANTICOLL_CL1_SEND:
      return String("anticoll_cl1_send");
    case PN5180_TA_STAGE_ANTICOLL_CL1_READ:
      return String("anticoll_cl1_read");
    case PN5180_TA_STAGE_ENABLE_RX_CRC:
      return String("enable_rx_crc");
    case PN5180_TA_STAGE_ENABLE_TX_CRC:
      return String("enable_tx_crc");
    case PN5180_TA_STAGE_SELECT_CL1_SEND:
      return String("select_cl1_send");
    case PN5180_TA_STAGE_SAK_READ:
      return String("sak_read");
    case PN5180_TA_STAGE_CASCADE_TAG_CHECK:
      return String("cascade_tag_check");
    case PN5180_TA_STAGE_CLEAR_RX_CRC_CL2:
      return String("clear_rx_crc_cl2");
    case PN5180_TA_STAGE_CLEAR_TX_CRC_CL2:
      return String("clear_tx_crc_cl2");
    case PN5180_TA_STAGE_ANTICOLL_CL2_SEND:
      return String("anticoll_cl2_send");
    case PN5180_TA_STAGE_ANTICOLL_CL2_READ:
      return String("anticoll_cl2_read");
    case PN5180_TA_STAGE_ENABLE_RX_CRC_CL2:
      return String("enable_rx_crc_cl2");
    case PN5180_TA_STAGE_ENABLE_TX_CRC_CL2:
      return String("enable_tx_crc_cl2");
    case PN5180_TA_STAGE_SELECT_CL2_SEND:
      return String("select_cl2_send");
    case PN5180_TA_STAGE_SAK_CL2_READ:
      return String("sak_cl2_read");
    case PN5180_TA_STAGE_SUCCESS:
      return String("success");
    case PN5180_TA_STAGE_NONE:
    default:
      return String("none");
  }
}

const __FlashStringHelper* typeAKindToString(uint8_t kind) {
  return kind == 0 ? F("REQA") : F("WUPA");
}

const __FlashStringHelper* boolText(bool value) {
  return value ? F("yes") : F("no");
}

bool parseUint32Value(const String& text, uint32_t* value) {
  if (value == nullptr) {
    return false;
  }

  String trimmed(text);
  trimmed.trim();
  if (trimmed.length() == 0) {
    return false;
  }

  int base = 10;
  size_t start = 0;
  if (trimmed.startsWith(F("0X"))) {
    base = 16;
    start = 2;
  }

  if (start >= trimmed.length()) {
    return false;
  }

  uint32_t result = 0;
  for (size_t i = start; i < trimmed.length(); ++i) {
    const char ch = trimmed.charAt(i);
    uint8_t digit = 0;
    if (ch >= '0' && ch <= '9') {
      digit = static_cast<uint8_t>(ch - '0');
    } else if (base == 16 && ch >= 'A' && ch <= 'F') {
      digit = static_cast<uint8_t>(10 + (ch - 'A'));
    } else if (base == 16 && ch >= 'a' && ch <= 'f') {
      digit = static_cast<uint8_t>(10 + (ch - 'a'));
    } else {
      return false;
    }

    if (base == 10) {
      result = (result * 10u) + digit;
    } else {
      result = (result << 4u) | digit;
    }
  }

  *value = result;
  return true;
}

bool versionLooksValid(const uint8_t version[2]) {
  const bool allZero = version[0] == 0x00 && version[1] == 0x00;
  const bool allFF = version[0] == 0xFF && version[1] == 0xFF;
  return !allZero && !allFF;
}

class Reader {
 public:
  Reader(
      uint8_t id,
      const char* label,
      uint8_t nssPin,
      uint8_t busyPin,
      uint8_t rstPin,
      uint8_t irqPin,
      bool enabled)
      : id_(id),
        label_(label),
        nssPin_(nssPin),
        busyPin_(busyPin),
        rstPin_(rstPin),
        irqPin_(irqPin),
        enabled_(enabled),
        iso14443_(nssPin, busyPin, rstPin),
        iso15693_(nssPin, busyPin, rstPin) {}

  void begin() {
    pinMode(irqPin_, INPUT);

    if (!enabled_) {
      return;
    }

    iso15693_.begin();
    digitalWrite(nssPin_, HIGH);
    holdInReset();
    updateSignalLevels();

    startupReadyMs_ = millis() + kReaderStartupSettleMs;
    lastInitAttemptMs_ = millis();
    lastError_ = F("boot_wait");
  }

  void printStartupInfo() const {
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] "));

    if (!enabled_) {
      Serial.println(F("Deaktiviert"));
      return;
    }

    Serial.print(F("Pins: NSS=GP"));
    Serial.print(nssPin_);
    Serial.print(F(", BUSY=GP"));
    Serial.print(busyPin_);
    Serial.print(F(", RST=GP"));
    Serial.print(rstPin_);
    Serial.print(F(", IRQ=GP"));
    Serial.println(irqPin_);

    Serial.print(F("["));
    Serial.print(label_);
    Serial.println(F("] Warte auf stabile Versorgung vor Reader-Init"));
  }

  void service(unsigned long now) {
    static_cast<void>(now);

    if (!enabled_) {
      return;
    }

    if (resetOverrideActive_) {
      applyResetOverrideLevel();
      return;
    }

    releaseToIdleReset();
  }

  void forceReinitialize() {
    if (!enabled_) {
      return;
    }

    resetOverrideActive_ = false;
    startupInitializationDone_ = true;
    online_ = false;
    clearTagState();
    clearStatusProbeSnapshots();
    holdInReset();
    updateSignalLevels();
    lastInitAttemptMs_ = millis() - kReconnectIntervalMs;
    lastError_ = F("manual_reinit");
  }

  void releaseToIdleReset() {
    activeProtocol_ = ProtocolMode::None;
    holdInReset();
    updateSignalLevels();
  }

  void setResetOverrideAuto() {
    if (!enabled_) {
      return;
    }

    resetOverrideActive_ = false;
    startupInitializationDone_ = true;
    online_ = false;
    clearTagState();
    clearStatusProbeSnapshots();
    holdInReset();
    updateSignalLevels();
    lastInitAttemptMs_ = millis() - kReconnectIntervalMs;
    lastError_ = F("rst_auto");
  }

  void setResetOverrideLevel(uint8_t level) {
    if (!enabled_) {
      return;
    }

    resetOverrideActive_ = true;
    resetOverrideLevelHigh_ = level != 0;
    startupInitializationDone_ = true;
    online_ = false;
    clearTagState();
    clearStatusProbeSnapshots();
    activeProtocol_ = ProtocolMode::None;
    applyResetOverrideLevel();
    lastError_ = resetOverrideLevelHigh_ ? F("rst_manual_high") : F("rst_manual_low");
  }

  void printResetState(Stream& out) {
    out.print(F("["));
    out.print(label_);
    out.print(F("] RST: "));

    if (!enabled_) {
      out.println(F("Reader deaktiviert"));
      return;
    }

    out.print(F("mode="));
    out.print(resetOverrideActive_ ? F("manual") : F("auto"));
    out.print(F(", level="));
    out.print(digitalRead(rstPin_) == HIGH ? 1 : 0);
    out.print(F(", target="));
    out.print(resetOverrideActive_ ? (resetOverrideLevelHigh_ ? 1 : 0) : 0);
    out.print(F(", online="));
    out.print(online_ ? 1 : 0);
    out.print(F(", last_error="));
    out.println(lastError_);
  }

  void printStatus(Stream& out) const {
    const TagSnapshot* primarySnapshot = statusProbeValid_ ? selectedStatusSnapshot() : nullptr;
    const TagSnapshot* iso15693Snapshot = statusProbeValid_ ? &statusIso15693Snapshot_ : nullptr;
    const TagSnapshot* iso14443Snapshot = statusProbeValid_ ? &statusIso14443ASnapshot_ : nullptr;

    out.print(F("READER id="));
    out.print(id_);
    out.print(F(" label="));
    out.print(label_);
    out.print(F(" enabled="));
    out.print(enabled_ ? 1 : 0);
    out.print(F(" online="));
    out.print(online_ ? 1 : 0);
    out.print(F(" fw="));
    out.print(formatHex32(packedVersion_));
    out.print(F(" tag="));
    out.print(primarySnapshot != nullptr ? 1 : (tagPresent_ ? 1 : 0));
    out.print(F(" uid="));
    out.print(primarySnapshot != nullptr ? primarySnapshot->uidString : lastUidString_);
    out.print(F(" tech="));
    out.print(primarySnapshot != nullptr ? protocolToString(primarySnapshot->protocol) : protocolToString(lastProtocol_));
    out.print(F(" len="));
    if (primarySnapshot != nullptr) {
      out.print(primarySnapshot->uidLength);
    } else if (tagPresent_) {
      out.print(lastUidLength_);
    } else {
      out.print('-');
    }
    out.print(F(" agc="));
    if (primarySnapshot != nullptr && primarySnapshot->rfStatusValid) {
      out.print(primarySnapshot->agcValue);
    } else if (tagPresent_ && lastRfStatusValid_) {
      out.print(lastAgcValue_);
    } else {
      out.print('-');
    }
    out.print(F(" rf_status="));
    if (primarySnapshot != nullptr && primarySnapshot->rfStatusValid) {
      out.print(formatHex32(primarySnapshot->rfStatus));
    } else if (tagPresent_ && lastRfStatusValid_) {
      out.print(formatHex32(lastRfStatus_));
    } else {
      out.print(F("-"));
    }
    out.print(F(" rx_status="));
    if (primarySnapshot != nullptr && primarySnapshot->rxStatusValid) {
      out.print(formatHex32(primarySnapshot->rxStatus));
    } else if (tagPresent_ && lastRxStatusValid_) {
      out.print(formatHex32(lastRxStatus_));
    } else {
      out.print(F("-"));
    }
    out.print(F(" rx_len="));
    if (primarySnapshot != nullptr && primarySnapshot->rxStatusValid) {
      out.print(primarySnapshot->rxLength);
    } else if (tagPresent_ && lastRxStatusValid_) {
      out.print(lastRxBytes_);
    } else {
      out.print(F("-"));
    }
    out.print(F(" tag15693="));
    out.print(iso15693Snapshot != nullptr && iso15693Snapshot->present ? 1 : 0);
    out.print(F(" uid15693="));
    out.print(iso15693Snapshot != nullptr && iso15693Snapshot->present ? iso15693Snapshot->uidString : String("-"));
    out.print(F(" len15693="));
    if (iso15693Snapshot != nullptr && iso15693Snapshot->present) {
      out.print(iso15693Snapshot->uidLength);
    } else {
      out.print(F("-"));
    }
    out.print(F(" tag14443a="));
    out.print(iso14443Snapshot != nullptr && iso14443Snapshot->present ? 1 : 0);
    out.print(F(" uid14443a="));
    out.print(iso14443Snapshot != nullptr && iso14443Snapshot->present ? iso14443Snapshot->uidString : String("-"));
    out.print(F(" len14443a="));
    if (iso14443Snapshot != nullptr && iso14443Snapshot->present) {
      out.print(iso14443Snapshot->uidLength);
    } else {
      out.print(F("-"));
    }
    out.print(F(" last_error="));
    out.print(lastError_);
    out.println();
  }

  bool isEnabled() const {
    return enabled_;
  }

  uint8_t id() const {
    return id_;
  }

  const char* label() const {
    return label_;
  }

  bool isOnline() const {
    return online_;
  }

  bool isTagPresent() const {
    return tagPresent_;
  }

  const String& lastUidString() const {
    return lastUidString_;
  }

  uint8_t lastUidLength() const {
    return lastUidLength_;
  }

  ProtocolMode lastProtocol() const {
    return lastProtocol_;
  }

  bool isStartupPending(unsigned long now) const {
    return enabled_ && !startupInitializationDone_ && now < startupReadyMs_;
  }

  void probeStatusNow() {
    clearStatusProbeSnapshots();
    clearTagState();

    if (!enabled_ || resetOverrideActive_) {
      online_ = false;
      return;
    }

    if (millis() < startupReadyMs_) {
      online_ = false;
      lastError_ = F("boot_wait");
      return;
    }

    String probeError = F("none");
    bool lowLevelOk = false;

    for (uint8_t attempt = 0; attempt < kStatusProbeMaxAttempts; ++attempt) {
      clearStatusProbeSnapshots();
      clearTagState();
      hardReset();
      activeProtocol_ = ProtocolMode::None;

      if (!refreshVersions()) {
        probeError = F("version_read_failed");
        online_ = false;
        releaseToIdleReset();
        if (attempt + 1 < kStatusProbeMaxAttempts) {
          delay(kStatusProbeRetryDelayMs);
          continue;
        }
        lastError_ = probeError;
        return;
      }

      if (!refreshSystemStatus()) {
        probeError = F("system_status_invalid");
        online_ = false;
        releaseToIdleReset();
        if (attempt + 1 < kStatusProbeMaxAttempts) {
          delay(kStatusProbeRetryDelayMs);
          continue;
        }
        lastError_ = probeError;
        return;
      }

      online_ = true;
      lowLevelOk = true;

      const TagReadOutcome iso14443Result =
          sampleTagSnapshot(ProtocolMode::Iso14443A, &statusIso14443ASnapshot_);
      const TagReadOutcome iso15693Result =
          sampleTagSnapshot(ProtocolMode::Iso15693, &statusIso15693Snapshot_);

      statusSelectedSnapshot_ = selectPreferredStatusSnapshot();
      statusProbeValid_ = true;

      if (statusSelectedSnapshot_.present) {
        lastError_ = F("none");
        releaseToIdleReset();
        return;
      }

      const bool transientReaderError =
          (iso14443Result == TagReadOutcome::ReaderError) ||
          (iso15693Result == TagReadOutcome::ReaderError);
      if (!transientReaderError) {
        lastError_ = F("none");
        releaseToIdleReset();
        return;
      }

      probeError = F("probe_retry_exhausted");
      releaseToIdleReset();
      if (attempt + 1 < kStatusProbeMaxAttempts) {
        delay(kStatusProbeRetryDelayMs);
      }
    }

    online_ = lowLevelOk;
    lastError_ = probeError;
  }

  void printUsbStatus(Stream& out) const {
    const TagSnapshot* primarySnapshot = statusProbeValid_ ? selectedStatusSnapshot() : nullptr;
    out.print(F("["));
    out.print(label_);
    out.print(F("] "));

    if (!enabled_) {
      out.println(F("Deaktiviert"));
      return;
    }

    if (!online_) {
      out.println(F("Offline"));
      return;
    }

    if (primarySnapshot == nullptr && !tagPresent_) {
      out.println(F("Kein Tag erkannt"));
      return;
    }

    out.print(F("Status: UID="));
    out.print(primarySnapshot != nullptr ? primarySnapshot->uidString : lastUidString_);
    out.print(F(", Tech="));
    out.print(primarySnapshot != nullptr ? protocolToString(primarySnapshot->protocol) : protocolToString(lastProtocol_));
    out.print(F(", Len="));
    out.print(primarySnapshot != nullptr ? primarySnapshot->uidLength : lastUidLength_);
    out.print(F(", AGC="));
    if (primarySnapshot != nullptr && primarySnapshot->rfStatusValid) {
      out.print(primarySnapshot->agcValue);
    } else if (lastRfStatusValid_) {
      out.print(lastAgcValue_);
    } else {
      out.print(F("-"));
    }
    out.print(F(", RF_STATUS="));
    if (primarySnapshot != nullptr && primarySnapshot->rfStatusValid) {
      out.println(formatHex32(primarySnapshot->rfStatus));
    } else if (lastRfStatusValid_) {
      out.println(formatHex32(lastRfStatus_));
    } else {
      out.println(F("-"));
    }
    out.print(F("["));
    out.print(label_);
    out.print(F("] RX: status="));
    if (primarySnapshot != nullptr && primarySnapshot->rxStatusValid) {
      out.print(formatHex32(primarySnapshot->rxStatus));
      out.print(F(", len="));
      out.print(primarySnapshot->rxLength);
    } else if (lastRxStatusValid_) {
      out.print(formatHex32(lastRxStatus_));
      out.print(F(", len="));
      out.print(lastRxBytes_);
    } else {
      out.print(F("-"));
    }
    out.println();
    if (statusProbeValid_ && statusIso15693Snapshot_.present && statusIso14443ASnapshot_.present) {
      out.print(F("["));
      out.print(label_);
      out.print(F("] Beide Tags: ISO15693="));
      out.print(statusIso15693Snapshot_.uidString);
      out.print(F(", ISO14443A="));
      out.println(statusIso14443ASnapshot_.uidString);
    }
  }

  void printDiag(Stream& out) {
    const bool startupPending = isStartupPending(millis());
    const bool probeOk = (!enabled_ || startupPending || resetOverrideActive_)
                             ? false
                             : ([&]() {
                                 hardReset();
                                 activeProtocol_ = ProtocolMode::None;
                                 const bool ok = refreshHealth();
                                 releaseToIdleReset();
                                 return ok;
                               })();
    updateSignalLevels();

    out.print(F("DIAG id="));
    out.print(id_);
    out.print(F(" enabled="));
    out.print(enabled_ ? 1 : 0);
    out.print(F(" online="));
    out.print(online_ ? 1 : 0);
    out.print(F(" probe="));
    if (!enabled_) {
      out.print(F("OFF"));
    } else if (resetOverrideActive_) {
      out.print(F("RST"));
    } else if (startupPending) {
      out.print(F("WAIT"));
    } else {
      out.print(probeOk ? F("OK") : F("FAIL"));
    }
    out.print(F(" nss=GP"));
    out.print(nssPin_);
    out.print(F(" busy=GP"));
    out.print(busyPin_);
    out.print(F(" rst=GP"));
    out.print(rstPin_);
    out.print(F(" irq=GP"));
    out.print(irqPin_);
    out.print(F(" irq_level="));
    out.print(lastIrqLevel_);
    out.print(F(" busy_level="));
    out.print(lastBusyLevel_);
    out.print(F(" product="));
    out.print(formatVersionText(productVersion_));
    out.print(F(" firmware="));
    out.print(formatVersionText(firmwareVersion_));
    out.print(F(" eeprom="));
    out.print(formatVersionText(eepromVersion_));
    out.print(F(" system="));
    out.print(formatHex32(systemStatus_));
    out.print(F(" rf_status="));
    if (lastRfStatusValid_) {
      out.print(formatHex32(lastRfStatus_));
    } else {
      out.print(F("-"));
    }
    out.print(F(" agc="));
    if (lastRfStatusValid_) {
      out.print(lastAgcValue_);
    } else {
      out.print('-');
    }
    out.print(F(" rx_status="));
    if (lastRxStatusValid_) {
      out.print(formatHex32(lastRxStatus_));
    } else {
      out.print(F("-"));
    }
    out.print(F(" rx_len="));
    if (lastRxStatusValid_) {
      out.print(lastRxBytes_);
    } else {
      out.print(F("-"));
    }
    out.print(F(" active_proto="));
    out.print(protocolToString(activeProtocol_));
    out.print(F(" tag_proto="));
    out.print(protocolToString(lastProtocol_));
    out.print(F(" last_error="));
    out.println(lastError_);
  }

  void runTypeADiag(Stream& out) {
    if (!enabled_) {
      out.print(F("["));
      out.print(label_);
      out.print(F("] "));
      out.println(F("TYPEA_DIAG nicht verfuegbar: Reader deaktiviert"));
      return;
    }

    if (resetOverrideActive_) {
      out.print(F("["));
      out.print(label_);
      out.println(F("] TYPEA_DIAG nicht verfuegbar: RST-Override aktiv"));
      return;
    }

    hardReset();
    activeProtocol_ = ProtocolMode::None;

    if (!refreshVersions()) {
      out.print(F("["));
      out.print(label_);
      out.println(F("] TYPEA_DIAG nicht verfuegbar: version_read_failed"));
      return;
    }
    if (!refreshSystemStatus()) {
      out.print(F("["));
      out.print(label_);
      out.println(F("] TYPEA_DIAG nicht verfuegbar: system_status_invalid"));
      return;
    }
    if (!ensureProtocol(ProtocolMode::Iso14443A)) {
      out.print(F("["));
      out.print(label_);
      out.println(F("] TYPEA_DIAG nicht verfuegbar: RF-Setup fehlgeschlagen"));
      return;
    }

    for (uint8_t kind = 0; kind < 2; ++kind) {
      static_cast<void>(iso14443_.setRF_off());
      delay(kTypeAFieldResetDelayMs);
      hardReset();
      activeProtocol_ = ProtocolMode::None;
      if (!refreshSystemStatus() || !ensureProtocol(ProtocolMode::Iso14443A)) {
        out.print(F("["));
        out.print(label_);
        out.print(F("] TYPEA "));
        out.print(typeAKindToString(kind));
        out.println(F(": setup_failed"));
        continue;
      }

      PN5180TypeADiagResult diag;
      static_cast<void>(iso14443_.runTypeADiag(&diag, kind));

      out.print(F("["));
      out.print(label_);
      out.print(F("] TYPEA "));
      out.print(typeAKindToString(kind));
      out.print(F(": success="));
      out.print(diag.success ? 1 : 0);
      out.print(F(", stage="));
      out.print(typeADiagStageToString(diag.stage));
      out.print(F(", uid_len="));
      out.print(diag.uidLength);
      out.print(F(", uid="));
      out.print(diag.uidLength > 0 ? uidToString(diag.uid, diag.uidLength, false) : String("-"));
      out.print(F(", atqa="));
      out.print(diag.atqaReadOk ? uidToString(diag.atqa, 2, false) : String("-"));
      out.print(F(", cl1="));
      out.print(diag.cl1ReadOk ? uidToString(diag.cl1Raw, 5, false) : String("-"));
      out.print(F(", sak="));
      out.print(diag.sakReadOk ? formatHex8(diag.sak) : String("-"));
      out.print(F(", cl2_used="));
      out.print(diag.cl2Used ? 1 : 0);
      out.print(F(", cl2="));
      out.print(diag.cl2ReadOk ? uidToString(diag.cl2Raw, 5, false) : String("-"));
      out.print(F(", sak2="));
      out.print(diag.sak2ReadOk ? formatHex8(diag.sak2) : String("-"));
      out.print(F(", irq="));
      out.print(diag.irqStatusValid ? formatHex32(diag.irqStatus) : String("-"));
      out.print(F(", rf="));
      out.print(diag.rfStatusValid ? formatHex32(diag.rfStatus) : String("-"));
      out.print(F(", rx="));
      out.print(diag.rxStatusValid ? formatHex32(diag.rxStatus) : String("-"));
      out.print(F(", rx_len="));
      out.print(diag.rxStatusValid ? String(diag.rxLength) : String("-"));
      out.print(F(", rx_flags="));
      out.print(diag.rxStatusValid ? formatHex24(diag.rxStatus >> 9) : String("-"));
      out.print(F(", ts="));
      out.println(diag.rfStatusValid ? String((diag.rfStatus >> 24) & 0x07) : String("-"));

      static_cast<void>(iso14443_.setRF_off());
      delay(kTypeAFieldResetDelayMs);
      activeProtocol_ = ProtocolMode::None;
    }

    online_ = true;
    lastError_ = F("none");
    refreshRfMetrics();
    refreshRxMetrics();
    releaseToIdleReset();
  }

  void printTypeATune(Stream& out) {
    out.print(F("["));
    out.print(label_);
    out.print(F("] TYPEA_TUNE: "));

    if (!enabled_) {
      out.println(F("Reader deaktiviert"));
      return;
    }

    if (!prepareTypeATuneAccess()) {
      out.println(F("Zugriff fehlgeschlagen"));
      return;
    }

    uint32_t rxWaitConfig = 0;
    uint32_t timer1Config = 0;
    uint32_t timer1Reload = 0;
    const bool rxWaitOk = iso14443_.readRegister(RX_WAIT_CONFIG, &rxWaitConfig);
    const bool timer1CfgOk = iso14443_.readRegister(TIMER1_CONFIG, &timer1Config);
    const bool timer1ReloadOk = iso14443_.readRegister(TIMER1_RELOAD, &timer1Reload);

    out.print(F("rxwait="));
    out.print(rxWaitOk ? formatHex32(rxWaitConfig) : String("-"));
    out.print(F(", timer1_cfg="));
    out.print(timer1CfgOk ? formatHex32(timer1Config) : String("-"));
    out.print(F(", timer1_reload="));
    out.print(timer1ReloadOk ? formatHex32(timer1Reload) : String("-"));
    out.print(F(", override_rxwait="));
    out.print(typeATuneRxWaitEnabled_ ? formatHex32(typeATuneRxWaitValue_) : String("off"));
    out.print(F(", override_timer1_cfg="));
    out.print(typeATuneTimer1ConfigEnabled_ ? formatHex32(typeATuneTimer1ConfigValue_) : String("off"));
    out.print(F(", override_timer1_reload="));
    out.println(typeATuneTimer1ReloadEnabled_ ? formatHex32(typeATuneTimer1ReloadValue_) : String("off"));
  }

  void printGpo1State(Stream& out) {
    out.print(F("["));
    out.print(label_);
    out.print(F("] GPO1: "));

    if (!enabled_) {
      out.println(F("Reader deaktiviert"));
      return;
    }

    if (!prepareTypeATuneAccess()) {
      out.println(F("Zugriff fehlgeschlagen"));
      return;
    }

    uint32_t padConfig = 0;
    uint32_t padOut = 0;
    const bool padConfigOk = iso14443_.readRegister(PADCONFIG, &padConfig);
    const bool padOutOk = iso14443_.readRegister(PAD_OUT, &padOut);

    out.print(F("driver="));
    out.print(padConfigOk ? (((padConfig & kPadConfigGpo1EnableMask) != 0) ? 1 : 0) : -1);
    out.print(F(", level="));
    out.print(padOutOk ? (((padOut & kPadOutGpo1Mask) != 0) ? 1 : 0) : -1);
    out.print(F(", padconfig="));
    out.print(padConfigOk ? formatHex32(padConfig) : String("-"));
    out.print(F(", pad_out="));
    out.println(padOutOk ? formatHex32(padOut) : String("-"));
  }

  bool configureGpo1Level(uint8_t level, String* errorMessage = nullptr) {
    if (!prepareTypeATuneAccess()) {
      if (errorMessage != nullptr) {
        *errorMessage = F("setup_failed");
      }
      return false;
    }

    if (!iso14443_.writeRegisterWithOrMask(PADCONFIG, kPadConfigGpo1EnableMask)) {
      if (errorMessage != nullptr) {
        *errorMessage = F("padconfig_write_failed");
      }
      return false;
    }

    const bool ok = level != 0 ? iso14443_.writeRegisterWithOrMask(PAD_OUT, kPadOutGpo1Mask)
                               : iso14443_.writeRegisterWithAndMask(PAD_OUT, ~kPadOutGpo1Mask);
    if (!ok) {
      if (errorMessage != nullptr) {
        *errorMessage = F("padout_write_failed");
      }
      return false;
    }

    return true;
  }

  bool configureTypeATuneRegister(const String& key, uint32_t value, String* errorMessage = nullptr) {
    uint8_t reg = 0;
    uint32_t* targetValue = nullptr;
    bool* targetEnabled = nullptr;

    if (key == F("RXWAIT")) {
      reg = RX_WAIT_CONFIG;
      targetValue = &typeATuneRxWaitValue_;
      targetEnabled = &typeATuneRxWaitEnabled_;
    } else if (key == F("TIMER1CFG")) {
      reg = TIMER1_CONFIG;
      targetValue = &typeATuneTimer1ConfigValue_;
      targetEnabled = &typeATuneTimer1ConfigEnabled_;
    } else if (key == F("TIMER1RELOAD")) {
      reg = TIMER1_RELOAD;
      targetValue = &typeATuneTimer1ReloadValue_;
      targetEnabled = &typeATuneTimer1ReloadEnabled_;
    } else {
      if (errorMessage != nullptr) {
        *errorMessage = F("unknown_key");
      }
      return false;
    }

    *targetValue = value;
    *targetEnabled = true;

    if (!prepareTypeATuneAccess()) {
      if (errorMessage != nullptr) {
        *errorMessage = F("setup_failed");
      }
      return false;
    }

    if (!iso14443_.writeRegister(reg, value)) {
      hardReset();
      activeProtocol_ = ProtocolMode::None;
      if (!ensureProtocol(ProtocolMode::Iso14443A) || !iso14443_.writeRegister(reg, value)) {
        if (errorMessage != nullptr) {
          *errorMessage = F("write_failed");
        }
        return false;
      }
    }

    return true;
  }

  void resetTypeATune() {
    typeATuneRxWaitEnabled_ = false;
    typeATuneTimer1ConfigEnabled_ = false;
    typeATuneTimer1ReloadEnabled_ = false;

    if (online_ && activeProtocol_ == ProtocolMode::Iso14443A) {
      hardReset();
      activeProtocol_ = ProtocolMode::None;
      static_cast<void>(ensureProtocol(ProtocolMode::Iso14443A));
    }
  }

  void runTypeASweep(Stream& out, uint8_t rounds) {
    out.print(F("["));
    out.print(label_);
    out.print(F("] TYPEA_SWEEP: rounds="));
    out.print(rounds);
    out.print(F(", values="));
    out.println(sizeof(kTypeASweepRxWaitValues) / sizeof(kTypeASweepRxWaitValues[0]));

    if (!enabled_) {
      out.print(F("["));
      out.print(label_);
      out.println(F("] TYPEA_SWEEP nicht verfuegbar: Reader deaktiviert"));
      return;
    }

    const bool previousRxWaitEnabled = typeATuneRxWaitEnabled_;
    const uint32_t previousRxWaitValue = typeATuneRxWaitValue_;

    for (uint32_t rxWaitValue : kTypeASweepRxWaitValues) {
      String errorMessage;
      if (!configureTypeATuneRegister(F("RXWAIT"), rxWaitValue, &errorMessage)) {
        out.print(F("["));
        out.print(label_);
        out.print(F("] SWEEP rxwait="));
        out.print(formatHex32(rxWaitValue));
        out.print(F(", error="));
        out.println(errorMessage);
        continue;
      }

      uint8_t reqaOk = 0;
      uint8_t wupaOk = 0;
      uint8_t anyOk = 0;
      uint8_t bothOk = 0;
      uint8_t reqaSetupFail = 0;
      uint8_t wupaSetupFail = 0;

      for (uint8_t round = 0; round < rounds; ++round) {
        PN5180TypeADiagResult reqaDiag;
        PN5180TypeADiagResult wupaDiag;
        const bool reqaReady = executeTypeADiagRound(0, &reqaDiag);
        const bool wupaReady = executeTypeADiagRound(1, &wupaDiag);

        if (!reqaReady) {
          ++reqaSetupFail;
        } else if (reqaDiag.success) {
          ++reqaOk;
        }

        if (!wupaReady) {
          ++wupaSetupFail;
        } else if (wupaDiag.success) {
          ++wupaOk;
        }

        if (reqaReady && wupaReady) {
          if (reqaDiag.success || wupaDiag.success) {
            ++anyOk;
          }
          if (reqaDiag.success && wupaDiag.success) {
            ++bothOk;
          }
        }

        delay(20);
      }

      out.print(F("["));
      out.print(label_);
      out.print(F("] SWEEP rxwait="));
      out.print(formatHex32(rxWaitValue));
      out.print(F(", reqa_ok="));
      out.print(reqaOk);
      out.print(F("/"));
      out.print(rounds);
      out.print(F(", wupa_ok="));
      out.print(wupaOk);
      out.print(F("/"));
      out.print(rounds);
      out.print(F(", any_ok="));
      out.print(anyOk);
      out.print(F("/"));
      out.print(rounds);
      out.print(F(", both_ok="));
      out.print(bothOk);
      out.print(F("/"));
      out.print(rounds);
      out.print(F(", reqa_setup_fail="));
      out.print(reqaSetupFail);
      out.print(F(", wupa_setup_fail="));
      out.println(wupaSetupFail);
    }

    typeATuneRxWaitEnabled_ = previousRxWaitEnabled;
    typeATuneRxWaitValue_ = previousRxWaitValue;
    hardReset();
    activeProtocol_ = ProtocolMode::None;
    static_cast<void>(ensureProtocol(ProtocolMode::Iso14443A));
  }

  void runSignalScan(Stream& out, uint8_t rounds) {
    out.print(F("["));
    out.print(label_);
    out.print(F("] "));

    if (!enabled_) {
      out.println(F("Scan nicht verfuegbar: Reader deaktiviert"));
      return;
    }
    if (!online_) {
      out.println(F("Scan nicht verfuegbar: Reader offline"));
      return;
    }

    const ProtocolMode protocol =
        lastProtocol_ != ProtocolMode::None ? lastProtocol_ : defaultPreferredProtocol();
    if (protocol == ProtocolMode::None) {
      out.println(F("Scan nicht verfuegbar: kein aktives Protokoll"));
      return;
    }

    const String expectedUid = lastUidString_;
    uint8_t okCount = 0;
    uint8_t uidMatchCount = 0;
    uint32_t agcSum = 0;
    uint8_t agcSampleCount = 0;
    uint16_t agcMin = UINT16_MAX;
    uint16_t agcMax = 0;
    uint32_t rxLenSum = 0;
    uint8_t rxSampleCount = 0;
    uint16_t rxLenMin = UINT16_MAX;
    uint16_t rxLenMax = 0;

    for (uint8_t i = 0; i < rounds; ++i) {
      String sampledUid("-");
      uint8_t sampledUidLength = 0;
      if (sampleTagQuiet(protocol, &sampledUid, &sampledUidLength) != TagReadOutcome::TagFound) {
        delay(20);
        continue;
      }

      ++okCount;
      if (expectedUid != "-" && sampledUid == expectedUid) {
        ++uidMatchCount;
      }
      if (lastRfStatusValid_) {
        agcSum += lastAgcValue_;
        ++agcSampleCount;
        if (lastAgcValue_ < agcMin) {
          agcMin = lastAgcValue_;
        }
        if (lastAgcValue_ > agcMax) {
          agcMax = lastAgcValue_;
        }
      }
      if (lastRxStatusValid_) {
        rxLenSum += lastRxBytes_;
        ++rxSampleCount;
        if (lastRxBytes_ < rxLenMin) {
          rxLenMin = lastRxBytes_;
        }
        if (lastRxBytes_ > rxLenMax) {
          rxLenMax = lastRxBytes_;
        }
      }
      delay(20);
    }

    out.print(F("Scan: rounds="));
    out.print(rounds);
    out.print(F(", ok="));
    out.print(okCount);
    if (expectedUid != "-") {
      out.print(F(", uid_match="));
      out.print(uidMatchCount);
    }
    if (okCount == 0) {
      out.println(F(", AGC=-, RX_LEN=-"));
      return;
    }

    out.print(F(", agc_min="));
    if (agcSampleCount > 0) {
      out.print(agcMin);
    } else {
      out.print(F("-"));
    }
    out.print(F(", agc_max="));
    if (agcSampleCount > 0) {
      out.print(agcMax);
    } else {
      out.print(F("-"));
    }
    out.print(F(", agc_avg="));
    if (agcSampleCount > 0) {
      out.print((agcSum + (agcSampleCount / 2)) / agcSampleCount);
    } else {
      out.print(F("-"));
    }
    out.print(F(", rx_len_min="));
    if (rxSampleCount > 0) {
      out.print(rxLenMin);
    } else {
      out.print(F("-"));
    }
    out.print(F(", rx_len_max="));
    if (rxSampleCount > 0) {
      out.print(rxLenMax);
    } else {
      out.print(F("-"));
    }
    out.print(F(", rx_len_avg="));
    if (rxSampleCount > 0) {
      out.print((rxLenSum + (rxSampleCount / 2)) / rxSampleCount);
    } else {
      out.print(F("-"));
    }
    out.print(F(", rf_status="));
    out.print(lastRfStatusValid_ ? formatHex32(lastRfStatus_) : String("-"));
    out.print(F(", rx_status="));
    out.println(lastRxStatusValid_ ? formatHex32(lastRxStatus_) : String("-"));
  }

  void runProfileScan(Stream& out, uint8_t rounds) {
    out.print(F("["));
    out.print(label_);
    out.print(F("] "));

    if (!enabled_) {
      out.println(F("Profile-Scan nicht verfuegbar: Reader deaktiviert"));
      return;
    }
    if (!online_) {
      out.println(F("Profile-Scan nicht verfuegbar: Reader offline"));
      return;
    }

    const ProtocolMode protocol =
        lastProtocol_ != ProtocolMode::None ? lastProtocol_ : defaultPreferredProtocol();

    const String expectedUid = lastUidString_;
    out.print(F("PROFILESCAN: proto="));
    out.print(protocolToString(protocol));
    out.print(F(", rounds="));
    out.println(rounds);

    int lastFullMatchIndex = -1;
    int lastAnyReadIndex = -1;

    const RfProfileSpec* profiles = nullptr;
    size_t profileCount = 0;
    switch (protocol) {
      case ProtocolMode::Iso14443A:
        profiles = kIso14443AProfileScanSpecs;
        profileCount = sizeof(kIso14443AProfileScanSpecs) / sizeof(kIso14443AProfileScanSpecs[0]);
        break;
      case ProtocolMode::Iso15693:
        profiles = kIso15693ProfileScanSpecs;
        profileCount = sizeof(kIso15693ProfileScanSpecs) / sizeof(kIso15693ProfileScanSpecs[0]);
        break;
      case ProtocolMode::None:
      default:
        out.println(F("Profile-Scan nicht verfuegbar: kein aktives Protokoll"));
        return;
    }

    for (size_t index = 0; index < profileCount; ++index) {
      const RfProfileSpec& profile = profiles[index];
      out.print(F("["));
      out.print(label_);
      out.print(F("] P"));
      out.print(index);
      out.print(F(": tx="));
      out.print(formatHex8(profile.txConf));
      out.print(F(", rx="));
      out.print(formatHex8(profile.rxConf));

      if (!applyRfProfile(protocol, profile.txConf, profile.rxConf)) {
        out.println(F(", load=FAIL"));
        continue;
      }

      uint8_t okCount = 0;
      uint8_t uidMatchCount = 0;
      for (uint8_t round = 0; round < rounds; ++round) {
        String sampledUid("-");
        uint8_t sampledUidLength = 0;
        if (sampleTagQuiet(protocol, &sampledUid, &sampledUidLength) == TagReadOutcome::TagFound) {
          ++okCount;
          if (expectedUid == "-" || sampledUid == expectedUid) {
            ++uidMatchCount;
          }
        }
        delay(20);
      }

      out.print(F(", ok="));
      out.print(okCount);
      out.print(F("/"));
      out.print(rounds);
      out.print(F(", uid_match="));
      out.print(uidMatchCount);
      out.print(F("/"));
      out.println(rounds);

      if (okCount > 0) {
        lastAnyReadIndex = static_cast<int>(index);
      }
      if (uidMatchCount == rounds) {
        lastFullMatchIndex = static_cast<int>(index);
      }
    }

    restoreDefaultRfProfile(protocol);
    refreshRfMetrics();
    refreshRxMetrics();

    out.print(F("["));
    out.print(label_);
    out.print(F("] PROFILE RESULT: last_full_match="));
    if (lastFullMatchIndex >= 0) {
      out.print('P');
      out.print(lastFullMatchIndex);
    } else {
      out.print(F("-"));
    }
    out.print(F(", last_any_read="));
    if (lastAnyReadIndex >= 0) {
      out.print('P');
      out.print(lastAnyReadIndex);
    } else {
      out.print(F("-"));
    }
    out.println();
  }

 private:
  void clearStatusProbeSnapshots() {
    statusProbeValid_ = false;
    statusIso15693Snapshot_ = TagSnapshot{};
    statusIso14443ASnapshot_ = TagSnapshot{};
    statusSelectedSnapshot_ = TagSnapshot{};
  }

  TagReadOutcome sampleTagSnapshot(ProtocolMode protocol, TagSnapshot* snapshot) {
    if (snapshot == nullptr) {
      return TagReadOutcome::ReaderError;
    }

    *snapshot = TagSnapshot{};
    String sampledUid("-");
    uint8_t sampledUidLength = 0;
    const TagReadOutcome outcome = sampleTagQuiet(protocol, &sampledUid, &sampledUidLength);
    if (outcome != TagReadOutcome::TagFound) {
      return outcome;
    }

    snapshot->present = true;
    snapshot->protocol = protocol;
    snapshot->uidString = sampledUid;
    snapshot->uidLength = sampledUidLength;
    snapshot->rfStatusValid = lastRfStatusValid_;
    snapshot->rfStatus = lastRfStatus_;
    snapshot->agcValue = lastAgcValue_;
    snapshot->rxStatusValid = lastRxStatusValid_;
    snapshot->rxStatus = lastRxStatus_;
    snapshot->rxLength = lastRxBytes_;
    return TagReadOutcome::TagFound;
  }

  TagSnapshot selectPreferredStatusSnapshot() const {
    if (statusIso14443ASnapshot_.present) {
      return statusIso14443ASnapshot_;
    }
    if (statusIso15693Snapshot_.present) {
      return statusIso15693Snapshot_;
    }
    return TagSnapshot{};
  }

  const TagSnapshot* selectedStatusSnapshot() const {
    return statusSelectedSnapshot_.present ? &statusSelectedSnapshot_ : nullptr;
  }

  void restoreAfterStatusProbe(ProtocolMode previousPreferredProtocol, ProtocolMode previousActiveProtocol) {
    preferredProtocol_ = previousPreferredProtocol;

    const ProtocolMode restoreProtocol =
        previousActiveProtocol != ProtocolMode::None ? previousActiveProtocol : defaultPreferredProtocol();
    hardReset();
    activeProtocol_ = ProtocolMode::None;
    static_cast<void>(ensureProtocol(restoreProtocol));
  }

  bool applyRfProfile(ProtocolMode protocol, uint8_t txConf, uint8_t rxConf) {
    if (activeProtocol_ != protocol && !ensureProtocol(protocol)) {
      return false;
    }

    switch (protocol) {
      case ProtocolMode::Iso14443A:
        if (!iso14443_.setRF_off()) {
          return false;
        }
        if (!iso14443_.loadRFConfig(txConf, rxConf)) {
          return false;
        }
        if (!iso14443_.setRF_on()) {
          return false;
        }
        if (!applyTypeATuneRegisters()) {
          return false;
        }
        break;
      case ProtocolMode::Iso15693:
        if (!iso15693_.setRF_off()) {
          return false;
        }
        if (!iso15693_.loadRFConfig(txConf, rxConf)) {
          return false;
        }
        if (!iso15693_.setRF_on()) {
          return false;
        }
        if (!iso15693_.writeRegisterWithAndMask(SYSTEM_CONFIG, 0xFFFFFFF8)) {
          return false;
        }
        if (!iso15693_.writeRegisterWithOrMask(SYSTEM_CONFIG, 0x00000003)) {
          return false;
        }
        break;
      case ProtocolMode::None:
      default:
        return false;
    }

    activeProtocol_ = protocol;
    activeTxConf_ = txConf;
    activeRxConf_ = rxConf;
    delay(5);
    return true;
  }

  bool restoreDefaultRfProfile(ProtocolMode protocol) {
    uint8_t txConf = 0;
    uint8_t rxConf = 0;
    if (!defaultRfProfileForProtocol(protocol, &txConf, &rxConf)) {
      return false;
    }
    return applyRfProfile(protocol, txConf, rxConf);
  }

  static bool defaultRfProfileForProtocol(ProtocolMode protocol, uint8_t* txConf, uint8_t* rxConf) {
    if (txConf == nullptr || rxConf == nullptr) {
      return false;
    }

    switch (protocol) {
      case ProtocolMode::Iso14443A:
        *txConf = kIso14443DefaultTxConf;
        *rxConf = kIso14443DefaultRxConf;
        return true;
      case ProtocolMode::Iso15693:
        *txConf = kIso15693DefaultTxConf;
        *rxConf = kIso15693DefaultRxConf;
        return true;
      case ProtocolMode::None:
      default:
        return false;
    }
  }

  bool initialize() {
    log(F("Initialisiere PN5180"));
    hardReset();
    activeProtocol_ = ProtocolMode::None;

    if (!refreshVersions()) {
      holdInReset();
      setError(F("version_read_failed"));
      return false;
    }

    if (!refreshSystemStatus()) {
      holdInReset();
      setError(F("system_status_invalid"));
      return false;
    }

    if (!ensureProtocol(defaultPreferredProtocol())) {
      holdInReset();
      setError(F("rf_setup_failed"));
      return false;
    }

    online_ = true;
    clearTagState();
    lastError_ = F("none");
    logConfiguration();
    log(F("PN5180 bereit"));
    releaseToIdleReset();
    return true;
  }

  void holdInReset() {
    digitalWrite(nssPin_, HIGH);
    digitalWrite(rstPin_, LOW);
  }

  void applyResetOverrideLevel() {
    digitalWrite(nssPin_, HIGH);
    digitalWrite(rstPin_, resetOverrideLevelHigh_ ? HIGH : LOW);
    updateSignalLevels();
  }

  void hardReset() {
    iso14443_.reset();
    delay(kPn5180PostResetSettleMs);
    updateSignalLevels();
  }

  bool refreshVersions() {
    iso14443_.readEEprom(PRODUCT_VERSION, productVersion_, sizeof(productVersion_));
    iso14443_.readEEprom(FIRMWARE_VERSION, firmwareVersion_, sizeof(firmwareVersion_));
    iso14443_.readEEprom(EEPROM_VERSION, eepromVersion_, sizeof(eepromVersion_));

    packedVersion_ =
        (static_cast<uint32_t>(productVersion_[1]) << 24) |
        (static_cast<uint32_t>(productVersion_[0]) << 16) |
        (static_cast<uint32_t>(firmwareVersion_[1]) << 8) |
        static_cast<uint32_t>(firmwareVersion_[0]);

    return versionLooksValid(productVersion_) && versionLooksValid(firmwareVersion_);
  }

  bool refreshSystemStatus() {
    iso14443_.readRegister(SYSTEM_STATUS, &systemStatus_);
    return systemStatus_ != 0x00000000 && systemStatus_ != 0xFFFFFFFF;
  }

  bool refreshHealth() {
    if (!refreshVersions()) {
      return false;
    }
    return refreshSystemStatus();
  }

  bool refreshRfMetrics() {
    uint32_t rfStatus = 0;
    if (!iso14443_.readRegister(RF_STATUS, &rfStatus)) {
      lastRfStatusValid_ = false;
      lastRfStatus_ = 0;
      lastAgcValue_ = 0;
      return false;
    }

    lastRfStatus_ = rfStatus;
    lastAgcValue_ = static_cast<uint16_t>(rfStatus & kRfStatusAgcMask);
    lastRfStatusValid_ = true;
    return true;
  }

  bool refreshRxMetrics() {
    uint32_t rxStatus = 0;
    if (!iso14443_.readRegister(RX_STATUS, &rxStatus)) {
      lastRxStatusValid_ = false;
      lastRxStatus_ = 0;
      lastRxBytes_ = 0;
      return false;
    }

    lastRxStatus_ = rxStatus;
    lastRxBytes_ = static_cast<uint16_t>(rxStatus & kRxStatusLenMask);
    lastRxStatusValid_ = true;
    return true;
  }

  void applyTypeADiagMetrics(const PN5180TypeADiagResult& diag) {
    lastRfStatusValid_ = diag.rfStatusValid;
    lastRfStatus_ = diag.rfStatusValid ? diag.rfStatus : 0;
    lastAgcValue_ = diag.rfStatusValid ? static_cast<uint16_t>(diag.rfStatus & kRfStatusAgcMask) : 0;
    lastRxStatusValid_ = diag.rxStatusValid;
    lastRxStatus_ = diag.rxStatusValid ? diag.rxStatus : 0;
    lastRxBytes_ = diag.rxStatusValid ? diag.rxLength : 0;
  }

  bool readTypeATagRobust(uint8_t* uid, uint8_t* uidLength) {
    return readTypeATagRobustDetailed(uid, uidLength) == TagReadOutcome::TagFound;
  }

  TagReadOutcome readTypeATagRobustDetailed(uint8_t* uid, uint8_t* uidLength) {
    if (uid != nullptr) {
      memset(uid, 0, 7);
    }
    if (uidLength != nullptr) {
      *uidLength = 0;
    }

    bool anyRoundCompleted = false;
    PN5180TypeADiagResult diag;
    if (executeTypeADiagRound(0, &diag)) {
      anyRoundCompleted = true;
      applyTypeADiagMetrics(diag);
      if (diag.success && diag.uidLength >= 4) {
        if (uid != nullptr) {
          memcpy(uid, diag.uid, diag.uidLength > 7 ? 7 : diag.uidLength);
        }
        if (uidLength != nullptr) {
          *uidLength = diag.uidLength;
        }
        return TagReadOutcome::TagFound;
      }
    }

    if (executeTypeADiagRound(1, &diag)) {
      anyRoundCompleted = true;
      applyTypeADiagMetrics(diag);
      if (diag.success && diag.uidLength >= 4) {
        if (uid != nullptr) {
          memcpy(uid, diag.uid, diag.uidLength > 7 ? 7 : diag.uidLength);
        }
        if (uidLength != nullptr) {
          *uidLength = diag.uidLength;
        }
        return TagReadOutcome::TagFound;
      }
    }

    return anyRoundCompleted ? TagReadOutcome::NoTag : TagReadOutcome::ReaderError;
  }

  TagReadOutcome sampleTagQuiet(ProtocolMode protocol, String* uidString, uint8_t* uidLength) {
    if (protocol == ProtocolMode::Iso14443A) {
      uint8_t uid[7] = {0};
      uint8_t detectedUidLength = 0;
      const TagReadOutcome outcome = readTypeATagRobustDetailed(uid, &detectedUidLength);
      if (outcome != TagReadOutcome::TagFound) {
        return outcome;
      }
      if (uidLength != nullptr) {
        *uidLength = detectedUidLength;
      }
      if (uidString != nullptr) {
        *uidString = uidToString(uid, detectedUidLength, false);
      }
      return TagReadOutcome::TagFound;
    }

    if (!ensureProtocol(protocol)) {
      return TagReadOutcome::ReaderError;
    }

    uint8_t uid[8] = {0};
    const ISO15693ErrorCode rc = iso15693_.getInventory(uid);
    if (rc == EC_NO_CARD) {
      return TagReadOutcome::NoTag;
    }
    if (rc != ISO15693_EC_OK) {
      return TagReadOutcome::ReaderError;
    }

    if (uidLength != nullptr) {
      *uidLength = sizeof(uid);
    }
    if (uidString != nullptr) {
      *uidString = uidToString(uid, sizeof(uid), true);
    }
    refreshRfMetrics();
    refreshRxMetrics();
    return TagReadOutcome::TagFound;
  }

  bool ensureProtocol(ProtocolMode protocol) {
    if (activeProtocol_ == protocol) {
      return true;
    }

    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] setupRF "));
      Serial.println(protocolToString(protocol));
    }

    if (activeProtocol_ != ProtocolMode::None) {
      if (kVerbosePollDebug) {
        Serial.print(F("["));
        Serial.print(label_);
        Serial.print(F("] RF off before protocol switch from "));
        Serial.print(protocolToString(activeProtocol_));
        Serial.print(F(" to "));
        Serial.println(protocolToString(protocol));
      }

      if (!iso14443_.setRF_off()) {
        if (kVerbosePollDebug) {
          Serial.print(F("["));
          Serial.print(label_);
          Serial.println(F("] setRF_off failed before protocol switch"));
        }
        activeProtocol_ = ProtocolMode::None;
        return false;
      }

      iso14443_.clearIRQStatus(0xFFFFFFFF);
      activeProtocol_ = ProtocolMode::None;
      delay(5);
    }

    bool ok = false;
    switch (protocol) {
      case ProtocolMode::Iso14443A:
        ok = iso14443_.setupRF();
        if (ok) {
          ok = applyTypeATuneRegisters();
        }
        break;
      case ProtocolMode::Iso15693:
        ok = iso15693_.setupRF();
        break;
      case ProtocolMode::None:
      default:
        return false;
    }

    if (!ok) {
      if (kVerbosePollDebug) {
        Serial.print(F("["));
        Serial.print(label_);
        Serial.print(F("] setupRF failed "));
        Serial.println(protocolToString(protocol));
      }
      return false;
    }

    activeProtocol_ = protocol;
    uint8_t txConf = 0;
    uint8_t rxConf = 0;
    if (defaultRfProfileForProtocol(protocol, &txConf, &rxConf)) {
      activeTxConf_ = txConf;
      activeRxConf_ = rxConf;
    }
    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] setupRF ok "));
      Serial.println(protocolToString(protocol));
    }
    delay(5);
    return true;
  }

  void pollTag(unsigned long now) {
    updateSignalLevels();

    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Poll start irq="));
      Serial.print(lastIrqLevel_);
      Serial.print(F(" busy="));
      Serial.println(lastBusyLevel_);
    }

    hardReset();
    activeProtocol_ = ProtocolMode::None;

    if (now - lastHealthCheckMs_ >= kHealthCheckIntervalMs) {
      lastHealthCheckMs_ = now;
      if (!refreshHealth()) {
        releaseToIdleReset();
        setError(F("health_check_failed"));
        return;
      }
    }

    const ProtocolMode preferred = preferredProtocol_;
    const ProtocolMode fallback =
        preferred == ProtocolMode::Iso14443A ? ProtocolMode::Iso15693 : ProtocolMode::Iso14443A;

    uint8_t iso14443UidLength = 0;
    ISO15693ErrorCode iso15693Rc = EC_NO_CARD;
    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Try preferred="));
      Serial.println(protocolToString(preferred));
    }
    const bool preferredFound = tryReadTag(preferred, &iso14443UidLength, &iso15693Rc);
    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Preferred done found="));
      Serial.print(boolText(preferredFound));
      Serial.print(F(" iso14443_uid_len="));
      Serial.print(iso14443UidLength);
      Serial.print(F(" iso15693_rc="));
      Serial.println(static_cast<int>(iso15693Rc));
    }
    bool fallbackFound = false;
    if (!preferredFound && protocolFallbackEnabled()) {
      fallbackFound = tryReadTag(fallback, &iso14443UidLength, &iso15693Rc);
    }
    if (!preferredFound && protocolFallbackEnabled() && kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Fallback done protocol="));
      Serial.print(protocolToString(fallback));
      Serial.print(F(" found="));
      Serial.print(boolText(fallbackFound));
      Serial.print(F(" iso14443_uid_len="));
      Serial.print(iso14443UidLength);
      Serial.print(F(" iso15693_rc="));
      Serial.println(static_cast<int>(iso15693Rc));
    }

    if (preferredFound || fallbackFound) {
      lastError_ = F("none");
      debugPoll(now, preferred, fallback, iso14443UidLength, iso15693Rc, true);
      releaseToIdleReset();
      return;
    }

    debugPoll(now, preferred, fallback, iso14443UidLength, iso15693Rc, false);

    if (tagPresent_) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Tag entfernt: UID="));
      Serial.print(lastUidString_);
      Serial.print(F(", Tech="));
      Serial.print(protocolToString(lastProtocol_));
      Serial.print(F(", AGC="));
      if (lastRfStatusValid_) {
        Serial.print(lastAgcValue_);
      } else {
        Serial.print(F("-"));
      }
      Serial.print(F(", RF_STATUS="));
      if (lastRfStatusValid_) {
        Serial.print(formatHex32(lastRfStatus_));
      } else {
        Serial.print(F("-"));
      }
      Serial.print(F(", RX_STATUS="));
      if (lastRxStatusValid_) {
        Serial.print(formatHex32(lastRxStatus_));
        Serial.print(F(", RX_LEN="));
        Serial.println(lastRxBytes_);
      } else {
        Serial.println(F("-"));
      }
    }

    clearTagState();
    lastError_ = F("none");
    releaseToIdleReset();
  }

  bool tryReadTag(ProtocolMode protocol, uint8_t* iso14443UidLength, ISO15693ErrorCode* iso15693Rc) {
    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Enter "));
      Serial.println(protocolToString(protocol));
    }

    if (!ensureProtocol(protocol)) {
      if (kVerbosePollDebug) {
        Serial.print(F("["));
        Serial.print(label_);
        Serial.print(F("] ensureProtocol failed for "));
        Serial.println(protocolToString(protocol));
      }
      return false;
    }

    if (protocol == ProtocolMode::Iso14443A) {
      uint8_t uid[7] = {0};
      uint8_t uidLength = 0;
      if (!readTypeATagRobust(uid, &uidLength)) {
        if (iso14443UidLength != nullptr) {
          *iso14443UidLength = uidLength;
        }
        if (kVerbosePollDebug) {
          Serial.print(F("["));
          Serial.print(label_);
          Serial.println(F("] Exit ISO14443A without tag"));
        }
        return false;
      }
      if (iso14443UidLength != nullptr) {
        *iso14443UidLength = uidLength;
      }
      updateTag(uid, uidLength, protocol, false);
      return true;
    }

    uint8_t uid[8] = {0};
    const ISO15693ErrorCode rc = iso15693_.getInventory(uid);
    if (iso15693Rc != nullptr) {
      *iso15693Rc = rc;
    }
    if (rc == ISO15693_EC_OK) {
      updateTag(uid, sizeof(uid), protocol, true);
      return true;
    }

    if (kVerbosePollDebug) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Exit ISO15693 rc="));
      Serial.println(static_cast<int>(rc));
    }

    return false;
  }

  void updateTag(const uint8_t* uid, uint8_t uidLength, ProtocolMode protocol, bool reverseUid) {
    const String uidString = uidToString(uid, uidLength, reverseUid);
    const bool isNewTag =
        !tagPresent_ ||
        protocol != lastProtocol_ ||
        uidLength != lastUidLength_ ||
        memcmp(lastUid_, uid, uidLength) != 0;

    refreshRfMetrics();
    refreshRxMetrics();

    tagPresent_ = true;
    lastUidLength_ = uidLength;
    memcpy(lastUid_, uid, uidLength);
    lastUidString_ = uidString;
    lastProtocol_ = protocol;
    preferredProtocol_ = protocol;

    if (isNewTag) {
      Serial.print(F("["));
      Serial.print(label_);
      Serial.print(F("] Tag erkannt: UID="));
      Serial.print(lastUidString_);
      Serial.print(F(", Tech="));
      Serial.print(protocolToString(lastProtocol_));
      Serial.print(F(", Len="));
      Serial.print(lastUidLength_);
      Serial.print(F(", AGC="));
      if (lastRfStatusValid_) {
        Serial.print(lastAgcValue_);
      } else {
        Serial.print(F("-"));
      }
      Serial.print(F(", RF_STATUS="));
      if (lastRfStatusValid_) {
        Serial.print(formatHex32(lastRfStatus_));
      } else {
        Serial.print(F("-"));
      }
      Serial.print(F(", RX_STATUS="));
      if (lastRxStatusValid_) {
        Serial.print(formatHex32(lastRxStatus_));
        Serial.print(F(", RX_LEN="));
        Serial.println(lastRxBytes_);
      } else {
        Serial.println(F("-"));
      }
    }
  }

  void clearTagState() {
    tagPresent_ = false;
    lastUidLength_ = 0;
    memset(lastUid_, 0, sizeof(lastUid_));
    lastUidString_ = F("-");
    lastProtocol_ = ProtocolMode::None;
    lastRfStatusValid_ = false;
    lastRfStatus_ = 0;
    lastAgcValue_ = 0;
    lastRxStatusValid_ = false;
    lastRxStatus_ = 0;
    lastRxBytes_ = 0;
  }

  void updateSignalLevels() {
    lastIrqLevel_ = digitalRead(irqPin_);
    lastBusyLevel_ = digitalRead(busyPin_);
  }

  void logConfiguration() const {
    if (!kVerbosePollDebug) {
      return;
    }

    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] Poll-Debug aktiv, poll_ms="));
    Serial.print(kTagPollIntervalMs);
    Serial.print(F(", quiet_debug_ms="));
    Serial.println(kNoTagDebugIntervalMs);
  }

  void debugPoll(
      unsigned long now,
      ProtocolMode preferred,
      ProtocolMode fallback,
      uint8_t iso14443UidLength,
      ISO15693ErrorCode iso15693Rc,
      bool tagFound) {
    if (!kVerbosePollDebug) {
      return;
    }

    if (!tagFound && now - lastNoTagDebugMs_ < kNoTagDebugIntervalMs) {
      return;
    }

    if (!tagFound) {
      lastNoTagDebugMs_ = now;
    }

    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] Poll"));
    Serial.print(F(" preferred="));
    Serial.print(protocolToString(preferred));
    Serial.print(F(" fallback="));
    Serial.print(protocolToString(fallback));
    Serial.print(F(" active="));
    Serial.print(protocolToString(activeProtocol_));
    Serial.print(F(" found="));
    Serial.print(boolText(tagFound));
    Serial.print(F(" irq="));
    Serial.print(lastIrqLevel_);
    Serial.print(F(" busy="));
    Serial.print(lastBusyLevel_);
    Serial.print(F(" iso14443_uid_len="));
    Serial.print(iso14443UidLength);
    Serial.print(F(" iso15693_rc="));
    Serial.print(static_cast<int>(iso15693Rc));
    Serial.print(F(" last_error="));
    Serial.println(lastError_);
  }

  void setError(const __FlashStringHelper* error) {
    online_ = false;
    clearTagState();
    lastError_ = String(error);
    log(error);
  }

  void log(const __FlashStringHelper* message) const {
    Serial.print(F("["));
    Serial.print(label_);
    Serial.print(F("] "));
    Serial.println(message);
  }

  static ProtocolMode defaultPreferredProtocol() {
    return ProtocolMode::Iso14443A;
  }

  static bool protocolFallbackEnabled() {
    return kEnableIso15693Fallback;
  }

  bool applyTypeATuneRegisters() {
    if (activeProtocol_ != ProtocolMode::None && activeProtocol_ != ProtocolMode::Iso14443A) {
      return true;
    }

    const uint32_t rxWaitValue = typeATuneRxWaitEnabled_ ? typeATuneRxWaitValue_ : kIso14443DefaultRxWaitConfig;
    if (!iso14443_.writeRegister(RX_WAIT_CONFIG, rxWaitValue)) {
      return false;
    }
    if (typeATuneTimer1ReloadEnabled_ && !iso14443_.writeRegister(TIMER1_RELOAD, typeATuneTimer1ReloadValue_)) {
      return false;
    }
    if (typeATuneTimer1ConfigEnabled_ && !iso14443_.writeRegister(TIMER1_CONFIG, typeATuneTimer1ConfigValue_)) {
      return false;
    }
    return true;
  }

  bool prepareTypeATuneAccess() {
    if (!enabled_ || resetOverrideActive_) {
      return false;
    }

    if (!online_) {
      hardReset();
      activeProtocol_ = ProtocolMode::None;
      online_ = ensureProtocol(ProtocolMode::Iso14443A);
      return online_;
    }

    if (activeProtocol_ == ProtocolMode::Iso14443A) {
      return true;
    }

    if (ensureProtocol(ProtocolMode::Iso14443A)) {
      return true;
    }

    hardReset();
    activeProtocol_ = ProtocolMode::None;
    return ensureProtocol(ProtocolMode::Iso14443A);
  }

  bool executeTypeADiagRound(uint8_t kind, PN5180TypeADiagResult* diag) {
    static_cast<void>(iso14443_.setRF_off());
    delay(kTypeAFieldResetDelayMs);
    hardReset();
    activeProtocol_ = ProtocolMode::None;
    if (!refreshSystemStatus() || !ensureProtocol(ProtocolMode::Iso14443A)) {
      return false;
    }

    static_cast<void>(iso14443_.runTypeADiag(diag, kind));
    static_cast<void>(iso14443_.setRF_off());
    delay(kTypeAFieldResetDelayMs);
    activeProtocol_ = ProtocolMode::None;
    return true;
  }

  uint8_t id_;
  const char* label_;
  uint8_t nssPin_;
  uint8_t busyPin_;
  uint8_t rstPin_;
  uint8_t irqPin_;
  bool enabled_;
  PN5180ISO14443 iso14443_;
  PN5180ISO15693 iso15693_;
  bool online_ = false;
  bool tagPresent_ = false;
  uint8_t lastUid_[8] = {0};
  uint8_t lastUidLength_ = 0;
  String lastUidString_ = "-";
  String lastError_ = "boot";
  uint8_t productVersion_[2] = {0};
  uint8_t firmwareVersion_[2] = {0};
  uint8_t eepromVersion_[2] = {0};
  uint32_t packedVersion_ = 0;
  uint32_t systemStatus_ = 0;
  uint32_t lastRfStatus_ = 0;
  uint16_t lastAgcValue_ = 0;
  bool lastRfStatusValid_ = false;
  uint32_t lastRxStatus_ = 0;
  uint16_t lastRxBytes_ = 0;
  bool lastRxStatusValid_ = false;
  bool statusProbeValid_ = false;
  TagSnapshot statusIso15693Snapshot_;
  TagSnapshot statusIso14443ASnapshot_;
  TagSnapshot statusSelectedSnapshot_;
  unsigned long lastInitAttemptMs_ = 0;
  unsigned long lastPollMs_ = 0;
  unsigned long lastHealthCheckMs_ = 0;
  unsigned long lastNoTagDebugMs_ = 0;
  unsigned long startupReadyMs_ = 0;
  int lastIrqLevel_ = -1;
  int lastBusyLevel_ = -1;
  bool startupInitializationDone_ = false;
  ProtocolMode activeProtocol_ = ProtocolMode::None;
  uint8_t activeTxConf_ = 0xFF;
  uint8_t activeRxConf_ = 0xFF;
  bool resetOverrideActive_ = false;
  bool resetOverrideLevelHigh_ = false;
  bool typeATuneRxWaitEnabled_ = false;
  uint32_t typeATuneRxWaitValue_ = 0;
  bool typeATuneTimer1ConfigEnabled_ = false;
  uint32_t typeATuneTimer1ConfigValue_ = 0;
  bool typeATuneTimer1ReloadEnabled_ = false;
  uint32_t typeATuneTimer1ReloadValue_ = 0;
  ProtocolMode preferredProtocol_ = defaultPreferredProtocol();
  ProtocolMode lastProtocol_ = ProtocolMode::None;
};

Reader reader1(1, "PN5180-1", 2, 3, 4, 5, kEnableReader1);
Reader reader2(2, "PN5180-2", 6, 7, 8, 9, kEnableReader2);
Reader* readers[] = {&reader1, &reader2};

Reader* getReaderById(int id);
void serviceHeartbeat(unsigned long now);

StatusJobState statusJobState = StatusJobState::Idle;
int statusJobReaderId = 0;
uint8_t statusJobNextReaderIndex = 0;
unsigned long statusJobStartedMs = 0;
unsigned long statusJobFinishedMs = 0;
bool statusJobDeferredStart = false;

void holdNonSelectedReadersInReset(const Reader* selectedReader) {
  for (Reader* reader : readers) {
    if (reader == nullptr || reader == selectedReader) {
      continue;
    }
    reader->releaseToIdleReset();
  }
}

void holdAllReadersInReset() {
  holdNonSelectedReadersInReset(nullptr);
}

bool isStatusJobReaderSelected(const Reader* reader) {
  if (reader == nullptr || !reader->isEnabled()) {
    return false;
  }
  return statusJobReaderId == 0 || reader->id() == statusJobReaderId;
}

void resetStatusJobState(StatusJobState state = StatusJobState::Idle) {
  statusJobState = state;
  statusJobReaderId = 0;
  statusJobNextReaderIndex = 0;
  statusJobStartedMs = 0;
  statusJobFinishedMs = 0;
  statusJobDeferredStart = false;
}

void cancelStatusJob() {
  resetStatusJobState();
  holdAllReadersInReset();
}

bool startStatusJob(int readerId) {
  if (readerId != 0) {
    Reader* reader = getReaderById(readerId);
    if (reader == nullptr || !reader->isEnabled()) {
      return false;
    }
  } else {
    bool anyEnabled = false;
    for (Reader* reader : readers) {
      if (reader->isEnabled()) {
        anyEnabled = true;
        break;
      }
    }
    if (!anyEnabled) {
      return false;
    }
  }

  statusJobState = StatusJobState::Pending;
  statusJobReaderId = readerId;
  statusJobNextReaderIndex = 0;
  statusJobStartedMs = millis();
  statusJobFinishedMs = 0;
  statusJobDeferredStart = true;
  holdAllReadersInReset();
  return true;
}

void serviceStatusJob() {
  if (statusJobState == StatusJobState::Idle || statusJobState == StatusJobState::Ready) {
    return;
  }

  if (statusJobDeferredStart) {
    statusJobDeferredStart = false;
    return;
  }

  if (statusJobState == StatusJobState::Pending) {
    statusJobState = StatusJobState::Running;
    statusJobNextReaderIndex = 0;
  }

  while (statusJobNextReaderIndex < (sizeof(readers) / sizeof(readers[0]))) {
    Reader* reader = readers[statusJobNextReaderIndex++];
    if (!isStatusJobReaderSelected(reader)) {
      continue;
    }

    holdNonSelectedReadersInReset(reader);
    reader->probeStatusNow();
    return;
  }

  holdAllReadersInReset();
  statusJobFinishedMs = millis();
  statusJobState = StatusJobState::Ready;
}

void waitForStatusJobCompletion() {
  while (statusJobState == StatusJobState::Pending || statusJobState == StatusJobState::Running) {
    serviceStatusJob();
    serviceHeartbeat(millis());
    delay(1);
  }
}

void printStatusJobResult(Stream& out) {
  for (Reader* reader : readers) {
    if (statusJobReaderId != 0 && reader->id() != statusJobReaderId) {
      continue;
    }
    if (!reader->isEnabled() && statusJobReaderId != 0) {
      continue;
    }
    reader->printStatus(out);
  }
}

char commandBuffer[kCommandBufferSize];
size_t commandLength = 0;
unsigned long lastCommandByteMs = 0;
bool uartPostBootResetDone = false;
char usbCommandBuffer[kCommandBufferSize];
size_t usbCommandLength = 0;
bool usbConsoleSawCarriageReturn = false;

HeartbeatMode determineHeartbeatMode(unsigned long now) {
  bool hasEnabledReader = false;
  bool anyStartupPending = false;
  bool anyOnline = false;
  bool anyTagPresent = false;

  for (const Reader* reader : readers) {
    if (!reader->isEnabled()) {
      continue;
    }

    hasEnabledReader = true;
    anyStartupPending = anyStartupPending || reader->isStartupPending(now);
    anyOnline = anyOnline || reader->isOnline();
    anyTagPresent = anyTagPresent || reader->isTagPresent();
  }

  if (!hasEnabledReader) {
    return HeartbeatMode::Error;
  }
  if (anyTagPresent) {
    return HeartbeatMode::TagPresent;
  }
  if (anyStartupPending) {
    return HeartbeatMode::BootWait;
  }
  if (anyOnline) {
    return HeartbeatMode::Idle;
  }
  return HeartbeatMode::Error;
}

void serviceHeartbeat(unsigned long now) {
  if (!kEnableHeartbeatDebug) {
    static bool ledForcedOff = false;
    if (!ledForcedOff) {
      pinMode(LED_BUILTIN, OUTPUT);
      digitalWrite(LED_BUILTIN, LOW);
      ledForcedOff = true;
    }
    return;
  }

  static bool initialized = false;
  static HeartbeatMode lastMode = HeartbeatMode::Error;
  static bool ledOn = false;

  if (!initialized) {
    pinMode(LED_BUILTIN, OUTPUT);
    digitalWrite(LED_BUILTIN, LOW);
    initialized = true;
  }

  const HeartbeatMode mode = determineHeartbeatMode(now);
  if (mode != lastMode) {
    lastMode = mode;
  }

  bool nextLedOn = false;
  switch (mode) {
    case HeartbeatMode::BootWait:
      nextLedOn = ((now / kHeartbeatBootWaitBlinkMs) % 2) == 0;
      break;
    case HeartbeatMode::Error:
      nextLedOn = ((now / kHeartbeatErrorBlinkMs) % 2) == 0;
      break;
    case HeartbeatMode::Idle:
      nextLedOn = (now % kHeartbeatIdlePulsePeriodMs) < kHeartbeatIdlePulseOnMs;
      break;
    case HeartbeatMode::TagPresent:
      nextLedOn = true;
      break;
  }

  if (nextLedOn != ledOn) {
    ledOn = nextLedOn;
    digitalWrite(LED_BUILTIN, ledOn ? HIGH : LOW);
  }
}

void printUsbBanner() {
  Serial.println();
  Serial.println(F("PN5180 Gateway auf Raspberry Pi Pico"));
  Serial.print(F("UART zum RP5: TX=GP"));
  Serial.print(kUartTxPin);
  Serial.print(F(", RX=GP"));
  Serial.println(kUartRxPin);
  Serial.print(F("SPI0: MISO=GP"));
  Serial.print(kSpiMisoPin);
  Serial.print(F(", MOSI=GP"));
  Serial.print(kSpiMosiPin);
  Serial.print(F(", SCK=GP"));
  Serial.println(kSpiSckPin);
  Serial.print(F("Reader mode: "));
  Serial.println(F("Reader 1, ISO14443A only"));

  for (const Reader* reader : readers) {
    reader->printStartupInfo();
  }

  Serial.println(F("[USB] Return druecken fuer aktuellen Tag-Status"));
  Serial.println(F("[USB] Befehle: HELP, STATUS, STATUS_START, STATUS_FETCH, TYPEA_DIAG, SCAN, PROFILESCAN"));
}

void printUsbHelp() {
  Serial.println(F("[USB] Befehle:"));
  Serial.println(F("[USB]   Return                aktueller Status"));
  Serial.println(F("[USB]   STATUS                aktueller Status"));
  Serial.println(F("[USB]   STATUS_START          Statusjob fuer alle Reader anstossen"));
  Serial.println(F("[USB]   STATUS_START <id>     Statusjob fuer einen Reader anstossen"));
  Serial.println(F("[USB]   STATUS_FETCH          Ergebnis des letzten Statusjobs abholen"));
  Serial.println(F("[USB]   TYPEA_DIAG            Low-Level-Diagnose fuer ISO14443A"));
  Serial.println(F("[USB]   TYPEA_TUNE            Type-A-RX-Register anzeigen"));
  Serial.println(F("[USB]   TYPEA_TUNE <id>       Type-A-RX-Register fuer Reader"));
  Serial.println(F("[USB]   TYPEA_TUNE RESET      Type-A-RX-Overrides aller Reader loeschen"));
  Serial.println(F("[USB]   TYPEA_TUNE <id> RESET Overrides fuer Reader loeschen"));
  Serial.println(F("[USB]   TYPEA_TUNE <id> RXWAIT <wert>"));
  Serial.println(F("[USB]   TYPEA_TUNE <id> TIMER1CFG <wert>"));
  Serial.println(F("[USB]   TYPEA_TUNE <id> TIMER1RELOAD <wert>"));
  Serial.println(F("[USB]   TYPEA_SWEEP          RXWAIT-Sweep fuer alle aktiven Reader"));
  Serial.println(F("[USB]   TYPEA_SWEEP <id>     RXWAIT-Sweep fuer Reader"));
  Serial.println(F("[USB]   TYPEA_SWEEP <id> <r> RXWAIT-Sweep mit 1..32 Runden je Wert"));
  Serial.println(F("[USB]   GPO1                 GPO1-Zustand aller Reader"));
  Serial.println(F("[USB]   GPO1 <id>            GPO1-Zustand fuer Reader"));
  Serial.println(F("[USB]   GPO1 <id> <0|1>      GPO1 explizit auf Low oder High setzen"));
  Serial.println(F("[USB]   RST                  RST-Zustand aller Reader"));
  Serial.println(F("[USB]   RST <id>             RST-Zustand fuer Reader"));
  Serial.println(F("[USB]   RST <id> <0|1>       RST-Leitung manuell auf Low oder High setzen"));
  Serial.println(F("[USB]   RST <id> AUTO        RST-Leitung wieder der Firmware uebergeben"));
  Serial.println(F("[USB]   HELP                  diese Hilfe"));
  Serial.println(F("[USB]   SCAN                  Signal-Scan fuer alle aktiven Reader"));
  Serial.println(F("[USB]   SCAN <id>             Signal-Scan fuer Reader <id>"));
  Serial.println(F("[USB]   SCAN <id> <runden>    Signal-Scan mit 1..32 Wiederholungen"));
  Serial.println(F("[USB]   PROFILESCAN          RF-Profil-Scan fuer alle aktiven Reader"));
  Serial.println(F("[USB]   PROFILESCAN <id>     RF-Profil-Scan fuer Reader <id>"));
  Serial.println(F("[USB]   PROFILESCAN <id> <r> RF-Profil-Scan mit 1..16 Wiederholungen"));
}

void printHelp() {
  rp5Serial.println(F("OK commands=PING,STATUS,STATUS 1,STATUS 2,STATUS_START,STATUS_START 1,STATUS_FETCH,TYPEA_DIAG,TYPEA_TUNE,TYPEA_TUNE 1 RXWAIT 0x00000878,TYPEA_SWEEP,TYPEA_SWEEP 1,TYPEA_SWEEP 1 10,GPO1,GPO1 1,GPO1 1 0,GPO1 1 1,RST,RST 1,RST 1 0,RST 1 1,RST 1 AUTO,REINIT,REINIT 1,REINIT 2,DIAG,HELP"));
  rp5Serial.flush();
}

void purgeUartRxBuffer() {
  while (rp5Serial.available() > 0) {
    static_cast<void>(rp5Serial.read());
  }
}

void restartGatewayUart() {
  rp5Serial.end();
  commandLength = 0;
  lastCommandByteMs = 0;
  rp5Serial.begin(kUartBaudRate);
  purgeUartRxBuffer();
  Serial.println(F("[UART] Serial1 nach Boot neu initialisiert"));
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

bool parseUnsignedInteger(const String& text, int* value) {
  if (value == nullptr) {
    return false;
  }

  const String trimmed = String(text);
  if (trimmed.length() == 0) {
    return false;
  }

  for (size_t i = 0; i < trimmed.length(); ++i) {
    if (!isDigit(trimmed.charAt(i))) {
      return false;
    }
  }

  *value = trimmed.toInt();
  return true;
}

uint8_t clampSignalScanRounds(int value) {
  if (value < 1) {
    return kDefaultSignalScanRounds;
  }
  if (value > kMaxSignalScanRounds) {
    return kMaxSignalScanRounds;
  }
  return static_cast<uint8_t>(value);
}

uint8_t clampProfileScanRounds(int value) {
  if (value < 1) {
    return kDefaultProfileScanRounds;
  }
  if (value > kMaxProfileScanRounds) {
    return kMaxProfileScanRounds;
  }
  return static_cast<uint8_t>(value);
}

void printStatusHeader() {
  rp5Serial.print(F("OK uptime_ms="));
  rp5Serial.println(millis());
}

void handleStatusCommand(const String& command) {
  cancelStatusJob();
  printStatusHeader();

  if (command == F("STATUS")) {
    for (Reader* reader : readers) {
      holdNonSelectedReadersInReset(reader);
      reader->probeStatusNow();
      reader->printStatus(rp5Serial);
    }
    holdAllReadersInReset();
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

  holdNonSelectedReadersInReset(reader);
  reader->probeStatusNow();
  reader->printStatus(rp5Serial);
  holdAllReadersInReset();
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void handleStatusStartCommand(const String& command) {
  String rest = command.substring(String(F("STATUS_START")).length());
  rest.trim();

  int readerId = 0;
  if (rest.length() > 0) {
    if (!parseUnsignedInteger(rest, &readerId)) {
      rp5Serial.println(F("ERR status_start_invalid_reader"));
      rp5Serial.flush();
      return;
    }
    Reader* reader = getReaderById(readerId);
    if (reader == nullptr || !reader->isEnabled()) {
      rp5Serial.println(F("ERR unknown_reader"));
      rp5Serial.flush();
      return;
    }
  }

  cancelStatusJob();
  if (!startStatusJob(readerId)) {
    rp5Serial.println(F("ERR status_start_failed"));
    rp5Serial.flush();
    return;
  }

  rp5Serial.print(F("OK status_start="));
  rp5Serial.print(readerId == 0 ? F("all") : String(readerId));
  rp5Serial.print(F(" uptime_ms="));
  rp5Serial.println(millis());
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void handleStatusFetchCommand() {
  if (statusJobState == StatusJobState::Idle) {
    rp5Serial.println(F("ERR no_status_job"));
    rp5Serial.flush();
    return;
  }

  waitForStatusJobCompletion();
  printStatusHeader();
  printStatusJobResult(rp5Serial);
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void handleReinitCommand(const String& command) {
  cancelStatusJob();
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
  cancelStatusJob();
  printStatusHeader();
  for (Reader* reader : readers) {
    holdNonSelectedReadersInReset(reader);
    reader->printDiag(rp5Serial);
  }
  holdAllReadersInReset();
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void handleTypeADiagCommand() {
  cancelStatusJob();
  printStatusHeader();
  for (Reader* reader : readers) {
    holdNonSelectedReadersInReset(reader);
    reader->runTypeADiag(rp5Serial);
  }
  holdAllReadersInReset();
  rp5Serial.println(F("END"));
  rp5Serial.flush();
}

void printTypeATuneForAll(Stream& out) {
  for (Reader* reader : readers) {
    holdNonSelectedReadersInReset(reader);
    reader->printTypeATune(out);
  }
  holdAllReadersInReset();
}

bool handleTypeATuneCommand(Stream& out, const String& command, bool withHeaderAndEnd) {
  cancelStatusJob();
  auto finish = [&]() {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("END"));
      rp5Serial.flush();
    }
  };

  if (withHeaderAndEnd) {
    printStatusHeader();
  }

  String rest = command.substring(String(F("TYPEA_TUNE")).length());
  rest.trim();
  if (rest.length() == 0) {
    printTypeATuneForAll(out);
    finish();
    return true;
  }

  if (rest == F("RESET")) {
    for (Reader* reader : readers) {
      reader->resetTypeATune();
    }
    printTypeATuneForAll(out);
    finish();
    return true;
  }

  const int firstSpace = rest.indexOf(' ');
  const String firstToken = firstSpace < 0 ? rest : rest.substring(0, firstSpace);
  int readerId = 0;
  if (!parseUnsignedInteger(firstToken, &readerId)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR typea_tune_invalid_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] TYPEA_TUNE: ungueltige Reader-ID."));
    }
    return false;
  }

  Reader* reader = getReaderById(readerId);
  if (reader == nullptr) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR unknown_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] TYPEA_TUNE: unbekannte Reader-ID."));
    }
    return false;
  }

  if (firstSpace < 0) {
    holdNonSelectedReadersInReset(reader);
    reader->printTypeATune(out);
    holdAllReadersInReset();
    finish();
    return true;
  }

  String tail = rest.substring(firstSpace + 1);
  tail.trim();
  const int secondSpace = tail.indexOf(' ');
  const String action = secondSpace < 0 ? tail : tail.substring(0, secondSpace);

  if (action == F("RESET")) {
    reader->resetTypeATune();
    holdNonSelectedReadersInReset(reader);
    reader->printTypeATune(out);
    holdAllReadersInReset();
    finish();
    return true;
  }

  if (secondSpace < 0) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR typea_tune_missing_value"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] TYPEA_TUNE: Wert fehlt."));
    }
    return false;
  }

  String valueText = tail.substring(secondSpace + 1);
  valueText.trim();
  uint32_t value = 0;
  if (!parseUint32Value(valueText, &value)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR typea_tune_invalid_value"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] TYPEA_TUNE: ungueltiger Wert."));
    }
    return false;
  }

  String errorMessage;
  holdNonSelectedReadersInReset(reader);
  if (!reader->configureTypeATuneRegister(action, value, &errorMessage)) {
    if (withHeaderAndEnd) {
      rp5Serial.print(F("ERR typea_tune_"));
      rp5Serial.println(errorMessage);
      rp5Serial.flush();
    } else {
      out.print(F("[USB] TYPEA_TUNE Fehler: "));
      out.println(errorMessage);
    }
    return false;
  }

  reader->printTypeATune(out);
  holdAllReadersInReset();
  finish();
  return true;
}

bool handleTypeASweepCommand(Stream& out, const String& command, bool withHeaderAndEnd) {
  cancelStatusJob();
  auto finish = [&]() {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("END"));
      rp5Serial.flush();
    }
  };

  if (withHeaderAndEnd) {
    printStatusHeader();
  }

  String rest = command.substring(String(F("TYPEA_SWEEP")).length());
  rest.trim();

  int readerId = 0;
  uint8_t rounds = kDefaultTypeASweepRounds;

  if (rest.length() == 0 || rest == F("ALL")) {
    bool anyEnabled = false;
    for (Reader* reader : readers) {
      if (!reader->isEnabled()) {
        continue;
      }
      anyEnabled = true;
      holdNonSelectedReadersInReset(reader);
      reader->runTypeASweep(out, rounds);
    }
    holdAllReadersInReset();
    if (!anyEnabled) {
      if (withHeaderAndEnd) {
        rp5Serial.println(F("ERR no_active_reader"));
        rp5Serial.flush();
      } else {
        out.println(F("[USB] TYPEA_SWEEP: kein aktiver Reader."));
      }
      return false;
    }
    finish();
    return true;
  }

  const int firstSpace = rest.indexOf(' ');
  const String firstToken = firstSpace < 0 ? rest : rest.substring(0, firstSpace);
  if (!parseUnsignedInteger(firstToken, &readerId)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR typea_sweep_invalid_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] TYPEA_SWEEP: ungueltige Reader-ID."));
    }
    return false;
  }

  Reader* reader = getReaderById(readerId);
  if (reader == nullptr) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR unknown_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] TYPEA_SWEEP: unbekannte Reader-ID."));
    }
    return false;
  }

  if (firstSpace >= 0) {
    int requestedRounds = 0;
    const String roundsText = rest.substring(firstSpace + 1);
    if (!parseUnsignedInteger(roundsText, &requestedRounds)) {
      if (withHeaderAndEnd) {
        rp5Serial.println(F("ERR typea_sweep_invalid_rounds"));
        rp5Serial.flush();
      } else {
        out.println(F("[USB] TYPEA_SWEEP: ungueltige Rundenzahl."));
      }
      return false;
    }
    rounds = requestedRounds < 1 ? kDefaultTypeASweepRounds
                                 : (requestedRounds > kMaxTypeASweepRounds ? kMaxTypeASweepRounds
                                                                           : static_cast<uint8_t>(requestedRounds));
  }

  holdNonSelectedReadersInReset(reader);
  reader->runTypeASweep(out, rounds);
  holdAllReadersInReset();
  finish();
  return true;
}

bool handleGpo1Command(Stream& out, const String& command, bool withHeaderAndEnd) {
  cancelStatusJob();
  auto finish = [&]() {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("END"));
      rp5Serial.flush();
    }
  };

  if (withHeaderAndEnd) {
    printStatusHeader();
  }

  String rest = command.substring(String(F("GPO1")).length());
  rest.trim();

  if (rest.length() == 0) {
    for (Reader* reader : readers) {
      holdNonSelectedReadersInReset(reader);
      reader->printGpo1State(out);
    }
    holdAllReadersInReset();
    finish();
    return true;
  }

  const int firstSpace = rest.indexOf(' ');
  const String firstToken = firstSpace < 0 ? rest : rest.substring(0, firstSpace);
  int readerId = 0;
  if (!parseUnsignedInteger(firstToken, &readerId)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR gpo1_invalid_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] GPO1: ungueltige Reader-ID."));
    }
    return false;
  }

  Reader* reader = getReaderById(readerId);
  if (reader == nullptr) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR unknown_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] GPO1: unbekannte Reader-ID."));
    }
    return false;
  }

  if (firstSpace < 0) {
    holdNonSelectedReadersInReset(reader);
    reader->printGpo1State(out);
    holdAllReadersInReset();
    finish();
    return true;
  }

  int level = 0;
  const String levelText = rest.substring(firstSpace + 1);
  if (!parseUnsignedInteger(levelText, &level) || (level != 0 && level != 1)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR gpo1_invalid_level"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] GPO1: ungueltiger Pegel, erlaubt ist nur 0 oder 1."));
    }
    return false;
  }

  String errorMessage;
  holdNonSelectedReadersInReset(reader);
  if (!reader->configureGpo1Level(static_cast<uint8_t>(level), &errorMessage)) {
    if (withHeaderAndEnd) {
      rp5Serial.print(F("ERR gpo1_"));
      rp5Serial.println(errorMessage);
      rp5Serial.flush();
    } else {
      out.print(F("[USB] GPO1 Fehler: "));
      out.println(errorMessage);
    }
    return false;
  }

  holdNonSelectedReadersInReset(reader);
  reader->printGpo1State(out);
  holdAllReadersInReset();
  finish();
  return true;
}

bool handleRstCommand(Stream& out, const String& command, bool withHeaderAndEnd) {
  cancelStatusJob();
  auto finish = [&]() {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("END"));
      rp5Serial.flush();
    }
  };

  if (withHeaderAndEnd) {
    printStatusHeader();
  }

  String rest = command.substring(String(F("RST")).length());
  rest.trim();

  if (rest.length() == 0) {
    for (Reader* reader : readers) {
      reader->printResetState(out);
    }
    finish();
    return true;
  }

  const int firstSpace = rest.indexOf(' ');
  const String firstToken = firstSpace < 0 ? rest : rest.substring(0, firstSpace);
  int readerId = 0;
  if (!parseUnsignedInteger(firstToken, &readerId)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR rst_invalid_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] RST: ungueltige Reader-ID."));
    }
    return false;
  }

  Reader* reader = getReaderById(readerId);
  if (reader == nullptr) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR unknown_reader"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] RST: unbekannte Reader-ID."));
    }
    return false;
  }

  if (firstSpace < 0) {
    reader->printResetState(out);
    finish();
    return true;
  }

  String modeText = rest.substring(firstSpace + 1);
  modeText.trim();

  if (modeText == F("AUTO")) {
    reader->setResetOverrideAuto();
    reader->printResetState(out);
    holdAllReadersInReset();
    finish();
    return true;
  }

  int level = 0;
  if (!parseUnsignedInteger(modeText, &level) || (level != 0 && level != 1)) {
    if (withHeaderAndEnd) {
      rp5Serial.println(F("ERR rst_invalid_level"));
      rp5Serial.flush();
    } else {
      out.println(F("[USB] RST: ungueltiger Wert, erlaubt sind AUTO, 0 oder 1."));
    }
    return false;
  }

  if (level != 0) {
    holdNonSelectedReadersInReset(reader);
  }
  reader->setResetOverrideLevel(static_cast<uint8_t>(level));
  reader->printResetState(out);
  finish();
  return true;
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

  if (command.startsWith(F("STATUS_START"))) {
    handleStatusStartCommand(command);
    return;
  }

  if (command == F("STATUS_FETCH")) {
    handleStatusFetchCommand();
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

  if (command == F("TYPEA_DIAG")) {
    handleTypeADiagCommand();
    return;
  }

  if (command.startsWith(F("TYPEA_TUNE"))) {
    static_cast<void>(handleTypeATuneCommand(rp5Serial, command, true));
    return;
  }

  if (command.startsWith(F("TYPEA_SWEEP"))) {
    static_cast<void>(handleTypeASweepCommand(rp5Serial, command, true));
    return;
  }

  if (command.startsWith(F("GPO1"))) {
    static_cast<void>(handleGpo1Command(rp5Serial, command, true));
    return;
  }

  if (command.startsWith(F("RST"))) {
    static_cast<void>(handleRstCommand(rp5Serial, command, true));
    return;
  }

  rp5Serial.print(F("ERR unknown_command="));
  rp5Serial.println(command);
  rp5Serial.flush();
}

void serviceUart() {
  while (rp5Serial.available() > 0) {
    const unsigned long now = millis();
    const char ch = static_cast<char>(rp5Serial.read());

    if (commandLength > 0 && lastCommandByteMs > 0 && now - lastCommandByteMs > kCommandInterByteTimeoutMs) {
      commandLength = 0;
    }
    lastCommandByteMs = now;

    if (ch == '\r') {
      continue;
    }

    if (ch == '\n') {
      commandBuffer[commandLength] = '\0';
      processCommand(commandBuffer);
      commandLength = 0;
      continue;
    }

    if (ch < 32 || ch > 126) {
      commandLength = 0;
      continue;
    }

    if (commandLength == 0 && !(ch >= 'A' && ch <= 'Z') && !(ch >= 'a' && ch <= 'z')) {
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

void printUsbStatusOnDemand() {
  cancelStatusJob();
  Serial.print(F("[USB] Statusabfrage bei uptime_ms="));
  Serial.println(millis());
  for (Reader* reader : readers) {
    holdNonSelectedReadersInReset(reader);
    reader->probeStatusNow();
    reader->printUsbStatus(Serial);
  }
  holdAllReadersInReset();
}

void runUsbSignalScanForAll(uint8_t rounds) {
  cancelStatusJob();
  bool anyEnabled = false;
  for (Reader* reader : readers) {
    if (!reader->isEnabled()) {
      continue;
    }
    anyEnabled = true;
    holdNonSelectedReadersInReset(reader);
    reader->runSignalScan(Serial, rounds);
  }
  holdAllReadersInReset();
  if (!anyEnabled) {
    Serial.println(F("[USB] Kein aktiver Reader verfuegbar."));
  }
}

void runUsbProfileScanForAll(uint8_t rounds) {
  cancelStatusJob();
  bool anyEnabled = false;
  for (Reader* reader : readers) {
    if (!reader->isEnabled()) {
      continue;
    }
    anyEnabled = true;
    holdNonSelectedReadersInReset(reader);
    reader->runProfileScan(Serial, rounds);
  }
  holdAllReadersInReset();
  if (!anyEnabled) {
    Serial.println(F("[USB] Kein aktiver Reader verfuegbar."));
  }
}

void processUsbCommand(const char* rawCommand) {
  String command(rawCommand);
  command.trim();

  if (command.length() == 0) {
    printUsbStatusOnDemand();
    return;
  }

  String upper(command);
  upper.toUpperCase();

  if (upper == F("HELP") || upper == F("?")) {
    printUsbHelp();
    return;
  }

  if (upper == F("STATUS")) {
    printUsbStatusOnDemand();
    return;
  }

  if (upper.startsWith(F("STATUS_START"))) {
    String rest = upper.substring(String(F("STATUS_START")).length());
    rest.trim();
    int readerId = 0;
    if (rest.length() > 0) {
      if (!parseUnsignedInteger(rest, &readerId)) {
        Serial.println(F("[USB] STATUS_START: ungueltige Reader-ID."));
        return;
      }
      Reader* reader = getReaderById(readerId);
      if (reader == nullptr || !reader->isEnabled()) {
        Serial.println(F("[USB] STATUS_START: unbekannte Reader-ID."));
        return;
      }
    }
    cancelStatusJob();
    if (!startStatusJob(readerId)) {
      Serial.println(F("[USB] STATUS_START: Start fehlgeschlagen."));
      return;
    }
    Serial.print(F("[USB] STATUS_START: gestartet fuer "));
    Serial.println(readerId == 0 ? F("alle Reader") : String(readerId));
    return;
  }

  if (upper == F("STATUS_FETCH")) {
    if (statusJobState == StatusJobState::Idle) {
      Serial.println(F("[USB] STATUS_FETCH: kein Statusjob aktiv."));
      return;
    }
    waitForStatusJobCompletion();
    Serial.print(F("[USB] STATUS_FETCH bei uptime_ms="));
    Serial.println(millis());
    printStatusJobResult(Serial);
    return;
  }

  if (upper == F("TYPEA_DIAG")) {
    cancelStatusJob();
    for (Reader* reader : readers) {
      holdNonSelectedReadersInReset(reader);
      reader->runTypeADiag(Serial);
    }
    holdAllReadersInReset();
    return;
  }

  if (upper.startsWith(F("TYPEA_TUNE"))) {
    static_cast<void>(handleTypeATuneCommand(Serial, upper, false));
    return;
  }

  if (upper.startsWith(F("TYPEA_SWEEP"))) {
    static_cast<void>(handleTypeASweepCommand(Serial, upper, false));
    return;
  }

  if (upper.startsWith(F("GPO1"))) {
    static_cast<void>(handleGpo1Command(Serial, upper, false));
    return;
  }

  if (upper.startsWith(F("RST"))) {
    static_cast<void>(handleRstCommand(Serial, upper, false));
    return;
  }

  if (upper == F("SCAN")) {
    runUsbSignalScanForAll(kDefaultSignalScanRounds);
    return;
  }

  if (upper == F("PROFILESCAN")) {
    runUsbProfileScanForAll(kDefaultProfileScanRounds);
    return;
  }

  const bool isProfileScan = upper.startsWith(F("PROFILESCAN"));
  const bool isSignalScan = upper.startsWith(F("SCAN"));
  if (!isProfileScan && !isSignalScan) {
    Serial.print(F("[USB] Unbekannter Befehl: "));
    Serial.println(command);
    printUsbHelp();
    return;
  }

  String rest = upper.substring(isProfileScan ? 11 : 4);
  rest.trim();
  if (rest.length() == 0 || rest == F("ALL")) {
    if (isProfileScan) {
      runUsbProfileScanForAll(kDefaultProfileScanRounds);
    } else {
      runUsbSignalScanForAll(kDefaultSignalScanRounds);
    }
    return;
  }

  const int firstSpace = rest.indexOf(' ');
  const String firstToken = firstSpace < 0 ? rest : rest.substring(0, firstSpace);
  int readerId = 0;
  if (!parseUnsignedInteger(firstToken, &readerId)) {
    Serial.print(F("[USB] Ungueltiger Befehl: "));
    Serial.println(command);
    printUsbHelp();
    return;
  }

  Reader* targetReader = getReaderById(readerId);
  if (targetReader == nullptr) {
    Serial.print(F("[USB] Unbekannte Reader-ID: "));
    Serial.println(readerId);
    return;
  }

  uint8_t rounds = isProfileScan ? kDefaultProfileScanRounds : kDefaultSignalScanRounds;
  if (firstSpace >= 0) {
    int requestedRounds = 0;
    const String roundsText = rest.substring(firstSpace + 1);
    if (!parseUnsignedInteger(roundsText, &requestedRounds)) {
      Serial.print(F("[USB] Ungueltige Rundenzahl: "));
      Serial.println(roundsText);
      return;
    }
    rounds = isProfileScan ? clampProfileScanRounds(requestedRounds) : clampSignalScanRounds(requestedRounds);
  }

  if (isProfileScan) {
    cancelStatusJob();
    holdNonSelectedReadersInReset(targetReader);
    targetReader->runProfileScan(Serial, rounds);
  } else {
    cancelStatusJob();
    holdNonSelectedReadersInReset(targetReader);
    targetReader->runSignalScan(Serial, rounds);
  }
  holdAllReadersInReset();
}

void serviceUsbConsole() {
  while (Serial.available() > 0) {
    const char ch = static_cast<char>(Serial.read());

    if (ch == '\r') {
      usbCommandBuffer[usbCommandLength] = '\0';
      processUsbCommand(usbCommandBuffer);
      usbCommandLength = 0;
      usbConsoleSawCarriageReturn = true;
      continue;
    }

    if (ch == '\n') {
      if (!usbConsoleSawCarriageReturn) {
        usbCommandBuffer[usbCommandLength] = '\0';
        processUsbCommand(usbCommandBuffer);
        usbCommandLength = 0;
      }
      usbConsoleSawCarriageReturn = false;
      continue;
    }

    if (ch < 32 || ch > 126) {
      usbCommandLength = 0;
      usbConsoleSawCarriageReturn = false;
      continue;
    }

    if (usbCommandLength + 1 < kCommandBufferSize) {
      usbCommandBuffer[usbCommandLength++] = ch;
    } else {
      usbCommandLength = 0;
      Serial.println(F("[USB] Befehl zu lang."));
    }

    usbConsoleSawCarriageReturn = false;
  }
}

}  // namespace

void setup() {
  Serial.begin(kDebugBaudRate);
  rp5Serial.begin(kUartBaudRate);
  serviceHeartbeat(millis());

  reader1.begin();
  reader2.begin();

  const unsigned long startupDelayStartedMs = millis();
  while (millis() - startupDelayStartedMs < kUsbConsoleStartupDelayMs) {
    serviceUart();
    serviceUsbConsole();
    serviceHeartbeat(millis());
    delay(1);
  }

  printUsbBanner();
}

void loop() {
  const unsigned long now = millis();

  if (!uartPostBootResetDone && now >= kUartPostBootResetMs) {
    restartGatewayUart();
    uartPostBootResetDone = true;
  }

  serviceUart();
  serviceUsbConsole();
  serviceStatusJob();
  serviceHeartbeat(now);
  for (Reader* reader : readers) {
    reader->service(now);
  }
}

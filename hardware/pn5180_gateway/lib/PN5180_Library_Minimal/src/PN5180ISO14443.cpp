// NAME: PN5180ISO14443.h
//
// DESC: ISO14443 protocol on NXP Semiconductors PN5180 module for Arduino.
//
// Copyright (c) 2019 by Dirk Carstensen. All rights reserved.
//
// This file is part of the PN5180 library for the Arduino environment.
//
// This library is free software; you can redistribute it and/or
// modify it under the terms of the GNU Lesser General Public
// License as published by the Free Software Foundation; either
// version 2.1 of the License, or (at your option) any later version.
//
// This library is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY; without even the implied warranty of
// MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
// Lesser General Public License for more details.
//
// #define DEBUG 1

#include <Arduino.h>
#include "PN5180ISO14443.h"
#include <PN5180.h>
#include "Debug.h"

namespace {

constexpr bool kVerboseIso14443RuntimeDebug = false;
constexpr unsigned long kTypeAResponseTimeoutMs = 20;
constexpr unsigned long kTypeAFieldResetDelayMs = 8;
constexpr unsigned long kTypeAIdleTimeoutMs = 10;

void logIso14443(const __FlashStringHelper* message) {
  if (!kVerboseIso14443RuntimeDebug) {
    return;
  }
  Serial.print(F("[PN5180/ISO14443] "));
  Serial.println(message);
}

void logIso14443Value(const __FlashStringHelper* label, uint32_t value) {
  if (!kVerboseIso14443RuntimeDebug) {
    return;
  }
  Serial.print(F("[PN5180/ISO14443] "));
  Serial.print(label);
  Serial.println(value);
}

void logIso14443HexBytes(const __FlashStringHelper* label, const uint8_t* data, uint8_t length) {
  if (!kVerboseIso14443RuntimeDebug) {
    return;
  }
  Serial.print(F("[PN5180/ISO14443] "));
  Serial.print(label);
  for (uint8_t i = 0; i < length; ++i) {
    if (i > 0) {
      Serial.print(' ');
    }
    if (data[i] < 0x10) {
      Serial.print('0');
    }
    Serial.print(data[i], HEX);
  }
  Serial.println();
}

void clearTypeADiagResult(PN5180TypeADiagResult* result, uint8_t kind) {
  if (result == nullptr) {
    return;
  }

  *result = PN5180TypeADiagResult{};
  result->kind = kind;
}

void captureTypeADiagStatus(PN5180ISO14443* reader, PN5180TypeADiagResult* result) {
  if (reader == nullptr || result == nullptr) {
    return;
  }

  result->irqStatusValid = reader->readRegister(IRQ_STATUS, &result->irqStatus);
  result->rfStatusValid = reader->readRegister(RF_STATUS, &result->rfStatus);
  result->rxStatusValid = reader->readRegister(RX_STATUS, &result->rxStatus);
  if (result->rxStatusValid) {
    result->rxLength = static_cast<uint16_t>(result->rxStatus & 0x000001FF);
  }
}

bool waitForTypeAResponse(PN5180ISO14443* reader, PN5180TypeADiagResult* result) {
  if (reader == nullptr) {
    return false;
  }

  const unsigned long start = millis();
  while (millis() - start < kTypeAResponseTimeoutMs) {
    uint32_t irqStatus = 0;
    uint32_t rxStatus = 0;
    const bool irqOk = reader->readRegister(IRQ_STATUS, &irqStatus);
    const bool rxOk = reader->readRegister(RX_STATUS, &rxStatus);
    const uint16_t rxLen = rxOk ? static_cast<uint16_t>(rxStatus & 0x000001FF) : 0;

    if (irqOk && ((irqStatus & RX_IRQ_STAT) != 0)) {
      if (result != nullptr) {
        result->irqStatusValid = true;
        result->irqStatus = irqStatus;
        result->rxStatusValid = rxOk;
        result->rxStatus = rxStatus;
        result->rxLength = rxLen;
      }
      return true;
    }

    delay(1);
  }

  captureTypeADiagStatus(reader, result);
  return false;
}

bool waitForTypeAFrame(PN5180ISO14443* reader, PN5180TypeADiagResult* result, uint16_t expectedLen) {
  if (!waitForTypeAResponse(reader, result)) {
    return false;
  }

  if (result != nullptr && result->rxStatusValid && result->rxLength != expectedLen) {
    return false;
  }

  return true;
}

bool forceTypeAIdle(PN5180ISO14443* reader) {
  if (reader == nullptr) {
    return false;
  }

  if (!reader->writeRegisterWithAndMask(SYSTEM_CONFIG, 0xFFFFFFF8)) {
    return false;
  }

  const unsigned long start = millis();
  while (millis() - start < kTypeAIdleTimeoutMs) {
    if (reader->getTransceiveState() == PN5180_TS_Idle) {
      static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
      delay(1);
      return true;
    }
    delay(1);
  }

  static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
  return false;
}

bool recycleTypeAField(PN5180ISO14443* reader) {
  if (reader == nullptr) {
    return false;
  }

  if (!reader->setRF_off()) {
    return false;
  }
  delay(kTypeAFieldResetDelayMs);
  if (!reader->setRF_on()) {
    return false;
  }
  delay(kTypeAFieldResetDelayMs);
  return true;
}

bool isAllFF(const uint8_t* data, uint8_t length) {
  if (data == nullptr) {
    return false;
  }
  for (uint8_t i = 0; i < length; ++i) {
    if (data[i] != 0xFF) {
      return false;
    }
  }
  return true;
}

bool isPlausibleAtqa(const uint8_t* atqa) {
  if (atqa == nullptr) {
    return false;
  }
  if ((atqa[0] == 0xFF && atqa[1] == 0xFF) || (atqa[0] == 0x00 && atqa[1] == 0x00)) {
    return false;
  }
  return atqa[1] == 0x00;
}

bool isPlausibleCl1(const uint8_t* cl1) {
  if (cl1 == nullptr || isAllFF(cl1, 5)) {
    return false;
  }
  return cl1[4] != 0xFF;
}

bool isPlausibleCl2(const uint8_t* cl2) {
  if (cl2 == nullptr || isAllFF(cl2, 5)) {
    return false;
  }
  return cl2[4] != 0xFF;
}

bool isPlausibleSak(uint8_t sak) {
  return sak == 0x00 || sak == 0x04;
}

uint8_t activateTypeAImpl(PN5180ISO14443* reader, uint8_t* buffer, uint8_t kind, PN5180TypeADiagResult* result) {
  if (reader == nullptr || buffer == nullptr) {
    return 0;
  }

  clearTypeADiagResult(result, kind);

  auto fail = [&](PN5180TypeADiagStage stage, bool refreshStatus) -> uint8_t {
    if (result != nullptr) {
      result->stage = stage;
      if (refreshStatus) {
        captureTypeADiagStatus(reader, result);
      }
    }
    static_cast<void>(forceTypeAIdle(reader));
    return 0;
  };

  uint8_t cmd[7];
  uint8_t uidLength = 0;

  if (!reader->writeRegisterWithAndMask(SYSTEM_CONFIG, 0xFFFFFFBF)) {
    return fail(PN5180_TA_STAGE_CLEAR_SYSTEM_CONFIG, true);
  }
  if (!reader->writeRegisterWithAndMask(CRC_RX_CONFIG, 0xFFFFFFFE)) {
    return fail(PN5180_TA_STAGE_CLEAR_RX_CRC, true);
  }
  if (!reader->writeRegisterWithAndMask(CRC_TX_CONFIG, 0xFFFFFFFE)) {
    return fail(PN5180_TA_STAGE_CLEAR_TX_CRC, true);
  }
  if (!forceTypeAIdle(reader)) {
    return fail(PN5180_TA_STAGE_REQA_WUPA_SEND, true);
  }

  cmd[0] = (kind == 0) ? 0x26 : 0x52;
  static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
  if (!reader->sendData(cmd, 1, 0x07)) {
    return fail(PN5180_TA_STAGE_REQA_WUPA_SEND, true);
  }

  if (!waitForTypeAFrame(reader, result, 2)) {
    return fail(PN5180_TA_STAGE_ATQA_READ, false);
  }
  if (!reader->readData(2, buffer)) {
    return fail(PN5180_TA_STAGE_ATQA_READ, true);
  }
  if (result != nullptr) {
    result->atqaReadOk = true;
    result->atqa[0] = buffer[0];
    result->atqa[1] = buffer[1];
  }
  if (!isPlausibleAtqa(buffer)) {
    return fail(PN5180_TA_STAGE_ATQA_READ, true);
  }
  if (!forceTypeAIdle(reader)) {
    return fail(PN5180_TA_STAGE_ATQA_READ, true);
  }

  cmd[0] = 0x93;
  cmd[1] = 0x20;
  static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
  if (!reader->sendData(cmd, 2, 0x00)) {
    return fail(PN5180_TA_STAGE_ANTICOLL_CL1_SEND, true);
  }

  if (!waitForTypeAFrame(reader, result, 5)) {
    return fail(PN5180_TA_STAGE_ANTICOLL_CL1_READ, false);
  }
  if (!reader->readData(5, cmd + 2)) {
    return fail(PN5180_TA_STAGE_ANTICOLL_CL1_READ, true);
  }
  if (result != nullptr) {
    result->cl1ReadOk = true;
    memcpy(result->cl1Raw, cmd + 2, 5);
  }
  if (!isPlausibleCl1(cmd + 2)) {
    return fail(PN5180_TA_STAGE_ANTICOLL_CL1_READ, true);
  }
  if (!forceTypeAIdle(reader)) {
    return fail(PN5180_TA_STAGE_ANTICOLL_CL1_READ, true);
  }

  if (!reader->writeRegisterWithOrMask(CRC_RX_CONFIG, 0x01)) {
    return fail(PN5180_TA_STAGE_ENABLE_RX_CRC, true);
  }
  if (!reader->writeRegisterWithOrMask(CRC_TX_CONFIG, 0x01)) {
    return fail(PN5180_TA_STAGE_ENABLE_TX_CRC, true);
  }
  if (!forceTypeAIdle(reader)) {
    return fail(PN5180_TA_STAGE_ENABLE_TX_CRC, true);
  }

  cmd[0] = 0x93;
  cmd[1] = 0x70;
  static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
  if (!reader->sendData(cmd, 7, 0x00)) {
    return fail(PN5180_TA_STAGE_SELECT_CL1_SEND, true);
  }

  if (!waitForTypeAFrame(reader, result, 1)) {
    return fail(PN5180_TA_STAGE_SAK_READ, false);
  }
  uint8_t sakFrame = 0;
  if (!reader->readData(1, &sakFrame)) {
    return fail(PN5180_TA_STAGE_SAK_READ, true);
  }
  buffer[2] = sakFrame;
  if (result != nullptr) {
    result->sakReadOk = true;
    result->sak = sakFrame;
  }
  if (!isPlausibleSak(sakFrame)) {
    return fail(PN5180_TA_STAGE_SAK_READ, true);
  }
  if (!forceTypeAIdle(reader)) {
    return fail(PN5180_TA_STAGE_SAK_READ, true);
  }

  if ((buffer[2] & 0x04) == 0) {
    for (int i = 0; i < 4; i++) {
      buffer[3 + i] = cmd[2 + i];
    }
    uidLength = 4;
  }
  else {
    if (result != nullptr) {
      result->cl2Used = true;
    }
    if (cmd[2] != 0x88) {
      return fail(PN5180_TA_STAGE_CASCADE_TAG_CHECK, true);
    }
    for (int i = 0; i < 3; i++) {
      buffer[3 + i] = cmd[3 + i];
    }
    if (!reader->writeRegisterWithAndMask(CRC_RX_CONFIG, 0xFFFFFFFE)) {
      return fail(PN5180_TA_STAGE_CLEAR_RX_CRC_CL2, true);
    }
    if (!reader->writeRegisterWithAndMask(CRC_TX_CONFIG, 0xFFFFFFFE)) {
      return fail(PN5180_TA_STAGE_CLEAR_TX_CRC_CL2, true);
    }
    if (!forceTypeAIdle(reader)) {
      return fail(PN5180_TA_STAGE_CLEAR_TX_CRC_CL2, true);
    }
    cmd[0] = 0x95;
    cmd[1] = 0x20;
    static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
    if (!reader->sendData(cmd, 2, 0x00)) {
      return fail(PN5180_TA_STAGE_ANTICOLL_CL2_SEND, true);
    }
    if (!waitForTypeAFrame(reader, result, 5)) {
      return fail(PN5180_TA_STAGE_ANTICOLL_CL2_READ, false);
    }
    if (!reader->readData(5, cmd + 2)) {
      return fail(PN5180_TA_STAGE_ANTICOLL_CL2_READ, true);
    }
    if (result != nullptr) {
      result->cl2ReadOk = true;
      memcpy(result->cl2Raw, cmd + 2, 5);
    }
    if (!isPlausibleCl2(cmd + 2)) {
      return fail(PN5180_TA_STAGE_ANTICOLL_CL2_READ, true);
    }
    for (int i = 0; i < 4; i++) {
      buffer[6 + i] = cmd[2 + i];
    }
    if (!forceTypeAIdle(reader)) {
      return fail(PN5180_TA_STAGE_ANTICOLL_CL2_READ, true);
    }
    if (!reader->writeRegisterWithOrMask(CRC_RX_CONFIG, 0x01)) {
      return fail(PN5180_TA_STAGE_ENABLE_RX_CRC_CL2, true);
    }
    if (!reader->writeRegisterWithOrMask(CRC_TX_CONFIG, 0x01)) {
      return fail(PN5180_TA_STAGE_ENABLE_TX_CRC_CL2, true);
    }
    if (!forceTypeAIdle(reader)) {
      return fail(PN5180_TA_STAGE_ENABLE_TX_CRC_CL2, true);
    }
    cmd[0] = 0x95;
    cmd[1] = 0x70;
    static_cast<void>(reader->clearIRQStatus(0xFFFFFFFF));
    if (!reader->sendData(cmd, 7, 0x00)) {
      return fail(PN5180_TA_STAGE_SELECT_CL2_SEND, true);
    }
    if (!waitForTypeAFrame(reader, result, 1)) {
      return fail(PN5180_TA_STAGE_SAK_CL2_READ, false);
    }
    uint8_t sak2Frame = 0;
    if (!reader->readData(1, &sak2Frame)) {
      return fail(PN5180_TA_STAGE_SAK_CL2_READ, true);
    }
    buffer[2] = sak2Frame;
    if (result != nullptr) {
      result->sak2ReadOk = true;
      result->sak2 = sak2Frame;
    }
    if (!isPlausibleSak(sak2Frame)) {
      return fail(PN5180_TA_STAGE_SAK_CL2_READ, true);
    }
    if (!forceTypeAIdle(reader)) {
      return fail(PN5180_TA_STAGE_SAK_CL2_READ, true);
    }
    uidLength = 7;
  }

  if (result != nullptr) {
    result->success = true;
    result->stage = PN5180_TA_STAGE_SUCCESS;
    result->uidLength = uidLength;
    memcpy(result->uid, buffer + 3, uidLength > 7 ? 7 : uidLength);
    captureTypeADiagStatus(reader, result);
  }
  return uidLength;
}

}  // namespace

PN5180ISO14443::PN5180ISO14443(uint8_t SSpin, uint8_t BUSYpin, uint8_t RSTpin) 
              : PN5180(SSpin, BUSYpin, RSTpin) {
}

bool PN5180ISO14443::setupRF() {
  PN5180DEBUG(F("Loading RF-Configuration...\n"));
  if (loadRFConfig(0x00, 0x80)) {  // ISO14443 parameters
    PN5180DEBUG(F("done.\n"));
  }
  else return false;

  PN5180DEBUG(F("Turning ON RF field...\n"));
  if (setRF_on()) {
    PN5180DEBUG(F("done.\n"));
  }
  else return false;

  return true;
}

uint16_t PN5180ISO14443::rxBytesReceived() {
	uint32_t rxStatus;
	uint16_t len = 0;
	readRegister(RX_STATUS, &rxStatus);
	// Lower 9 bits has length
	len = (uint16_t)(rxStatus & 0x000001ff);
	return len;
}
/*
* buffer : must be 10 byte array
* buffer[0-1] is ATQA
* buffer[2] is sak
* buffer[3..6] is 4 byte UID
* buffer[7..9] is remaining 3 bytes of UID for 7 Byte UID tags
* kind : 0  we send REQA, 1 we send WUPA
*
* return value: the uid length:
* -	zero if no tag was recognized
* -	single Size UID (4 byte)
* -	double Size UID (7 byte)
* -	triple Size UID (10 byte) - not yet supported
*/
uint8_t PN5180ISO14443::activateTypeA(uint8_t *buffer, uint8_t kind) {
  logIso14443(F("activateTypeA start"));
  return activateTypeAImpl(this, buffer, kind, nullptr);
}

uint8_t PN5180ISO14443::runTypeADiag(PN5180TypeADiagResult *result, uint8_t kind) {
  uint8_t buffer[10] = {0};
  return activateTypeAImpl(this, buffer, kind, result);
}

bool PN5180ISO14443::mifareBlockRead(uint8_t blockno, uint8_t *buffer) {
	bool success = false;
	uint16_t len;
	uint8_t cmd[2];
	// Send mifare command 30,blockno
	cmd[0] = 0x30;
	cmd[1] = blockno;
	if (!sendData(cmd, 2, 0x00))
	  return false;
	//Check if we have received any data from the tag
	delay(5);
	len = rxBytesReceived();
	if (len == 16) {
		// READ 16 bytes into  buffer
		if (readData(16, buffer))
		  success = true;
	}
	return success;
}


uint8_t PN5180ISO14443::mifareBlockWrite16(uint8_t blockno, uint8_t *buffer) {
	uint8_t cmd[2];
	// Clear RX CRC
	writeRegisterWithAndMask(CRC_RX_CONFIG, 0xFFFFFFFE);

	// Mifare write part 1
	cmd[0] = 0xA0;
	cmd[1] = blockno;
	sendData(cmd, 2, 0x00);
	readData(1, cmd);

	// Mifare write part 2
	sendData(buffer,16, 0x00);
	delay(10);

	// Read ACK/NAK
	readData(1, cmd);

	//Enable RX CRC calculation
	writeRegisterWithOrMask(CRC_RX_CONFIG, 0x1);
	return cmd[0];
}

bool PN5180ISO14443::mifareHalt() {
	uint8_t cmd[2];
	//mifare Halt
	cmd[0] = 0x50;
	cmd[1] = 0x00;
	sendData(cmd, 2, 0x00);	
	return true;
}

uint8_t PN5180ISO14443::readCardSerial(uint8_t *buffer) {
  
    uint8_t response[10];
	uint8_t uidLength;
	// Always return 10 bytes
    // Offset 0..1 is ATQA
    // Offset 2 is SAK.
    // UID 4 bytes : offset 3 to 6 is UID, offset 7 to 9 to Zero
    // UID 7 bytes : offset 3 to 9 is UID
    for (int i = 0; i < 10; i++) response[i] = 0;
    uidLength = activateTypeA(response, 0);
    if (uidLength < 4) {
      static_cast<void>(recycleTypeAField(this));
      for (int i = 0; i < 10; i++) response[i] = 0;
      uidLength = activateTypeA(response, 1);
    }
	if ((response[0] == 0xFF) && (response[1] == 0xFF))
	  return 0;
	// check for valid uid
	if ((response[3] == 0x00) && (response[4] == 0x00) && (response[5] == 0x00) && (response[6] == 0x00))
	  return 0;
	if ((response[3] == 0xFF) && (response[4] == 0xFF) && (response[5] == 0xFF) && (response[6] == 0xFF))
	  return 0;
    for (int i = 0; i < 7; i++) buffer[i] = response[i+3];
	mifareHalt();
    static_cast<void>(recycleTypeAField(this));
	return uidLength;  
}

bool PN5180ISO14443::isCardPresent() {
    uint8_t buffer[10];
	return (readCardSerial(buffer) >=4);
}

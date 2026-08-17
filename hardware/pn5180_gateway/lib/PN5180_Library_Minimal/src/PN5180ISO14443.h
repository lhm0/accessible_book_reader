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
#ifndef PN5180ISO14443_H
#define PN5180ISO14443_H

#include "PN5180.h"

enum PN5180TypeADiagStage : uint8_t {
  PN5180_TA_STAGE_NONE = 0,
  PN5180_TA_STAGE_LOAD_RF_CONFIG,
  PN5180_TA_STAGE_CLEAR_SYSTEM_CONFIG,
  PN5180_TA_STAGE_CLEAR_RX_CRC,
  PN5180_TA_STAGE_CLEAR_TX_CRC,
  PN5180_TA_STAGE_REQA_WUPA_SEND,
  PN5180_TA_STAGE_ATQA_READ,
  PN5180_TA_STAGE_ANTICOLL_CL1_SEND,
  PN5180_TA_STAGE_ANTICOLL_CL1_READ,
  PN5180_TA_STAGE_ENABLE_RX_CRC,
  PN5180_TA_STAGE_ENABLE_TX_CRC,
  PN5180_TA_STAGE_SELECT_CL1_SEND,
  PN5180_TA_STAGE_SAK_READ,
  PN5180_TA_STAGE_CASCADE_TAG_CHECK,
  PN5180_TA_STAGE_CLEAR_RX_CRC_CL2,
  PN5180_TA_STAGE_CLEAR_TX_CRC_CL2,
  PN5180_TA_STAGE_ANTICOLL_CL2_SEND,
  PN5180_TA_STAGE_ANTICOLL_CL2_READ,
  PN5180_TA_STAGE_ENABLE_RX_CRC_CL2,
  PN5180_TA_STAGE_ENABLE_TX_CRC_CL2,
  PN5180_TA_STAGE_SELECT_CL2_SEND,
  PN5180_TA_STAGE_SAK_CL2_READ,
  PN5180_TA_STAGE_SUCCESS
};

struct PN5180TypeADiagResult {
  uint8_t kind = 0;
  bool success = false;
  PN5180TypeADiagStage stage = PN5180_TA_STAGE_NONE;
  bool atqaReadOk = false;
  uint8_t atqa[2] = {0};
  bool cl1ReadOk = false;
  uint8_t cl1Raw[5] = {0};
  bool sakReadOk = false;
  uint8_t sak = 0;
  bool cl2Used = false;
  bool cl2ReadOk = false;
  uint8_t cl2Raw[5] = {0};
  bool sak2ReadOk = false;
  uint8_t sak2 = 0;
  uint8_t uid[7] = {0};
  uint8_t uidLength = 0;
  bool irqStatusValid = false;
  uint32_t irqStatus = 0;
  bool rfStatusValid = false;
  uint32_t rfStatus = 0;
  bool rxStatusValid = false;
  uint32_t rxStatus = 0;
  uint16_t rxLength = 0;
};

class PN5180ISO14443 : public PN5180 {

public:
  PN5180ISO14443(uint8_t SSpin, uint8_t BUSYpin, uint8_t RSTpin);
  
private:
  uint16_t rxBytesReceived();
public:
  // Mifare TypeA
  uint8_t activateTypeA(uint8_t *buffer, uint8_t kind);
  uint8_t runTypeADiag(PN5180TypeADiagResult *result, uint8_t kind);
  bool mifareBlockRead(uint8_t blockno,uint8_t *buffer);
  uint8_t mifareBlockWrite16(uint8_t blockno, uint8_t *buffer);
  bool mifareHalt();
  /*
   * Helper functions
   */
public:   
  bool setupRF();
  uint8_t readCardSerial(uint8_t *buffer);    
  bool isCardPresent();    
};

#endif /* PN5180ISO14443_H */

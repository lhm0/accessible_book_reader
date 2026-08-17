/**
    @modified picospuch
*/

#include "PN532/PN532_I2C/PN532_I2C.h"
#include "PN532/PN532/PN532_debug.h"
#include "Arduino.h"

#define PN532_I2C_ADDRESS (0x48 >> 1)

PN532_I2C::PN532_I2C(TwoWire& wire) {
    _wire = &wire;
    command = 0;
}

void PN532_I2C::begin() {
    _wire->begin();
}

void PN532_I2C::wakeup() {
    delay(500); // wait for all ready to manipulate pn532
}

int8_t PN532_I2C::writeCommand(const uint8_t* header, uint8_t hlen, const uint8_t* body, uint8_t blen) {
    command = header[0];
    _wire->beginTransmission(PN532_I2C_ADDRESS);

    write(PN532_PREAMBLE);
    write(PN532_STARTCODE1);
    write(PN532_STARTCODE2);

    uint8_t length = hlen + blen + 1; // length of data field: TFI + DATA
    write(length);
    write(~length + 1); // checksum of length

    write(PN532_HOSTTOPN532);
    uint8_t sum = PN532_HOSTTOPN532; // sum of TFI + DATA

    DMSG("write: ");

    for (uint8_t i = 0; i < hlen; i++) {
        if (write(header[i])) {
            sum += header[i];

            DMSG_HEX(header[i]);
        } else {
            DMSG("\nToo many data to send, I2C doesn't support such a big packet\n"); // I2C max packet: 32 bytes
            return PN532_INVALID_FRAME;
        }
    }

    for (uint8_t i = 0; i < blen; i++) {
        if (write(body[i])) {
            sum += body[i];

            DMSG_HEX(body[i]);
        } else {
            DMSG("\nToo many data to send, I2C doesn't support such a big packet\n"); // I2C max packet: 32 bytes
            return PN532_INVALID_FRAME;
        }
    }

    uint8_t checksum = ~sum + 1; // checksum of TFI + DATA
    write(checksum);
    write(PN532_POSTAMBLE);

    _wire->endTransmission();

    DMSG('\n');

    #if defined(ARDUINO_ARCH_MBED)
    return 0;
    #else
    return readAckFrame();
    #endif
}

int16_t PN532_I2C::requestChunk(uint8_t* buf, uint8_t len, uint16_t timeout) {
    #if defined(ARDUINO_ARCH_MBED)
    uint16_t time = 0;

    do {
        const uint8_t received = _wire->requestFrom(PN532_I2C_ADDRESS, len);
        if (received > 0) {
            uint8_t index = 0;
            while (_wire->available() && index < received && index < len) {
                buf[index++] = read();
            }
            return index;
        }

        delay(1);
        time++;
        if ((0 != timeout) && (time > timeout)) {
            return -1;
        }
    } while (1);
    #else
    uint16_t time = 0;

    do {
        const uint8_t received = _wire->requestFrom(PN532_I2C_ADDRESS, len);
        if (received > 0) {
            uint8_t index = 0;
            while (_wire->available() && index < received && index < len) {
                buf[index++] = read();
            }
            return index;
        }

        delay(1);
        time++;
        if ((0 != timeout) && (time > timeout)) {
            return -1;
        }
    } while (1);
    #endif
}

int16_t PN532_I2C::findStartCode(const uint8_t* buf, uint8_t len) {
    if (len < 3) {
        return -1;
    }

    for (uint8_t i = 0; i <= len - 3; ++i) {
        if (buf[i] == 0x00 && buf[i + 1] == 0x00 && buf[i + 2] == 0xFF) {
            return i;
        }
    }

    return -1;
}

bool PN532_I2C::isAckFrame(const uint8_t* buf, uint8_t len, uint8_t start) {
    if (start + 6 > len) {
        return false;
    }

    return buf[start + 0] == 0x00 &&
           buf[start + 1] == 0x00 &&
           buf[start + 2] == 0xFF &&
           buf[start + 3] == 0x00 &&
           buf[start + 4] == 0xFF &&
           buf[start + 5] == 0x00;
}

int16_t PN532_I2C::getResponseLength(uint8_t buf[], uint8_t len, uint16_t timeout) {
    const uint8_t PN532_NACK[] = {0, 0, 0xFF, 0xFF, 0, 0};
    #if defined(ARDUINO_ARCH_MBED)
    const uint8_t probeLen = 16;
    uint16_t elapsed = 0;

    while ((timeout == 0) || (elapsed <= timeout)) {
        int16_t chunkLength = requestChunk(buf, probeLen, 20);
        if (chunkLength < 0) {
            elapsed += 20;
            continue;
        }

        int16_t start = findStartCode(buf, static_cast<uint8_t>(chunkLength));
        if (start < 0 || start + 5 > chunkLength) {
            elapsed += 20;
            continue;
        }

        if (isAckFrame(buf, static_cast<uint8_t>(chunkLength), static_cast<uint8_t>(start))) {
            elapsed += 20;
            continue;
        }

        return buf[start + 3];
    }

    return -1;
    #else
    const uint8_t probeLen = len < 16 ? 16 : len;
    int16_t chunkLength = requestChunk(buf, probeLen, timeout);
    if (chunkLength < 0) {
        return -1;
    }

    int16_t start = findStartCode(buf, static_cast<uint8_t>(chunkLength));
    if (start < 0 || start + 5 > chunkLength) {
        return PN532_INVALID_FRAME;
    }

    uint8_t length = buf[start + 3];

    // request for last respond msg again
    _wire->beginTransmission(PN532_I2C_ADDRESS);
    for (uint16_t i = 0; i < sizeof(PN532_NACK); ++i) {
        write(PN532_NACK[i]);
    }
    _wire->endTransmission();

    return length;
    #endif
}

int16_t PN532_I2C::readResponse(uint8_t buf[], uint8_t len, uint16_t timeout) {
    #if defined(ARDUINO_ARCH_MBED)
    uint8_t streamBuf[96];
    uint8_t streamLen = 0;
    uint16_t elapsed = 0;

    while ((timeout == 0) || (elapsed <= timeout)) {
        uint8_t rawBuf[32];
        const uint8_t requestLen = static_cast<uint8_t>(min<uint16_t>(sizeof(rawBuf), len + 8));
        int16_t rawLength = requestChunk(rawBuf, requestLen, 20);
        if (rawLength < 0) {
            elapsed += 20;
            continue;
        }

        if (rawLength == 0) {
            delay(1);
            elapsed += 1;
            continue;
        }

        if ((rawBuf[0] & 0x01) == 0) {
            delay(2);
            elapsed += 2;
            continue;
        }

        for (int16_t i = 1; i < rawLength && streamLen < sizeof(streamBuf); ++i) {
            streamBuf[streamLen++] = rawBuf[i];
        }

        while (true) {
            int16_t start = findStartCode(streamBuf, streamLen);
            if (start < 0) {
                if (streamLen > 2) {
                    memmove(streamBuf, streamBuf + streamLen - 2, 2);
                    streamLen = 2;
                }
                break;
            }

            if (start > 0) {
                memmove(streamBuf, streamBuf + start, streamLen - start);
                streamLen -= start;
            }

            if (streamLen >= 6 && isAckFrame(streamBuf, streamLen, 0)) {
                memmove(streamBuf, streamBuf + 6, streamLen - 6);
                streamLen -= 6;
                continue;
            }

            if (streamLen < 5) {
                break;
            }

            uint8_t frameLength = streamBuf[3];
            if (0 != static_cast<uint8_t>(frameLength + streamBuf[4])) {
                memmove(streamBuf, streamBuf + 1, streamLen - 1);
                streamLen -= 1;
                continue;
            }

            const uint16_t totalFrameLength = static_cast<uint16_t>(frameLength) + 7;
            if (streamLen < totalFrameLength) {
                break;
            }

            if (PN532_PN532TOHOST != streamBuf[5] || static_cast<uint8_t>(command + 1) != streamBuf[6]) {
                memmove(streamBuf, streamBuf + 1, streamLen - 1);
                streamLen -= 1;
                continue;
            }

            if (frameLength < 2) {
                return PN532_INVALID_FRAME;
            }

            uint8_t payloadLength = frameLength - 2;
            if (payloadLength > len) {
                return PN532_NO_SPACE;
            }

            uint8_t sum = 0;
            for (uint8_t i = 0; i < frameLength; ++i) {
                sum += streamBuf[5 + i];
            }

            const uint8_t checksum = streamBuf[5 + frameLength];
            if (0 != static_cast<uint8_t>(sum + checksum)) {
                memmove(streamBuf, streamBuf + 1, streamLen - 1);
                streamLen -= 1;
                continue;
            }

            if (streamBuf[6 + frameLength] != PN532_POSTAMBLE) {
                memmove(streamBuf, streamBuf + 1, streamLen - 1);
                streamLen -= 1;
                continue;
            }

            for (uint8_t i = 0; i < payloadLength; ++i) {
                buf[i] = streamBuf[7 + i];
            }

            return payloadLength;
        }
    }

    return PN532_TIMEOUT;
    #else
    uint8_t length;

    length = getResponseLength(buf, len, timeout);
    if (length > len) {
        return PN532_NO_SPACE;
    }

    uint8_t frameBuf[96];
    #if defined(ARDUINO_ARCH_MBED)
    const uint8_t requestLen = static_cast<uint8_t>(min<uint16_t>(sizeof(frameBuf), 16 + length));
    #else
    const uint8_t requestLen = static_cast<uint8_t>(min<uint16_t>(sizeof(frameBuf), 12 + length));
    #endif
    int16_t chunkLength = requestChunk(frameBuf, requestLen, timeout);
    if (chunkLength < 0) {
        return -1;
    }

    int16_t start = findStartCode(frameBuf, static_cast<uint8_t>(chunkLength));
    if (start < 0 || start + 8 > chunkLength) {
        return PN532_INVALID_FRAME;
    }

    length = frameBuf[start + 3];

    if (start + 8 + length > chunkLength) {
        return PN532_INVALID_FRAME;
    }

    if (0 != (uint8_t)(length + frameBuf[start + 4])) {
        // checksum of length
        return PN532_INVALID_FRAME;
    }

    uint8_t cmd = command + 1; // response command
    if (PN532_PN532TOHOST != frameBuf[start + 5] || cmd != frameBuf[start + 6]) {
        return PN532_INVALID_FRAME;
    }

    length -= 2;
    if (length > len) {
        return PN532_NO_SPACE; // not enough space
    }

    DMSG("read:  ");
    DMSG_HEX(cmd);

    uint8_t sum = PN532_PN532TOHOST + cmd;
    for (uint8_t i = 0; i < length; i++) {
        buf[i] = frameBuf[start + 7 + i];
        sum += buf[i];

        DMSG_HEX(buf[i]);
    }
    DMSG('\n');

    uint8_t checksum = frameBuf[start + 7 + length];
    if (0 != (uint8_t)(sum + checksum)) {
        DMSG("checksum is not ok\n");
        return PN532_INVALID_FRAME;
    }

    return length;
    #endif
}

int8_t PN532_I2C::readAckFrame() {
    const uint8_t PN532_ACK[] = {0, 0, 0xFF, 0, 0xFF, 0};
    uint8_t ackBuf[sizeof(PN532_ACK)];

    DMSG("wait for ack at : ");
    DMSG(millis());
    DMSG('\n');

    uint16_t time = 0;
    do {
        if (_wire->requestFrom(PN532_I2C_ADDRESS, sizeof(PN532_ACK) + 1)) {
            if (read() & 1) {
                // check first byte --- status
                break; // PN532 is ready
            }
        }

        delay(1);
        time++;
        if (time > PN532_ACK_WAIT_TIME) {
            DMSG("Time out when waiting for ACK\n");
            return PN532_TIMEOUT;
        }
    } while (1);

    DMSG("ready at : ");
    DMSG(millis());
    DMSG('\n');

    for (uint8_t i = 0; i < sizeof(PN532_ACK); i++) {
        ackBuf[i] = read();
    }

    if (memcmp(ackBuf, PN532_ACK, sizeof(PN532_ACK))) {
        DMSG("Invalid ACK\n");
        return PN532_INVALID_ACK;
    }

    return 0;
}

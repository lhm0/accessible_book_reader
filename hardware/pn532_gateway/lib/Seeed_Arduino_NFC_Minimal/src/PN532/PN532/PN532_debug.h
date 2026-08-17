#ifndef __DEBUG_H__
#define __DEBUG_H__

//#define DEBUG

#include "Arduino.h"

#if defined(ARDUINO_SAMD_VARIANT_COMPLIANCE) && defined(SerialUSB)
    #define SERIAL SerialUSB
#else
    #define SERIAL Serial
#endif

#ifdef DEBUG
    #define DMSG(args...)       SERIAL.print(args)
    #define DMSG_STR(str)       SERIAL.println(str)
    #define DMSG_HEX(num)       SERIAL.print(' '); SERIAL.print((num>>4)&0x0F, HEX); SERIAL.print(num&0x0F, HEX)
    #define DMSG_INT(num)       SERIAL.print(' '); SERIAL.print(num)
#else
    #define DMSG(args...)
    #define DMSG_STR(str)
    #define DMSG_HEX(num)
    #define DMSG_INT(num)
#endif

#endif

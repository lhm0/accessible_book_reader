"""Host regression test for the actual Type-A RX snapshot helpers (no hardware)."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class AgcSnapshotTest(unittest.TestCase):
    def test_rx_timeout_and_failed_register_read(self):
        source = (ROOT / 'lib/PN5180_Library_Minimal/src/PN5180ISO14443.cpp').read_text()
        helpers = source[source.index('void captureTypeADiagStatus('):source.index('bool waitForTypeAFrame(')]
        stub = r'''
#include <cassert>
#include <cstdint>
constexpr int IRQ_STATUS=0, RF_STATUS=1, RX_STATUS=2, RX_IRQ_STAT=1;
constexpr unsigned long kTypeAResponseTimeoutMs=20;
unsigned long now=0;
unsigned long millis() { return now; }
void delay(unsigned long ms) { now+=ms; }
struct PN5180TypeADiagResult {
 bool rfSampleCaptured=false, rfSampleTimedOut=false;
 unsigned long rfSampleMs=0;
 bool irqStatusValid=false, rfStatusValid=false, rxStatusValid=false;
 uint32_t irqStatus=0, rfStatus=0, rxStatus=0;
 uint16_t rxLength=0;
};
struct PN5180ISO14443 {
 bool response=true, rfOk=true;
 uint32_t agc=123;
 bool readRegister(int reg, uint32_t* out) {
   if (reg==RF_STATUS) { if (!rfOk) return false; *out=agc; }
   else *out=reg==IRQ_STATUS ? (response ? RX_IRQ_STAT : 0) : 2;
   return true;
 }
};
'''
        checks = r'''
int main() {
 PN5180ISO14443 reader;
 PN5180TypeADiagResult result;
 assert(waitForTypeAResponse(&reader, &result));
 assert(result.rfSampleCaptured && result.rfStatusValid && result.rfStatus==123);
 assert(!result.rfSampleTimedOut);
 reader.agc=999; // Later chip changes must not alter the saved measurement.
 assert(result.rfStatus==123);
 reader.response=false;
 assert(!waitForTypeAResponse(&reader, &result));
 assert(result.rfSampleTimedOut && result.rfStatus==999 && result.rfSampleMs==20);
 reader.response=true;
 reader.rfOk=false; // Never advertise the old numeric value as valid.
 assert(waitForTypeAResponse(&reader, &result));
 assert(!result.rfStatusValid && !result.rfSampleTimedOut);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            cpp=Path(tmp)/'snapshot.cpp'
            exe=Path(tmp)/'snapshot'
            cpp.write_text(stub+helpers+checks)
            subprocess.run(['c++', '-std=c++11', str(cpp), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True)

if __name__ == '__main__':
    unittest.main()

<Qucs Schematic 26.1.0>
<Properties>
  <View=124,104,1018,709,1.25906,0,0>
  <Grid=10,10,1>
  <DataSet=PN5180_Matching.dat>
  <DataDisplay=PN5180_Matching.dpl>
  <OpenDisplay=0>
  <Script=PN5180_Matching.m>
  <RunScript=0>
  <showFrame=0>
  <FrameText0=Title>
  <FrameText1=Drawn By:>
  <FrameText2=Date:>
  <FrameText3=Revision:>
</Properties>
<Symbol>
</Symbol>
<Components>
  <L L0A 1 270 170 -26 10 0 0 "470nH" 1 "" 0>
  <L L0B 1 270 320 -26 10 0 0 "470nH" 1 "" 0>
  <GND * 1 350 270 0 0 0 0>
  <GND * 1 530 270 0 0 0 0>
  <GND * 1 530 420 0 0 0 0>
  <GND * 1 350 420 0 0 0 0>
  <C C0A 1 350 220 17 -26 0 1 "127pF" 1 "" 0 "neutral" 0>
  <C C0B 1 350 370 17 -26 0 1 "127pF" 1 "" 0 "neutral" 0>
  <Vac V1 1 190 240 18 -26 0 1 "1 V" 1 "1 kHz" 0 "0" 0 "0" 0 "0" 0 "0" 0>
  <L L1 1 700 240 -50 -26 0 3 "1.33uH" 1 "" 0>
  <R RQA 1 620 170 -26 15 0 0 "1 Ohm" 1 "26.85" 0 "0.0" 0 "0.0" 0 "26.85" 0 "european" 0>
  <R RQB 1 620 320 -26 15 0 0 "1 Ohm" 1 "26.85" 0 "0.0" 0 "0.0" 0 "26.85" 0 "european" 0>
  <C C2A 1 530 220 17 -26 0 1 "{C2}" 1 "" 0 "neutral" 0>
  <C C2B 1 530 370 17 -26 0 1 "{C2}" 1 "" 0 "neutral" 0>
  <C C1A 1 450 170 -26 17 0 0 "{C1}" 1 "" 0 "neutral" 0>
  <C C1B 1 450 320 -26 17 0 0 "{C1}" 1 "" 0 "neutral" 0>
  <NutmegEq NutmegEq1 1 180 490 -21 14 0 0 "ALL" 1 "Vin=v(tx1,tx2)" 1 "Vant=v(ant_top,ant_bottom)" 1 "Zin=Vin / (-v1#branch)" 1 "Rin=real(Zin)" 1 "Xin=imag(Zin)" 1 "Zmag=mag(Zin)" 1 "Zphase=ph(Zin)*180/pi" 1 "VantMag=mag(Vant)" 1 "VantPhase=ph(Vant)*180/pi" 1 "ZerrR=real(Zin)-20" 1 "ZerrX=imag(Zin)" 1 "Error=sqrt(ZerrR*ZerrR + ZerrX*ZerrX)" 1 "Gamma=(Zin-50)/(Zin+50)" 1 "GammaRe=real(Gamma)" 1 "GammaIm=imag(Gamma)" 1>
  <.SW SW1 1 610 590 0 50 0 0 "AC1" 1 "lin" 1 "C1" 1 "20pF" 1 "200pF" 1 "10" 1>
  <SpicePar SpicePar1 1 630 490 -21 14 0 0 "C1=20pF" 1 "C2=150pF" 1>
  <.AC AC1 1 380 470 0 31 0 0 "lin" 1 "10MHz" 1 "15MHz" 1 "501" 1 "no" 0>
</Components>
<Wires>
  <300 170 350 170 "" 0 0 0 "">
  <350 170 420 170 "" 0 0 0 "">
  <350 170 350 190 "" 0 0 0 "">
  <300 320 350 320 "" 0 0 0 "">
  <350 320 420 320 "" 0 0 0 "">
  <350 320 350 340 "" 0 0 0 "">
  <350 400 350 420 "" 0 0 0 "">
  <480 320 530 320 "" 0 0 0 "">
  <530 320 590 320 "" 0 0 0 "">
  <530 320 530 340 "" 0 0 0 "">
  <530 250 530 270 "" 0 0 0 "">
  <530 400 530 420 "" 0 0 0 "">
  <350 250 350 270 "" 0 0 0 "">
  <480 170 530 170 "" 0 0 0 "">
  <530 170 590 170 "" 0 0 0 "">
  <530 170 530 190 "" 0 0 0 "">
  <650 170 700 170 "" 0 0 0 "">
  <700 170 700 210 "" 0 0 0 "">
  <650 320 700 320 "" 0 0 0 "">
  <700 270 700 320 "" 0 0 0 "">
  <190 170 190 210 "" 0 0 0 "">
  <190 170 240 170 "" 0 0 0 "">
  <190 270 190 320 "" 0 0 0 "">
  <190 320 240 320 "" 0 0 0 "">
  <240 170 240 170 "TX1" 200 130 0 "">
  <240 320 240 320 "TX2" 200 290 0 "">
  <700 170 700 170 "ant_top" 730 140 0 "">
  <700 320 700 320 "ant_bottom" 730 290 0 "">
</Wires>
<Diagrams>
  <Rect 860 240 240 160 3 #c0c0c0 1 00 1 1.2e+07 1e+06 1.5e+07 1 -109.203 500 1202.81 1 -1 1 1 315 0 225 1 0 0 "" "" "">
	<"ngspice/ac.rin" #0000ff 0 3 0 0 0>
  </Rect>
  <Rect 860 420 240 160 3 #c0c0c0 1 00 1 0 0.2 1 1 -0.1 0.5 1.1 1 -0.1 0.5 1.1 315 0 225 1 0 0 "" "" "">
	<"ngspice/ac.xin" #0000ff 1 3 0 0 0>
  </Rect>
  <Rect 860 630 240 160 3 #c0c0c0 1 00 1 0 0.2 1 1 -0.1 0.5 1.1 1 -0.1 0.5 1.1 315 0 225 1 0 0 "" "" "">
	<"ngspice/ac.zmag" #0000ff 1 3 0 0 0>
  </Rect>
</Diagrams>
<Paintings>
</Paintings>

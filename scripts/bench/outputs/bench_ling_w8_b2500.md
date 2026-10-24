## CH32V208 Datasheet

## Overview

CH32V series are industrial-grade general-purpose microcontrollers designed based on QingKe 32-bit RISC-V. The whole series of products into the hardware stack area, fast interrupt entry and other designs, compared to the standard greatly improved the interrupt response speed.   CH32V208 is equipped with V4C_core, which adds memory protection function and reduces hardware division cycle. In terms of product features, it supports 144MHz main frequency zero-wait operation. The series integrates 2Mbps low-power Bluetooth BLE communication module, 10M Ethernet MAC+PHY module, USB2.0 full-speed device + host/device interface, CAN controller, etc.

## Features

-  Core:

- - QingKe 32-bit RISC-V core with multiple instruction set combinations - Fast programmable interrupt controller + hardware interrupt stack - Branch prediction, conflict handling mechanism

- - Single cycle multiplication, hardware division

- - System main frequency 144MHz

-  Memory:

- - Available with up to 64KB volatile data storage area SRAM

- - Available with 480KB program memory CodeFlash (zero-wait application area + non-zero-wait data area)

- - 28KB BootLoader - 128B non-volatile system configuration memory

- - 128B user-defined memory

-  Power management and low-power consumption:

- - System power supply VDD : 3.3V

- - Independent power supply for GPIO unit V_I/O :

- 3.3V

- - Low-power mode: Sleep, Stop, Standby

- - VBAT independently powers RTC and backup register

-  Clock & Reset

- - Built-in factory-trimmed 8MHz RC oscillator

- - Built-in 40 KHz RC oscillator

- - Built-in PLL, optional CPU clock up to 144MHz

- - High-speed external 32MHz oscillator

- - Low-speed external 32.768 KHz oscillator

- - Power on/down reset, programmable voltage detector

-  Real-time clock (RTC): 32-bit independent

- RTC timer

-  1 group of 8-channel general-purpose DMA controllers

- - 8 channels, support ring buffer

- - Support TIMx/ADC /USART/I 2 C/SPI

-  2 groups of OPAs and comparators: connected with ADC and TIMx

-  1 group of 12-bit ADC

- - Analog input range: VSSA ~VDDA

- - 16 external signals + 2 internal signals

- - On-chip temperature sensor

-  16-channels Touch-Key detection Timers

-  Multiple timers

- - 1 16-bit advanced-control timer, with dead zone control and emergency brake; can offer PWM complementary output for motor control - 3 16-bit general-purpose timers, provide input capture/output comparison/PWM/pulse counting/incremental encoder input

- - 1 32-bit general-purpose timer

- - 2 watchdog timers (independent watchdog and window watchdog)
- - 4 USART interfaces

-  Fast GPIO port

- - 2 I²C interfaces (support SMBus/PMBus)

- - 53 I/O ports, with 16 external interrupts

- - 2 SPI interfaces

-  Security features: CRC unit, 96-bit unique ID

- - USB2.0 full-speed device interface (full-speed and low-speed)

-  Debug mode: 2-wire serial debug interface (SDI)

- - USB2.0 full-speed host/device interface

- - 1 CAN interfaces (2.0B active)

-  Package: LQFP or QFN

- - SysTick: 64-bit counter

-  Communication interfaces:

- - Built-in 10MPHY transceiver

- - Low-power Bluetooth BLE5.3
V2.7                                                 1

*Table 1-1 Series overview*

|  | Small-and-medium capacity general-purpose device (V203) | Small-and-medium capacity general-purpose device (V203) | High-capacity general-purpose device (V303) | High-capacity general-purpose device (V303) Connectivity device (V305) | Interconnectivity device (V307) | Wireless device (V208) |
| --- | --- | --- | --- | --- | --- | --- |
|  | QingKe V4B | QingKe V4B |  | QingKe V4F | QingKe V4F | QingKe V4C |
| 32K   Flash | 64K   Flash | 128K   Flash | 256K   Flash | 128K   Flash | 256K   Flash | 128K   Flash |
| 10K SRAM | 20K SRAM | 32K SRAM | 64K SRAM | 32K SRAM | 64K SRAM | 64K SRAM |
| 2*ADC(TKey) | 2*ADC(TKey) | 2*ADC(TKey) | 2*ADC(TKey) 2*DAC 4*ADTM | 2*ADC(TKey) 2*DAC 4*ADTM | 2*ADC(TKey) 2*DAC 4*ADTM 4*GPTM 2*BCTM | ADC(TKey) ADTM |
| ADTM 3*GPTM | ADTM 3*GPTM | 2*DAC ADTM | 4*GPTM 2*BCTM | 4*GPTM 2*BCTM | CRC 8*USART/UART | 3*GPTM GPTM(32) |
| CRC 2*USART SPI I 2 CUSBD USBFS | CRC 4*USART 2*SPI 2*I 2 CUSBD USBFS | 3*GPTM CRC 3*USART 2*SPI 2*I 2 C USBFS | CRC 8*USART/UART 3*SPI(2*I 2 S) 2*I 2 C USBFS CAN | CRC 5*USART/UART 3*SPI(2*I 2 S) 2*I 2 C OTG_FS USBHS(+PHY) | 3*SPI(2*I 2 S) 2*I 2 C OTG_FS USBHS(+PHY) 2*CAN RTC | CRC 4*USART/UART 2*SPI 2*I 2 CUSBD USBFS |
| CAN RTC | CAN RTC | CAN RTC | RTC 2*WDG | 2*CAN RTC | 2*WDG 4*OPA | CAN RTC |
| 2*WDG 2*OPA | 2*WDG 2*OPA | 2*WDG 4*OPA | 4*OPA RNG | 2*WDG 4*OPA | RNG SDIO | 2*WDG 2*OPA |
|  |  |  | SDIO FSMC | RNG SDIO | FSMC DVP ETH-1000MAC 10M-PHY | ETH-10M(+PHY) BLE5.3 |

Note: The number of peripherals or functions of some products in the same category may be limited by the

CH32V series are industrial-grade general-purpose enhanced MCUs based on 32-bit RISC-V instruction set and architecture. Its products are divided by function resources into categories such as general-purpose, connectivity, and wireless communication. They extend each other in terms of package types, peripheral resources and quantities, pin numbers, and device characteristics, but they are compatible with each other in software, functions, and hardware pin configurations. The product iterations and rapid applications provide freedom and convenience for users in product development.

For the features of this series of products, please refer to the datasheet.

For the peripheral function description, usage and register configuration, please refer to "CH32FV2_V3RM".

The datasheets and reference manuals can be downloaded on the official website of WCH: http://www.wch.cn/

Information about the RISC-V instruction set architecture can be downloaded from:  https://riscv.org/

This manual is for CH32V208 series datasheet. Please refer to "CH32V307DS0" for V303_305_307 series and "CH32V203DS0" for V203 series.

## Chapter 1 Series Product Description
package, please confirm the product package when selecting. Abbreviations: ADTM: Advanced-control Timer RNG: Random Number Generator GPTM: General-purpose Timer USBD: Universal Serial Bus Full-speed Device GPTM (32): 32-bit General-purpose Timer USBFS: Universal Serial Bus Full-speed BCTM: Basic Timer Host/Device TKey: Touch key USBHS: Universal Serial Bus High-speed OPA: Operational Amplifier/Comparator Host/Device

*Table 1-2 Overview of Cores*

| Feature Core | Instruction Set | Hardware Stack Level | Interrupt Nesting Level | Number of Fast Interrupt Channels | Integer Division Period | Vector table mode | Extended instruction | Memory protection |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| V4B | IMAC | 2 | 2 | 4 | 9 | Address or instruction | Support | No |
| V4C | IMAC | 2 | 2 | 4 | 5 | Address or instruction | Support | Standard |
| V4F | IMAFC | 3 | 8 | 4 | 5 | Address or instruction | Support | Standard |

Note: For information about the core, please refer to the QingKeV4 microprocessor manual "QingKeV4_Processor_Manual".
## Chapter 2 Specification

CH32V208 series are 32-bit RISC core MCUs based on the RISC-V instruction set architecture (ISA), with 144MHz operating frequency, and built-in high-speed memory. It has multiple buses working synchronously, and provides a wealth of peripheral functions and enhanced I/O ports. This series of products has built-in 1 12-bit ADC modules, multiple timers, multi-channel capacitance touch key detection (TKey) and other functions. It also contains standard and dedicated communication interfaces: I²C, SPI, USART, CAN controller, USB2.0 full-speed host/device controller, USB2.0 full-speed device controller, etc.

The rated working voltage of the product is 3.3V, and the working temperature range is -40℃ ～ 85℃ in industrial grade. It supports several power-saving operating modes to meet the product's low-power application requirements. Various models in the series are different in terms of resource allocation, number of peripherals, peripheral functions, etc., and can be selected as needed.

## 2.1 Model comparison

*Table 2-1 Wireless products resource allocation*

| Differences | Part No. | GB | CH32V208 CB | CH32V208 RB | WB |
| --- | --- | --- | --- | --- | --- |
|  | Pin count | Pin count 28 | 48 | 64 | 68 |
|  | Flash (bytes)  (1) | Flash (bytes)  (1) 128K (2) | 128K (2) | 128K (2) | 128K (2) |
|  | SRAM (bytes) | SRAM (bytes) 64K (2) | 64K (2) | 64K (2) | 64K (2) |
|  | GPIO port count | GPIO port count 21 | 35 | 49 | 53 |
|  | GPIO power supply | GPIO power supply | Shared with VDD |  | Independent VIO |
|  | Advanced-control (16 bits) | 1 | 1 | 1 | 1 |
|  | General-purpose (16 bits) | 3 | 3 | 3 | 3 |
| Timer | General-purpose (32 bits) | 1 | 1 | 1 | 1 |
| Timer | Watchdog | 2 | 2 | 2 | 2 |
|  | SysTick (64 bits) |  | Supported | Supported |  |
|  | RTC |  | Supported | Supported |  |
|  | ADC/TKey (channel@ unit count) | ADC/TKey (channel@ unit count) 8@1 | 10@1 | 16@1 | 16@1 |
|  | OPA | OPA2 | 2 | 2 | 2 |
|  | USART/UART | 2 | 4 | 4 | 4 |
|  | SPI | 1 | 2 | 2 | 2 |
|  | I 2 C | 1 | 2 | 2 | 2 |
| Communication | CAN | 1 | 1 | 1 | 1 |
| interfaces | USB USBD | 1 | 1 | 1 | 1 |
|  | (FS) USBHD | 1 | 1 | 1 | 1 |
|  | Ethernet | 10M | - |  | 10M |
|  | BLE 5.3 |  | supported | supported |  |
| Part No. |  | CH32V208 | CH32V208 |  |
| --- | --- | --- | --- | --- |
| Differences | GB | CB | RB | WB |
| CPU clock speed |  | Max: 144MHz | Max: 144MHz |  |
| Rated voltage |  | 3.3V | 3.3V |  |
| Operating temperature |  | Industrial-grade: -40℃~85℃ | Industrial-grade: -40℃~85℃ |  |
| Package | QFN28 | QFN48 | LQFP64M | QFN68 |
Note: 1. Flash bytes represent zero-wait run area R 0WAIT . For the V208 series, non-zero-wait area is (480K-R 0WAIT ).

2. The 208 series with 128K FLASH+64K SRAM support user select word to be configured as one of several combinations of (128K FLASH+64K SRAM), (144K FLASH+48K SRAM), and (160K FLASH+32K SRAM).

## 2.2 System architecture

The microcontroller is based on the RISC-V instruction set architecture (ISA) in which the core, arbitration unit, DMA module, SRAM storage and other parts are interacted through multiple sets of buses. A general-purpose DMA controller is integrated in the chip to reduce the burden on the CPU and improve access efficiency. The application of a multi-level clock management mechanism reduces the operating power consumption of peripherals. At the same time, it has a data protection mechanism and measures such as automatic clock switching protection to increase system stability. The following figure is a block diagram of the overall internal structure of the series of products.
*Figure 2-1 System block diagram*

[Figure-3](97,98,532,629)

## 2.3 Memory map

*Figure 2-2 Memory address map*

[Figure-5](95,126,497,760)

## 2.4 Clock tree

Four groups of clock sources are introduced into the system: internal high-frequency RC oscillator (HSI), internal low-frequency RC oscillator (LSI), external high-frequency oscillator (HSE), and external low-frequency oscillator (LSE). Among them, the low-frequency clock source provides the clock reference for RTC and independent watchdog. The high-frequency clock source is directly or indirectly multiplied by the PLL and output as the system clock (SYSCLK). The system clock is then provided by each prescaler to provide the HB domain, PB1 domain, PB2 domain peripheral control clock and sampling or output clock. Some modules need to be directly provided by the PLL clock.
*Figure 2-3 CH32V208 clock tree block diagram*

[Figure-3](90,102,501,600)

Note: 1. When using USB, the CPU clock speed must be 48MHz or 96MHz or 144MHz. When the system wakes up from Stop mode or Standby mode, the system will automatically select HSI as the system clock frequency. If USB and ETH both are enabled, select USBPRE=5DIV, configure PLLCKR=SYSCLK to be 240M, HBPRE=2DIV, and the CPU clock speed is 120M.

2. For the CH32V208, the external crystal or clock (HSE) is 32M. When the external crystal is enabled, no load capacitor is needed as it is built in.
## 2.5.3 Power supply scheme

-    VDD  = 2.4~3.6V: Power supply for some I/O pins and internal voltage regulator.

-    VIO  = 2.4~3.6V: It supplies power to most of the I/O pins and the Ethernet module, which determines the pin output high voltage amplitude. Normal work during operation, the VIO  voltage cannot be higher than the VDD  voltage.

-    VDDA  = 2.4~3.6V: It supplies power to the analog part of the high-frequency RC oscillator, ADC, temperature sensor, DAC and PLL. The VDDA  voltage must be the same as the VIO  voltage (If VDD  is powered down and VIO  is live, Then VDDA  must be live and consistent with VIO). When using ADC,

## 2.5.2 On-chip memory and boot mode

Up to 128K bytes of built-in SRAM area, used to store data, data will be lost after power failure. The specific capacity depends on the corresponding chip model.

Up to 480K bytes of built-in program Flash memory (Code FLASH), used for user application and constant data storage, including zero-wait program run area and non-zero-wait area. The specific size depends on the corresponding chip model.

Built-in 28K byte system memory (System FLASH), used for system boot program storage (manufacturer curing boot loader).

128 bytes are used for system non-volatile configuration word storage, and 128 bytes are used for user selection word storage.

At startup, one of 3 boot modes can be selected through the boot pins (BOOT0 and BOOT1):

-    Boot from program flash

-    Boot from system memory

-    Boot from internal SRAM

The bootloader is stored in the system memory, and the contents of the program Flash memory storage can be reprogrammed through the USART1 and USB interface.

## 2.5 Functional description

## 2.5.1 RISC-V4C processor

RISC-V4C supports the IMAC subset of the RISC-V instruction set. The processor is managed internally in a modular fashion and contains units such as fast programmable interrupt controller (PFIC), memory protection, branch prediction mode, and extended instruction support. Externally multiple buses are connected to external unit modules to enable interaction between external function modules and the core.

The processor can be flexibly applied in different scenarios, such as small-area low-power embedded scenarios, high-performance application operating system scenarios, etc., due to its minimal instruction set, multiple working modes, and modular customization extensions.

-    Support machine and user privilege mode

-    Fast Programmable Interrupt Controller (FPIC)

-    Multi-level hardware interrupt stack

-    Serial 2-wire debug interface

-    Standard memory protection design

-    Static or dynamic branch prediction, efficient jump, conflict detection

-    Custom extended instructions
VDDA  must not be less than 2.4V.

-    VBAT  = 1.8~3.6V: Optional backup power supply, when VDD  is turned off, independently powers the RTC, external low-frequency oscillator and backup registers (via the internal power switch).

## 2.5.4 Power supply monitor

This product integrates a power-on reset (POR)/power-down reset (PDR) circuit, which is always in working condition to ensure that the system is in supply. It works when the power exceeds 2.4V; when VDD  is lower than the set threshold (VPOR/PDR ), the device is placed in the reset state without using an external reset circuit.

In addition, the system is equipped with a programmable voltage monitor (PVD), which needs to be turned on by software to compare the voltage of VDD power supply with the set threshold VPVD.

Turn on the corresponding edge interrupt of PVD, and you can receive interrupt notification when VDD drops to the PVD threshold or rises to the PVD threshold. Refer to Chapter 4 for the values of VPOR/PDR and VPVD.

## 2.5.5 Voltage regulator

After reset, the regulator is automatically turned on, and there are 3 operation modes according to the application mode.

-    ON mode: normal operation, providing stable core power.

-    Low-power mode: When the CPU enters Stop mode, the regulator can be selected to run with low- power consumption.

-    OFF mode: When the CPU enters Standby mode, it automatically switches the regulator to this mode, the voltage regulator output is in high impedance, and the core power.

The voltage regulator is always ON after reset. It is OFF in Standby mode, and the regulator output is in high impedance.

## 2.5.6 Low-power mode

The system supports 3 low-power modes, which can be selected for low-power consumption, short start-up time and multiple wake-up events to achieve the best balance.

##  Sleep mode

In Sleep mode, only the CPU clock is stopped, but all peripheral clocks are powered normally and the peripherals are in a working state. This mode is the shallowest low-power mode, but it is the fastest mode to wake-up the system.

Exit condition: any interrupt or wake-up event.

##  Stop mode

In this mode, the FLASH enters low-power mode, and the PLL, HSI RC oscillator and HSE crystal oscillator are turned off. In the case of keeping the contents of SRAM and registers not lost, the Stop mode can achieve the lowest power consumption.

Exit conditions: any external interrupt/event (EXTI signal), external reset signal on NRST, IWDG reset, among which EXTI signal includes one of 16 external I/O ports, PVD output, RTC alarm clock, Ethernet wake-up signal or USB wake-up signal.

##  Standby mode

In this mode, the main LDO of the system is turned off, the low-power LDO supplies power to the wake-up circuit, all other digital circuits are powered off, and the FLASH is powered off. The system wakes up from Standby mode will generate a reset, and SBF (PWR_CSR) will be set at the same time. After waking up, check the SBF status to know the low-power mode before waking up. SBF is cleared by the CSBF (PWR_CR) bit. In the Standby mode, the contents of 32KB of SRAM can be kept (depending on the planning and configuration before going to bed), and the contents of the backup registers are kept.

Exit conditions: any external interrupt/event (EXTI signal), external reset signal on NRST, IWDG reset, a rising edge on the WKUP pin, where EXTI signal includes one of 16 external I/O ports, RTC alarm clock, Ethernet Wake-up signal, USB.

## 2.5.7 CRC (cyclic redundancy check) calculation unit

The CRC (cyclic redundancy check) calculation unit uses a fixed polynomial generator to generate a CRC code from a 32-bit data word. In many applications, CRC-based technology is used to verify the consistency of data transmission or storage. Within the scope of the EN/IEC 60335-1 standard, a means of detecting flash errors is provided. The CRC calculation unit can be used to calculate the signature of the software in real time and compare it with the signature generated when the software is linked and generated.

## 2.5.8 Fast programmable interrupt controller (FPIC)

The product has a built-in Fast Programmable Interrupt Controller (FPIC), which supports up to 255 interrupt vectors, and provides flexible interrupt management functions with minimal interrupt latency. The current product manages 8 core private interrupts and 88 peripheral interrupt management, and other interrupt sources are reserved. FPIC registers can be accessed in user and machine privileged modes.

-  2 individual maskable interrupts

-  A non-maskable interrupt NMI

-  Support hardware interrupt stack (HPE) without instruction overhead

-  4-channel vector table free interrupts (VTF)

-  Vector table supports address or command mode

-  Configurable interrupt nesting depth, up to 2 levels

-  Support interrupt tail-chaining

## 2.5.9 External interrupt/event controller (EXTI)

The external interrupt/event controller contains a total of 19 edge detectors for generating interrupt/event requests. Each interrupt line can independently configure its trigger event (rising edge or falling edge or both edges), and can be individually masked; the suspend register maintains all interrupt request states. EXTI can detect that the pulse width is smaller than the clock period of the internal PB2. Up to 80 general-purpose I/O ports can be connected to 16 external interrupt lines.

## 2.5.10 General DMA controller

The system has built-in 2 groups of general-purpose DMA controllers, manages 18 channels in total, and flexibly handles high-speed data transmission from memory to memory, peripherals to memory, and memory to peripherals, and supports ring buffer mode. Each channel has a dedicated hardware DMA request logic to support one or more peripherals' access requests to the memory. The access priority, transfer length, source address and destination address of the transfer can be configured.

The main peripherals used by DMA include: general/advanced/basic timers TIMx, DAC, USART, I²C and SPI.

Note: DMA and CPU access the system SRAM after arbitration by the arbiter.
## 2.5.14 Timer and watchdog

The timers in the system include advanced timers, general timers, basic timers, watchdog timers, and system time base timers. The number of timers included in different products in the series is different, please refer to

## 2.5.13 Analog-to-digital converter (ADC) and touch key capacitance detection (TKey)

The product is embedded with 2 12-bit analog/digital converters (ADC), sharing up to 16 external channels and 2 internal channels for sampling. The programmable channel sampling time can realize single, continuous, scanning or discontinuous conversion. The analog watchdog function is provided to allow very precise monitoring of one or more selected channels for monitoring the signal voltage of the channel. It supports external event-triggered conversion, the trigger source includes the internal signal and external pin of the on-chip timer; it also supports the use of DMA operations.

ADC internal channel sampling includes 1 channel of built-in temperature sensor sampling and 1 channel of internal reference power sampling. The temperature sensor generates a voltage that varies linearly with temperature. The temperature sensor is internally connected to the IN16 input channel, which is used to convert the output of the sensor to a digital value.

The capacitance touch key detection unit provides up to 16 detection channels, multiplexing the external channels of the ADC module. The detection result is converted and output by the ADC module, and the state of the touch key is recognized by the user software.

## 2.5.11 Clock and Boot

The system clock source HSI is turned on by default. After the clock is not configured or reset, the internal 8MHz RC oscillator is used as the default CPU clock, and then an external 32MHz clock or PLL clock can be additionally selected. When the clock security mode is turned on, if the HSE is used as the system clock (directly or indirectly), the system clock will automatically switch to the internal RC oscillator when the external clock is detected to be invalid, and the HSE and PLL will be automatically turned off at the same time; in low-power consumption mode, the system will automatically switch to the internal RC oscillator after waking up. If the clock interrupt is enabled, the software can receive the corresponding interrupt.

Multiple prescalers are used to configure the frequency of HB. The high-speed PB (PB2) and low-speed PB (PB1) regions provide peripheral clocks with a maximum frequency of 144MHz. Refer to the clock tree block diagram in Figure 2-3.

## 2.5.12 Real time clock (RTC) and backup registers

The RTC and the backup register are in the backup power supply area inside the system. When VDD is valid, it is powered by VDD, and when VDD is invalid, the internal power is automatically switched to the VBAT pin.

The RTC real-time clock is a set of 32-bit programmable counters, and the time base supports 20-bit prescaler for measurement in a longer period of time. The clock reference source is a high-speed external clock divided by 512 (HSE/512), external crystal low-frequency oscillator (LSE) or internal low-power RC oscillator (LSI). The LSE also has a backup power supply area, so when the LSE is selected as the RTC time base, the RTC setting and time can remain unchanged after the system resets or wakes up from Standby mode.

The backup register contains up to 42 16-bit registers, which can be used to store 84 bytes of user application data. This data can continue to be maintained after wake-up from Standby, or system Reset or power Reset. When the intrusion detection function is turned on, once the intrusion detection signal is valid, all contents in the backup register will be cleared.
##  Independent watchdog

*Table 2-2 for details.*

*Table 2-2 Timer comparison*

| Timer | Timer | Resolution | Count Type | Time Base | DMA | Function |  |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Advanced |  |  | Up | PB2 time |  | PWM complementary single pulse output | output, |
| control | TIM1 | 16 bits | Down | domain | Supported | Input capture |  |
| timer |  |  | Up/down | 16-bit divider |  | Output compare |  |
|  |  |  |  |  |  | Timer count |  |
| General- purpose timer | TIM2 TIM3 TIM4 TIM5 | 16 bits 32 bits | Up Down Up/down | PB1 time domain 16-bit divider | Supported | Input capture Output compare Timer count |  |
|  |  |  |  | PB1 time |  |  |  |
| Window watchdog | Window watchdog | 7 bits | Down | domain 4 types of frequency division | Not supported | Timing Reset the system (normal work) | Reset the system (normal work) |
| Independent watchdog | Independent watchdog | 12 bits | Down | PB1 time domain 7 types of frequency division | Not supported | Timing Reset the system (normal work + low-power work) | Reset the system (normal work + |
| SysTick Timer | SysTick Timer | 64 bits | Up/down | SYSCLK or SYSCLK/8 | Not supported<br>Timing | supported   Timing |  |

##  Advanced control timer

The advanced control timer is a 16-bit auto-loading up/down counter with a 16-bit programmable prescaler. In addition to the complete general-purpose timer function, it can be regarded as a three-phase PWM generator distributed to 6 channels, with a complementary PWM output function with dead zone insertion, allowing the timer to be updated after a specified number of counter cycles to repeat counting cycle, braking function, etc. Many functions of the advanced control timer are the same as the general timer, and the internal structure is also the same. Therefore, the advanced control timer can cooperate with other TIM timers through the timer link function to provide synchronization or event link functions.

##  General-purpose timer

The general timer is a 16-bit or 32-bit auto-loading up/down counter with a programmable 16-bit prescaler and 4 independent channels. Each channel supports input capture, output comparison, and PWM generation and single pulse mode output. It can also work with advanced control timers through the timer link function to provide synchronization or event link functions. In Debug mode, the counter can be frozen while the PWM outputs are disabled, thereby cutting off the switches controlled by these outputs. Any general-purpose timer can be used to generate PWM output. Each timer has an independent DMA request mechanism. These timers can also process signals from incremental encoders, as well as digital outputs from 1 to 3 Hall sensors.
The independent watchdog is a configurable 12-bit down counter that supports 7 frequency division factors. The clock is provided by an internal independent 40 KHz RC oscillator (LSI); because the LSI is independent of the main clock, it can run in Stop and Standby modes. IWDG is outside the main program and can work completely independently. Therefore, it is used to reset the entire system when a problem occurs, or as a free timer to provide timeout management for the application. It can be configured as software or hardware to start the watchdog through the option byte. In Debug mode, the counter can be frozen.

##  Window Watchdog

The window watchdog is a 7-bit down counter and can be set to free-running. It can be used to reset the entire system when a problem occurs. It is driven by the main clock and has an early warning interrupt function; in Debug mode, the counter can be frozen.

##  SysTick Timer

QingKe microprocessor core comes with a 64-bit optional incremental or decremental counter for generating SYSTICK exceptions (exception number: 15), which can be used exclusively in real-time operating systems to provide a "heartbeat" rhythm for the system, or as a standard 64-bit counter. With automatic reload function and programmable clock source.

## 2.5.15 Communication interface

## 2.5.15.1 Universal Synchronous/Asynchronous Receiver Transmitter (USART)

The product provides 3 groups of Universal Synchronous/Asynchronous Receiver Transmitters (USART1, USART2, USART3), and 1 groups of Universal Asynchronous Receiver Transmitters (UART4). It supports full-duplex asynchronous communication, synchronous one-way communication and half-duplex single-wire communication. It also supports LIN (Local Interconnect Network), compatible with ISO7816 smart card protocol and IrDA SIR ENDEC transmission codec specification, and modem (CTS/RTS hardware flow control) operation. It also allows multi-processor communication. It uses a fractional baud rate generator system and supports DMA operation continuous communication.

## 2.5.15.2 Serial Peripheral Interface (SPI)

Up to 2 groups of serial peripherals interface (SPI) provide master or slave operation, dynamic switching. Support multi-master mode, full-duplex or half-duplex synchronous transmission, support basic SD card and MMC mode. Programmable clock polarity and phase, data bit width provides 8 or 16-bit selection, hardware CRC generation/check for reliable communication, and continuous communication support for DMA operation.

## 2.5.15.3 I2C_bus

Up to 2 I²C_bus interfaces can work in multi-master mode or Slave mode, perform all I²C_Bus specific timing, protocol, arbitration, etc. It supports both standard and fast speed, and is compatible with SMBus2.0.

The I²C interface provides 7-bit or 10-bit addressing, and supports dual slave addressing in 7-bit Slave mode. It integrates built-in hardware CRC generator/checker. It also supports DMA operation and supports SMBus bus version 2.0 / PMBus bus.

## 2.5.15.4 Controller Area Network (CAN)

The CAN interface is compatible with specifications 2.0A and 2.0B (active), the baud rate is up to 1Mbits/s, and it supports time-triggered communication functions. It can receive and send standard frames with 11-bit identifiers, as well as extended frames with 29-bit identifiers. It has 3 sending mailboxes and 2 3-level deep receiving FIFOs.

With 1 set of CAN controller products, there are only 14 configurable filters, and share a dedicated 512-byte SRAM memory with the USBD module for data transmission and reception. When USBD and CAN are used at the same time, in order to prevent access to SRAM conflicts, USBD can only use the lower 384 bytes.

## 2.5.15.5 Universal Serial Bus device (USBD)

The product is embedded with a USB2.0 full-speed controller, which complies with the USB2.0 full-speed standard. USBD provides 16 configurable USB device endpoints, supports low-speed devices and full-speed devices, supports control/batch/synchronization/interrupt transmission, double buffer mechanism, USB suspend/resume operations, and has standby/wake-up functions. The USB dedicated 48MHz clock is directly generated by the internal main PLL frequency division.

## 2.5.15.6 Universal Serial Bus USB2.0 full-speed Host/Device controller (USBFS)

The USB2.0 full-speed host controller and device controller (USBFS) follow the USB2.0 full-speed standard. It provides 16 configurable USB device endpoints and a set of host endpoints. Support control/batch/synchronization/interrupt transmission, double buffer mechanism, USB bus suspend/resume operation, and provide standby/wake-up functions. The 48MHz clock dedicated to the USBFS module is directly generated by the internal main PLL frequency division (the PLL must be 144MHz or 96MHz or 48MHz).

## 2.5.16 General-purpose input and output (GPIO)

The system provides 4 groups of GPIO ports with a total of 53 GPIO pins. Each pin can be configured by software as output (push-pull or open-drain), input (with or without pull-up or pull-down) or multiplexed peripheral function port. Most GPIO pins are shared with digital or analog multiplexed peripherals. Except for ports with analog input functions, all GPIO pins have high current passing capabilities. A locking mechanism is provided to freeze the IO configuration to avoid accidental writing to the I/O register.

Most of the IO pins in the system are provided by VIO. Changing the VIO power supply will change the high value of the IO pin output level to adapt to the external communication interface level. Please refer to the pin description for specific pins.

## 2.5.17 Operational amplifier/comparator (OPA)

The product has built-in 2 groups of operational amplifiers/comparators, and the internal selection is linked to the ADC and TIMx peripherals. Its input and output can be selected by changing the configuration to select multiple channels. It supports to amplify the external analog small signal and send it to the ADC to realize the small signal ADC conversion. It can also complete the signal comparator function. The comparison result is output by GPIO or directly connected to the input channel of TIMx.

## 2.5.18 Serial debug interface (SDI)

The core comes with a 2-wire serial debug interface (SDI), including SWDIO and SWCLK pins. The default debug interface pin function is turned on after system power on or reset, and SDI can be turned off as needed after the main program is running.
## Chapter 3 Pinouts and Pin Definition

## 3.1 Pinouts

[Figure-4](118,131,459,138)

[Figure-5](62,160,539,703)

[Figure-6](156,427,481,434)
V2.7                                                17

## 3.2 Pin description

## Table 3-1 Pin definitions

Note: The pin function in the table below refer to all functions and does not involve specific model(s). There are differences in peripheral resources between different models. Please confirm whether this function is available according to the particular model's resource table before viewing this table.

| QFN28 QFN48 | Pin No. LQFP64 | Pin No. QFN68 | Pin name | Pin type (1) | I/O structure | Main function (after reset) | Default alternate function | Remapping function |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 0 0 | - | 0 | VSS | P | - | VSS |  |  |
| - 48 | 1 | 1 | VBAT | P | - | VBAT |  |  |
| - 1 | 2 | 2 | PC13- TAMPER-RTC (2) | I/O | - | PC13 (3) | TAMPER-RTC |  |
| 28 2 | 3 | 3 | PC14- OSC32_IN (2) | I/O/A | - | PC14 (3) | OSC32_IN |  |
| 1 3 | 4 | 4 | PC15- OSC32_OUT (2) | I/O/A | - | PC15 (3) | OSC32_OUT |  |
| - 4 | 5 | 5 | VSSA | P | - | VSSA |  |  |
| 2 5 | 6 | 6 | OSC_IN | I/A | - | OSC_IN |  |  |
| 3 6 | 7 | 7 | OSC_OUT | O/A | - | OSC_OUT |  |  |
| - 7 | 8 | 8 | NRST | I | - | NRST |  |  |
| - - | 9 | 9 | PC0 | I/O/A | - | PC0 | ADC_IN10 |  |
| - - | 10 | 10 | PC1 | I/O/A | - | PC1 | ADC_IN11 |  |
| - - | 11 | 11 | PC2 | I/O/A | - | PC2 | ADC_IN12 |  |
| - - | 12 | 12 | PC3 | I/O/A | - | PC3 | ADC_IN13 |  |
| 4 8 | 13 | 13 | VDDA | P | - | VDDA |  |  |
| 5 9 | 14 | 14 | PA0-WKUP | I/O/A | - | PA0 | WKUP/USART2_CTS ADC_IN0/TIM2_CH1 (9) TIM2_ETR (9) /TIM5_CH1 | TIM2_CH1_2 (9) TIM2_ETR_2 (9) |
| 6 10 | 15 | 15 | PA1 | I/O/A | - | PA1 | USART2_RTS/ADC_IN1 TIM5_CH2/TIM2_CH2 | TIM2_CH2_2 |
| 7 11 | 16 | 16 | PA2 | I/O/A | - | PA2 | USART2_TX/TIM5_CH3 ADC_IN2/TIM2_CH3 | TIM2_CH3_1 |
|  |  |  |  |  |  |  | OPA2_OUT0 |  |
| - - | - | 17 | V IO_4 | P | - | V IO_4 |  |  |
| - - | - | 18 | PD4 | I/O | FT | PD4 |  |  |
| 8 12 | 17 | 19 | PA3 | I/O/A | - | PA3 | USART2_RX/TIM5_CH4 ADC_IN3/TIM2_CH4 OPA1_OUT0 | TIM2_CH4_1 |
| - - | 18 |  | V SS_4 | P | - | V SS_4 |  |  |
| - - | 19 | - | V DD_IO_4 | P | - | V DD_IO_4 |  |  |
| 9 13 | 20 | 20 | PA4 | I/O/A | - | PA4 | SPI1_NSS/USART2_CK |  |
V2.7                                                18

| QFN28 QFN48 | Pin No. LQFP64 | Pin No. QFN68 | Pin name | Pin type (1) | I/O structure | Main function (after reset) | Default alternate function | Remapping function |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
|  |  |  |  |  |  |  | ADC_IN4/OPA2_OUT1 |  |
| 10 14 | 21 | 21 | PA5 | I/O/A | - | PA5 | SPI1_SCK/ADC_IN5 OPA2_CH1N |  |
| 11 15 | 22 | 22 | PA6 | I/O/A | - | PA6 | SPI1_MISO/ADC_IN6 TIM3_CH1/OPA1_CH1N | TIM1_BKIN_1 |
| 12 16 | 23 | 23 | PA7 | I/O/A | - | PA7 | SPI1_MOSI/ADC_IN7 TIM3_CH2/OPA2_CH1P | TIM1_CH1N_1 |
| - - | 24 | 24 | PC4 | I/O/A | - | PC4 | ADC_IN14 |  |
| - - | 25 | 25 | PC5 | I/O/A | - | PC5 | ADC_IN15 |  |
| - 17 | 26 | 26 | PB0 | I/O/A | - | PB0 | ADC_IN8/TIM3_CH3 OPA1_CH1P | TIM1_CH2N_1 TIM3_CH3_2 UART4_TX_1 |
| - 18 | 27 | 27 | PB1 | I/O/A | - | PB1 | ADC_IN9 TIM3_CH4 OPA1_OUT1 | TIM1_CH3N_1 TIM3_CH4_2 UART4_RX_1 |
| - 19 | 28 | 28 | PB2 | I/O | FT | PB2/BOOT1 |  |  |
| - 20 | 29 | 29 | PB10 | I/O/A | FT | PB10 | I2C2_SCL/USART3_TX OPA2_CH0N | TIM2_CH3_2 TIM2_CH3_3 |
| - 21 | 30 | 30 | PB11 | I/O/A | FT | PB11 | I2C2_SDA/USART3_RX OPA1_CH0N | TIM2_CH4_2 TIM2_CH4_3 |
| - - | 31 | - | V SS_1 | P |  | V SS_1 |  |  |
| 13 22 | 32 | - | V DD_IO_1 | P |  | V DD_IO_1 |  |  |
| - - | - | 31 | V IO_1 | P |  | V IO_1 |  |  |
| - - | - | 32 | V DD_1 | P |  | V DD_1 |  |  |
| - - | - | 33 | PD5 | I/O | FT | PD5 |  |  |
| - - | - | 34 | PD6 | I/O | FT | PD6 |  |  |
| - 23 | 33 | 35 | PB12 | I/O/A | FT | PB12 | SPI2_NSS/I2C2_SMBA USART3_CK/TIM1_BKIN |  |
| - 24 | 34 | 36 | PB13 | I/O/A | FT | PB13 | SPI2_SCK/TIM1_CH1N USART3_CTS | USART3_CTS_1 |
| - 25 | 35 | 37 | PB14 | I/O/A | FT | PB14 | SPI2_MISO/TIM1_CH2N USART3_RTS/OPA2_CH0P   USART3_RTS_1 | USART3_RTS/OPA2_CH0P   USART3_RTS_1 |
| - 26 | 36 | 38 | PB15 | I/O/A | FT | PB15 | SPI2_MOSI/TIM1_CH3N OPA1_CH0P |  |
| 14 - | 37 | 39 | PC6 | I/O | FT | PC6 | ETH_RXP | TIM3_CH1_3 |
| 15 - | 38 | 40 | PC7 | I/O | FT | PC7 | ETH_RXN | TIM3_CH2_3 |
| 16 - | 39 | 41 | PC8 | I/O | FT | PC8 | ETH_TXP | TIM3_CH3_3 |
| 17 - | 40 | 42 | PC9 | I/O | FT | PC9 | ETH_TXN | TIM3_CH4_3 |
| - 27 | 41 | 43 | PA8 | I/O | FT | PA8 | USART1_CK TIM1_CH1/MCO | USART1_CK_1 TIM1_CH1_1 |
V2.7                                                19

| QFN28 | QFN48 | Pin No. LQFP64 | Pin No. QFN68 | Pin name | Pin type (1) | I/O structure | Main function (after reset) | Default alternate function | Remapping function |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| - | 28 | 42 | 44 | PA9 | I/O | FT | PA9 | USART1_TX TIM1_CH2 | TIM1_CH2_1 |
| - | 29 | 43 | 45 | PA10 | I/O | FT | PA10 | USART1_RX TIM1_CH3 | TIM1_CH3_1 |
| 18 | 30 | 44 | 46 | PA11 | I/O/A | FT | PA11 | USART1_CTS/USBDM CAN1_RX/TIM1_CH4 | USART1_CTS_1 TIM1_CH4_1 |
| 19 | 31 | 45 | 47 | PA12 | I/O/A | FT | PA12 | USART1_RTS/USBDP CAN1_TX/TIM1_ETR | USART1_RTS_1 TIM1_ETR_1 |
| 20 | 32 | 46 | 48 | PA13 | I/O | FT | SWDIO |  | PA13 |
| - | 35 | - | 49 | V SS_2 | P | - | V SS_2 |  |  |
| 21 | 33 | 47 | 50 | VINTA | P | - | VINTA |  |  |
| 22 | 34 | 48 | 51 | ANT | A | - | ANT |  |  |
| 23 | 36 | 49 | 52 | PA14 | I/O | FT | SWCLK |  | PA14 |
|  |  |  |  |  |  |  |  |  | TIM2_CH1_1 (9) |
| - | 37 | 50 | 53 | PA15 | I/O | FT | PA15 |  | TIM2_ETR_1 (9) TIM2_CH1_3 (9) TIM2_ETR_3 (9) SPI1_NSS_1 |
| - | - | 51 | 54 | PC10 | I/O | FT | PC10 | UART4_TX | TIM2_ETR_1 (9) USART3_TX_1 |
| - | - | 52 | 55 | PC11 | I/O | FT | PC11 | UART4_RX | USART3_RX_1 |
| - | - | 53 | 56 | PC12 | I/O | FT | PC12 |  | USART3_CK_1 |
| - | - | 54 | 57 | PD2 | I/O | FT | PD2 | TIM3_ETR | TIM3_ETR_2 TIM3_ETR_3 |
| - | 38 | 55 | 58 | PB3 | I/O | FT | PB3 |  | TIM2_CH2_1 TIM2_CH2_3 SPI1_SCK_1 |
| - | 39 | 56 | 59 | PB4 | I/O | FT | PB4 |  | TIM3_CH1_2 SPI1_MISO_1 |
| - | 40 | 57 | 60 | PB5 | I/O | FT | PB5 | I2C1_SMBA | TIM3_CH2_2 SPI1_MOSI_1 |
| 24 | 41 | 58 | 61 | PB6 | I/O | FT | PB6 | I2C1_SCL TIM4_CH1/USBFS_DM | USART1_TX_1 |
| 25 | 42 | 59 | 62 | PB7 | I/O | FT | PB7 | I2C1_SDA TIM4_CH2/USBFS_DP | USART1_RX_1 |
|  | 43 | 60 | 63 | BOOT0 | I | - | BOOT0 |  |  |
| 26 (6) | 44 | 61 | 64 | PB8 | I/O/A | FT | PB8 | TIM4_CH3 | I2C1_SCL_1 /CAN1_RX_2 |
| - - | 45 - | 62 - | 65 66 | PB9 PD3 | I/O/A I/O | FT FT | PB9 PD3 | TIM4_CH4 | I2C1_SDA_1 /CAN1_TX_2 |
|  | Pin No. | Pin No. |  |  | Pin |  | Main |  |  |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| QFN28 | QFN48 | LQFP64 | QFN68 | Pin name | type (1) | I/O structure | function (after reset) | Default alternate function | Remapping function |
| - | 46 | 63 | - | V SS_3 | P | - | V SS_3 |  |  |
| 27 | 47 | 64 | - | V DD_IO_3 | P | - | V DD_IO_3 |  |  |
| - | - | - | 67 | V IO_3 | P | - | V IO_3 |  |  |
| - | - | - | 68 | V DD_3 | P | - | V DD_3 |  |  |
Note 1: Abbreviations in the table

- I = TTL/CMOS Schmitt input;

- O = CMOS tri-state output;

- A = analog signal input or output;

- P = power;

FT = 5V tolerance;

ANT = RF signal input and output (antenna);

Note 2: The PC13, PC14 and PC15 pins are powered through a power switch which can only pass a limited current (3mA). PC13 can be used as TAMPER pin, RTC alarm clock or second output; PC14 and PC15 can only be used as LSE pins; when used as output pins, they can only work in 2MHz mode, the maximum driving load is 30pF, and cannot be used as a current source (such as driving LED).

Note 3: These pins are in the main function state when the backup area is powered on for the first time. Even after reset, the state of these pins is controlled by the backup area registers (these registers will not be reset by the main reset system). For specific information on how to control these IO ports, please refer to the relevant chapters on the battery backup area and BKP register in the CH32FV2x_V3xRM datasheet.

Note 4: For chips with neither BOOT0 nor BOOT1/PB2 pins lead out, the internal BOOT0 pin has been shorted to GND and the BOOT1/PB2 pins are floating. Under low power consumption, it is recommended to configure PB2 in pull-down input mode to prevent additional current.

For chips where the BOOT1/PB2 pin is lead out but the BOOT0 pin is not, the BOOT0 pin is internally shorted to GND.

For chips with the BOOT0 pin but not the BOOT1/PB2 pin, the internal BOOT1/PB2 pin has been shorted to GND. Under low power consumption, it is recommended to configure the PB2 pull-down input mode to prevent additional current.

Note 5: The BOOT0 and PB8 pins are in a packaged chip. It is recommended to connect an external 4.7K pull-down resistor to ensure that BOOT0 is low level during power-on in order to enter the program flash memory boot mode. After normal operation, the PB8 pin can be used for output as needed.

Note 6: The 28-pin package chip has many combined pins (at least 2 IO function pins are physically combined into one pin). At this time, the driver should not configure the output function at the same time, otherwise the pins may be damaged. Pay attention to the pin status if there are power consumption requirements.

Note 7: The value after the underline in the remapping function indicates the configuration value of the corresponding bit in the AFIO register. For example: UART4_RX_3 means that the corresponding bit of the AFIO register is configured as 11b.

Note 8: TIM2_CH1 and TIM2_ETR share a common pin, but cannot be used at the same time.
## 3.3 Pin alternate functions

Note: The pin function in the table below refer to all functions and does not involve specific model(s). There are differences in peripheral resources between different models. Please confirm whether this function is available according to the particular model's resource table before viewing this table.

*Table 3-2 Pin alternate  and  remapping functions*

| Alternate Pin | ADC | TIM1 | TIM2/3/4/5 | UART/USART | USB | SYS | I 2 C | SPI | ETH | OPA | CAN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PA0 | ADC_IN0 |  | TIM2_CH1 TIM2_ETR TIM2_CHI_ETR_2 TIM5_CH1 | USART2_CTS |  | WKUP |  |  |  |  |  |
| PA1 | ADC_IN1 |  | TIM2_CH2 TIM2_CH2_2 TIM5_CH2 | USART2_RTS |  |  |  |  |  |  |  |
| PA2 | ADC_IN2 |  | TIM2_CH3 TIM2_CH3_1 TIM5_CH3 | USART2_TX |  |  |  |  |  | OPA2_OUT0 |  |
| PA3 | ADC_IN3 |  | TIM2_CH4 TIM2_CH4_1 TIM5_CH4 | USART2_RX |  |  |  |  |  | OPA1_OUT0 |  |
| PA4 | ADC_IN4 |  |  | USART2_CK |  |  |  | SPI1_NSS |  | OPA2_OUT1 |  |
| PA5 | ADC_IN5 |  |  | USART1_CTS_2 USART1_CK_3 |  |  |  | SPI1_SCK |  | OPA2_CH1N |  |
| PA6 | ADC_IN6 | TIM1_BKIN_1 | TIM3_CH1 | USART1_TX_3 |  |  |  | SPI1_MISO |  | OPA1_CH1N |  |
| PA7 | ADC_IN7 | TIM1_CH1N_1 | TIM3_CH2 | USART1_RX_3 |  |  |  | SPI1_MOSI |  | OPA2_CH1P |  |
| PA8 |  | TIM1_CH1 TIM1_CH1_1 |  | USART1_CK USART1_CK_1 USART1_RX_2 |  | MCO |  |  |  |  |  |
| PA9 |  | TIM1_CH2 TIM1_CH2_1 |  | USART1_TX USART1_RTS_2 |  |  |  |  |  |  |  |
| PA10 |  | TIM1_CH3 TIM1_CH3_1 |  | USART1_RX USART1_CK_2 |  |  |  |  |  |  |  |
| PA11 |  | TIM1_CH4 TIM1_CH4_1 |  | USART1_CTS USART1_CTS_1 | USBDM |  |  |  |  |  | CAN1_RX |
| PA12 |  | TIM1_ETR TIM1_ETR_1 |  | USART1_RTS USART1_RTS_1 | USBDP |  |  |  |  |  | CAN1_TX |
| PA13 |  |  |  |  |  | SWDIO |  |  |  |  |  |
| PA14 |  |  |  |  |  | SWCLK |  |  |  |  |  |
| PA15 |  |  | TIM2_CH1_ETR_1 TIM2_CH1_ETR_3 |  |  |  |  | SPI1_NSS |  |  |  |
| PB0 | ADC_IN8 | TIM1_CH2N_1 | TIM3_CH3 TIM3_CH3_2 | UART4_TX_1 |  |  |  |  |  | OPA1_CH1P |  |
| PB1 | ADC_IN9 | TIM1_CH3N_1 | TIM3_CH4 TIM3_CH4_2 | UART4_RX_1 |  |  |  |  |  | OPA1_OUT1 |  |
| PB2 |  |  |  |  |  | BOOT1 |  |  |  |  |  |
| PB3 |  |  | TIM2_CH2_1 TIM2_CH2_3 |  |  |  |  | SPI1_SCK |  |  |  |
| Alternate Pin ADC | TIM1 | TIM2/3/4/5 | UART/USART | USB | SYS | I 2 C | SPI | ETH | OPA | CAN |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| PB4 |  | TIM3_CH1_2 |  |  |  |  | SPI1_MISO |  |  |  |
| PB5 |  | TIM3_CH2_2 |  |  |  | I 2 C1_SMBA | SPI1_MOSI |  |  |  |
| PB6 |  | TIM4_CH1 | USART1_TX_1 | USBFS_DM |  | I 2 C1_SCL |  |  |  |  |
| PB7 |  | TIM4_CH2 | USART1_RX_1 | USBFS_DP |  | I 2 C1_SDA |  |  |  |  |
| PB8 |  | TIM4_CH3 |  |  |  | I 2 C1_SCL |  |  |  | CAN1_RX |
| PB9 |  | TIM4_CH4 |  |  |  | I 2 C1_SDA |  |  |  | CAN1_TX |
| PB10 |  | TIM2_CH3_2 TIM2_CH3_3 | USART3_TX |  |  | I 2 C2_SCL |  |  | OPA2_CH0N |  |
| PB11 |  | TIM2_CH4_2 TIM2_CH4_3 | USART3_RX |  |  | I 2 C2_SDA |  |  | OPA1_CH0N |  |
| PB12 | TIM1_BKIN |  | USART3_CK |  |  | I 2 C2_SMBA | SPI2_NSS |  |  |  |
| PB13 | TIM1_CH1N |  | USART3_CTS USART3_CTS_1 |  |  |  | SPI2_SCK |  |  |  |
| PB14 | TIM1_CH2N |  | USART3_RTS USART3_RTS_1 |  |  |  | SPI2_MISO |  | OPA2_CH0P |  |
| PB15 | TIM1_CH3N |  | USART1_TX_2 |  |  |  | SPI2_MOSI |  | OPA1_CH0P |  |
| PC0 ADC_IN10 |  |  |  |  |  |  |  |  |  |  |
| PC1 ADC_IN11 |  |  |  |  |  |  |  |  |  |  |
| PC2 ADC_IN12 |  |  |  |  |  |  |  |  |  |  |
| PC3 ADC_IN13 |  |  |  |  |  |  |  |  |  |  |
| PC4 ADC_IN14 |  |  | USART1_CTS_3 |  |  |  |  |  |  |  |
| PC5 ADC_IN15 |  |  | USART1_RTS_3 |  |  |  |  |  |  |  |
| PC6 |  | TIM3_CH1_3 |  |  |  |  |  | ETH_RXP |  |  |
| PC7 |  | TIM3_CH2_3 |  |  |  |  |  | ETH_RXN |  |  |
| PC8 |  | TIM3_CH3_3 |  |  |  |  |  | ETH_TXP |  |  |
| PC9 |  | TIM3_CH4_3 |  |  |  |  |  | ETH_TXN |  |  |
| PC10 |  |  | UART4_TX USART3_TX_1 |  |  |  |  |  |  |  |
| PC11 |  |  | UART4_RX USART3_RX_1 |  |  |  |  |  |  |  |
| PC12 |  |  | USART3_CK_1 |  |  |  |  |  |  |  |
| PC13 |  |  |  |  | TAMPER_RTC |  |  |  |  |  |
| PC14 |  |  |  |  | OSC32_IN |  |  |  |  |  |
| PC15 |  |  |  |  | OSC33_OUT |  |  |  |  |  |
| PD2 |  | TIM3_ETR TIM3_ETR_2 TIM3_ETR_3 |  |  |  |  |  |  |  |  |
## Chapter 4 Electrical Characteristics

## 4.1 Test conditions

Unless otherwise specified and marked, all voltages are referenced to VSS .

All minimum and maximum values are guaranteed in the worst conditions of ambient temperature, supply voltage and clock frequency. Typical values are based on normal temperature (25 ℃ ) and VDD  = 3.3V environment, which are given only as design guidelines.

The data based on comprehensive evaluation, design simulation or technology characteristics are not tested in production. On the basis of comprehensive evaluation, the minimum and maximum values refer to sample tests. Unless otherwise specified that is tested, the characteristic parameters are guaranteed by comprehensive evaluation or design.

Power supply scheme:

*Figure 4-1 Typical circuit for conventional power supply*

[Figure-9](226,328,360,469)

V2.7                                               24

## 4.2 Absolute maximum ratings

Stresses at or above the absolute maximum ratings listed in the table below may cause permanent damage to the device.

*Table 4-1 Absolute maximum ratings*

| Symbol | Description | Min. | Max. | Unit |
| --- | --- | --- | --- | --- |
| T A | Ambient temperature during operation | Ambient temperature during operation -40 | 85 | ℃ |
| T_S | Ambient temperature during storage | Ambient temperature during storage -40 | 125 | ℃ |
| VDD -V SS | External main supply voltage (including VDDA  and VDD ) | External main supply voltage (including VDDA  and VDD ) -0.3 | 4.0 | V |
| V_I/O -V SS | I/O domain supply voltage | I/O domain supply voltage -0.3 | 4.0 | V |
| V IN | Input voltage on the FT (5V tolerance) pin | Input voltage on the FT (5V tolerance) pin VSS -0.3 | 5.5 | V |
| V IN | Input voltage on other pins | Input voltage on other pins VSS -0.3 | VDD +0.3 |  |
| \| △ V DD_x \| | Variations between different main power supply pins | Variations between different main power supply pins | 50 | mV |
| \| △ V IO_x \| | Variations between different I/O power supply pins | Variations between different I/O power supply pins | 50 | mV |
| Symbol | Description | Min. | Max. | Unit |
| --- | --- | --- | --- | --- |
| \| △ V SS_x \| | Variations between different ground pins | Variations between different ground pins | 50 | mV |
|  | Electrostatic discharge voltage (human body model, non-contact) | Electrostatic discharge voltage (human body model, non-contact) 4K |  | V |
| VESD(HBM) | USB pins (PA11, PA12) | USB pins (PA11, PA12) 3K |  | V |
| VESD(HBM) I_VDD | Total current into VDD /VDDA /VIO  power lines (source) | Total current into VDD /VDDA /VIO  power lines (source) | 150 |  |
| I_Vss | Total current out of VSS  ground lines (sink) | Total current out of VSS  ground lines (sink) | 150 |  |
|  | Sink current on any I/O and control pin | Sink current on any I/O and control pin | 25 |  |
| I_I/O | Output current on any I/O and control pin | Output current on any I/O and control pin | -25 | mA |
| I_I/O | Injected current on NRST pin | Injected current on NRST pin | +/-5 | mA |
| I_INJ(PIN) | Injected current on HSE's OSC_IN pin and LSE's OSC_IN pin | Injected current on HSE's OSC_IN pin and LSE's OSC_IN pin | +/-5 |  |
|  | Injected current on other pins | Injected current on other pins | +/-5 |  |
| ∑I_INJ(PIN) | Total injected current on all I/Os and control pins | Total injected current on all I/Os and control pins | +/-25 |  |

## 4.3 Electrical characteristics

## 4.3.1 Operating conditions

*Table 4-2 General operating conditions*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
| F HCLK | Internal HB clock frequency |  |  | 144 | MHz |
| F PCLK1 | Internal PB1 clock frequency |  |  | 144 | MHz |
| F PCLK2 | Internal PB2 clock frequency |  |  | 144 | MHz |
|  |  |  | 2.4 | 3.6 |  |
| VDD | Standard operating voltage | Use USB or ETH | 3.0 | 3.6 | V |
| VDD VIO | Standard operating voltage Output voltage on most I/O pins | V_I/O  cannot be more than VDD | 2.4 | 3.6 | V_V |
|  | Analog operating voltage (ADC is not used) | VDDA  must be the same as V_I/O , VREF+ cannot be | 2.4 | 3.6 | V |
| VDDA | Analog operating voltage (ADC is used) | higher than VDDA , VREF-  is equal to VSS. | 2.4 | 3.6 | V |
| VDDA VBAT (1) | Backup operating voltage |  | 1.8 | 3.6 | V |
| T A | Ambient temperature |  | -40 | 85 | ℃ |
| T_J | Junction temperature range |  | -40 | 105 | ℃ |

Note: 1. The connection line from the battery to VBAT  should be as short as possible.

*Table 4-3 Power-on and power-down conditions*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
|  | VDD  rise time rate |  | 0 | ∞ |  |
| tVDD | VDD  fall time rate |  | 20 | ∞ | us/V |
| tVDD | VDDA  rise time rate |  | 0 | 10000 | us/V |
| tVDDA | VDDA  fall time rate | VDD  is powered | 20 | ∞ | us/V |
| tVDDA |  | VDD  is powered |  |  | us/V |
## 4.3.2 Embedded reset and power control block characteristics

*Table 4-4 Reset and voltage monitor (For PDR, select high threshold gear)*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
|  |  | PLS[2:0] = 000 (rising edge) |  | 2.39 |  | V |
|  |  | PLS[2:0] = 000 (falling edge) |  | 2.31 |  | V |
|  |  | PLS[2:0] = 001 (rising edge) |  | 2.56 |  | V |
|  |  | PLS[2:0] = 001 (falling edge) |  | 2.48 |  | V |
|  |  | PLS[2:0] = 010 (rising edge) |  | 2.65 |  | V |
|  |  | PLS[2:0] = 010 (falling edge) |  | 2.57 |  | V |
|  |  | PLS[2:0] = 011 (rising edge) |  | 2.78 |  | V |
| VPVD (1) | Programmable voltage | PLS[2:0] = 011 (falling edge) |  | 2.69 |  | V |
| VPVD (1) | detector level selection | PLS[2:0] = 100 (rising edge) |  | 2.89 |  | V |
|  |  | PLS[2:0] = 100 (falling edge) |  | 2.81 |  | V |
|  |  | PLS[2:0] = 101 (rising edge) |  | 3.05 |  | V |
|  |  | PLS[2:0] = 101 (falling edge) |  | 2.96 |  | V |
|  |  | PLS[2:0] = 110 (rising edge) |  | 3.17 |  | V |
|  |  | PLS[2:0] = 110 (falling edge) |  | 3.08 |  | V |
|  |  | PLS[2:0] = 111 (rising edge) |  | 3.31 |  | V |
|  |  | PLS[2:0] = 111 (falling edge) |  | 3.21 |  | V |
| V PVDhyst | PVD hysteresis |  |  | 0.08 |  | V |
|  | Power-on/power-down | Rising edge | 1.9 | 2.2 | 2.4 | V |
| VPOR/PDR | reset threshold | Falling edge | 1.9 | 2.2 | 2.4 | V |
| VPOR/PDR V PDRhyst | PDR hysteresis |  |  | 20 |  | mV |
|  | Power on reset |  | 24 | 28 | 30 |  |
| t RSTTEMPO | Other resets |  | 8 | 10 | 30 | mS |
| t RSTTEMPO |  |  |  |  |  | mS |

Note: 1. Normal temperature test value.

## 4.3.3 Embedded reference voltage

*Table 4-5 Embedded reference voltage*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| V REFINT | Internal reference voltage | T A  = -40℃~85℃ | 1.17 | 1.2 | 1.23 | V |
|  | ADC sampling time when |  |  |  |  |  |
| T S_vrefint | reading the internal |  | 17.1 |  |  | us |
|  | reference voltage |  |  |  |  |  |

## 4.3.4 Supply current characteristics

Current consumption is a comprehensive index of a variety of parameters and factors. These parameters and factors include operating voltage, ambient temperature, I/O pin load, the software configuration of the product, the operating frequency, flip rate of the I/O pin, the location of the program in memory and the executed code, etc. The current consumption measurement method is as follows:
*Figure 4-2 Current consumption measurement*

[Figure-3](257,82,343,190)

The microcontroller is in the following conditions:

Under normal temperature conditions and when VDD  = 3.3V, all I/O ports are configured with pull-down inputs, only one of HSE and HIS is enabled, HSE=32M, HIS=8M (calibrated), F PLCK1 =F HCLK /2, F PLCK2 =F HCLK , PLL is enabled when F HCLK >8MHz. Enable or disable the power consumption of all peripheral clocks.

*Table 4-6-1 Typical current consumption in Run mode, the data processing code runs from the internal Flash*

| Symbol | Parameter | Condition | Condition | All peripherals enabled | Typ. Unit All peripherals disabled (2) | Typ. |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  | F HCLK  = 144MHz | 16.21 | 11.46 |  |
|  |  |  | F HCLK  = 72MHz | 8.44 | 5.99 |  |
|  |  |  | F HCLK  = 48MHz | 5.84 | 4.20 |  |
|  |  |  | F HCLK  = 36MHz | 4.50 | 3.31 |  |
|  |  | External clock | F HCLK  = 24MHz | 3.24 | 2.44 |  |
|  |  |  | F HCLK  = 16MHz | 2.37 | 1.83 |  |
|  |  |  | F HCLK  = 8MHz | 1.38 | 1.12 |  |
|  |  |  | F HCLK  = 4MHz | 0.97 | 0.83 |  |
| I_DD (1) | Supply |  | F HCLK  = 500KHz | 0.60 | 0.58 |  |
| I_DD (1) | Supply current in |  | F HCLK  = 144MHz | 15.61 | mA 10.65 |  |
|  | current in Run mode |  | F HCLK  = 72MHz | 8.06 | mA 5.60 |  |
|  | Run mode | Runs on the | F HCLK  = 48MHz | 5.56 | 3.92 |  |
|  |  | the high-speed internal | F HCLK  = 36MHz | 4.31 | 3.07 |  |
|  |  | high-speed internal RC oscillator (HSI). | F HCLK  = 24MHz | 3.07 | 2.24 |  |
|  |  | RC oscillator (HSI). Uses HB prescaler to reduce the | F HCLK  = 16MHz | 2.24 | 1.69 |  |
|  |  | Uses HB prescaler to reduce the frequency. | F HCLK  = 8MHz | 1.28 | 1.02 |  |
|  |  | frequency. | F HCLK  = 4MHz | 0.88 | 0.76 |  |
|  |  |  | F HCLK  = 500KHz | 0.53 | 0.51 |  |

Note: 1. The above are measured parameters.

2. During the test, the clocks of USART1 and GPIOA are not disabled when all peripheral clocks are disabled.
*Table 4-6-2 BLE power consumption*

| Symbol |  | Parameter | Parameter Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- |
|  |  | RX |  |  | 15.2 |  |  |
| I_DD(BLE) (1) |  | -18dBm | Under normal temperature |  | 6.28 |  | mA |
| I_DD(BLE) (1) | TX | 0dBm | VDD  = 3.3V |  | 12.8 |  | mA |
|  |  | +7dBm |  |  | 35.1 |  |  |

Note: 1. The above are measured parameters.

*Table 4-7 Typical current consumption in Sleep mode, data processing code runs from internal Flash or SRAM*

| Symbol | Parameter | Condition | Condition | All peripherals enabled | Typ. Unit All peripherals disabled (2) | Typ. |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  | F HCLK  = 144MHz | 8.24 | 3.34 |  |
|  |  |  | F HCLK  = 72MHz | 4.40 | 1.95 |  |
|  |  |  | F HCLK  = 48MHz | 3.14 | 1.51 |  |
|  |  |  | F HCLK  = 36MHz | 2.51 | 1.29 |  |
|  | Supply | External clock | F HCLK  = 24MHz | 1.89 | 1.08 |  |
|  | current in |  | F HCLK  = 16MHz | 1.47 | 0.93 |  |
|  | Sleep mode |  | F HCLK  = 8MHz | 0.94 | 0.67 |  |
|  | (In this |  | F HCLK  = 4MHz | 0.74 | 0.61 |  |
| I_DD (1) | case, |  | F HCLK  = 500KHz | 0.58 | 0.56 |  |
| I_DD (1) | peripheral |  | F HCLK  = 144MHz | 8.25 | mA 3.30 |  |
|  | power |  | F HCLK  = 72MHz | 4.38 | mA 1.90 |  |
|  | supply and | Runs on the | F HCLK  = 48MHz | 3.11 | 1.46 |  |
|  | clock are | Runs the high-speed internal | F HCLK  = 36MHz | 2.47 | 1.23 |  |
|  | maintained) | high-speed internal RC oscillator (HSI). | F HCLK  = 24MHz | 1.84 | 1.01 |  |
|  |  | RC oscillator (HSI). Uses HB prescaler reduce the | F HCLK  = 16MHz | 1.42 | 0.87 |  |
|  |  | Uses HB prescaler to reduce the frequency. | F HCLK  = 8MHz | 0.87 | 0.61 |  |
|  |  | to frequency. | F HCLK  = 4MHz | 0.67 | 0.54 |  |
|  |  |  | F HCLK  = 500KHz | 0.51 | 0.49 |  |

Note: 1. The above are measured parameters.

2. During the test, the clocks of USART1, GPIOA and power module are not disabled.

*Table 4-8 Typical current consumption in Stop and Standby mode*

| Symbol | Parameter | Condition | Typ. | Unit |
| --- | --- | --- | --- | --- |
| I_DD | Supply current in Stop mode | Voltage regulator in Run mode, low-speed and high-speed internal RC oscillators and external oscillators off (no independent watchdog) | 269.2 | uA |
| Symbol |  | Parameter |  | Condition | Typ. Unit |
| --- | --- | --- | --- | --- | --- |
|  |  |  |  | Voltage regulator in low-power mode, low-speed and high-speed internal RC oscillators and external oscillators off (no independent watchdog, PVD off), RAM enters low-power mode | 32.7 |
|  |  |  |  | Low-speed internal RC oscillator and independent watchdog on, all RAM not powered | 1.6 |
|  |  |  |  | Low-speed internal RC oscillator on, independent watchdog off, all RAM not powered | 1.6 |
|  | mode | Supply current in Standby | Supply current in Standby | Supply current in Standby LSI/LSE/RTC/IWDG off, 32K_RAM powered and in low-power mode | 2.5 |
|  |  |  |  | LSI/LSE/RTC/IWDG off, 2K_RAM powered and in low-power mode | 1.2 |
|  |  |  |  | LSI/LSE/RTC/IWDG off, all RAM not powered | 1.0 |
| I DD_VBAT | Backup | domain current (Remove VDD  and VDDA , only powered by VBAT | supply current (Remove VDD  and VDDA , only powered by VBAT | current (Remove VDD  and VDDA , only powered by VBAT Low-speed external oscillator and RTC on | 1.63 |

Note: The above are measured parameters.

## 4.3.5 External clock source characteristics

*Table 4-9 From external high-speed clock*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| F HSE_ext | External clock frequency |  |  | 32 |  | MHz |
| VHSEH (1) | OSC_IN   input pin high level voltage |  | 0.8VIO |  | VIO | V |
| VHSEL (1) | OSC_IN input pin low-level voltage |  | 0 |  | 0.2VIO | V |
| C in(HSE) | OSC_IN input capacitance |  |  | 5 |  | pF |
| DuCy (HSE) | Duty cycle |  |  | 50 |  | % |
| I_L | OSC_IN   input leakage current |  |  |  | ±1 | uA |

Note: 1. Failure to meet this condition may cause level recognition error.
*Figure 4-3 External high-frequency clock source circuit*

[Figure-3](204,81,361,155)

*Table 4-10 From external low-speed clock*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| F LSE_ext | User external clock frequency |  |  | 32.768 | 1000 | KHz |
| VLSEH | OSC32_IN input pin high level voltage |  | 0.8VDD |  | VDD | V |
| VLSEL | OSC32_IN input pin low voltage |  | 0 |  | 0.2VDD | V |
| C in(LSE) | OSC32_IN input capacitance |  |  | 5 |  | pF |
| DuCy (LSE) | Duty cycle |  |  | 50 |  | % |
| I_L | OSC32_IN input leakage current |  |  |  | ±1 | uA |

Circuit reference design and requirements:

The load capacitance of the crystal is subject to the recommendation of the crystal manufacturer, CL1 =CL2 . For the CH32V208xx series, they are connected with external 32M crystals, and they have built-in load

*Table 4-11 High-speed external clock generated from a crystal/ceramic resonator*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| F OSC_IN | Resonator frequency |  |  | 32 (2) |  | MHz |
| R_F | Feedback resistance |  |  | 250 |  | kΩ |
|  | Recommended load |  |  |  |  |  |
| C | capacitance and corresponding crystal series impedance RS | R_S =60Ω (1) |  | 20 |  | pF |
| I 2 | HSE drive current |  |  | 0.53 |  | mA |
| g m | Oscillator transconductance | Startup |  | 17 |  | mA/V |
| tSU(HSE) | Startup time | VDD   is stable, 8M crystal |  | 2.5 (2) |  | ms |

Note 1: It is recommended that the crystal ESR does not exceed 80Ω, and crystals with smaller ESR are preferred. For load capacitance, refer to the crystal manual requirements.

- 2. Startup time refers to the time difference from when HSEON is turned on to when HSERDY is set.

- 3. No external load capacitor is required.

*Figure 4-4 External low-frequency clock source circuit*

[Figure-15](204,369,361,443)
capacitor, so the external circuit is not necessary.

|  |  | OSC_IN 32MHz Crystal Oscillator CL1 CL2 | OSC_OUT |  |  |  |
| --- | --- | --- | --- | --- | --- | --- |
| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| R_F | Feedback resistance |  |  | 5 |  | MΩ |
|  | Recommended load capacitance |  |  |  |  |  |
| C | and corresponding crystal serial impedance  R_S | R_S <70kΩ |  |  | 15 | pF |
| i 2 | LSE drive current | VDD = 3.3V |  | 0.35 |  | uA |
| g m | Oscillator transconductance | Startup |  | 25.3 |  | uA/V |
| tSU(LSE) | Startup time | VDD is stable |  | 800 |  | mS |

*Figure 4-5 Typical circuit of external 32M crystal*

V2.7                                               31

## 4.3.6 Internal clock source characteristics

*Table 4-13 Internal high-speed (HSI) RC oscillator characteristics*

| Symbol | Parameter |  | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F HSI | Frequency (after calibration) | Frequency (after calibration) |  |  | 8 |  | MHz |
| DuCy HSI | Duty cycle |  |  | 45 | 50 | 55 | % |
|  | Accuracy of HSI oscillator (after | Accuracy of HSI oscillator (after | TA = 0℃~70℃ | -1.6 |  | 1.6 | % |
| ACC HSI | calibration) |  | TA = -40℃~85℃ | -2.2 |  | 2.2 | % |
| ACC HSI tSU(HSI) | HSI oscillator | startup |  |  | 10 |  | us |

Circuit reference design and requirements:

The load capacitance of the crystal is subject to the recommendation of the crystal manufacturer, CL1 =CL2 , generally 12pF is recommended.

*Figure 4-6 Typical circuit of external 32.768K crystal*

[Figure-12](266,473,360,557)

Note: The load capacitance C_L  is calculated by the following formula: C_L  = CL1  x C L2  / (CL1  + CL2 ) + C stray . C stray  is the capacitance of the pin and the PCB board or PCB-related capacitance. Its typical value is between 2pF and 7pF.

*Table 4-12 Low-speed external clock generated by generated from a crystal/ceramic resonator*

*(fLSE=32.768KHz)*
stabilization time

| I_DD(HSI) HSI oscillator power consumption | 120 180 270 uA |
| --- | --- |

*Table 4-14 Internal low-speed (LSI) RC oscillator characteristics*

| Symbol | Parameter |  | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F LSI | Frequency |  |  | 25 | 39 | 60 | KHz |
| DuCy LSI | Duty cycle |  |  | 45 | 50 | 55 | % |
| ACC LSI | Accuracy of LSI oscillator (after calibration) | Accuracy of LSI oscillator | constant temperature (±1℃), it is recommended calibrate once every 10s | to | ±500 |  | ppm |
| tSU(LSI) | LSI oscillator stabilization time | startup |  |  | 100 |  | us |
| I_DD(LSI) | LSI oscillator consumption | power |  |  | 0.6 |  | uA |

## 4.3.7 PLL characteristics

*Table 4-15 PLL characteristics*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
|  | PLL input clock |  | 4 | 8 | 25 | MHz |
| F PLL_IN | PLL input clock duty cycle |  | 40 |  | 60 | % |
| F PLL_IN F PLL_OUT | PLL multiplier output clock |  | 40 |  | 240 (1) | MHz |
| tLOCK | PLL lock time |  |  |  | 200 | us |

Note 1: The frequency multiplier must be selected to meet the PLL output frequency range.

## 4.3.8 Wakeup time from low-power mode

*Table 4-16 Wakeup time from low-power mode (1)*

| Symbol | Parameter | Condition | Typ. | Unit |
| --- | --- | --- | --- | --- |
| t wusleep | Wakeup from Sleep mode | Wakeup from Sleep mode Wake up using HSI RC clock | 2.6 | us |
|  | Wakeup from Stop mode (voltage regulator is in Run mode) | Wakeup from Stop mode (voltage regulator is in Run mode) Wake on HSI RC clock | 23.1 | us |
| t wustop | Wakeup from Stop mode (voltage regulator is in low-power mode) | Wakeup from Stop mode (voltage regulator is in low-power mode) Voltage regulator wakeup time from low-power mode + HSI RC clock wake up | 299 | us |
|  |  | LDO stabilization time + HSI RC |  |  |
| t WUSTDBY | Wakeup from Standby mode | Wakeup from Standby mode clock wake up + code load time (2) (take 128K as example) | 5.0 | ms |

Note: 1. The above parameters are measured parameters.

2. The code load time is calculated based on the current zero-wait area capacity configured by the chip and the size of the loading configuration clock.
## 4.3.9 Memory characteristics

*Table 4-17 Flash memory characteristics*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| F prog | Programming frequency (1) | Programming frequency (1) T A  = -40℃ ～ 85℃ |  |  | 60 | MHz |
| t prog_page | Page (256 bytes) programming time | Page (256 bytes) programming time T A  = -40℃ ～ 85℃ |  | 2 |  | ms |
| t erase_page | Page (256 bytes) erase time | Page (256 bytes) erase time T A  = -40℃ ～ 85℃ |  | 16 |  | ms |
| t erase_sec | Sector (4K bytes) erase time | Sector (4K bytes) erase time T A  = -40℃ ～ 85℃ |  | 16 |  | ms |
| V_prog | Programming voltage | Programming voltage | 2.4 |  | 3.6 | V |

Note: 1. For the programming frequency of flash, read operation, program operation and erase operation are included. The clock is from HCLK.

*Table 4-18 Flash memory endurance and data retention*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| NEND | Endurance | T A  = 25℃ | 10K | 80K (1) |  | times |
| tRET | Data retention |  | 20 |  |  | year |

Note: The endurance parameter is actual measured, which is not guaranteed.

## 4.3.10 I/O port characteristics

*Table 4-19 General-purpose I/O static characteristics*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
|  | Standard I/O pin, input high level voltage | Standard I/O pin, input high level voltage | 0.41*(V * - 1.8)+1.3 |  | VIO +0.3 | V |
| VIH | FT I/O pin, input high level voltage | FT I/O pin, input high level voltage | 0.42*(V * - 1.8)+1 |  | 5.0 | V |
| VIH VIL | Standard I/O pin, input low-level voltage | Standard I/O pin, input low-level voltage | -0.3 |  | 0.28*(V * - 1.8)+0.6 | V |
| VIL | FT I/O pin, input low-level voltage | FT I/O pin, input low-level voltage | -0.3 |  | 0.32*(V * - 1.8)+0.55 | V |
|  | Standard I/O pin Schmitt trigger voltage hysteresis | Standard I/O pin Schmitt trigger voltage hysteresis | 150 |  |  | mV |
| V_hys | FT I/O pin Schmitt trigger voltage hysteresis | FT I/O pin Schmitt trigger voltage hysteresis | 90 |  |  | mV |
| V_hys |  | Standard I/O port |  |  | 1 |  |
| I_lkg | Input leakage current | Input leakage current FT I/O port |  |  | 3 | uA |
| I_lkg RPU | Input leakage current Weak pull-up equivalent resistance | Input leakage current Weak pull-up equivalent resistance | 30 | 40 | 50 | uA kΩ |
| RPD | Weak pull-down equivalent resistance | Weak pull-down equivalent resistance | 30 | 40 | 50 | kΩ |
| CIO | I/O pin capacitance | I/O pin capacitance |  | 5 |  | pF |

Note: I/O pins are powered by VIO , VDD  or VBAT . V *  in the above table can be expressed as VIO , VDD  or VBAT depending on the specific pin.
## Output drive current characteristics

GPIO (General-Purpose Input/Output Port) can sink or output up to ±8mA current, and sink or output ±20mA current (not strictly to VOL /VOH ). In user applications, the total driving current of all I/O pins cannot exceed the absolute maximum ratings given in Section 4.2:

*Table 4-20-1 Output voltage characteristics(Excluding PC13~PC15 pins)*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
| VOL | Output low level, 8 pins sink current | Output low level, 8 pins sink current TTL port, I_IO  = 8mA |  | 0.4 | V |
| VOH | Output high level, 8 pins source current | 2.7V< V *  <3.6V Output high level, 8 pins source current | VDD -0.4 |  | V |
| VOL | Output low level, 8 pins sink current | Output low level, 8 pins sink current CMOS port, I_IO  = 8mA |  | 0.4 | V |
| VOH | Output high level, 8 pins source current | 2.7V< V *  <3.6V Output high level, 8 pins source current | 2.3 |  | V |
| VOL | Output low level, 8 pins sink current | Output low level, 8 pins sink current I_IO  = 20mA |  | 1.0 | V |
| VOH | Output high level, 8 pins source current | 2.7V< V *  <3.6V Output high level, 8 pins source current | VDD -1.3 |  | V |
| VOL | Output low level, 8 pins sink current | Output low level, 8 pins sink current I_IO  = 6mA |  | 0.4 | V |
| VOH | Output high level, 8 pins source current | 2.4V< V *  <2.7V Output high level, 8 pins source current | VDD -1.3 |  | V |

Note: 1. In the above conditions, if multiple I/O pins are driven at the same time, the total current cannot exceed the absolute maximum ratings given in Table 3.2. In addition, when multiple I/O pins are driven at the same time, the current on the power/ground point is very large, which will cause the voltage drop to make the internal I/O voltage not reach the power supply voltage in the table, resulting in the drive current being less than the nominal value.

- 2. V *  in the above table can be expressed as VIO  or VDD  according to the specific pin.

V2.7                                               34

*Table 4-21 Input/output AC characteristics (Excluding PC13~PC15 pins)*

| MODEx[1:0] configuration | Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| 10 | F max(IO)out | Maximum frequency | CL=50pF, V * =2.7-3.6V |  | 2 | MHz |
| 10 (2MHz) | t_f(IO)out | Output high to low fall time | CL=50pF, V * =2.7-3.6V |  | 125 | ns |
| (2MHz) | t_r(IO)out | Output low to high rise time | CL=50pF, V * =2.7-3.6V |  | 125 | ns |
| 01 | F max(IO)out | Maximum frequency | CL=50pF, V * =2.7-3.6V |  | 10 | MHz |
| (10MHz) | t_f(IO)out | Output high to low fall time | CL=50pF, V * =2.7-3.6V |  | 25 | ns |

*Table 4-20-2 Output voltage characteristics   (For PC13~PC15 pins)*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
| VOL | Output low level, 3 pins sink current | Output low level, 3 pins sink current I_IO  = +5mA 2.7V≤ V *  ≤3.6V |  | 0.4 | V |
| VOH | Output high level, 3 pins source current | Output high level, 3 pins source current I_IO  = +1.5mA 2.7V≤ V *  ≤3.6V | V * -0.4 |  |  |
| VOL | Output low level, 3 pins sink current | Output low level, 3 pins sink current I_IO  = +4mA 2.4V≤ V *  ≤3.6V |  | 0.4 | V |
| VOH | Output high level, 3 pins source current | Output high level, 3 pins source current I_IO  = +1mA 2.4V≤V *  ≤3.6V | V * -0.4 |  |  |

Note: V *  in the above table can be expressed as VDD  or VBAT  according to the specific pin.
|  | t_r(IO)out | Output low to high rise time | Output low to high rise time |  | 25 | ns |
| --- | --- | --- | --- | --- | --- | --- |
|  |  |  | CL=30pF, V * =2.7-3.6V |  | 50 | MHz |
|  | F max(IO)out | Maximum frequency | Maximum frequency CL=50pF, V * =2.7-3.6V |  | 30 | MHz |
| 11 | F max(IO)out | Maximum frequency | Maximum frequency CL=30pF, V * =2.7-3.6V |  | 5 | ns |
| (50MHz) | t_f(IO)out | Output high to low fall time | Output high to low fall time CL=50pF, V * =2.7-3.6V |  | 8 | ns |
|  | t_f(IO)out | Output high to low fall time | Output high to low fall time CL=30pF, V * =2.7-3.6V |  | 5 | ns |
|  | t_r(IO)out | Output low to high rise time | Output low to high rise time CL=50pF, V * =2.7-3.6V |  | 8 | ns |
|  | t_r(IO)out t EXTIpw | Output low to high rise time The EXTI controller detects the pulse width of the external signal | Output low to high rise time The EXTI controller detects the pulse width of the external signal | 10 |  | ns |

Note: 1. V *  in the above table can be expressed as VIO  or VDD  according to the specific pin.

- 2. When PC13, PC14 and PC15 are used as GPIO output pins, they can only work below 2MHz, and the maximum driving load is 30pF.

- 3. The USB interface I/O complies only with the parameter MODEx[1:0]=10b or 01b.

## 4.3.11 NRST pin characteristics

*Table 4-22 External reset pin characteristics*

| Symbol |  | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- |
| VIL(NRST) | NRST voltage | input low-level |  | -0.3 |  | 0.28*(VDD -1.8)+0.6 | V |
| VIH(NRST) | NRST voltage | input high-level |  | 0.41*(VDD -1.8)+1.3 |  | VDD +0.3 | V |
| V_hys(NRST) | NRST | Schmitt Trigger voltage hysteresis | voltage hysteresis | 150 |  |  | mV |
| RPU (1) | resistance | Weak pull-up equivalent resistance | Weak pull-up equivalent | 30 | 40 | 50 | kΩ |
| V_F(NRST) | width | NRST input filtered pulse | NRST input filtered pulse |  |  | 100 | ns |
| VNF(NRST) | pulse width | NRST input not filtered pulse width | NRST input not filtered | 300 |  |  | ns |

Note: 1. The pull-up resistor is a real resistor in series with a switchable PMOS implementation. The resistance of this PMOS/NMOS switch is very small (approximately 10%).

Circuit reference design and requirements:

*Figure 4-7 Typical circuit of external reset pin*

[Figure-12](227,638,342,698)
## 4.3.12 TIM timer characteristics

*Table 4-23-1 TIM1/2/3/4 characteristics*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
|  |  |  | 1 |  | t TIMxCLK |
| t_res(TIM) | Timer reference clock | f TIMxCLK  = 72MHz | 13.9 |  | ns |
| t_res(TIM) | Timer reference clock Timer external clock frequency on |  | 0 | f TIMxCLK /2 | MHz |
| F EXT | CH1 to CH4 | f TIMxCLK  = 72MHz | 0 | 36 | MHz |
| F EXT R esTIM | Timer resolution |  |  | 16 | bit |
|  | 16-bit counter clock cycle when the |  | 1 | 65536 | t TIMxCLK |
| t COUNTER | internal clock is selected | f TIMxCLK  = 72MHz | 0.0139 | 910 | us |
| t COUNTER |  |  |  | 65536 | t TIMxCLK |
| t MAX_COUNT | Maximum possible count | f TIMxCLK  = 72MHz |  | 59.6 | s |
| t MAX_COUNT | Maximum possible count |  |  |  |  |

V2.7                                               36

## 4.3.13 I2C interface characteristics

*Figure 4-8 I²C_bus timing diagram*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
|  |  |  | 1 |  | t TIMxCLK |
| t_res(TIM) | Timer reference clock | f TIMxCLK  = 72MHz | 13.9 |  | ns |
| t_res(TIM) | Timer reference clock Timer external clock frequency on |  | 0 | f TIMxCLK /2 | MHz |
| F EXT | CH1 to CH4 | f TIMxCLK  = 72MHz | 0 | 36 | MHz |
| F EXT R esTIM | Timer resolution |  |  | 32 | 位 |
|  | 32-bit counter clock cycle when the |  | 1 | 2 32 | t TIMxCLK |
| t COUNTER | internal clock is selected | f TIMxCLK  = 72MHz | 0.0139 | 2 32 /72 | us |
| t COUNTER |  |  |  | 2 32 | t TIMxCLK |
| t MAX_COUNT | Maximum possible count | f TIMxCLK  = 72MHz |  | 2 32 *2 32 /72 | us |
| t MAX_COUNT | t_w(SCKH) t_r(SCL) Maximum possible count |  |  |  |  |
| SCL t_h(STA) | t_w(SCKL) t_f(SCL) |  | tSU(STO) |  |  |
|  | t_f(SDA) tSU(SDA) | t_h(SDA) |  |  |  |
| SDA |  |  | t_w(STO:STA) | Repeat start condition | Repeat start condition |
| Start condition | t_r(SDA) Start condition |  | tSU(STA) | Stop condition | Stop condition |

*Table 4-24 I²C interface characteristics*

|  |  |  | Standard I 2 C | Standard I 2 C | Fast I 2 C | Fast I 2 C |
| --- | --- | --- | --- | --- | --- | --- |
| Symbol | Parameter |  |  |  |  | Unit |
| Symbol |  | Min. | Max. | Min. | Max. | Unit |
| Symbol t_w(SCKL) | SCL clock low time | 4.7 |  | 1.2 |  | us |
| t_w(SCKH) | SCL clock high time | 4.0 |  | 0.6 |  | us |
| tSU(SDA) | SDA data setup time | 250 |  | 100 |  | ns |

*Table 4-23-2 TIM1/2/3/4 characteristics*
| t_h(SDA) | SDA data hold time | SDA data hold time 0 |  | 0 | 900 | ns |
| --- | --- | --- | --- | --- | --- | --- |
| t_r(SDA) /t_r(SCL) | SDA and SCL rise time | SDA and SCL rise time | 1000 | 20 |  | ns |
| t_f(SDA) /t_f(SCL) | SDA and SCL fall time | SDA and SCL fall time | 300 |  |  | ns |
| t_h(STA) | Start condition hold time | Start condition hold time 4.0 |  | 0.6 |  | us |
| tSU(STA) | Repeated start condition setup time | Repeated start condition setup time 4.7 |  | 0.6 |  | us |
| tSU(STO) | Stop condition setup time | Stop condition setup time 4.0 |  | 0.6 |  | us |
| t_w(STO:STA) | Time from stop condition to start condition (bus free) | Time from stop condition to start condition (bus free) 4.7 |  | 1.2 |  | us |
| C_b | Capacitive load for each bus | Capacitive load for each bus | 400 |  | 400 | pF |

## 4.3.14 SPI interface characteristics

*Figure 4-9 SPI timing diagram in Master mode*

[Figure-5](66,278,446,521)
*Figure 4-10 SPI timing diagram in Slave mode (CPHA=0)*

[Figure-3](64,80,502,281)

*Figure 4-11 SPI timing diagram in Slave mode (CPHA=1)*

[Figure-5](63,357,486,558)

V2.7                                               38

*Table 4-25 SPI interface characteristics*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
|  |  | Master mode |  | 36 | MHz |
| fSCK /tSCK | SPI clock frequency | Slave mode |  | 36 | MHz |
| fSCK /tSCK t_r(SCK) /t_f(SCK) | SPI clock frequency SPI clock rise and fall time | Load capacitance:C = 30pF |  | 20 | ns |
| tSU(NSS) | NSS setup time | Slave mode | 2tPCLK |  | ns |
| t_h(NSS) | NSS hold time | Slave mode | 2tPCLK |  | ns |
| t_w(SCKH) /t_w(SCKL) | SCK high and low time | Master mode, fPCLK  = 36MHz, | 40 | 60 | ns |
|  |  | Prescaler factor = 4 |  |  |  |
| --- | --- | --- | --- | --- | --- |
| tSU(MI) |  | Master mode | 5 |  | ns |
| tSU(SI) | Data input setup time | Data input setup time Slave mode | 5 |  | ns |
| t_h(MI) | Data input setup time | Data input setup time Master mode | 5 |  | ns |
| t_h(SI) | Data input hold time | Data input hold time Slave mode | 4 |  | ns |
| t a(SO) | Data input hold time Data output access time | Data input hold time Data output access time Slave mode, fPCLK  = 20MHz | 0 | 1tPCLK | ns |
| t_dis(SO) | Data output disable time | Data output disable time Slave mode | 0 | 10 | ns |
| t_V(SO) |  | Slave mode (After enable edge) |  | 25 | ns |
| t_V(MO) | Data output valid time | Data output valid time Master mode (After enable edge) |  | 5 | ns |
| t_h(SO) | Data output valid time | Data output valid time Slave mode (After enable edge) | 15 |  | ns |
| t_h(MO) | Data output hold time | Data output hold time Master mode (After enable edge) | 0 |  | ns |
|  | Data output hold time | Data output hold time |  |  |  |

## 4.3.15 USB interface characteristics

*Table 4-26 USB characteristics*

| Symbol | Parameter | Condition | Min. | Max. | Unit |
| --- | --- | --- | --- | --- | --- |
| VDD | USB operating voltage |  | 3.0 | 3.6 | V |
| VSE | Single-ended receiver threshold | VDD  = 3.3V | 1.2 | 1.9 | V |
| VOL | Static output low level |  |  | 0.3 | V |
| VOH | Static output high level |  | 2.8 | 3.6 | V |
| VHSSQ | High-speed suppression information detection threshold |  | 100 | 150 | mV |
| V HSDSC | High-speed disconnection detection threshold |  | 500 | 625 | mV |
| VHSOI | High-speed idle level |  | -10 | 10 | mV |
| VHSOH | High-speed data high level |  | 360 | 440 | mV |
| VHSOL | High-speed data low level |  | -10 | 10 | mV |

## 4.3.16 12-bit ADC characteristics

*Table 4-27 ADC characteristics*

| Symbol |  | Parameter |  | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| VDDA |  | Supply voltage | Supply voltage |  | 2.4 |  | 3.6 | V |
| VREF+ |  | Positive reference voltage | Positive reference voltage | VREF+  cannot be more than VDDA | 2.4 |  | VDDA | V |
| I_VREF |  | Reference current | Reference current |  |  | 160 | 220 | uA |
| I_DDA |  | Supply current | Supply current |  |  | 480 | 530 | uA |
| fADC |  | ADC clock frequency | ADC clock frequency |  |  |  | 14 | MHz |
| f_S |  | Sampling rate | Sampling rate |  | 0.05 |  | 1 | MHz |
| fTRIG |  | External trigger frequency | External trigger frequency |  |  |  | 16 | 1/fADC |
| VAIN |  | Conversion voltage range | Conversion voltage range |  | 0 |  | VREF+ | V |
| RAIN |  | External input impedance | External input impedance |  |  |  | 50 | kΩ |
| RADC |  | Sampling switch resistance | Sampling switch resistance |  |  | 0.6 | 1 | kΩ |
| CADC | Internal | Internal sample and | hold | hold |  | 8 |  | pF |

V2.7                                               39
|  | capacitor |  |  |  |  |
| --- | --- | --- | --- | --- | --- |
|  |  |  | 40 |  |  |
| t_Iat | Injected trigger conversion latency |  |  | 2 | 1/fADC |
| t_Iatr | Regular trigger conversion latency |  |  | 2 | 1/fADC |
| t_s | Sampling time | 1.5 |  | 239.5 | 1/fADC |
| tSTAB | Power-on time |  |  | 1 | us |
| tCONV | Total conversion time (including sampling time) | 14 |  | 252 | 1/fADC |

Note: Above parameters are guaranteed by design.

The above formula is used to determine the maximum external impedance so that the error can be less than 1/4 LSB. Where N=12 (representing 12-bit resolution).

*Table 4-28 Maximum RAIN when fADC  = 14MHz*

| T_S (cycle) | t_S  (us) | Maximum RAIN (kΩ) |
| --- | --- | --- |
| 1.5 | 0.11 | 0.4 |
| 7.5 | 0.54 | 5.9 |
| 13.5 | 0.96 | 11.4 |
| 28.5 | 2.04 | 25.2 |
| 41.5 | 2.96 | 37.2 |
| 55.5 | 3.96 | 50 |
| 71.5 | 5.11 | Invalid |
| 239.5 | 17.1 | Invalid |

Formula: Maximum RAIN

*Table 4-29 ADC error*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| EO | Offset error | f PCLK2  = 56MHz, |  | ±4 |  |  |
| ED | Differential nonlinearity error | fADC  = 14MHz, RAIN |  | ±2 |  | LSB |
| EL | Integral nonlinearity error | < 10kΩ, VDDA  = 3.3V |  | ±2.5 |  | LSB |

C_p  represents the parasitic capacitance on the PCB and the pad (about 5pF), which may be related to the quality of the pad and PCB layout. A larger C_p  value will reduce the conversion accuracy, the solution is to reduce the fADC  value.
*Figure 4-12 ADC typical connection diagram*

[Figure-3](103,90,448,168)

V2.7                                               41

*Figure 4-13 Analog power supply and decoupling circuit reference*

## 4.3.17 Temperature sensor characteristics

*Table 4-30 Temperature sensor characteristics*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| RTS | Measurement range of temperature sensor |  | -40 |  | 85 | ℃ |
| A TSC | Measurement range of temperature sensor after software calibration |  |  | ±12 |  | ℃ |
| Avg_Slope | Average slope (negative temperature coefficient) |  | 3.8 | 4.3 | 4.7 | mV/℃ |
| V 25 | Voltage at 25℃ |  | 1.34 | 1.40 | 1.46 | V |
| T S_temp | ADC sampling time when reading temperature | fADC  = 14MHz |  |  | 17.1 | us |

## 4.3.18 OPA characteristics

*Table 4-31 OPA characteristics*

| Symbol | Parameter | Condition | Min. | Typ. | Max. | Unit |
| --- | --- | --- | --- | --- | --- | --- |
| VDDA | Supply voltage |  | 2.4 | 3.3 | 3.6 | V |
| CMIR | Common mode input voltage |  | 0 |  | VDDA -0.9 | V |
| V IOFFSET | Input offset voltage |  |  | ±2.5 | ±8 | mV |
| I_LOAD | Drive current |  |  |  | 600 | uA |
| I DDOPAMP | Current consumption | No load, static mode |  | 195 |  | uA |
| CMRR (1) | Common mode rejection ratio | @1KHz |  | 96 |  | dB |
| PSRR (1) | Power supply rejection ratio | @1KHz |  | 86 |  | dB |
| A V (1) | Open loop gain | CLOAD =5pF |  |  | 136 |  | dB |
| --- | --- | --- | --- | --- | --- | --- | --- |
| G BW (1) | Unit gain bandwidth | CLOAD =5pF |  |  | 19 |  | MHz |
| P_M (1) | Phase margin | CLOAD =5pF |  |  | 93 |  |  |
| S R (1) | Slew rate limited | CLOAD =5pF |  |  | 8 |  | V/us |
| t WAKUP (1) | Setup time from shutdown to wake up, 0.1% | Input VDDA /2, CLOAD =5pF,RLOAD =4kΩ | Input VDDA /2, CLOAD =5pF,RLOAD =4kΩ |  |  | 368 | ns |
| RLOAD | Resistive load |  |  | 4 |  |  | kΩ |
| CLOAD | Capacitive load |  |  |  |  | 50 | pF |
|  |  | RLOAD =4kΩ, VDDA | input | VDDA -45 |  |  |  |
| V OHSAT (2) | High saturation output voltage | RLOAD =20kΩ, VDDA | input | VDDA -10 |  |  | mV |
| V OHSAT (2) |  | RLOAD =4kΩ, input 0 | RLOAD =4kΩ, input 0 |  |  | 0.5 |  |
| V OLSAT (2) | Low saturation output voltage | RLOAD =20kΩ, input 0 | RLOAD =20kΩ, input 0 |  |  | 0.5 | mV |
| V OLSAT (2) EN (1) | Low saturation output voltage | RLOAD =4kΩ,@1KHz | RLOAD =4kΩ,@1KHz |  | 83 |  | mV nv |
| EN (1) | Equivalent input voltage noise | RLOAD =4kΩ,@10KHz | RLOAD =4kΩ,@10KHz |  | 42 |  | z H |
|  | Equivalent input voltage noise |  |  |  |  |  |  |

Note: 1. The source simulation is not a real measurement.

2. The load current limits the saturated output voltage.
## Chapter 5 Package and Ordering Information

## Packages

| Package Form | Bidy Size | Pin Pitch | Pin Pitch | Package Description | Order Model |
| --- | --- | --- | --- | --- | --- |
| QFN28 | 4*4mm | 0.4mm | 15.7mil | Quad Flat No-Lead Package | CH32V208GBU6 |
| QFN48 | 5*5mm | 0.35mm | 13.8mil | Quad Flat No-Lead Package | CH32V208CBU6 |
| LQFP64M | 10*10mm | 0.5mm | 19.7mil | Low Profile Quad Flat Pack | CH32V208RBT6 |
| QFN68 | 8*8mm | 0.4mm | 15.7mil | Quad Flat No-Lead Package | CH32V208WBU6 |
Note: All dimensions are in millimeters. The pin center spacing values are nominal values, with no error. Other than that, the dimensional error is not greater than the greater of ±0.2mm or 10%.

## 5.1 QFN28 Package
## 5.2 QFN48 Package

## 5.3 QFN68 Package

V2.7                                                45
## 5.4 LQFP64M Package
## Series Product Naming Rules

| Example: CH32 Device family | V | 3      03     R     8      T      6 | 3      03     R     8      T      6 |
| --- | --- | --- | --- |
| F = ARM-based, general-purpose MCU V = QingKe RISC-V-based, general-purpose MCU L = QingKe RISC-V-based, low power MCU | F = ARM-based, general-purpose MCU V = QingKe RISC-V-based, general-purpose MCU L = QingKe RISC-V-based, low power MCU |  |  |
| X = QingKe RISC-V-based, Dedicated architecture or special IO | X = QingKe RISC-V-based, Dedicated architecture or special IO |  |  |
| Product type |  |  |  |
| 0 = QingKe V2/V4 core, main frequency @48M 1 = M3/ QingKe V3/V4 core, main frequency @72M 3 = QingKe V4F floating-point core, main frequency @144M | 0 = QingKe V2/V4 core, main frequency @48M 1 = M3/ QingKe V3/V4 core, main frequency @72M 2 = M3/ QingKe V4 non-floating-point core, main frequency @144M 3 = QingKe V4F floating-point core, main frequency @144M | 2 = M3/ QingKe V4 non-floating-point core, main frequency @144M |  |
| Device subfamily |  |  |  |
| 03 = General-purpose 05 = Connectivity (USB high-speed, SDIO, dual CAN) | 05 = Connectivity (USB high-speed, SDIO, dual CAN) |  |  |
|  | 07 = Interconnectivity (USB high-speed, dual CAN, Ethernet, DVP, SDIO, FSMC) | 07 = Interconnectivity (USB high-speed, dual CAN, Ethernet, DVP, SDIO, FSMC) | 07 = Interconnectivity (USB high-speed, dual CAN, Ethernet, DVP, SDIO, FSMC) |
| 08 = Wireless (BLE5.X, CAN, USB, Ethernet) | 08 = Wireless (BLE5.X, CAN, USB, Ethernet) |  |  |
| 35 = Connectivity (USB, USB PD) Pin count |  |  |  |
| J = 8 pins       A = 16 pins      F = 20 pins | J = 8 pins       A = 16 pins      F = 20 pins |  |  |
| G = 28 pins      K = 32 pins      T = 36 pins | G = 28 pins      K = 32 pins      T = 36 pins |  |  |
| C = 48 pins      R = 64 pins      W = 68 pins V = 100 pins     Z = 144 pins | C = 48 pins      R = 64 pins      W = 68 pins |  |  |
| Flash memory size |  |  |  |
| 4 = 16 Kbytes of Flash memory |  |  |  |
| 6 = 32 Kbytes of Flash memory |  |  |  |
| 7 = 48 Kbytes of Flash memory |  |  |  |
| 8 = 64 Kbytes of Flash memory |  |  |  |
| B = 128 Kbytes of Flash memory |  |  |  |
| C = 256 Kbytes of Flash memory |  |  |  |
| Package |  |  |  |
|  | T = LQFP      U = QFN       R = QSOP       P = TSSOP       M = SOP | T = LQFP      U = QFN       R = QSOP       P = TSSOP       M = SOP | T = LQFP      U = QFN       R = QSOP       P = TSSOP       M = SOP |
| Temperature range 6 = -40℃~85℃ 7 = -40℃~105℃ 3 = -40℃~125℃ D = -40℃~150℃ |  |  |  |
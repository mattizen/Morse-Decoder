# SPDX-FileCopyrightText: © 2026 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0
#
# Test for the Morse tree LED decoder.
# Timing: base tick = 2^15 clocks, dot = 2^SPEED base ticks.

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, Timer

CLK_NS = 100                 # 10 MHz
BASE_TICK = 1 << 15          # clocks per base tick
SPEED = 1                    # test speed: dot = 2 base ticks = 65536 clocks
UNIT = (1 << SPEED) * BASE_TICK

BIT_KEY = 1 << 0
BIT_HOLD = 1 << 4
BIT_RAW = 1 << 5
BIT_INV = 1 << 7

MORSE = {
    "E": ".", "T": "-", "I": "..", "A": ".-", "N": "-.", "M": "--",
    "S": "...", "U": "..-", "R": ".-.", "W": ".--", "D": "-..", "K": "-.-",
    "G": "--.", "O": "---", "H": "....", "V": "...-", "F": "..-.", "L": ".-..",
    "P": ".--.", "J": ".---", "B": "-...", "X": "-..-", "C": "-.-.", "Y": "-.--",
    "Z": "--..", "Q": "--.-", "5": ".....", "0": "-----", "1": ".----",
}


def node_of(code):
    """Heap index of a Morse code string in the tree (root = 1)."""
    n = 1
    for c in code:
        n = n * 2 + (1 if c == "-" else 0)
    return n


class Keyer:
    def __init__(self, dut, speed=SPEED, hold=False, raw=True, inv=False):
        self.dut = dut
        self.ctrl = (speed << 1) | (BIT_HOLD if hold else 0) | (BIT_RAW if raw else 0) | (BIT_INV if inv else 0)
        self.inv = inv
        self.set_key(False)

    def set_key(self, pressed):
        k = pressed ^ self.inv
        self.dut.ui_in.value = self.ctrl | (BIT_KEY if k else 0)

    async def wait_units(self, n):
        await Timer(int(n * UNIT * CLK_NS), unit="ns")

    async def symbol(self, sym):
        self.set_key(True)
        await self.wait_units(3 if sym == "-" else 1)
        self.set_key(False)
        await self.wait_units(1)          # inter-symbol gap

    async def send(self, code, gap=2):
        """Send one character, then wait `gap` extra units (total gap = gap + 1)."""
        for c in code:
            await self.symbol(c)
        await self.wait_units(gap)


def node(dut):
    return int(dut.uo_out.value) & 0x3F


def done(dut):
    return (int(dut.uo_out.value) >> 6) & 1


async def reset(dut):
    dut.ena.value = 1
    dut.ui_in.value = 0
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 2)


@cocotb.test()
async def test_letters(dut):
    """Decode a few characters in raw output mode."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset(dut)
    k = Keyer(dut)
    await ClockCycles(dut.clk, 2)

    assert node(dut) == 1, "after reset the tree must be at the root"
    assert done(dut) == 1
    assert int(dut.uio_oe.value) == 0xFF
    assert int(dut.uio_out.value) == 0xFD, "column 1 (root) must be active low"

    for ch in ["S", "O", "A", "H", "Q", "5", "1"]:
        code = MORSE[ch]
        # walk the tree symbol by symbol
        for i in range(1, len(code) + 1):
            await k.symbol(code[i - 1])
            exp = node_of(code[:i])
            assert node(dut) == exp, f"{ch}: after '{code[:i]}' expected node {exp}, got {node(dut)}"
            assert done(dut) == 0
        await k.wait_units(2)             # total gap now 3 units -> character complete
        assert done(dut) == 1, f"{ch}: character should be complete"
        assert node(dut) == node_of(code), f"{ch}: node must stay at {node_of(code)}"

    # word gap (>= 8 units) returns to the root
    await k.wait_units(7)
    assert node(dut) == 1, "after the word gap the tree must be back at the root"
    assert done(dut) == 1


@cocotb.test()
async def test_hold_and_error(dut):
    """HOLD keeps the character; more than 5 symbols is an error (node 0)."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset(dut)
    k = Keyer(dut, hold=True)
    await ClockCycles(dut.clk, 2)

    await k.send(MORSE["E"], gap=10)
    assert node(dut) == 2, "HOLD: E must stay lit after a long gap"

    # the next character starts at the root while the key is pressed
    k.set_key(True)
    await k.wait_units(1)
    assert node(dut) == 1, "new character: root while keying the first symbol"
    await k.wait_units(2)                 # dash: 3 units total
    k.set_key(False)
    await k.wait_units(3)
    assert node(dut) == 3, "T expected"

    # six dots -> error (node 0)
    await k.send("......", gap=2)
    assert node(dut) == 0, "6 symbols must give the error node"
    assert done(dut) == 1

    # leaving HOLD: word gap clears the error
    k = Keyer(dut, hold=False)
    await k.wait_units(9)
    assert node(dut) == 1, "error must be cleared after the word gap"


@cocotb.test()
async def test_matrix_and_polarity(dut):
    """LED matrix outputs (row one-hot on uo_out, column active low on uio_out)."""
    cocotb.start_soon(Clock(dut.clk, CLK_NS, unit="ns").start())
    await reset(dut)
    k = Keyer(dut, raw=False)
    await ClockCycles(dut.clk, 2)

    assert int(dut.uo_out.value) == 0x01      # root: row 0
    assert int(dut.uio_out.value) == 0xFD     # root: column 1

    await k.send(MORSE["A"])                  # node 5: row 0, column 5
    assert int(dut.uo_out.value) == 0x01
    assert int(dut.uio_out.value) == 0xDF
    await k.wait_units(7)

    await k.send(MORSE["H"])                  # node 16: row 2, column 0
    assert int(dut.uo_out.value) == 0x04
    assert int(dut.uio_out.value) == 0xFE
    await k.wait_units(7)

    await k.send(MORSE["0"])                  # node 63: row 7, column 7
    assert int(dut.uo_out.value) == 0x80
    assert int(dut.uio_out.value) == 0x7F
    await k.wait_units(7)

    # inverted key (active-low button)
    k = Keyer(dut, raw=True, inv=True)
    await k.wait_units(1)
    assert node(dut) == 1, "idle inverted key must not count as a press"
    await k.send(MORSE["N"])
    assert node(dut) == 6, "N expected with inverted key"

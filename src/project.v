/*
 * Copyright (c) 2026 Matthias Wegmann
 * Morse tree LED decoder for Tiny Tapeout (IHP SG13G2)
 * SPDX-License-Identifier: Apache-2.0
 *
 * Reads a Morse key on ui[0] and walks the Morse binary tree:
 * dot = left child, dash = right child. The current tree node is shown
 * on an 8x8 LED matrix (row on uo_out, column on uio_out), one LED at a time.
 *
 * Node numbering (heap style): root = 1, child = node*2 + symbol (0 = dot, 1 = dash)
 *   E=2 T=3 I=4 A=5 N=6 M=7 S=8 U=9 R=10 W=11 D=12 K=13 G=14 O=15 ... 0(zero)=63
 *   node 0 = error (more than 5 symbols)
 * LED position: row = node[5:3] (uo_out, one-hot, active high, LED anodes)
 *               col = node[2:0] (uio_out, one-hot, active low, LED cathodes)
 */

`default_nettype none

module tt_um_mattizen_morse_tree (
    input  wire [7:0] ui_in,    // Dedicated inputs
    output wire [7:0] uo_out,   // Dedicated outputs
    input  wire [7:0] uio_in,   // IOs: Input path
    output wire [7:0] uio_out,  // IOs: Output path
    output wire [7:0] uio_oe,   // IOs: Enable path (active high: 0=input, 1=output)
    input  wire       ena,      // always 1 when the design is powered, so you can ignore it
    input  wire       clk,      // clock
    input  wire       rst_n     // reset_n - low to reset
);

  // -------------------------------------------------------------------------
  // Control inputs
  // -------------------------------------------------------------------------
  wire       key_in   = ui_in[0] ^ ui_in[7];  // ui[7] = 1: key is active low
  wire [2:0] speed    = ui_in[3:1];           // dot length = 2^speed base ticks
  wire       hold     = ui_in[4];             // 1: keep last character until next key press
  wire       raw_mode = ui_in[5];             // 1: uo_out = {key, done, node[5:0]}

  // -------------------------------------------------------------------------
  // Free-running prescaler
  //   base tick : every 2^15 clocks  (3.3 ms @ 10 MHz)  -> Morse timing unit
  //   db tick   : every 2^11 clocks  (0.2 ms @ 10 MHz)  -> debounce sampling
  // -------------------------------------------------------------------------
  reg [14:0] pre;
  always @(posedge clk) begin
    if (!rst_n) pre <= 15'd0;
    else        pre <= pre + 15'd1;
  end
  wire db_tick   = &pre[10:0];
  wire base_tick = &pre;

  // -------------------------------------------------------------------------
  // Synchronizer + debounce: the key must be stable for 15 db ticks (~3 ms)
  // -------------------------------------------------------------------------
  reg [1:0] key_sync;
  reg       key;       // debounced key, 1 = pressed
  reg [3:0] db_cnt;
  always @(posedge clk) begin
    if (!rst_n) begin
      key_sync <= 2'b00;
      key      <= 1'b0;
      db_cnt   <= 4'd0;
    end else begin
      key_sync <= {key_sync[0], key_in};
      if (key_sync[1] == key) begin
        db_cnt <= 4'd0;
      end else if (db_tick) begin
        if (db_cnt == 4'd15) begin
          key    <= key_sync[1];
          db_cnt <= 4'd0;
        end else begin
          db_cnt <= db_cnt + 4'd1;
        end
      end
    end
  end

  // -------------------------------------------------------------------------
  // Morse decoder: walk the binary tree
  //   press >= 2 units  -> dash, otherwise dot
  //   gap   >= 2 units  -> character complete
  //   gap   >= 8 units  -> back to the root (unless HOLD)
  // -------------------------------------------------------------------------
  wire [10:0] dash_th = 11'd2 << speed;
  wire [10:0] char_th = 11'd2 << speed;
  wire [10:0] word_th = 11'd8 << speed;

  reg        key_prev;
  reg [10:0] dur;        // base ticks since the last key edge (saturating)
  reg [5:0]  node;       // current tree node (1 = root, 0 = error)
  reg        char_done;  // character finished (gap >= 2 units)

  wire key_down = key & ~key_prev;
  wire key_up   = ~key & key_prev;
  wire dash     = (dur >= dash_th);

  always @(posedge clk) begin
    if (!rst_n) begin
      key_prev  <= 1'b0;
      dur       <= 11'd0;
      node      <= 6'd1;
      char_done <= 1'b1;
    end else begin
      key_prev <= key;
      if (key_down) begin
        dur       <= 11'd0;
        char_done <= 1'b0;
        if (char_done) node <= 6'd1;          // new character starts at the root
      end else if (key_up) begin
        dur <= 11'd0;
        if (node == 6'd0 || node[5]) node <= 6'd0;             // error / no room
        else                         node <= {node[4:0], dash}; // descend
      end else begin
        if (base_tick && dur != 11'h7FF) dur <= dur + 11'd1;
        if (!key) begin
          if (dur >= char_th)          char_done <= 1'b1;
          if (dur >= word_th && !hold) node      <= 6'd1;
        end
      end
    end
  end

  // -------------------------------------------------------------------------
  // Outputs: 8x8 LED matrix, one LED at a time
  // -------------------------------------------------------------------------
  wire [7:0] row_oh = 8'b0000_0001 << node[5:3];
  wire [7:0] col_oh = 8'b0000_0001 << node[2:0];

  assign uo_out  = raw_mode ? {key, char_done, node} : row_oh;
  assign uio_out = ~col_oh;
  assign uio_oe  = 8'hFF;

  // List all unused inputs to prevent warnings
  wire _unused = &{ena, uio_in, ui_in[6], 1'b0};

endmodule

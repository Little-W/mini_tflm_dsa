#!/usr/bin/env python3
"""从生产 RTL 提取描述符选择、数据字比较和完整状态更新表达式。"""
from pathlib import Path
import re
import runpy

ROOT = Path(__file__).resolve().parents[2]


def uncomment(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


class Statements:
    """保留实际条件与顺序，只保留指定对象的赋值。"""
    def __init__(self, text, target="state"):
        self.text = uncomment(text)
        self.target = target
        self.pos = 0

    def space(self):
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def word(self, value):
        self.space()
        return re.match(re.escape(value) + r"\b", self.text[self.pos:]) is not None

    def take(self, value):
        assert self.word(value), self.text[self.pos:self.pos + 80]
        self.pos += len(value)

    def balanced(self):
        self.space()
        assert self.text[self.pos] == "("
        start, depth = self.pos, 0
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            depth += (char == "(") - (char == ")")
            if depth == 0:
                return self.text[start:self.pos]
        raise RuntimeError("表达式括号未闭合")

    def parse(self):
        self.space()
        if self.word("begin"):
            self.take("begin")
            items = []
            while not self.word("end"):
                items.append(self.parse())
            self.take("end")
            values = [item for item in items if item]
            return "begin\n" + "\n".join(values) + "\nend" if values else ""
        if self.word("if"):
            self.take("if")
            cond = self.balanced()
            yes, no = self.parse(), ""
            if self.word("else"):
                self.take("else")
                no = self.parse()
            if not yes and not no:
                return ""
            return "if " + cond + " " + (yes or "begin end") + (" else " + no if no else "")
        if self.word("case"):
            self.take("case")
            expr, values, has_default, has_effect = self.balanced(), [], False, False
            while not self.word("endcase"):
                self.space()
                start = self.pos
                self.pos = self.text.index(":", start) + 1
                label = self.text[start:self.pos]
                value = self.parse()
                values.append(label + " " + (value or "begin end"))
                has_default |= "default" in label
                has_effect |= bool(value)
            self.take("endcase")
            if not has_effect:
                return ""
            if not has_default:
                values.append("default: ;")
            return "case " + expr + "\n" + "\n".join(values) + "\nendcase"
        if self.word("for"):
            self.take("for")
            self.balanced()
            assert not self.parse(), "选定赋值不应位于循环中"
            return ""
        start = self.pos
        self.pos = self.text.index(";", start) + 1
        raw = self.text[start:self.pos]
        return raw if re.match(re.escape(self.target) + r"\s*(?:<=|=(?!=))", raw) else ""


def state_body(text):
    first = text.index("  always_ff @(posedge clk or negedge rst_n) begin\n    if (!rst_n) begin\n      state<=IDLE;")
    parser = Statements(text[text.index("begin", first):])
    return parser.parse()


def assignment(text, name):
    return re.search(r"  assign " + re.escape(name) + r"\s*=.*?;", text, re.S)[0] + "\n"


def section(text, start, end):
    first = text.index(start)
    return text[first:text.index(end, first)]


INPUTS = (
    ("win_busy", 1), ("win_frontend_p0", 32), ("win_frontend_q0", 32),
    ("p0_q", 32), ("q0_q", 32), ("dma_rows_q", 5), ("tile_cols", 5), ("tile_valid", 1),
    ("ch0_q", 16), ("cols_q", 5), ("group_c", 16), ("p0", 32), ("q0", 32),
    ("next_group_q", 33), ("rows_q", 5), ("windowed", 1), ("row_base_valid", 1),
    ("coordinate_address_valid", 1), ("row_base_addr", 32), ("word_addr", 32),
    ("addr", 32), ("tap_wrap_bytes", 32), ("tap_step_bytes", 32),
    ("incoming_tap_wrap", 1), ("state", 5), ("word_valid", 1),
    ("rst_n", 1), ("cfg_valid", 1), ("cache_cfg_ready", 1), ("cfg_prepare_phase", 2),
    ("address_step_phase", 2), ("prefetch_phase", 4), ("pred_busy", 1), ("pred_cfg_busy", 1),
    ("pred_cfg_pending", 1), ("cache_cfg_pending", 1), ("cache_hint_pending", 1),
    ("request_pending", 1), ("configured", 1), ("error", 1),
    ("cache_rsp_valid", 1), ("cache_rsp_error", 1), ("wr_ready", 1),
    ("chunk_reaches_end", 1), ("row_last_q", 1), ("cache_req_ready", 1),
    ("tile_q_before_end", 1), ("tile_rows_in_range", 1),
    ("incoming_base_padding", 1), ("incoming_wrap_padding", 1), ("incoming_step_padding", 1),
    ("geometry_tile", 1), ("next_row_padding", 1), ("row_coordinate_valid", 1),
    ("col_idx", 5), ("active_cols_q", 5), ("chunk_count", 3), ("active_remaining", 5),
    ("group_end_o_equal", 1), ("next_tap_padding", 1), ("next_word_o_equal", 1),
    ("pad_q", 1), ("current_coordinate_valid", 1), ("tap_wrap", 1),
    ("input_c", 16), ("group_offset", 16), ("dilation_w", 16),
    ("ix_step_below_limit", 1), ("input_s16", 1), ("col_remaining", 5), ("group_remaining", 17),
    ("p_fast_valid", 1), ("decode_index", 32), ("group_shape_o_valid", 1),
    ("kernel_shape_o_valid", 1), ("kernel_w", 16), ("tap0", 32),
    ("q_current", 33), ("reduction_len", 32), ("ix", 35), ("iy", 35),
    ("input_w", 16), ("input_h", 16),
)


def body(text):
    previous = runpy.run_path(str(ROOT / "test/frontend_incoming_depth/formal.py"))
    regions = previous["REGIONS"]
    # 原版的步长位于字比较之前，当前版的步长位于描述符比较的 generate 内。
    word_start = "  // 两种步长的低位进位并行计算，晚到的描述符比较只选择进位结果。"
    words = section(text, word_start, regions["word"][1])
    compare = section(text, *regions["fast"])
    delta = assignment(text, "incoming_delta")
    if "assign incoming_delta" not in compare:
        compare += delta
    result = section(text, *regions["group"]) + compare + words
    result += assignment(text, "incoming_word_hit")
    result += section(text, "  if (p_cfg_idle_use_lut) begin : g_cfg_idle_lut", "  assign finishing_tile=")
    for name in ("finishing_tile", "tile_ready_context", "tile_ready", "wr_valid", "wr_last",
                 "byte_offset_sum", "word_boundary", "stream_context", "stream_next_request"):
        result += assignment(text, name)
    first = text.index("  always_comb begin\n    incoming_tap=tap0;")
    selected = Statements(text[text.index("begin", first):], "incoming_padding").parse()
    result += "\nalways_comb " + selected + "\n"
    selected = re.sub(r"\bstate\s*<=", "state_nxt =", state_body(text))
    result += "\nalways_comb begin\n state_nxt=state;\n" + selected + "\nend\n"
    for field in ("group_c", "windowed", "input_c", "group_offset", "dilation_w", "input_s16", "kernel_w", "input_w", "input_h"):
        result = result.replace("c." + field, field)
    return result


def unit(text, dma, registered=True):
    ports = ",\n".join("input logic " + ("signed " if name in ("ix", "iy") else "") +
                        f"[{width}-1:0] " + ("i_" if registered else "") + name for name, width in INPUTS)
    result = "module delta_path(" + ("input logic clk,\n" if registered else "") + ports + """,
output logic [4:0] o_state,
output logic o_word_equal, o_live_equal, o_word_hit);
localparam int SIZE=16, RW=5, CONV_RW=5, TILE_COUNT_W=5, CHUNK_COUNT_W=3, COORD_W=35, CACHE_POLICY=3;
localparam bit p_cfg_idle_use_lut=1'b1;
logic [31:0] frontend_i_tile_p0,frontend_i_tile_q0;
logic [4:0] frontend_i_tile_rows;
logic win_payload_select;
logic [4:0] tile_rows;
logic [31:0] tile_p0,tile_q0;
logic [31:0] incoming_delta;
logic [2:0] incoming_step_low_sum,incoming_wrap_low_sum;
logic incoming_q_equal;
logic [29:0] incoming_word_i_a,incoming_word_i_b,incoming_word_i_target,incoming_live_word_i_target;
logic incoming_word_i_carry_in,incoming_word_o_equal,incoming_live_word_o_equal,incoming_word_hit;
logic incoming_group_fits,incoming_fast,incoming_q_fast;
logic [5:0] incoming_fast_i_flags;
logic [1:0] incoming_position_equal;
logic [31:0] ch0;
logic prefetch_active;
logic cfg_ready,tile_ready_context,tile_ready,wr_valid,wr_last,finishing_tile;
logic [3:0] byte_offset_sum;
logic word_boundary,stream_context,stream_next_request,incoming_padding;
logic [4:0] state_nxt;
"""
    if registered:
        result += "\n".join("logic " + ("signed " if name in ("ix", "iy") else "") +
                            f"[{width}-1:0] {name};" for name, width in INPUTS) + "\n"
        result += "always_ff @(posedge clk) begin\n" + "\n".join(name + "<=i_" + name + ";" for name, _ in INPUTS) + "\nend\n"
    result += re.search(r"typedef enum logic \[4:0\].*?} st_t;", text, re.S)[0] + "\n"
    selections = "\n".join(assignment(dma, "frontend_i_tile_" + name) for name in ("p0", "q0", "rows"))
    selections = selections.replace(" : rows_q;", " : dma_rows_q;")
    result += assignment(dma, "win_payload_select") + selections
    result += """
assign tile_p0=frontend_i_tile_p0;
assign tile_q0=frontend_i_tile_q0;
assign tile_rows=frontend_i_tile_rows;
assign ch0=32'(ch0_q);
assign prefetch_active=prefetch_phase!=4'd0;
""" + body(text)
    if registered:
        result += "always_ff @(posedge clk) begin\no_state<=state_nxt;\no_word_equal<=incoming_word_o_equal;\no_live_equal<=incoming_live_word_o_equal;\no_word_hit<=incoming_word_hit;\nend\n"
    else:
        result += "assign o_state=state_nxt;\nassign o_word_equal=incoming_word_o_equal;\nassign o_live_equal=incoming_live_word_o_equal;\nassign o_word_hit=incoming_word_hit;\n"
    return result + "endmodule\n"

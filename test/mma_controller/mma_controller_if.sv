/* verilator lint_off DECLFILENAME */
// IA Loader接口
interface ia_loader_if(input logic clk);
    logic load_ia_req;
    logic load_ia_granted;
    logic send_ia_trigger;
    logic ia_sending_done;
    logic ia_calc_done;
    logic ia_data_valid;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output load_ia_req;
        input  load_ia_granted;
        input  send_ia_trigger;
        output ia_sending_done;
        output ia_calc_done;
        output ia_data_valid;
    endclocking

    modport controller (
        input  load_ia_req,
        output load_ia_granted,
        output send_ia_trigger,
        input  ia_sending_done,
        input  ia_calc_done,
        input  ia_data_valid
    );

    modport tb (
        output load_ia_req,
        input  load_ia_granted,
        input  send_ia_trigger,
        output ia_sending_done,
        output ia_calc_done,
        output ia_data_valid
    );
endinterface

// Weight Loader接口
interface weight_loader_if(input logic clk);
    logic load_weight_req;
    logic load_weight_granted;
    logic send_weight_trigger;
    logic weight_sending_done;
    logic weight_data_valid;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output load_weight_req;
        input  load_weight_granted;
        input  send_weight_trigger;
        output weight_sending_done;
        output weight_data_valid;
    endclocking

    modport controller (
        input  load_weight_req,
        output load_weight_granted,
        output send_weight_trigger,
        input  weight_sending_done,
        input  weight_data_valid
    );

    modport tb (
        output load_weight_req,
        input  load_weight_granted,
        input  send_weight_trigger,
        output weight_sending_done,
        output weight_data_valid
    );
endinterface

// Bias Loader接口
interface bias_loader_if(input logic clk);
    logic load_bias_req;
    logic load_bias_granted;
    logic bias_valid;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output load_bias_req;
        input  load_bias_granted;
        output bias_valid;
    endclocking

    modport controller (
        input  load_bias_req,
        output load_bias_granted,
        input  bias_valid
    );

    modport tb (
        output load_bias_req,
        input  load_bias_granted,
        output bias_valid
    );
endinterface

// Requantization接口
interface requant_if(input logic clk);
    logic load_quant_req;
    logic load_quant_granted;
    logic quant_params_valid;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output load_quant_req;
        input  load_quant_granted;
        output quant_params_valid;
    endclocking

    modport controller (
        input  load_quant_req,
        output load_quant_granted,
        input  quant_params_valid
    );

    modport tb (
        output load_quant_req,
        input  load_quant_granted,
        output quant_params_valid
    );
endinterface

// OA Writer接口
interface oa_writer_if(input logic clk);
    logic write_oa_req;
    logic write_oa_granted;
    logic write_done;
    logic oa_calc_over;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output write_oa_req;
        input  write_oa_granted;
        output write_done;
        output oa_calc_over;
    endclocking

    modport controller (
        input  write_oa_req,
        output write_oa_granted,
        input  write_done,
        input  oa_calc_over
    );

    modport tb (
        output write_oa_req,
        input  write_oa_granted,
        output write_done,
        output oa_calc_over
    );
endinterface

// Compute Core接口
interface compute_core_if(input logic clk);
    logic partial_sum_calc_over;
    logic tile_calc_over;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output partial_sum_calc_over;
        output tile_calc_over;
    endclocking

    modport controller (
        input partial_sum_calc_over,
        input tile_calc_over
    );

    modport tb (
        output partial_sum_calc_over,
        output tile_calc_over
    );
endinterface

// 控制接口
interface control_if #(
    parameter int unsigned REG_WIDTH = 32
)(input logic clk);
    logic                 calc_start;
    logic                 cfg_16bits_ia;
    logic                 sa_ready;
    logic [          2:0] icb_sel;
    logic                 init_cfg_ia;
    logic                 init_cfg_weight;
    logic                 init_cfg_bias;
    logic                 init_cfg_requant;
    logic                 init_cfg_oa;
    logic                 use_16bits;
    logic [REG_WIDTH-1:0] tile_count;
    logic                 fifo_full_flag;

    // Clocking block for testbench
    clocking cb @(posedge clk);
        default input #1ns output #1ns;
        output calc_start;
        output cfg_16bits_ia;
        input  sa_ready;
        input  icb_sel;
        input  init_cfg_ia;
        input  init_cfg_weight;
        input  init_cfg_bias;
        input  init_cfg_requant;
        input  init_cfg_oa;
        input  use_16bits;
        input  tile_count;
        output fifo_full_flag;
    endclocking

    modport controller (
        input  calc_start,
        input  cfg_16bits_ia,
        output sa_ready,
        output icb_sel,
        output init_cfg_ia,
        output init_cfg_weight,
        output init_cfg_bias,
        output init_cfg_requant,
        output init_cfg_oa,
        output use_16bits,
        output tile_count,
        input  fifo_full_flag
    );

    modport tb (
        output calc_start,
        output cfg_16bits_ia,
        input  sa_ready,
        input  icb_sel,
        input  init_cfg_ia,
        input  init_cfg_weight,
        input  init_cfg_bias,
        input  init_cfg_requant,
        input  init_cfg_oa,
        input  use_16bits,
        input  tile_count,
        output fifo_full_flag
    );
endinterface
/* verilator lint_on DECLFILENAME */
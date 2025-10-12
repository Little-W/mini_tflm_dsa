`ifndef MMA_INTERFACES_SVH
`define MMA_INTERFACES_SVH

// IA Loader Interface
interface ia_loader_if;
    logic load_req;
    logic load_granted;
    logic send_trigger;
    logic sending_done;
    logic calc_done;
    logic data_valid;

    modport controller (
        input  load_req,
        input  sending_done,
        input  calc_done,
        input  data_valid,
        output load_granted,
        output send_trigger
    );

    modport loader (
        output load_req,
        output sending_done,
        output calc_done,
        output data_valid,
        input  load_granted,
        input  send_trigger
    );
endinterface

// Weight Loader Interface
interface weight_loader_if;
    logic load_req;
    logic load_granted;
    logic send_trigger;
    logic sending_done;
    logic data_valid;

    modport controller (
        input  load_req,
        input  sending_done,
        input  data_valid,
        output load_granted,
        output send_trigger
    );

    modport loader (
        output load_req,
        output sending_done,
        output data_valid,
        input  load_granted,
        input  send_trigger
    );
endinterface

// Bias Loader Interface
interface bias_loader_if;
    logic load_req;
    logic load_granted;
    logic valid;

    modport controller (
        input  load_req,
        input  valid,
        output load_granted
    );

    modport loader (
        output load_req,
        output valid,
        input  load_granted
    );
endinterface

// Requantization Interface
interface requant_if;
    logic load_req;
    logic load_granted;
    logic params_valid;

    modport controller (
        input  load_req,
        input  params_valid,
        output load_granted
    );

    modport requant (
        output load_req,
        output params_valid,
        input  load_granted
    );
endinterface

// OA Writer Interface
interface oa_writer_if;
    logic write_req;
    logic write_granted;
    logic write_done;
    logic calc_over;

    modport controller (
        input  write_req,
        input  write_done,
        input  calc_over,
        output write_granted
    );

    modport writer (
        output write_req,
        output write_done,
        output calc_over,
        input  write_granted
    );
endinterface

// Compute Core Interface
interface compute_core_if;
    logic partial_sum_calc_over;
    logic tile_calc_over;

    modport controller (
        input partial_sum_calc_over,
        input tile_calc_over
    );

    modport core (
        output partial_sum_calc_over,
        output tile_calc_over
    );
endinterface

// ICB Arbiter Slave Interface
interface icb_slave_if;
    logic req;
    logic granted;
    logic done;

    modport master (
        output req,
        input  granted,
        output done
    );

    modport arbiter (
        input  req,
        output granted,
        input  done
    );
endinterface

`endif

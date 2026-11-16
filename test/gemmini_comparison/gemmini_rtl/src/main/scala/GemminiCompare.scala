package comparison

import chisel3._
import chisel3.util._
import chisel3.experimental.DataMirror
import chisel3.util.experimental.BoringUtils
import org.chipsalliance.cde.config._
import freechips.rocketchip.diplomacy._
import freechips.rocketchip.rocket._
import freechips.rocketchip.subsystem._
import freechips.rocketchip.system.DefaultConfig
import freechips.rocketchip.tile._
import freechips.rocketchip.tilelink._
import freechips.rocketchip.amba.axi4._
import gemmini._

class HardwareIm2ColConfig(base: GemminiArrayConfig[SInt, Float, Float])
  extends GemminiArrayConfig[SInt, Float, Float](
    opcodes = base.opcodes,
    inputType = base.inputType,
    weightType = base.weightType,
    accType = base.accType,
    spatialArrayInputType = base.spatialArrayInputType,
    spatialArrayWeightType = base.spatialArrayWeightType,
    spatialArrayOutputType = base.spatialArrayOutputType,
    dataflow = base.dataflow,
    tileRows = base.tileRows,
    tileColumns = base.tileColumns,
    meshRows = base.meshRows,
    meshColumns = base.meshColumns,
    ld_queue_length = base.ld_queue_length,
    st_queue_length = base.st_queue_length,
    ex_queue_length = base.ex_queue_length,
    reservation_station_entries_ld = base.reservation_station_entries_ld,
    reservation_station_entries_st = base.reservation_station_entries_st,
    reservation_station_entries_ex = base.reservation_station_entries_ex,
    sp_banks = base.sp_banks,
    sp_singleported = base.sp_singleported,
    sp_capacity = base.sp_capacity,
    spad_read_delay = base.spad_read_delay,
    acc_banks = base.acc_banks,
    acc_singleported = base.acc_singleported,
    acc_sub_banks = base.acc_sub_banks,
    acc_capacity = base.acc_capacity,
    acc_latency = base.acc_latency,
    dma_maxbytes = base.dma_maxbytes,
    dma_buswidth = base.dma_buswidth,
    shifter_banks = base.shifter_banks,
    aligned_to = base.aligned_to,
    mvin_scale_args = base.mvin_scale_args,
    mvin_scale_acc_args = base.mvin_scale_acc_args,
    mvin_scale_shared = base.mvin_scale_shared,
    acc_scale_args = base.acc_scale_args,
    acc_read_full_width = base.acc_read_full_width,
    acc_read_small_width = base.acc_read_small_width,
    use_dedicated_tl_port = base.use_dedicated_tl_port,
    tlb_size = base.tlb_size,
    use_tlb_register_filter = base.use_tlb_register_filter,
    max_in_flight_mem_reqs = base.max_in_flight_mem_reqs,
    ex_read_from_spad = base.ex_read_from_spad,
    ex_read_from_acc = base.ex_read_from_acc,
    ex_write_to_spad = base.ex_write_to_spad,
    ex_write_to_acc = base.ex_write_to_acc,
    hardcode_d_to_garbage_addr = base.hardcode_d_to_garbage_addr,
    use_shared_tlb = base.use_shared_tlb,
    tile_latency = base.tile_latency,
    mesh_output_delay = base.mesh_output_delay,
    use_tree_reduction_if_possible = base.use_tree_reduction_if_possible,
    num_counter = base.num_counter,
    has_training_convs = base.has_training_convs,
    has_max_pool = base.has_max_pool,
    has_nonlinear_activations = base.has_nonlinear_activations,
    has_dw_convs = base.has_dw_convs,
    has_normalizations = base.has_normalizations,
    has_first_layer_optimizations = base.has_first_layer_optimizations,
    has_loop_conv = base.has_loop_conv,
    use_firesim_simulation_counters = base.use_firesim_simulation_counters,
    use_shared_ext_mem = base.use_shared_ext_mem,
    use_tl_ext_mem = base.use_tl_ext_mem,
    tl_ext_mem_base = base.tl_ext_mem_base,
    clock_gate = base.clock_gate,
    headerFileName = base.headerFileName) {
  override val hasIm2Col = true
}

class GemminiCompare(spKiB: Int = 256, accKiB: Int = 64, busBits: Int = 32, inflight: Int = 4, enableIm2Col: Boolean = false, dmaMaxBytes: Int = 64)
  (implicit p: Parameters) extends LazyModule {
  val visibility = TLEphemeralNode()
  val gp = p.alterPartial {
    case TileVisibilityNodeKey => visibility
    case TileKey => RocketTileParams(core = RocketCoreParams(useVM = false, useDebug = false, nPMPs = 0))
    case MaxHartIdBits => 1
  }
  val baseConfig = GemminiConfigs.defaultConfig.copy(
    sp_capacity = CapacityInKilobytes(spKiB),
    acc_capacity = CapacityInKilobytes(accKiB),
    dma_buswidth = busBits,
    dma_maxbytes = dmaMaxBytes,
    max_in_flight_mem_reqs = inflight,
    clock_gate = false,
    has_loop_conv = true,
    has_dw_convs = true,
    has_first_layer_optimizations = true)
  val cfg = if (enableIm2Col) new HardwareIm2ColConfig(baseConfig) else baseConfig
  require(cfg.productIterator.toSeq == baseConfig.productIterator.toSeq,
    "The comparison configuration must preserve every official constructor parameter")
  require(cfg.hasIm2Col == enableIm2Col && cfg.has_loop_conv && cfg.has_dw_convs)
  val accelerator = LazyModule(new Gemmini(cfg)(implicitly[Arithmetic[SInt]], gp))
  val device = new SimpleDevice("comparison-memory", Seq("comparison,memory"))
  val memory = AXI4SlaveNode(Seq(AXI4SlavePortParameters(
    slaves = Seq(AXI4SlaveParameters(
      address = Seq(AddressSet(0, BigInt("ffffffff", 16))),
      resources = device.reg,
      regionType = RegionType.UNCACHED,
      executable = true,
      supportsRead = TransferSizes(1, dmaMaxBytes),
      supportsWrite = TransferSizes(1, dmaMaxBytes),
      interleavedId = Some(0))),
    beatBytes = busBits / 8,
    minLatency = 1)))
  memory := AXI4UserYanker() := TLToAXI4() := visibility := accelerator.node
  override lazy val module = new LazyModuleImp(this) {
    val command_valid = IO(Input(Bool()))
    val command_ready = IO(Output(Bool()))
    val command_funct = IO(Input(UInt(7.W)))
    val command_rs1 = IO(Input(UInt(64.W)))
    val command_rs2 = IO(Input(UInt(64.W)))
    val busy = IO(Output(Bool()))
    val load_busy = IO(Output(Bool()))
    val execute_busy = IO(Output(Bool()))
    val store_busy = IO(Output(Bool()))
    val im2col_active = IO(Output(Bool()))
    val im2col_request_valid = IO(Output(Bool()))
    val im2col_request_ready = IO(Output(Bool()))
    val im2col_response_valid = IO(Output(Bool()))
    val im2col_response_ready = IO(Output(Bool()))
    val mem = IO(new AXI4Bundle(memory.in.head._2.bundle))
    mem <> memory.in.head._1

    def zeroInputs(data: Data): Unit = data match {
      case aggregate: Aggregate => aggregate.getElements.foreach(zeroInputs)
      case element: Element if DataMirror.directionOf(element) == ActualDirection.Input =>
        element := 0.U.asTypeOf(element)
      case _ =>
    }
    zeroInputs(accelerator.module.io)
    accelerator.module.io.cmd.valid := command_valid
    command_ready := accelerator.module.io.cmd.ready
    accelerator.module.io.cmd.bits := 0.U.asTypeOf(accelerator.module.io.cmd.bits)
    accelerator.module.io.cmd.bits.inst.funct := command_funct
    accelerator.module.io.cmd.bits.inst.opcode := "b1111011".U
    accelerator.module.io.cmd.bits.inst.xs1 := true.B
    accelerator.module.io.cmd.bits.inst.xs2 := true.B
    accelerator.module.io.cmd.bits.rs1 := command_rs1
    accelerator.module.io.cmd.bits.rs2 := command_rs2
    accelerator.module.io.cmd.bits.status.prv := 3.U
    accelerator.module.io.cmd.bits.status.dprv := 3.U
    accelerator.module.io.resp.ready := true.B
    busy := accelerator.module.io.busy
    load_busy := false.B
    execute_busy := false.B
    store_busy := false.B
    im2col_active := false.B
    im2col_request_valid := false.B
    im2col_request_ready := false.B
    im2col_response_valid := false.B
    im2col_response_ready := false.B
    BoringUtils.bore(accelerator.module.load_controller.io.busy, Seq(load_busy))
    BoringUtils.bore(accelerator.module.ex_controller.io.busy, Seq(execute_busy))
    BoringUtils.bore(accelerator.module.store_controller.io.busy, Seq(store_busy))
    BoringUtils.bore(accelerator.module.ex_controller.im2col_en, Seq(im2col_active))
    BoringUtils.bore(accelerator.module.im2col.io.req.valid, Seq(im2col_request_valid))
    BoringUtils.bore(accelerator.module.im2col.io.req.ready, Seq(im2col_request_ready))
    BoringUtils.bore(accelerator.module.im2col.io.resp.valid, Seq(im2col_response_valid))
    BoringUtils.bore(accelerator.module.im2col.io.resp.ready, Seq(im2col_response_ready))
  }
}

object Generate extends App {
  implicit val p: Parameters = new DefaultConfig
  val output = args.headOption.getOrElse("generated")
  val sp = args.lift(1).map(_.toInt).getOrElse(256)
  val acc = args.lift(2).map(_.toInt).getOrElse(64)
  val bus = args.lift(3).map(_.toInt).getOrElse(32)
  val outstanding = args.lift(4).map(_.toInt).getOrElse(4)
  val im2col = args.lift(5).exists(_.toBoolean)
  val dmaMaxBytes = args.lift(6).map(_.toInt).getOrElse(64)
  require(dmaMaxBytes >= 16 && dmaMaxBytes <= 1024 && isPow2(dmaMaxBytes))
  lazy val design = LazyModule(new GemminiCompare(sp, acc, bus, outstanding, im2col, dmaMaxBytes))
  (new chisel3.stage.ChiselStage).emitSystemVerilog(
    design.module,
    Array("--target-dir", output))
  val configuration = s"""{
    "dma_max_bytes": ${design.cfg.dma_maxbytes},
    "has_im2col": ${design.cfg.hasIm2Col},
    "has_loop_conv": ${design.cfg.has_loop_conv},
    "has_dw_convs": ${design.cfg.has_dw_convs},
    "has_first_layer_optimizations": ${design.cfg.has_first_layer_optimizations}
  }
  """
  java.nio.file.Files.write(
    java.nio.file.Paths.get(output, "generated_configuration.json"),
    configuration.getBytes(java.nio.charset.StandardCharsets.UTF_8))
  java.nio.file.Files.copy(
    java.nio.file.Paths.get("gemmini_params.h"),
    java.nio.file.Paths.get(output, "gemmini_params.h"),
    java.nio.file.StandardCopyOption.REPLACE_EXISTING)
}

package comparison

import chisel3._
import chisel3.util._
import chisel3.experimental.DataMirror
import chisel3.util.experimental.BoringUtils
import freechips.rocketchip.config._
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
    spatialArrayOutputType = base.spatialArrayOutputType,
    accType = base.accType,
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
    has_first_layer_optimizations = base.has_first_layer_optimizations,
    use_firesim_simulation_counters = base.use_firesim_simulation_counters,
    use_shared_ext_mem = base.use_shared_ext_mem,
    clock_gate = base.clock_gate,
    headerFileName = base.headerFileName) {
  override val hasIm2Col = true
  override def generateHeader(guard: String = "GEMMINI_PARAMS_H"): String = {
    super.generateHeader(guard).replaceAll(
      "(?m)^#define MAX_BYTES [0-9]+$", s"#define MAX_BYTES $dma_maxbytes")
  }
}

class GemminiCompare(spKiB: Int = 32, accKiB: Int = 32, busBits: Int = 64, inflight: Int = 4,
                     enableIm2Col: Boolean = true, spadReadDelay: Int = 1)
  (implicit p: Parameters) extends LazyModule {
  require(Set(32, 64).contains(busBits))
  val maxTransferBytes = (busBits / 8) * 256
  val visibility = TLEphemeralNode()
  val coreClient = TLClientNode(Seq(TLClientPortParameters(Seq(
    TLClientParameters(name = "comparison-core", sourceId = IdRange(0, 1))))))
  val coreManager = TLManagerNode(Seq(TLManagerPortParameters(Seq(
    TLManagerParameters(address = Seq(AddressSet(0, BigInt("ffffffff", 16))),
      supportsGet = TransferSizes(1, maxTransferBytes))), beatBytes = 8)))
  coreManager := visibility := coreClient
  val gp = p.alterPartial {
    case TileVisibilityNodeKey => visibility
    case TileKey => RocketTileParams(core = RocketCoreParams(useVM = false, useDebug = false, nPMPs = 0))
    case MaxHartIdBits => 1
  }
  val baseConfig = GemminiConfigs.defaultConfig.copy(
    sp_capacity = CapacityInKilobytes(spKiB),
    acc_capacity = CapacityInKilobytes(accKiB),
    dma_buswidth = busBits,
    spad_read_delay = spadReadDelay,
    max_in_flight_mem_reqs = inflight,
    dma_maxbytes = maxTransferBytes,
    clock_gate = false)
  val cfg = if (enableIm2Col) new HardwareIm2ColConfig(baseConfig) else baseConfig
  require(cfg.productIterator.toSeq == baseConfig.productIterator.toSeq)
  require(cfg.hasIm2Col == enableIm2Col)
  val accelerator = LazyModule(new Gemmini(cfg)(implicitly[Arithmetic[SInt]], gp))
  val device = new SimpleDevice("comparison-memory", Seq("comparison,memory"))
  val memory = AXI4SlaveNode(Seq(AXI4SlavePortParameters(
    slaves = Seq(AXI4SlaveParameters(
      address = Seq(AddressSet(0, BigInt("ffffffff", 16))),
      resources = device.reg,
      regionType = RegionType.UNCACHED,
      executable = true,
      supportsRead = TransferSizes(1, maxTransferBytes),
      supportsWrite = TransferSizes(1, maxTransferBytes),
      interleavedId = Some(0))),
    beatBytes = busBits / 8,
    minLatency = 1)))
  memory := AXI4UserYanker() := TLToAXI4() := accelerator.node
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
    val dwconv_active = IO(Output(Bool()))
    val loop_dwconv_busy = IO(Output(Bool()))
    val im2col_active = IO(Output(Bool()))
    val im2col_request_valid = IO(Output(Bool()))
    val im2col_request_ready = IO(Output(Bool()))
    val im2col_response_valid = IO(Output(Bool()))
    val im2col_response_ready = IO(Output(Bool()))
    val mem = IO(new AXI4Bundle(memory.in.head._2.bundle))
    mem <> memory.in.head._1
    val coreMaster = coreClient.out.head._1
    val coreSlave = coreManager.in.head._1
    coreMaster.a.valid := false.B
    coreMaster.a.bits := 0.U.asTypeOf(coreMaster.a.bits)
    coreMaster.c.valid := false.B
    coreMaster.c.bits := 0.U.asTypeOf(coreMaster.c.bits)
    coreMaster.e.valid := false.B
    coreMaster.e.bits := 0.U.asTypeOf(coreMaster.e.bits)
    coreMaster.b.ready := true.B
    coreMaster.d.ready := true.B
    coreSlave.a.ready := true.B
    coreSlave.c.ready := true.B
    coreSlave.e.ready := true.B
    coreSlave.b.valid := false.B
    coreSlave.b.bits := 0.U.asTypeOf(coreSlave.b.bits)
    coreSlave.d.valid := false.B
    coreSlave.d.bits := 0.U.asTypeOf(coreSlave.d.bits)

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
    dwconv_active := false.B
    loop_dwconv_busy := false.B
    im2col_active := false.B
    im2col_request_valid := false.B
    im2col_request_ready := false.B
    im2col_response_valid := false.B
    im2col_response_ready := false.B
    BoringUtils.bore(accelerator.module.load_controller.io.busy, Seq(load_busy))
    BoringUtils.bore(accelerator.module.ex_controller.io.busy, Seq(execute_busy))
    BoringUtils.bore(accelerator.module.store_controller.io.busy, Seq(store_busy))
    BoringUtils.bore(accelerator.module.ex_controller.is_dwconv_depthwise, Seq(dwconv_active))
    BoringUtils.bore(accelerator.module.loop_conv_dw_unroller_busy, Seq(loop_dwconv_busy))
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
  val sp = args.lift(1).map(_.toInt).getOrElse(32)
  val acc = args.lift(2).map(_.toInt).getOrElse(32)
  val bus = args.lift(3).map(_.toInt).getOrElse(64)
  val outstanding = args.lift(4).map(_.toInt).getOrElse(4)
  val im2col = args.lift(5).exists(_.toBoolean)
  val spadReadDelay = args.lift(6).map(_.toInt).getOrElse(1)
  lazy val design = LazyModule(new GemminiCompare(sp, acc, bus, outstanding, im2col, spadReadDelay))
  (new chisel3.stage.ChiselStage).emitVerilog(
    design.module,
    Array("--target-dir", output))
  val configuration = s"""{
    "has_im2col": ${design.cfg.hasIm2Col},
    "has_dwconv_dataflow": true,
    "dma_max_bytes": ${design.maxTransferBytes},
    "axi_max_beats": 256,
    "axi_boundary_bytes": 4096,
    "spad_read_delay": $spadReadDelay,
    "convolution_interface": "LoopConv, LoopConvDW and CONFIG_IM2COL",
    "host_interface_bits": 64,
    "external_dma_bits": $bus
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

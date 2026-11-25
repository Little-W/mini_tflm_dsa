"""读取指定版本的 RTL，并统一公共模块名称及可选端口。"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

SOURCE_GROUPS = {
    'conv_im2col_frontend.sv': ('conv_im2col_frontend_pkg.sv', 'conv_im2col_frontend.sv',
                               'conv_im2col_geometry.sv', 'conv_im2col_descriptor.sv',
                               'conv_im2col_stream.sv', 'conv_im2col_prefetch.sv'),
    'npu_top.sv': ('npu_top.sv', 'npu_task_configuration.sv',
                   'npu_output_pipeline.sv', 'npu_matrix_engine.sv',
                   'npu_operand_cache_bridge.sv'),
    'vector_engine.sv': ('vector_engine_control_pkg.sv', 'vector_engine.sv',
                         'vector_engine_control.sv', 'vector_engine_address.sv',
                         'vector_engine_operand_store.sv'),
    'axi_dual_block_dma.sv': ('axi_dual_block_dma.sv', 'dma_register_buffer.sv'),
    'conv_read_cache.sv': ('conv_read_cache.sv', 'conv_read_cache_reference.sv',
                          'conv_windowed_cache.sv', 'conv_cache_metadata_way.sv',
                          'conv_cache_rank_table.sv'),
    'ia_loader.sv': ('ia_loader.sv', 'ia_ordered_coordinate_equal.sv', 'ia_ordered_coordinate_same.sv'),
    'ia_loader_ctrl.sv': ('ia_loader_ctrl.sv', 'ia_row_step_register.sv'),
    'kernel_loader.sv': ('kernel_loader.sv', 'kernel_request_idle.sv',
                         'kernel_candidate_equal.sv', 'kernel_burst_encode.sv'),
    'kernel_loader_ctrl.sv': ('kernel_loader_ctrl.sv', 'kernel_count_increment.sv',
                              'kernel_count_compare.sv', 'kernel_count_next_reaches.sv'),
    'ia_ps_shared_ram.sv': ('ia_ps_shared_ram.sv', 'shared_ram_read_mux.sv', 'ia_ps_channel_ram.sv'),
    'ps_buffer.sv': ('ps_buffer.sv', 'ps_buffer_wide_fifo.sv', 'ps_buffer_exact_ram.sv'),
    'ps_window_scheduler.sv': ('ps_window_scheduler.sv', 'ps_scheduler_any.sv', 'ps_scheduler_priority.sv'),
    'vec_s8_to_fifo.sv': ('vec_s8_to_fifo_full.sv', 'vec_s8_to_fifo_linear.sv',
                         'vec_s8_to_fifo.sv', 'vec_s8_fifo_row_ram.sv', 'fifo_bank_watermark.sv'),
    'ps_frame_store.sv': ('ps_frame_store.sv', 'ps_raw_address.sv', 'ps_frame_store_capacity.sv'),
    'soc_axi_interconnect.sv': ('soc_axi_interconnect.sv', 'soc_axi_step_address.sv'),
    'soc_axi_pingpong_buffer.sv': ('soc_axi_pingpong_chan.sv', 'soc_axil_pingpong_buffer.sv',
        'soc_axi_read_pingpong_buffer.sv', 'soc_axi_write_pingpong_buffer.sv', 'soc_axi_pingpong_buffer.sv'),
    'picorv32_npu.v': ('picorv32_npu.v', 'picorv32_regs.v', 'picorv32_pcpi_mul.v',
        'picorv32_pcpi_fast_mul.v', 'picorv32_pcpi_div.v', 'picorv32_axi.v',
        'picorv32_axi_adapter.v', 'picorv32_wb.v'),
}


def shared_ia_parameters(parameters, module_source):
    """各版本共用共享 SRAM 测试配置，参考模块按其声明选择外部存储。"""
    selected = {name: value for name, value in parameters.items() if name != 'EXTERNAL_RAM'}
    if re.search(r'\bparameter\s+(?:(?:bit|logic|int|integer|unsigned|signed)\s+)*EXTERNAL_RAM\b',
                 module_source):
        selected['EXTERNAL_RAM'] = 1
    return selected


def shared_ia_options(options, module_source):
    """为 read_slang 的同一共享 SRAM 配置生成对应版本的参数选项。"""
    selected = [option for option in options if not option.startswith('-GEXTERNAL_RAM=')]
    if 'EXTERNAL_RAM' in shared_ia_parameters({}, module_source):
        selected.append('-GEXTERNAL_RAM=1')
    return selected


def read_current_source(path, *args, **kwargs):
    """为局部提取与版本比较读取一个功能模块及其独立子模块。"""
    path = Path(path)
    content = path.read_text(*args, **kwargs)
    group = SOURCE_GROUPS.get(path.name)
    if group is None or len(re.findall(r'^\s*module\s+\w+', content, re.M)) != 1:
        return content
    files = [path.with_name(name) for name in group if path.with_name(name).is_file()]
    return '\n'.join(source.read_text(*args, **kwargs) for source in files)


def optional_shared_write_port(content, path, cwd):
    """让默认关闭的共享写数据接口参与不同版本的完整端口比较。"""
    interfaces = {
        'rtl/npu/loaders/ia_loader.sv': ('ia_loader', 'ram_shared_wr_data', 'output'),
        'rtl/npu/loaders/ia_loader_cache_mgr.sv': ('ia_loader_cache_mgr', 'ram_shared_wr_data', 'output'),
        'rtl/npu/buffers/ia_ps_shared_ram.sv': ('ia_ps_channel_ram', 'i_ia_shared_write_data', 'input'),
    }
    if path not in interfaces:
        return content
    module_name, port, direction = interfaces[path]
    port_bytes = port.encode()
    current = Path(cwd) / path
    if not current.exists() or port_bytes not in current.read_bytes() or port_bytes in content:
        return content
    module = re.search(rb'\bmodule\s+' + module_name.encode() + rb'\b', content)
    if module is None:
        raise ValueError('找不到共享写数据接口对应的模块')
    end = re.search(rb'\)\s*;', content[module.end():])
    if end is None:
        raise ValueError('找不到模块端口列表的结束位置')
    start = module.end() + end.start()
    stop = module.end() + end.end()
    prefix = content[:start].rstrip()
    if not prefix.endswith(b','):
        prefix += b','
    declaration = f'\n    {direction} wire [127:0] {port}'
    if direction == 'input':
        declaration += " = 128'd0"
    body = prefix + declaration.encode() + b'\n' + content[start:stop]
    if direction == 'output':
        body += f"\nassign {port} = 128'd0;\n".encode()
    return body + content[stop:]


def read_rtl_source(revision_path, *, cwd=ROOT, text=False):
    revision, separator, path = str(revision_path).partition(':')
    if not separator or not revision or not path:
        raise ValueError('需要提供版本号和仓库内路径')
    result = subprocess.run(['git', 'show', str(revision_path)], cwd=cwd,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode and path == 'rtl/common/regfile.v':
        result = subprocess.run(['git', 'show', f'{revision}:rtl/common/REGFILE.v'], cwd=cwd,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    result.check_returncode()
    content = result.stdout
    if Path(path).suffix in ('.v', '.sv', '.svh', '.vh'):
        content = re.sub(rb'\bREGFILE\b', b'regfile', content)
        content = optional_shared_write_port(content, path, cwd)
    return content.decode() if text else content


def read_rtl_source_group(revision_path, *, cwd=ROOT, text=False):
    """读取指定版本的功能模块与当时存在的独立子模块。"""
    revision, _, name = str(revision_path).partition(':')
    path = Path(name)
    content = read_rtl_source(revision_path, cwd=cwd, text=True)
    group = SOURCE_GROUPS.get(path.name)
    if group is not None and len(re.findall(r'^\s*module\s+\w+', content, re.M)) == 1:
        parts = {}
        for member in group:
            relative = path.with_name(member)
            if member == path.name:
                parts[member] = content
                continue
            exists = subprocess.run(['git', 'cat-file', '-e', f'{revision}:{relative}'],
                                    cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if exists.returncode == 0:
                parts[member] = read_rtl_source(f'{revision}:{relative}', cwd=cwd, text=True)
        content = '\n'.join(parts[member] for member in group if member in parts)
    return content if text else content.encode()

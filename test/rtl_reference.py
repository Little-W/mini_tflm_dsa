"""读取指定版本的 RTL，并统一公共模块名称及可选端口。"""
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]

SOURCE_GROUPS = {'npu_controller.sv': ('npu_controller.sv', 'npu_ia_issue_select.sv'),
 'unsigned_compare.sv': ('unsigned_compare.sv', 'parallel_prefix_native_differences.sv', 'zero_reduce.sv'),
 'add_equal.sv': ('add_equal.sv', 'add_equal_bit.sv', 'add_equal_reduce.sv'),
 'increment_equal.sv': ('increment_equal.sv', 'increment_equal_pair.sv'),
 'onehot_mux.sv': ('onehot_mux.sv', 'onehot_mux_group.sv'),
 'parallel_prefix_add.sv': ('parallel_prefix_add.sv',
                            'parallel_prefix_native_sums.sv',
                            'parallel_prefix_native_differences.sv',
                            'parallel_prefix_high_group.sv'),
 'parallel_unsigned_compare.sv': ('parallel_unsigned_compare.sv',
                                  'parallel_unsigned_compare_leaf.sv',
                                  'parallel_unsigned_compare_merge.sv'),
 'conv_im2col_frontend.sv': ('conv_im2col_frontend_pkg.sv',
        'conv_im2col_frontend.sv',
        'conv_im2col_geometry.sv',
        'conv_im2col_descriptor.sv',
        'conv_im2col_stream.sv',
        'conv_im2col_prefetch.sv',
        'conv_history_wrap_select.sv',
        'conv_geometry_movement_add.sv', 'conv_full_address_add.sv',
        'conv_im2col_descriptor_state.sv',
        'conv_im2col_address_sources.sv',
        'conv_im2col_stream_position.sv',
        'conv_im2col_error_select.sv',
        'conv_im2col_error_operation_select.sv',
        'conv_im2col_error_update.sv',
        'conv_im2col_wrap_update_select.sv',
        'conv_im2col_tile_context.sv',
        'conv_im2col_runtime_registers.sv',
        'conv_im2col_state_control.sv',
        'conv_im2col_wrap_state.sv',
        'conv_im2col_payload_select.sv',
        'conv_im2col_request_index.sv',
        'conv_descriptor_match.sv',
        'conv_descriptor_qualify.sv',
        'conv_descriptor_row_range_result.sv',
        'conv_descriptor_addresses.sv',
        'conv_descriptor_add.sv',
        'conv_descriptor_commit.sv',
        'conv_descriptor_extent.sv',
        'conv_descriptor_position.sv',
        'conv_im2col_stream_control.sv',
        'conv_stream_row_request.sv',
        'conv_stream_tap_request.sv',
        'conv_stream_column_request.sv',
        'conv_im2col_request_control.sv',
        'conv_im2col_mask_end.sv',
        'conv_im2col_group_end_select.sv',
        'conv_im2col_descriptor_request.sv',
        'conv_im2col_chunk_lane.sv',
        'conv_im2col_chunk_end_select.sv',
        'conv_tile_low_difference.sv',
        'conv_tile_high_compare.sv',
        'conv_tile_low_less_select.sv',
        'conv_tile_low_flag_select.sv',
        'conv_tile_group_low5.sv',
        'conv_tile_group_range_result.sv',
        'conv_im2col_sample_sum_group.sv',
        'conv_im2col_sample_sum_carry.sv',
        'conv_im2col_sample_sum_select.sv',
        'conv_im2col_sample_sum.sv',
        'conv_im2col_formatter_reduce.sv',
        'conv_im2col_formatter_mux.sv',
        'conv_im2col_sample_offsets.sv',
        'conv_tile_group_low.sv',
        'conv_descriptor_group_context.sv',
        'conv_descriptor_group_steps.sv',
        'conv_channel_increment_match.sv',
        'conv_descriptor_address_add.sv',
        'conv_descriptor_window_target.sv',
        'conv_group_decode_select.sv',
        'conv_group_high_compare.sv',
        'conv_group_lane_range.sv',
        'conv_group_range_choice.sv',
        'conv_group_range_select.sv',
        'conv_im2col_group_ranges.sv',
        'conv_stream_range_after.sv',
        'conv_word_step_match.sv',
        'conv_count_threshold.sv',
        'conv_history_row_increment.sv',
        'conv_kernel_step_equal.sv',
        'conv_stream_address_select.sv',
        'conv_stream_chunk_end.sv',
        'conv_stream_group_end.sv',
        'conv_stream_group_value.sv',
        'conv_stream_request_eligible.sv',
        'conv_stream_word_select.sv',
        'conv_word_byte_range.sv',
        'conv_stream_epoch_sum.sv',
        'conv_stream_epoch_increment.sv',
        'conv_stream_epoch_low_carry.sv',
        'conv_stream_epoch_carry_bit.sv',
        'conv_stream_format_range.sv'),
 'conv_im2col_geometry.sv': ('conv_im2col_geometry.sv',
                             'conv_history_wrap_select.sv',
                             'conv_geometry_movement_add.sv', 'conv_full_address_add.sv', 'conv_history_row_increment.sv'),
 'conv_channel_range_compare.sv': ('conv_channel_range_compare.sv',
                                   'conv_channel_outside_interval.sv',
                                   'conv_channel_wrap_threshold.sv'),
 'conv_coordinate_range.sv': ('conv_coordinate_range.sv', 'conv_coordinate_range_result.sv'),
 'conv_coordinate_step.sv': ('conv_coordinate_step.sv', 'conv_coordinate_step_four_state.sv',
                             'conv_coordinate_upper_group.sv'),
 'conv_im2col_stream_control.sv': ('conv_im2col_stream_control.sv',
        'conv_stream_row_request.sv', 'conv_stream_tap_request.sv', 'conv_stream_column_request.sv'),
 'conv_axi_read_guard.sv': ('conv_axi_read_guard.sv', 'conv_guard_page_boundary.sv', 'conv_guard_read_valid.sv'),
 'conv_window_queue.sv': ('conv_window_queue.sv',
                          'conv_window_data_enable.sv',
                          'conv_window_data_select.sv',
                          'conv_window_prepared_flag.sv',
                          'conv_window_cols_range.sv',
                          'conv_window_cols_candidates.sv',
                          'conv_window_cols_select.sv'),
 'npu_top.sv': ('npu_top.sv',
                'npu_task_configuration.sv',
                'npu_bias_address_zero.sv',
                'npu_bias_presence.sv',
                'npu_bias_execution_address.sv',
                'npu_frame_row_tiles.sv',
                'npu_packed_extent.sv',
                'npu_task_accept_qualify.sv',
                'npu_output_pipeline.sv',
                'npu_matrix_engine.sv',
                'npu_operand_cache_bridge.sv',
                'npu_output_bias_mask.sv',
                'npu_output_bias_advance.sv',
                'npu_output_bias_row_select.sv'),
 'npu_output_pipeline.sv': ('npu_output_pipeline.sv', 'npu_output_bias_mask.sv',
                            'npu_output_bias_advance.sv',
                            'npu_output_bias_row_select.sv'),
 'vector_engine.sv': ('vector_engine_control_pkg.sv',
                      'vector_window_bounds.sv',
                      'vector_window_request_qualify.sv',
                      'vector_engine.sv',
                      'vector_engine_error_select.sv',
                      'vector_engine_control.sv',
                      'vector_tap_update_select.sv',
                      'vector_engine_address.sv',
                      'vector_window_count_add.sv',
                      'vector_window_count_group.sv',
                      'vector_engine_operand_store.sv',
                      'vector_window_bank_map.sv',
                      'vector_window_valid_mux.sv',
                      'vector_activation_clamp.sv'),
 'axi_dual_block_dma.sv': ('axi_dual_block_dma.sv', 'dma_register_buffer.sv'),
 'conv_read_cache.sv': ('conv_read_cache.sv',
                        'conv_read_cache_reference.sv',
                        'conv_windowed_cache.sv',
                        'conv_cache_offer_duplicate.sv',
                        'conv_cache_prefetch_priority.sv',
                        'conv_cache_queued_read_select.sv',
                        'conv_cache_metadata_way.sv',
                        'conv_cache_rank_table.sv',
                        'conv_cache_snapshot_fields.sv',
                        'conv_cache_registered_equal.sv',
                        'conv_cache_snapshot_equal.sv',
                        'conv_cache_snapshot_range.sv',
                        'conv_cache_next_line.sv',
                        'conv_cache_increment_bit.sv',
                        'conv_cache_offer_match_select.sv',
                        'conv_cache_input_set_match.sv',
                        'conv_cache_lookup_qualification.sv',
                        'conv_cache_tag_qualification.sv',
                        'conv_cache_direct_response.sv',
                        'conv_cache_request_qualification.sv',
                        'conv_cache_work_lookup.sv',
                        'conv_cache_snapshot_response.sv',
                        'conv_cache_response_data_select.sv',
                        'conv_cache_victim_qualification.sv',
                        'conv_cache_metadata_hit_select.sv',
                        'conv_cache_metadata_hit_finish.sv',
                        'conv_cache_metadata_eligibility.sv',
                        'conv_cache_prefetch_epoch_value.sv',
                        'conv_cache_select_busy.sv',
                        'conv_cache_lookup_hit.sv',
                        'conv_cache_demand_lookup.sv',
                        'conv_cache_lookup_qualifier.sv',
                        'conv_cache_demand_hit.sv',
                        'conv_cache_request_path.sv',
                        'conv_cache_queued_preview.sv',
                        'conv_cache_lookup_valid_select.sv',
                        'conv_cache_valid_forward.sv',
                        'conv_cache_metadata_rank_hit.sv',
                        'conv_cache_rank_hit_write.sv'),
 'ia_loader.sv': ('ia_loader.sv', 'ia_ordered_coordinate_equal.sv', 'ia_ordered_coordinate_same.sv',
                   'ia_ordered_coordinate_update.sv'),
 'ia_loader_ctrl.sv': ('ia_loader_ctrl.sv', 'ia_row_step_register.sv', 'ia_completion_select.sv',
                       'ia_burst_decrement.sv'),
 'kernel_loader.sv': ('kernel_loader.sv',
                      'kernel_request_idle.sv',
                      'kernel_candidate_equal.sv',
                      'kernel_burst_encode.sv',
                      'kernel_column_position.sv'),
 'kernel_loader_ctrl.sv': ('kernel_loader_ctrl.sv', 'kernel_completion_check.sv',
                           'kernel_count_increment.sv',
                           'kernel_count_compare.sv',
                           'kernel_count_next_reaches.sv',
                           'kernel_group_step.sv'),
 'kernel_loader_buffer.sv': ('kernel_loader_buffer.sv', 'kernel_column_select4.sv'),
 'bias_loader_buffer.sv': ('bias_loader_buffer.sv', 'bias_bank_readiness.sv',
                           'bias_scalar_word_match.sv',
                           'bias_read_enable_select.sv',
                           'bias_request_end_compare.sv',
                           'bias_resident_qualify.sv'),
 'oa_writer.sv': ('oa_writer.sv', 'oa_writer_compare.sv'),
 'vec_requant.sv': ('vec_requant.sv',
                    'requant_group_difference.sv',
                    'requant_group_last.sv',
                    'requant_load_advance.sv',
                    'requant_parameter_last.sv'),
 'ia_ps_shared_ram.sv': ('ia_ps_shared_ram.sv', 'shared_ram_read_mux.sv', 'shared_ram_capacity_next.sv', 'ia_ps_channel_ram.sv',
                        'ia_channel_segment_enable.sv', 'ia_ps_role_ram.sv',
                            'ps_channel_write_enable.sv', 'ps_channel_read_enable.sv',
                            'ps_channel_request_fault.sv'),
 'ia_ps_channel_ram.sv': ('ia_ps_channel_ram.sv',
                        'ia_channel_segment_enable.sv', 'ia_ps_role_ram.sv',
                            'ps_channel_write_enable.sv', 'ps_channel_read_enable.sv',
                            'ps_channel_request_fault.sv'),
 'ps_buffer.sv': ('ps_buffer.sv', 'ps_buffer_wide_fifo.sv', 'ps_buffer_exact_ram.sv'),
 'ps_window_scheduler.sv': ('ps_window_scheduler.sv', 'ps_scheduler_any.sv', 'ps_scheduler_priority.sv'),
 'vec_s8_to_fifo.sv': ('vec_s8_to_fifo_full.sv',
                       'vec_s8_to_fifo_linear.sv',
                       'vec_s8_to_fifo.sv',
                       'vec_s8_fifo_row_ram.sv',
                       'fifo_bank_watermark.sv', 'fifo_ready_threshold.sv'),
 'ps_frame_store.sv': ('ps_frame_store.sv', 'ps_raw_address.sv', 'ps_frame_store_capacity.sv',
                       'ps_frame_ready_select.sv', 'ps_frame_read_enable.sv', 'ps_frame_address_increment.sv',
                       'ps_frame_prepare_branch.sv', 'ps_frame_prepare_enable.sv'),
 'soc_axi_interconnect.sv': ('soc_axi_interconnect.sv', 'soc_axi_step_address.sv'),
 'soc_axi_pingpong_buffer.sv': ('soc_axi_pingpong_chan.sv',
                                'soc_axil_pingpong_buffer.sv',
                                'soc_axi_read_pingpong_buffer.sv',
                                'soc_axi_write_pingpong_buffer.sv',
                                'soc_axi_pingpong_buffer.sv'),
 'picorv32_npu.v': ('picorv32_frontend_pkg.sv',
                    'picorv32_npu.v',
                    'picorv32_frontend.sv',
                    'picorv32_regs.v',
                    'picorv32_pcpi_mul.v',
                    'picorv32_pcpi_fast_mul.v',
                    'picorv32_pcpi_div.v',
                    'picorv32_axi.v',
                    'picorv32_axi_adapter.v',
                    'picorv32_wb.v',
                    'pico_operand_comparison.sv',
                    'pico_sequential_address.sv',
                    'pico_result_negation.sv'),
 'picorv32_pcpi_div.v': ('picorv32_pcpi_div.v', 'pico_result_negation.sv'),
 'conv_im2col_descriptor.sv': ('conv_im2col_descriptor.sv',
        'conv_descriptor_match.sv',
        'conv_descriptor_qualify.sv',
        'conv_descriptor_row_range_result.sv',
        'conv_descriptor_addresses.sv',
        'conv_descriptor_add.sv',
        'conv_descriptor_commit.sv',
        'conv_descriptor_extent.sv',
        'conv_descriptor_position.sv',
        'conv_channel_increment_match.sv',
        'conv_descriptor_address_add.sv',
        'conv_descriptor_window_target.sv',
        'conv_kernel_step_equal.sv'),
 'conv_im2col_stream.sv': ('conv_im2col_stream.sv',
        'conv_im2col_stream_control.sv',
        'conv_stream_row_request.sv',
        'conv_stream_tap_request.sv',
        'conv_stream_column_request.sv',
        'conv_im2col_request_control.sv',
        'conv_im2col_mask_end.sv',
        'conv_im2col_group_end_select.sv',
        'conv_im2col_descriptor_request.sv',
        'conv_im2col_chunk_lane.sv',
        'conv_im2col_chunk_end_select.sv',
        'conv_tile_low_difference.sv',
        'conv_tile_high_compare.sv',
        'conv_tile_low_less_select.sv',
        'conv_tile_low_flag_select.sv',
        'conv_tile_group_low5.sv',
        'conv_tile_group_range_result.sv',
        'conv_im2col_sample_sum_group.sv',
        'conv_im2col_sample_sum_carry.sv',
        'conv_im2col_sample_sum_select.sv',
        'conv_im2col_sample_sum.sv',
        'conv_im2col_formatter_reduce.sv',
        'conv_im2col_formatter_mux.sv',
        'conv_im2col_sample_offsets.sv',
        'conv_tile_group_low.sv',
        'conv_descriptor_group_context.sv',
        'conv_descriptor_group_steps.sv',
        'conv_channel_increment_match.sv',
        'conv_group_decode_select.sv',
        'conv_group_high_compare.sv',
        'conv_group_lane_range.sv',
        'conv_group_range_choice.sv',
        'conv_group_range_select.sv',
        'conv_im2col_group_ranges.sv',
        'conv_stream_range_after.sv',
        'conv_word_step_match.sv',
        'conv_count_threshold.sv',
        'conv_stream_address_select.sv',
        'conv_stream_chunk_end.sv',
        'conv_stream_group_end.sv',
        'conv_stream_group_value.sv',
        'conv_stream_request_eligible.sv',
        'conv_stream_word_select.sv',
        'conv_word_byte_range.sv',
        'conv_stream_epoch_sum.sv',
        'conv_stream_epoch_increment.sv',
        'conv_stream_epoch_low_carry.sv',
        'conv_stream_epoch_carry_bit.sv',
        'conv_stream_format_range.sv'),
 'conv_windowed_cache.sv': ('conv_windowed_cache.sv',
                            'conv_cache_offer_duplicate.sv',
                        'conv_cache_prefetch_priority.sv',
                        'conv_cache_queued_read_select.sv',
                            'conv_cache_snapshot_fields.sv',
                            'conv_cache_registered_equal.sv',
                            'conv_cache_snapshot_equal.sv',
                            'conv_cache_snapshot_range.sv',
                            'conv_cache_next_line.sv',
                            'conv_cache_increment_bit.sv',
                            'conv_cache_offer_match_select.sv',
                            'conv_cache_input_set_match.sv',
                            'conv_cache_lookup_qualification.sv',
                            'conv_cache_tag_qualification.sv',
                            'conv_cache_direct_response.sv',
                            'conv_cache_request_qualification.sv',
                            'conv_cache_work_lookup.sv',
                            'conv_cache_snapshot_response.sv',
                            'conv_cache_response_data_select.sv',
                            'conv_cache_victim_qualification.sv',
                            'conv_cache_metadata_hit_select.sv',
                            'conv_cache_metadata_hit_finish.sv',
                            'conv_cache_metadata_eligibility.sv',
                            'conv_cache_prefetch_epoch_value.sv',
                            'conv_cache_select_busy.sv',
                            'conv_cache_lookup_hit.sv',
                            'conv_cache_demand_lookup.sv',
                            'conv_cache_lookup_qualifier.sv',
                            'conv_cache_demand_hit.sv',
                            'conv_cache_request_path.sv',
                            'conv_cache_lookup_valid_select.sv'),
 'conv_cache_metadata_way.sv': ('conv_cache_metadata_way.sv',
                                'conv_cache_valid_forward.sv',
                                'conv_cache_metadata_rank_hit.sv'),
 'conv_cache_rank_table.sv': ('conv_cache_rank_table.sv', 'conv_cache_rank_hit_write.sv')}


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

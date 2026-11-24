#!/usr/bin/env python3
"""Reuse identical elaborated source definitions while preserving every instance."""
from __future__ import annotations

from preserve_rtl_hierarchy import circuit_inventory, json_digest, opaque, original_module


SUPPORTED_MODULES = frozenset({'ws_systolic_cell'})
LOCATION_ATTRIBUTES = frozenset({'src', 'hdlname', 'scopename'})


def canonical_definition(design, module):
    """Compare complete resolved definitions under an explicit private-name bijection.

    Public names and all hardware attributes remain exact. Private objects use
    their declaration order; differing orders simply prevent a match. The full
    wire, cell, parameter, and connection records must agree before reuse.
    """
    if opaque(module) or module.has_processes() or module.memories:
        raise RuntimeError('Definition reuse requires a resolved leaf component: ' + design.str(module.name))

    def const(value):
        return [value.as_string(), int(value.flags)]

    def attributes(obj):
        return {design.str(key): const(value) for key, value in obj.attributes.items()
                if design.str(key).lstrip('\\') not in LOCATION_ATTRIBUTES}

    wires = list(module.wires_.values())
    cells = list(module.cells_.values())
    wire_names = {design.str(wire.name): (design.str(wire.name)
                  if design.str(wire.name).startswith('\\') else '@private_wire_' + str(index))
                  for index, wire in enumerate(wires)}
    cell_names = {design.str(cell.name): (design.str(cell.name)
                  if design.str(cell.name).startswith('\\') else '$definition_cell$' + str(index))
                  for index, cell in enumerate(cells)}
    if len({name.lstrip('\\') for name in cell_names.values()}) != len(cell_names):
        raise RuntimeError('Ambiguous canonical cell names in ' + design.str(module.name))

    def signal(value):
        result = []
        for index in range(value.size()):
            bit = value[index]
            result.append(['wire', wire_names[design.str(bit.wire.name)], bit.offset]
                          if bit.wire is not None else ['constant', str(bit.data)])
        return result

    wire_records = {wire_names[design.str(wire.name)]: {
        'width': wire.width, 'start_offset': wire.start_offset, 'upto': wire.upto,
        'signed': wire.is_signed, 'input': wire.port_input, 'output': wire.port_output,
        'port_id': wire.port_id, 'attributes': attributes(wire)} for wire in wires}
    cell_records = {}
    for cell in cells:
        if design.module(cell.type) is not None:
            raise RuntimeError('Definition reuse does not accept nested instances: ' + design.str(module.name))
        cell_records[cell_names[design.str(cell.name)]] = {
            'type': design.str(cell.type), 'attributes': attributes(cell),
            'parameters': {design.str(key): const(value) for key, value in cell.parameters.items()},
            'connections': {design.str(port): signal(value) for port, value in cell.connections().items()}}
    connections = sorted(([signal(left), signal(right)] for left, right in module.connections()),
                         key=lambda item: json_digest(item))
    payload = {'source_module': original_module(design, module),
               'attributes': attributes(module),
               'available_parameters': sorted(design.str(key) for key in module.avail_parameters.keys()),
               'parameter_defaults': {design.str(key): const(value)
                                      for key, value in module.parameter_default_values.items()},
               'wires': wire_records, 'cells': cell_records, 'connections': connections}
    return payload, cell_names, wire_names


def reuse_definitions(design, top, selected, allowed_primitives, requested):
    """Merge equal definitions and audit the complete expanded physical circuit."""
    if not requested or not requested <= SUPPORTED_MODULES:
        raise ValueError('Supported source definition reuse: ' + ', '.join(sorted(SUPPORTED_MODULES)))
    if not requested <= selected:
        raise ValueError('Reused source definitions must retain their original RTL hierarchy')

    reachable = {}

    def walk(module, active):
        name = design.str(module.name)
        if name in active:
            raise RuntimeError('Recursive hierarchy while checking source definitions')
        if name in reachable:
            return
        reachable[name] = module
        for cell in module.cells_.values():
            child = design.module(cell.type)
            if child is not None and not opaque(child):
                walk(child, active | {name})

    walk(design.module('\\' + top), set())
    candidates = {name: module for name, module in reachable.items()
                  if original_module(design, module) in requested}
    found = {original_module(design, module) for module in candidates.values()}
    if found != requested:
        raise RuntimeError('Requested reusable source modules are not active')

    groups, leaf_maps, definition_records = {}, {}, {}
    for name, module in sorted(candidates.items()):
        payload, cells, wires = canonical_definition(design, module)
        signature = json_digest(payload).hex()
        if signature in groups and groups[signature]['definition'] != payload:
            raise RuntimeError('Canonical definition digest collision')
        groups.setdefault(signature, {'definition': payload, 'modules': []})['modules'].append(name)
        leaf_maps[name] = cells
        definition_records[name] = {'canonical_sha256': signature,
                                    'cell_name_bijection': cells, 'wire_name_bijection': wires}

    before = circuit_inventory(design, top, selected, allowed_primitives, leaf_maps)
    replacements = {name: group['modules'][0] for group in groups.values() for name in group['modules'][1:]}
    for module in reachable.values():
        for cell in module.cells_.values():
            kind = design.str(cell.type)
            if kind in replacements:
                cell.type = design.module(replacements[kind]).name
    after = circuit_inventory(design, top, selected, allowed_primitives, leaf_maps)
    fields = ('circuit_sha256', 'state_connections_sha256', 'memory_declarations_sha256',
              'module_port_connections_sha256', 'leaf_cell_count', 'leaf_cell_counts',
              'leaf_pin_count', 'state_cell_count', 'memory_count', 'expanded_module_instances',
              'retained_instance_count', 'top_ports')
    for field in fields:
        if before[field] != after[field]:
            raise RuntimeError('Source definition reuse changed the expanded circuit: ' + field)
    physical = lambda value: {path: {key: item for key, item in entry.items() if key != 'definition'}
                              for path, entry in value['retained_instances'].items()}
    if physical(before) != physical(after):
        raise RuntimeError('Source definition reuse changed physical instance ports')

    referenced_types = {design.str(cell.type) for module in design.modules_.values()
                        for cell in module.cells_.values()}
    for name in replacements:
        # Only unreachable definitions are removed; every original cell instance remains.
        if name in referenced_types:
            raise RuntimeError('A reusable definition still has an unconverted instance')
        design.remove(design.module(name))

    return {'passed': True, 'requested_modules': sorted(requested),
            'ignored_location_attributes': sorted(LOCATION_ATTRIBUTES),
            'private_name_method': 'Exact definition comparison using explicit declaration-order bijections',
            'original_definitions': len(candidates), 'reused_definitions': len(groups),
            'removed_definitions': len(replacements),
            'physical_instance_count': sum(entry['source_module'] in requested
                                           for entry in before['retained_instances'].values()),
            'all_resolved_parameters_equal': True, 'all_hardware_attributes_equal': True,
            'all_leaf_pin_connections_equal': True, 'all_state_connections_equal': True,
            'all_physical_instance_ports_equal': True,
            'before': before, 'after': after, 'definition_records': definition_records,
            'equivalent_definition_groups': groups}

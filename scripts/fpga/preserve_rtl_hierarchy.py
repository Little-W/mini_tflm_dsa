#!/usr/bin/env python3
"""Preserve selected source modules and verify the complete elaborated circuit."""
from __future__ import annotations

import argparse
from array import array
import collections
import hashlib
import json
from pathlib import Path
import re
import shlex


IGNORED_ATTRIBUTES = {'src', 'hdlname', 'scopename', 'keep_hierarchy'}
STATE_PATTERN = re.compile(r'dff|latch|mem', re.IGNORECASE)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(name):
    """Use the same physical instance path before and after Yosys flatten."""
    value = name.lstrip('\\')
    return value.replace('$flatten\\', '').replace('.\\', '.') if value.startswith('$flatten\\') else value


def qualify(path, name):
    return '.'.join(item for item in (path, normalized(name)) if item)


def original_module(design, module):
    if module.has_attribute('\\hdlname'):
        return module.get_string_attribute('\\hdlname').split()[0]
    return design.str(module.name).lstrip('\\').split('$', 1)[0]


def opaque(module):
    return module.get_blackbox_attribute() or module.get_bool_attribute('\\whitebox')


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).digest()


def circuit_inventory(design, top, selected, allowed_primitives, leaf_name_maps=None):
    """Hash every leaf pin, memory, state parameter, and connected top/module port.

    Module boundaries are expanded into an alias graph. The canonical name of a
    net is derived from its physical cell pins and retained ports, so flattening
    intermediate source modules does not change the circuit signature.
    """
    from pyosys import libyosys as yosys

    leaf_name_maps = leaf_name_maps or {}

    def leaf_name(context, cell):
        names = leaf_name_maps.get(design.str(context['module'].name), {})
        local = design.str(cell.name)
        return qualify(context['path'], names.get(local, local))

    constants = ('0', '1', 'x', 'z', '-', 'm')
    constant_ids = {'S0': 0, 'S1': 1, 'Sx': 2, 'Sz': 3, 'Sa': 4, 'Sm': 5}
    parents = array('I', range(len(constants)))
    contexts, retained = [], {}
    all_instances, used_definitions = {}, {}

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def join(first, second):
        first, second = find(first), find(second)
        if first == second:
            return
        if first < len(constants):
            if second < len(constants):
                raise RuntimeError('Conflicting constant connections in the elaborated design')
            parents[second] = first
        else:
            parents[first] = second

    def bit_id(context, bit):
        if bit.wire is None:
            return constant_ids[str(bit.data).split('.')[-1]]
        return context['offsets'][design.str(bit.wire.name)] + bit.offset

    def signal_ids(context, signal):
        return [bit_id(context, signal[index]) for index in range(signal.size())]

    def attributes(obj, excluded=()):
        return {design.str(key).lstrip('\\'): [value.as_string(), int(value.flags)]
                for key, value in obj.attributes.items()
                if design.str(key).lstrip('\\') not in IGNORED_ATTRIBUTES | set(excluded)}

    def walk(module, path, active):
        name = design.str(module.name)
        if name in active or opaque(module):
            raise RuntimeError('Invalid source hierarchy at ' + path + ': ' + name)
        if module.has_processes():
            raise RuntimeError('Unlowered processes remain in ' + name)
        offsets = {}
        for wire in module.wires_.values():
            offsets[design.str(wire.name)] = len(parents)
            parents.extend(range(len(parents), len(parents) + wire.width))
        context = {'module': module, 'path': path, 'offsets': offsets}
        contexts.append(context)
        origin = original_module(design, module)
        ports = {design.str(wire.name).lstrip('\\'): {
                    'width': wire.width, 'input': wire.port_input, 'output': wire.port_output,
                    'port_id': wire.port_id}
                 for wire in module.wires_.values() if wire.port_input or wire.port_output}
        all_instances[path] = {'definition': name.lstrip('\\'), 'source_module': origin,
                               'ports': ports}
        used_definitions[name] = module
        if origin in selected:
            retained[path] = all_instances[path]
        for left, right in module.connections():
            if left.size() != right.size():
                raise RuntimeError('Unequal connection widths in ' + name)
            for index in range(left.size()):
                join(bit_id(context, left[index]), bit_id(context, right[index]))
        for cell in module.cells_.values():
            kind = design.str(cell.type)
            child = design.module(cell.type)
            if child is None:
                if not kind.startswith('$'):
                    raise RuntimeError('Unresolved source instance ' + qualify(path, design.str(cell.name)))
                continue
            if opaque(child):
                if kind.lstrip('\\') not in allowed_primitives:
                    raise RuntimeError('Opaque source instance ' + qualify(path, design.str(cell.name)))
                continue
            child_path = qualify(path, design.str(cell.name))
            child_context = walk(child, child_path, active | {name})
            child_ports = {design.str(wire.name): wire for wire in child.wires_.values()
                           if wire.port_input or wire.port_output}
            connections = {design.str(port): signal for port, signal in cell.connections().items()}
            if not set(connections) <= set(child_ports):
                raise RuntimeError('Unknown source module port connections: ' + child_path)
            all_instances[child_path]['connected_ports'] = sorted(port.lstrip('\\') for port in connections)
            for port, signal in connections.items():
                wire = child_ports[port]
                if signal.size() != wire.width:
                    raise RuntimeError('Source module port width changed: ' + child_path + '.' + port)
                internal = yosys.SigSpec(wire)
                for index in range(signal.size()):
                    join(bit_id(context, signal[index]), bit_id(child_context, internal[index]))
        return context

    top_module = design.module('\\' + top)
    if top_module is None:
        raise RuntimeError('Missing top module ' + top)
    walk(top_module, '', set())

    canonical = {find(index): json_digest(['constant', value]) for index, value in enumerate(constants)}

    def register_pin(node, endpoint):
        root = find(node)
        if root < len(constants):
            return
        token = json_digest(endpoint)
        previous = canonical.get(root)
        if previous is None or token < previous:
            canonical[root] = token

    def leaf_cells(context):
        for cell in context['module'].cells_.values():
            child = design.module(cell.type)
            if child is None or opaque(child):
                yield cell

    for context in contexts:
        path, module = context['path'], context['module']
        if not path or path in retained:
            for wire in module.wires_.values():
                if wire.port_input or wire.port_output:
                    port = design.str(wire.name).lstrip('\\')
                    for index, node in enumerate(signal_ids(context, yosys.SigSpec(wire))):
                        register_pin(node, ['port', path, port, index])
        for cell in leaf_cells(context):
            name = leaf_name(context, cell)
            for port, signal in cell.connections().items():
                for index, node in enumerate(signal_ids(context, signal)):
                    register_pin(node, ['cell', name, design.str(port).lstrip('\\'), index])

    def net(node):
        root = find(node)
        if root not in canonical:
            raise RuntimeError('A circuit connection has no canonical endpoint')
        return canonical[root].hex()

    records, state_records, memory_records = [], [], []
    cell_names, initial_values = set(), set()
    cell_counts = collections.Counter()
    leaf_pin_count = 0
    retained_connections, top_ports = {}, {}
    for context in contexts:
        path, module = context['path'], context['module']
        for wire in module.wires_.values():
            if (not path or path in retained) and (wire.port_input or wire.port_output):
                port = design.str(wire.name).lstrip('\\')
                connections = [net(node) for node in signal_ids(context, yosys.SigSpec(wire))]
                if path:
                    retained_connections.setdefault(path, {})[port] = connections
                else:
                    top_ports[port] = dict(all_instances['']['ports'][port], connections=connections)
            if wire.has_attribute('\\init'):
                value = wire.attributes['\\init'].as_string()[::-1]
                if len(value) != wire.width:
                    raise RuntimeError('Initial-value width differs from the source wire')
                for index, node in enumerate(signal_ids(context, yosys.SigSpec(wire))):
                    if value[index] != 'x':
                        initial_values.add((net(node), value[index]))
        for memory in module.memories.values():
            record = ['memory', qualify(path, design.str(memory.name)), memory.width,
                      memory.size, memory.start_offset, attributes(memory)]
            memory_records.append(json_digest(record))
            records.append(memory_records[-1])
        for cell in leaf_cells(context):
            name, kind = leaf_name(context, cell), design.str(cell.type)
            if name in cell_names:
                raise RuntimeError('Ambiguous expanded cell name: ' + name)
            cell_names.add(name)
            cell_counts[kind.lstrip('\\')] += 1
            parameters = {}
            for key, value in cell.parameters.items():
                key = design.str(key).lstrip('\\')
                parameters[key] = (qualify(path, value.decode_string()) if key == 'MEMID'
                                   else [value.as_string(), int(value.flags)])
            connections = {design.str(port).lstrip('\\'): [net(node) for node in signal_ids(context, signal)]
                           for port, signal in cell.connections().items()}
            leaf_pin_count += sum(len(bits) for bits in connections.values())
            record = json_digest(['cell', name, kind, parameters, attributes(cell), connections])
            records.append(record)
            if STATE_PATTERN.search(kind):
                state_records.append(record)
    records += [json_digest(['top_ports', top_ports]), json_digest(['initial_values', sorted(initial_values)])]
    connected_ports = {'top': top_ports, 'retained': retained_connections}

    def combined(items):
        return hashlib.sha256(b''.join(sorted(items))).hexdigest()

    return {
        'circuit_sha256': combined(records), 'state_connections_sha256': combined(state_records),
        'memory_declarations_sha256': combined(memory_records),
        'module_port_connections_sha256': json_digest(connected_ports).hex(),
        'leaf_cell_count': sum(cell_counts.values()), 'leaf_cell_counts': dict(sorted(cell_counts.items())),
        'leaf_pin_count': leaf_pin_count,
        'state_cell_count': len(state_records), 'memory_count': len(memory_records),
        'expanded_module_instances': len(all_instances) - 1,
        'retained_instances': retained, 'retained_instance_count': len(retained),
        'module_definitions': {name.lstrip('\\'): {'source_module': original_module(design, module),
                                'cells': module.cells_size(), 'source': module.get_src_attribute()}
                               for name, module in used_definitions.items()},
        'top_ports': all_instances['']['ports'],
    }


def production_structure(design, top, destination):
    """Check required production structures along reachable physical instances."""
    matches = {'shared_ram': [], 'partial_sum_store': [], 'clock_buffer': [], 'axi_memory': []}

    def walk(module, path):
        for wire in module.wires_.values():
            name = qualify(path, design.str(wire.name))
            if re.search(r'g_shared_ia_ps\..*u_ram\.', name):
                matches['shared_ram'].append(name)
            if 'u_ps_buffer.g_compressed.u_store.' in name:
                matches['partial_sum_store'].append(name)
        for memory in module.memories.values():
            name = qualify(path, design.str(memory.name))
            if name == 'u_axi_sim_ram.mem_r':
                matches['axi_memory'].append(name)
        for cell in module.cells_.values():
            name = qualify(path, design.str(cell.name))
            if design.str(cell.type).lstrip('\\') == 'BUFGCE':
                matches['clock_buffer'].append(name)
            child = design.module(cell.type)
            if child is not None and not opaque(child):
                walk(child, name)

    walk(design.module('\\' + top), '')
    if not matches['shared_ram'] or not matches['partial_sum_store']:
        raise RuntimeError('Required shared RAM or partial-sum store is absent from the active production design')
    if top == 'soc_top' and (len(matches['clock_buffer']) != 1 or len(matches['axi_memory']) != 1):
        raise RuntimeError('The active SoC requires one BUFGCE and one AXI memory')
    destination.write_text(json.dumps(matches, indent=2) + '\n')
    return {name: len(items) for name, items in matches.items()}


def run(specification):
    from pyosys import libyosys as yosys

    spec = json.loads(specification.read_text())
    frontend = Path(spec['frontend_script'])
    if digest(frontend) != spec['frontend_script_sha256']:
        raise RuntimeError('The saved elaboration script has changed')
    selected = set(spec['modules'])
    design = yosys.Design()
    yosys.run_pass('script ' + shlex.quote(str(frontend)), design)
    definition_reuse = None
    if spec.get('reuse_definitions'):
        from reuse_rtl_definitions import reuse_definitions
        definition_reuse = reuse_definitions(design, spec['top'], selected,
            set(spec['allowed_primitives']), set(spec['reuse_definitions']))
    before = circuit_inventory(design, spec['top'], selected, set(spec['allowed_primitives']))
    found = {item['source_module'] for item in before['retained_instances'].values()}
    if found != selected:
        raise RuntimeError('Requested source modules are not active in this design: ' + ', '.join(sorted(selected - found)))
    for name, entry in before['module_definitions'].items():
        if entry['source_module'] in selected:
            design.module('\\' + name).set_bool_attribute('\\keep_hierarchy', True)
    yosys.run_pass('flatten -noscopeinfo', design)
    after = circuit_inventory(design, spec['top'], selected, set(spec['allowed_primitives']))
    for key in ('circuit_sha256', 'state_connections_sha256', 'memory_declarations_sha256',
                'module_port_connections_sha256', 'leaf_cell_count', 'leaf_cell_counts',
                'state_cell_count', 'memory_count', 'retained_instances', 'top_ports'):
        if before[key] != after[key]:
            raise RuntimeError('The elaborated circuit changed while retaining source modules: ' + key)
    structure = (production_structure(design, spec['top'], Path(spec['structure_report']))
                 if spec.get('production_configuration') else None)
    yosys.run_pass('write_rtlil ' + shlex.quote(spec['output']), design)
    report = {'passed': True, 'requested_modules': sorted(selected),
              'all_leaf_pin_connections_equal': True, 'all_state_connections_equal': True,
              'all_memory_declarations_equal': True, 'all_retained_module_ports_equal': True,
              'source_rtl_instances_resolved': True, 'before': before, 'after': after,
              'production_structure': structure, 'specification_sha256': digest(specification),
              'output_sha256': digest(Path(spec['output']))}
    if definition_reuse is not None:
        report['definition_reuse'] = definition_reuse
    Path(spec['report']).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in ('passed', 'requested_modules',
          'all_leaf_pin_connections_equal', 'all_state_connections_equal')}), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--specification', type=Path, required=True)
    run(parser.parse_args().specification)

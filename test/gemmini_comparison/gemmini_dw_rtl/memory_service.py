"""Memory response configuration shared by the RTL comparison runners."""


def add_arguments(parser, *, beat_option='--read-interval', beat_default=None):
    parser.add_argument(beat_option, dest='read_interval', type=int, choices=(1, 2),
                        default=beat_default)
    parser.add_argument('--first-read-latency', '--read-latency-cycles', dest='read_latency_cycles', type=int,
                        help='Minimum first-response latency from each AR handshake.')
    parser.add_argument('--inter-burst-gap-cycles', type=int,
                        help='Minimum last-R to next-first-R interval for ready requests.')
    parser.add_argument('--read-outstanding-limit', type=int, choices=(1, 4),
                        help='Maximum accepted read requests in the synchronous memory service.')


def configuration(base, args):
    service = dict(base)
    if args.read_interval is not None:
        service['read_beat_interval_cycles'] = args.read_interval
    mode = service.get('response_mode', 'queued_pop_fill')
    if args.read_latency_cycles is not None:
        mode = 'request_deadline'
        service['first_read_latency_cycles'] = args.read_latency_cycles
        service['inter_burst_read_gap_cycles'] = 1
    if args.inter_burst_gap_cycles is not None:
        if mode != 'request_deadline':
            raise ValueError('--inter-burst-gap-cycles requires --first-read-latency')
        service['inter_burst_read_gap_cycles'] = args.inter_burst_gap_cycles
    if mode == 'request_deadline':
        service['read_outstanding_limit'] = args.read_outstanding_limit or service.get('read_outstanding_limit', 4)
    elif args.read_outstanding_limit is not None:
        raise ValueError('--read-outstanding-limit requires --first-read-latency')
    if any(service[key] < 1 for key in ('read_beat_interval_cycles',
                                       'first_read_latency_cycles',
                                       'inter_burst_read_gap_cycles')):
        raise ValueError('Memory response intervals must be positive')
    service['response_mode'] = mode
    service['read_latency_semantics'] = ('per_request_from_ar_handshake'
        if mode == 'request_deadline' else 'queue_selection_then_registered_response')
    service['synchronous_read_register'] = True
    return service


def simulator_arguments(service):
    values = [service['read_beat_interval_cycles']]
    if service['response_mode'] == 'request_deadline':
        values.extend([service['first_read_latency_cycles'],
                       service['inter_burst_read_gap_cycles'], service['read_outstanding_limit']])
    return list(map(str, values))


def validate_result(result, service):
    if result['read_beat_interval'] != service['read_beat_interval_cycles']:
        raise ValueError('Observed read beat interval differs from the selected memory service')
    if result.get('memory_response_mode', 'queued_pop_fill') != service['response_mode']:
        raise ValueError('Observed memory response mode differs from the selected service')
    if service['response_mode'] == 'request_deadline':
        if (result['read_latency_cycles'] != service['first_read_latency_cycles'] or
                result['inter_burst_gap_cycles'] != service['inter_burst_read_gap_cycles'] or
                result['read_outstanding_limit'] != service['read_outstanding_limit']):
            raise ValueError('Observed read timing configuration differs from the selected service')
        if result['read_requests'] and result['read_latency_min'] < service['first_read_latency_cycles']:
            raise ValueError('A read response arrived before its request deadline')
        if result['read_first_responses'] != result['read_requests']:
            raise ValueError('Per-request read latency accounting is incomplete')
        if result['max_read_outstanding_observed'] > service['read_outstanding_limit']:
            raise ValueError('Observed requests exceed the selected outstanding read limit')

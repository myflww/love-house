#!/usr/bin/env python3
"""Reproducible, offline recall microbenchmark. Never opens a user library.

This measures one synthetic, sparse graph and the semantic retrieval lane only;
it does not claim end-to-end chat, network, dense-graph or disk performance.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import gc
import json
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from nkb import Brain
from nkb.organizer.state import semantic_recall


def fixture(count, stamp):
    nodes = {}
    for index in range(count):
        nid = 'synthetic_' + str(index)
        text = '蓝莓航海计划' if index == 0 else '合成编号' + str(index) + '，资料主题为预算归档。'
        nodes[nid] = {'id': nid, 'label': text, 'text': text, 'kind': 'fact',
                      'tags': [], 'salience': .6, 'recalls': 0, 'created': stamp - 1,
                      'meta': {'library_id': 'synthetic-benchmark'}}
    return Brain({'name': '合成性能测试', 'config': {'max_nodes': None},
                  'meta': {'library_id': 'synthetic-benchmark', 'long_term_archive': True},
                  'nodes': nodes, 'edges': {}})


def legacy(brain, query, stamp):
    # Exact costly stages of the previous alias-free semantic read. Fixtures
    # have no disabled/duplicate/alias records, so its filters are identities.
    data = deepcopy(brain.to_dict())
    data['nodes'] = dict(data['nodes'])
    data['edges'] = dict(data['edges'])
    snapshot = Brain(data)
    result = snapshot.recall(query, as_of=stamp)
    for node in snapshot.export(as_of=stamp)['nodes']:
        if node.get('meta', {}).get('source') == 'organizer':
            raise AssertionError('This benchmark baseline is the alias-free path')
    return result


def measure(call):
    start = time.perf_counter()
    value = call()
    elapsed = (time.perf_counter() - start) * 1000
    assert [row['id'] for row in value['hits']] == ['synthetic_0']
    return round(elapsed, 3)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--counts', type=int, nargs='+', default=[10000, 50000, 100000])
    parser.add_argument('--output', type=Path)
    parser.add_argument('--full-context', action='store_true', help='Also measure actual context construction and structured packet projection')
    args = parser.parse_args()
    if any(count < 1 or count > 1000000 for count in args.counts):
        parser.error('Probe counts must be between 1 and 1000000; this bounds the probe, not memory storage')
    rows = []
    for count in args.counts:
        gc.collect()
        stamp = time.time()
        start = time.perf_counter()
        brain = fixture(count, stamp)
        load = round((time.perf_counter() - start) * 1000, 3)
        query = '蓝莓航海'
        baseline = measure(lambda: legacy(brain, query, stamp))
        cold = measure(lambda: semantic_recall(brain, query, as_of=stamp))
        warm = measure(lambda: semantic_recall(brain, query, as_of=stamp))
        reserved = measure(lambda: semantic_recall(brain, query, as_of=stamp, candidate_ids={'synthetic_0'}))
        assert len(brain.nodes) == count
        row = {'nodes': count, 'edges': 0, 'fixture_build_ms': load, 'legacy_read_ms': baseline,
               'cold_read_ms': cold, 'warm_read_ms': warm, 'reserved_lane_ms': reserved,
               'stored_nodes_unchanged': True, 'target_recalled': True}
        if args.full_context:
            from nkb.companion.memory import build_context
            from nkb.companion.structured import build_structured_context
            start = time.perf_counter()
            context = build_context(brain, query, library_id='synthetic-benchmark')
            context_ms = (time.perf_counter() - start) * 1000
            assert 'synthetic_0' in context['memory_ids']
            start = time.perf_counter()
            packet = build_structured_context(brain, query, context, library_id='synthetic-benchmark')
            packet_ms = (time.perf_counter() - start) * 1000
            assert 'synthetic_0' in packet['memory_ids']
            row.update(context_ms=round(context_ms, 3), packet_projection_ms=round(packet_ms, 3),
                       context_and_packet_ms=round(context_ms + packet_ms, 3), context_target_recalled=True)
        rows.append(row)
        print(json.dumps(row), flush=True)
        del brain
    result = {'schema': 'love-house-recall-benchmark/v1', 'python': platform.python_version(),
              'system': platform.system(), 'machine': platform.machine(), 'model_calls': 0,
              'user_data_read': False, 'rows': rows, 'ok': True,
              'limits': ['Synthetic short-text sparse graph without edges',
                         'One process, one sample per measurement; no statistical latency guarantee',
                         'Includes live eligibility scans; warm reads are not claimed to be sublinear',
                         'Excludes disk persistence, network and rendering',
                         'Full context measured only when full_context_measured is true'],
              'full_context_measured': args.full_context}
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


if __name__ == '__main__':
    main()

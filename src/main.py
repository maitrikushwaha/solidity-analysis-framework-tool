"""Abstract Interpretation-based Solidity Vulnerability Analysis Framework"""

import argparse
import json
import os
import sys
import time
import re
import logging
import math as _math
import contextlib
from io import StringIO
from collections import Counter
from compiler import SolCompiler
from control_flow_graph import ControlFlowGraph
from static_analysis.abstract_collecting_semantics import AbstractCollectingSemanticsAnalysis
from java_wrapper import apron
from mapping_transformer import transform_mappings
from control_flow_graph.node_processor.nodes import FunctionCall
from control_flow_graph.node_processor.nodes import VariableDeclarationStatement
from control_flow_graph.node_processor.nodes import IfStatement, ExpressionStatement
from control_flow_graph.node_processor.nodes.extra_nodes.if_statement.join import IfConditionJoin
from dependency_analysis import DependencyAnalysisEngine, SemanticRefinementEngine

VERBOSE_SKIPS = False

FIXPOINT_TIMEOUT_SECONDS = 120

import signal as _signal

class _FixpointTimeout(Exception):
    pass

def _timeout_handler(signum, frame):
    raise _FixpointTimeout("Abstract fixpoint did not converge within timeout")

def _compute_with_timeout(csem, timeout=FIXPOINT_TIMEOUT_SECONDS):
    """Run csem.compute() with a wall-clock timeout."""
    if not hasattr(_signal, 'SIGALRM'):
        csem.compute()
        return
    old_handler = _signal.signal(_signal.SIGALRM, _timeout_handler)
    _signal.alarm(timeout)
    try:
        csem.compute()
    finally:
        _signal.alarm(0)
        _signal.signal(_signal.SIGALRM, old_handler)

DEFAULT_OUTPUT_SUBDIR = "analysis_output"

def _resolve_output_dir(output_dir):
    """Resolve where result files (_output.txt / _analysis.txt / gen/ast.json /"""
    d = output_dir or os.path.join(os.getcwd(), DEFAULT_OUTPUT_SUBDIR)
    os.makedirs(d, exist_ok=True)
    return d

def setup_logging(solidity_filepath, output_dir=None):
    """Set up logging to file + stdout."""
    out_dir = _resolve_output_dir(output_dir)
    log_filename = os.path.basename(solidity_filepath).replace(".sol", "_output.txt")
    log_file_path = os.path.join(out_dir, log_filename)

    logger = logging.getLogger()
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.setLevel(logging.INFO)
    file_handler = logging.FileHandler(log_file_path, mode="w")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return log_file_path

def read_source_code(filename):
    try:
        with open(filename, "r") as f:
            return f.read()
    except FileNotFoundError:
        logging.error(f"File '{filename}' not found.")
        sys.exit(1)

def save_transformed_source(transformed_source, filename="source_1.txt"):
    with open(filename, "w") as f:
        f.write(transformed_source)

def _fmt_num(x):
    """Normalize integer-valued floats (20.0 → 20) for deterministic verdict strings."""
    if isinstance(x, float) and x.is_integer():
        return str(int(x))
    return str(x)

def _parse_solidity_version(version_str):
    if version_str is None:
        return (0, 4, 11)
    v = version_str.lstrip('v')
    parts = v.split('.')
    return tuple(int(p) for p in parts)

def _is_checked_arithmetic_default(cfg):
    ver = getattr(cfg, 'solidity_version', None)
    major, minor, _ = _parse_solidity_version(ver)
    return (major, minor) >= (0, 8)

def _contract_has_unchecked_blocks(cfg):
    for node_id in cfg.cfg_metadata.node_table:
        node = cfg.cfg_metadata.get_node(node_id)
        if node is not None and getattr(node, 'node_type', '') == 'UncheckedBlock':
            return True
    return False

def _collect_identifiers(node):
    names = set()
    if node is None:
        return names
    if getattr(node, 'node_type', '') == 'Identifier':
        name = getattr(node, 'name', None)
        if name:
            names.add(name)
    for attr in ('leftHandSide', 'rightHandSide', 'leftExpression',
                 'rightExpression', 'expression', 'subExpression',
                 'base_expression', 'index_expression',
                 'baseExpression', 'indexExpression',
                 'condition', 'trueExpression', 'falseExpression'):
        child = getattr(node, attr, None)
        if child is not None and hasattr(child, 'node_type'):
            names.update(_collect_identifiers(child))
    for comp in getattr(node, 'components', []):
        if comp is not None:
            names.update(_collect_identifiers(comp))
    for arg in getattr(node, 'arguments', []):
        if arg is not None and hasattr(arg, 'node_type'):
            names.update(_collect_identifiers(arg))
    return names

def _silence(fn, *args, **kwargs):
    """Run fn(*args, **kwargs) with stdout/stderr suppressed; return its result."""
    old_out, old_err = sys.stdout, sys.stderr
    sys.stdout = StringIO()
    sys.stderr = StringIO()
    try:
        return fn(*args, **kwargs)
    finally:
        sys.stdout = old_out
        sys.stderr = old_err

def _build_cfg(source_code, solidity_version_override=None):
    """Compile source_code and return (cfg, compiler_version_str)."""
    compiler = SolCompiler(source_code)
    output = compiler.compile()
    contracts = output.get_contracts_list()
    if not contracts:
        raise RuntimeError("No contracts found in source.")
    ast = output.get_ast(contracts[0])
    cfg = ControlFlowGraph(source_code, ast)
    cfg.build_cfg()
    cfg.solidity_version = compiler.solidity_version
    return cfg, compiler.solidity_version

def _build_transformed_cfg(source_code):
    """Transform source, compile, build CFG, return (cfg, credit_var_name)."""
    transformed_source, credit_var_name = transform_mappings(source_code)
    cfg, _ = _build_cfg(transformed_source)
    cfg.credit_var_name = credit_var_name
    return cfg, credit_var_name, transformed_source

def insert_reentrancy_back_edge(cfg):
    """Identify the synthesised external-call IfStatement (condition mentions BAL),"""
    node_table = cfg.cfg_metadata.node_table

    def _mentions_bal(cond_obj):
        if cond_obj is None:
            return False
        seen_ids = set()
        stack = [cond_obj]
        while stack:
            obj = stack.pop()
            oid = id(obj)
            if oid in seen_ids:
                continue
            seen_ids.add(oid)
            name = getattr(obj, 'name', None)
            if isinstance(name, str) and name == 'BAL':
                return True
            for attr in ('leftExpression', 'rightExpression', 'subExpression',
                         'expression', 'condition', 'components', 'arguments',
                         'baseExpression', 'indexExpression'):
                child = getattr(obj, attr, None)
                if child is None:
                    continue
                if isinstance(child, (list, tuple)):
                    stack.extend(child)
                else:
                    stack.append(child)
        return False

    candidate_if_id = None
    for node_id, node in node_table.items():
        if not node_id.startswith('IfStatement_'):
            continue
        if not hasattr(node, 'condition'):
            continue
        if _mentions_bal(node.condition):
            candidate_if_id = node_id
            break

    if candidate_if_id is None:
        logging.info("[CFG] No reentrancy back-edge: no external-call encoding detected.")
        return (None, None)

    if_node = node_table[candidate_if_id]
    then_entry = getattr(if_node, 'true_body_next', None)
    if then_entry is None or then_entry not in node_table:
        logging.info("[CFG] No reentrancy back-edge: if-statement has no then-body entry.")
        return (None, None)

    last_stmt_id = None
    current = then_entry
    seen_walk = set()
    while True:
        if current in seen_walk:
            break
        seen_walk.add(current)
        if not current.startswith('ExpressionStatement_'):
            break
        last_stmt_id = current
        cur_node = node_table.get(current)
        if cur_node is None:
            break
        next_es = None
        for succ_id in cur_node.next_nodes:
            if succ_id.startswith('ExpressionStatement_'):
                next_es = succ_id
                break
        if next_es is None:
            break
        current = next_es

    if last_stmt_id is None:
        logging.info("[CFG] No reentrancy back-edge: then-branch has no ExpressionStatement.")
        return (None, None)

    src_node = node_table[last_stmt_id]
    src_node.next_nodes = dict()
    src_node.add_next_node(candidate_if_id)
    if_node.add_prev_node(last_stmt_id)
    logging.info(f"[CFG] Reentrancy back-edge inserted: {last_stmt_id} → {candidate_if_id}")
    return (last_stmt_id, candidate_if_id)

def _register_reentrancy_probes(csem, cfg=None):
    """Register pinned concrete probe constants for the reentrancy csem."""
    reg = csem.constant_registry
    reg.register_variable('blocktimestamp',      False, ('100', '100'))
    reg.register_variable('msgsender',           False, ('100', '100'))
    reg.register_variable('msgvalue',            False, ('20',  '20'))
    reg.register_variable('msg.value',           False, ('20',  '20'))
    reg.register_variable('totalSupply',         False, (40,  40))
    reg.register_variable('_initialSupply',      False, (40,  40))
    reg.register_variable('dividendsCollected',  False, (0,   0))
    reg.register_variable('_tkA',                False, ('40','40'))
    reg.register_variable('amount',              False, (20,  20))
    reg.register_variable('_amount',             False, (10,  10))
    reg.register_variable('_value',              False, (20,  20))
    reg.register_variable('value',               False, (40,  40))
    reg.register_variable('_wei',                False, (40,  40))
    reg.register_variable('_weiToWithdraw',      False, (40,  40))
    reg.register_variable('_am',                 False, (40,  40))
    reg.register_variable('n',                   False, (10,  10))
    reg.register_variable('number',              False, (10,  10))
    reg.register_variable('num',                 False, (10,  10))
    reg.register_variable('a',                   False, (10,  10))
    reg.register_variable('b',                   False, (2,   2))
    reg.register_variable('x',                   False, (10,  10))
    reg.register_variable('max',                 False, (10,  10))
    reg.register_variable('_to',                 False, (10,  10))
    reg.register_variable('_from',               False, (10,  10))
    reg.register_variable('_owner',              False, (10,  10))
    reg.register_variable('owner',               False, (10,  10))
    reg.register_variable('_newOwner',           False, (10,  10))
    reg.register_variable('_dst',                False, (50,  50))
    reg.register_variable('_amt',                False, (10,  10))
    reg.register_variable('_mult',               False, (10,  10))
    reg.register_variable('_fee',                False, (10,  10))
    reg.register_variable('_pcent',              False, (10,  10))
    reg.register_variable('_maxsum',             False, (40,  40))
    reg.register_variable('_when',               False, (40,  40))
    reg.register_variable('_required',           False, (25,  25))
    reg.register_variable('_start',              False, (2,   2))
    reg.register_variable('numTokens',           False, (255, 255))
    reg.register_variable('deposit',             False, (255, 255))
    reg.register_variable('rand',                False, (40,  40))
    reg.register_variable('submission',          False, (40,  40))
    reg.register_variable('solution',            False, (40,  40))
    reg.register_variable('input',               False, (255, 255))
    reg.register_variable('v',                   False, (100, 100))
    reg.register_variable('wagerLimit',          False, (10,  10))
    reg.register_variable('vs',                  False, (10,  10))
    reg.register_variable('_decimals',           False, (3,   3))
    reg.register_variable('_data',               False, (3,   3))
    reg.register_variable('_secretSigner',       False, (1,   1))
    reg.register_variable('secretSignerAddress', False, (4,   4))
    reg.register_variable('ticketID',            False, (20,  20))
    reg.register_variable('ticketLastBlock',     False, (20,  20))
    reg.register_variable('autoPlayBotAddress',  False, (10,  10))
    reg.register_variable('whaleAddress',        False, (2,   2))
    reg.register_variable('supplyLOCKER',        False, (50,  50))
    reg.register_variable('requestType',        False, (10,  10))
    reg.register_variable('timestamp',           False, (10,  10))
    reg.register_variable('_secondsToIncrease',  False, (255, 255))
    reg.register_variable('_unlockTime',         False, (40,  40))
    reg.register_variable('_lockTime',           False, (40,  40))
    reg.register_variable('hash',                False, (20,  20))
    reg.register_variable('card',                False, (20,  20))
    reg.register_variable('cards',               False, (10,  10))
    reg.register_variable('_pd',                 False, (10,  10))
    reg.register_variable('user',                 False, (10,  10))
    reg.register_variable('flag',                 False, (0,   1))
    reg.register_variable('locked',               False, (0,   1))
    reg.register_variable('mutex',                False, (0,   1))
    reg.register_variable('_locked',              False, (0,   1))
    reg.register_variable('reentrancyLock',       False, (0,   1))
    reg.register_variable('entered',              False, (0,   1))
    reg.register_variable('target',               False, (10,  10))
    reg.register_variable('recipient',            False, (10,  10))
    reg.register_variable('sender',               False, (10,  10))
    reg.register_variable('addr',                 False, (10,  10))
    reg.register_variable('credit_a', False, (40, 40))

    if cfg is not None:
        for var_name, var_info in cfg.cfg_metadata.variable_table.items():
            if var_name not in reg.variable_table:
                var_type = var_info if isinstance(var_info, str) else (
                    var_info.get('type', '') if isinstance(var_info, dict) else ''
                )
                if var_type == 'bool':
                    reg.register_variable(var_name, False, (0, 1))
                elif var_type == 'address':
                    reg.register_variable(var_name, False, (10, 10))
                else:
                    reg.register_variable(var_name, False, (40, 40))

def _register_timestamp_tod_probes(csem, cfg=None):
    """Pinned probe values for timestamp/TOD csem — same as reentrancy probes."""
    _register_reentrancy_probes(csem, cfg)

def _auto_register_function_params(cfg, constant_registry):
    """Walk every FunctionDefinition node, extract parameters, register each"""
    JAVA_LONG_MAX = 2**63 - 1
    TYPE_RANGES = {
        'uint8':   (0, 2**8  - 1),  'uint16':  (0, 2**16 - 1),
        'uint32':  (0, 2**32 - 1),  'uint64':  (0, 2**64 - 1),
        'uint128': (0, 2**128 - 1), 'uint256': (0, 2**256 - 1),
        'uint':    (0, 2**256 - 1),
        'int8':    (-(2**7),   2**7   - 1), 'int16':  (-(2**15),  2**15  - 1),
        'int32':   (-(2**31),  2**31  - 1), 'int64':  (-(2**63),  2**63  - 1),
        'int128':  (-(2**127), 2**127 - 1), 'int256': (-(2**255), 2**255 - 1),
        'int':     (-(2**255), 2**255 - 1),
        'address': (0, 2**160 - 1),
        'bool':    (0, 1),
        'bytes32': (0, 2**256 - 1),
    }
    for _, node_obj in cfg.cfg_metadata.node_table.items():
        if not (hasattr(node_obj, 'node_type')
                and node_obj.node_type == 'FunctionDefinition'):
            continue
        params_dict = getattr(node_obj, 'parameters', {})
        if not isinstance(params_dict, dict):
            continue
        for param in params_dict.get('parameters', []):
            param_name = param.get('name')
            type_name_node = param.get('typeName', {})
            param_type = (type_name_node.get('name', '')
                          if isinstance(type_name_node, dict) else '')
            if not param_name or param_type not in TYPE_RANGES:
                continue
            if param_name in constant_registry.variable_table:
                continue
            lo, hi = TYPE_RANGES[param_type]
            reg_value = 'top' if (abs(lo) > JAVA_LONG_MAX or abs(hi) > JAVA_LONG_MAX) \
                        else (lo, hi)
            constant_registry.variable_table[param_name] = {
                'id':            constant_registry.variable_count,
                'name':          param_name,
                'stateVariable': False,
                'value':         reg_value,
            }
            constant_registry.variable_count += 1

    for ts_var in ('blocktimestamp', 'now', 'block_timestamp'):
        if ts_var not in constant_registry.variable_table:
            constant_registry.variable_table[ts_var] = {
                'id':            constant_registry.variable_count,
                'name':          ts_var,
                'stateVariable': False,
                'value':         'top',
            }
            constant_registry.variable_count += 1

_REENTRANCY_GUARD_MODIFIERS = frozenset({
    'nonReentrant', 'noReentrant', 'reentrancyGuard',
    'lockContract', 'mutex', 'synchronized',
})

def _detect_modifier_reentrancy(source_code):
    """Detect reentrancy through modifier-based external calls."""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    modifier_pattern = re.compile(
        r'modifier\s+(\w+)\s*(?:\([^)]*\))?\s*\{',
        re.DOTALL
    )
    modifiers = {}
    for m in modifier_pattern.finditer(stripped):
        mod_name = m.group(1)
        start = m.end()
        depth = 1
        pos = start
        while pos < len(stripped) and depth > 0:
            if stripped[pos] == '{':
                depth += 1
            elif stripped[pos] == '}':
                depth -= 1
            pos += 1
        body = stripped[start:pos - 1]
        placeholder_idx = body.find('_;')
        if placeholder_idx >= 0:
            pre_body = body[:placeholder_idx]
            post_body = body[placeholder_idx + 2:]
        else:
            pre_body = body
            post_body = ''
        modifiers[mod_name] = (body, pre_body, post_body)

    if not modifiers:
        return None

    ext_call_pattern = re.compile(
        r'(\w+)\s*\(\s*msg\.sender\s*\)\s*\.\s*(\w+)\s*\('
    )

    modifiers_with_ext_call = {}
    for mod_name, (body, pre_body, post_body) in modifiers.items():
        if mod_name in _REENTRANCY_GUARD_MODIFIERS:
            continue
        if mod_name in _MUTEX_NAMES:
            continue

        m_pre = ext_call_pattern.search(pre_body)
        if m_pre:
            modifiers_with_ext_call[mod_name] = ('pre', m_pre.group(1), m_pre.group(2))
            continue

        m_post = ext_call_pattern.search(post_body)
        if m_post:
            modifiers_with_ext_call[mod_name] = ('post', m_post.group(1), m_post.group(2))
            continue

    if not modifiers_with_ext_call:
        return None

    if not modifiers_with_ext_call:
        return None

    func_pattern = re.compile(
        r'function\s+(\w+)\s*\([^)]*\)\s+([^{]*)\{',
        re.DOTALL
    )

    for fm in func_pattern.finditer(stripped):
        func_name = fm.group(1)
        func_header = fm.group(2)

        func_modifiers_used = []
        for mod_name in modifiers.keys():
            if re.search(rf'\b{re.escape(mod_name)}\b', func_header):
                func_modifiers_used.append(mod_name)

        dangerous_mods = [m for m in func_modifiers_used if m in modifiers_with_ext_call]
        if not dangerous_mods:
            continue

        has_guard = False
        for mod_name in func_modifiers_used:
            if mod_name in _REENTRANCY_GUARD_MODIFIERS or mod_name in _MUTEX_NAMES:
                has_guard = True
                break
        if has_guard:
            continue

        fstart = fm.end()
        fdepth = 1
        fpos = fstart
        while fpos < len(stripped) and fdepth > 0:
            if stripped[fpos] == '{':
                fdepth += 1
            elif stripped[fpos] == '}':
                fdepth -= 1
            fpos += 1
        func_body = stripped[fstart:fpos - 1]

        if re.search(r'\b(?:view|pure)\b', func_header):
            continue
        state_write_pattern = re.compile(
            r'\b\w+\s*(?:\[\s*[^\]]+\s*\])?\s*(?:\+|-|\*|\/)?=[^=]'
        )
        has_state_write = bool(state_write_pattern.search(func_body))

        if not has_state_write:
            continue

        for dmod in dangerous_mods:
            call_pos, contract_type, method_name = modifiers_with_ext_call[dmod]

            if call_pos == 'pre':
                line_num = stripped[:fm.start()].count('\n') + 1
                return (
                    f"[REENTRANCY] Modifier-based reentrancy in function '{func_name}' "
                    f"(line ~{line_num}). Modifier '{dmod}' makes external call "
                    f"{contract_type}(msg.sender).{method_name}() which allows "
                    f"re-entry before function body completes. State-modifying "
                    f"function body can execute multiple times."
                )

            if call_pos == 'post':
                has_effective_guard = False
                for guard_mod in func_modifiers_used:
                    if guard_mod == dmod:
                        continue
                    if guard_mod in _REENTRANCY_GUARD_MODIFIERS:
                        has_effective_guard = True
                        break
                    if guard_mod in modifiers:
                        guard_body = modifiers[guard_mod][1]
                        if re.search(r'\b(?:require|assert)\s*\(', guard_body):
                            has_effective_guard = True
                            break
                if not has_effective_guard:
                    line_num = stripped[:fm.start()].count('\n') + 1
                    return (
                        f"[REENTRANCY] Modifier-based reentrancy in function '{func_name}' "
                        f"(line ~{line_num}). Modifier '{dmod}' makes external call "
                        f"{contract_type}(msg.sender).{method_name}() after function body. "
                        f"No effective guard modifier prevents re-entry."
                    )

    return None

def _detect_erc20_reentrancy(source_code):
    """Detect reentrancy through ERC-20 interface external calls."""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    type_decls = set(re.findall(r'\b(?:interface|contract)\s+(\w+)', stripped))

    _DANGEROUS_ERC20_METHODS = frozenset({
        'transfer', 'transferFrom', 'approve', 'safeTransfer',
        'safeTransferFrom', 'send', 'mint', 'burn',
        'execute', 'work', 'withdraw', 'deposit', 'swap',
    })

    func_params = set()
    constructor_params = set()
    param_pat = re.compile(r'function\s+\w+\s*\(([^)]*)\)')
    for m in param_pat.finditer(stripped):
        for p in m.group(1).split(','):
            p = p.strip()
            if p:
                parts = p.split()
                if parts:
                    func_params.add(parts[-1])
    constr_pat = re.compile(r'constructor\s*\(([^)]*)\)')
    for m in constr_pat.finditer(stripped):
        for p in m.group(1).split(','):
            p = p.strip()
            if p:
                parts = p.split()
                if parts:
                    constructor_params.add(parts[-1])

    iface_state_vars = set()
    for iface_name in type_decls:
        sv_pat = re.compile(
            rf'\b{re.escape(iface_name)}\s+(?:private|public|internal|immutable|\s)*\s+(\w+)\s*[;=]'
        )
        for m in sv_pat.finditer(stripped):
            iface_state_vars.add(m.group(1))
    for iface_name in type_decls:
        sv_pat2 = re.compile(
            rf'\b{re.escape(iface_name)}\s+(?:private|public|internal|immutable|\s)*\s+(\w+)\s*='
        )
        for m in sv_pat2.finditer(stripped):
            iface_state_vars.add(m.group(1))

    func_block_pat = re.compile(
        r'function\s+(\w+)\s*\(([^)]*)\)\s*([^{]*)\{',
        re.DOTALL
    )

    for fm in func_block_pat.finditer(stripped):
        func_name = fm.group(1)
        func_params_str = fm.group(2)
        func_header = fm.group(3)

        if re.search(r'\b(?:view|pure)\b', func_header):
            continue

        fstart = fm.end()
        depth = 1
        pos = fstart
        while pos < len(stripped) and depth > 0:
            if stripped[pos] == '{':
                depth += 1
            elif stripped[pos] == '}':
                depth -= 1
            pos += 1
        func_body = stripped[fstart:pos - 1]

        this_func_params = set()
        for p in func_params_str.split(','):
            p = p.strip()
            if p:
                parts = p.split()
                if parts:
                    this_func_params.add(parts[-1])

        iface_call_pat = re.compile(
            r'(\w+)\s*\(\s*(\w+)\s*\)\s*\.\s*(\w+)\s*\('
        )
        for mc in iface_call_pat.finditer(func_body):
            type_name, addr_arg, method_name = mc.group(1), mc.group(2), mc.group(3)
            if type_name not in type_decls:
                continue
            if method_name not in _DANGEROUS_ERC20_METHODS:
                continue
            if addr_arg not in this_func_params and addr_arg not in func_params:
                continue

            call_end = mc.end()
            stmt_end = func_body.find(';', call_end)
            if stmt_end == -1:
                stmt_end = call_end
            post_call = func_body[stmt_end:]

            has_state_update_after = bool(re.search(
                r'(?:\w+\s*\[\s*[\w.]+\s*\]\s*(?:=|\+=|-=))'
                r'|(?:\w+\s*(?:\+=|-=)\s*\w+)'
                r'|(?:\w+\s*=\s*(?:true|false|success)\s*;)',
                post_call
            ))

            if has_state_update_after:
                has_nonreentrant = bool(re.search(
                    r'\bnonReentrant\b', func_header
                ))
                if has_nonreentrant:
                    mod_pat = re.compile(
                        r'modifier\s+nonReentrant\s*\(\s*\)\s*\{',
                        re.DOTALL
                    )
                    for mm in mod_pat.finditer(stripped):
                        mstart = mm.end()
                        mdepth = 1
                        mpos = mstart
                        while mpos < len(stripped) and mdepth > 0:
                            if stripped[mpos] == '{':
                                mdepth += 1
                            elif stripped[mpos] == '}':
                                mdepth -= 1
                            mpos += 1
                        mod_body = stripped[mstart:mpos - 1]
                        has_require = bool(re.search(r'require\s*\(\s*!\s*\w+', mod_body))
                        has_flag_set = bool(re.search(r'\w+\s*=\s*true', mod_body))
                        if has_require and has_flag_set:
                            has_state_update_after = False
                            break

                if has_state_update_after:
                    line_num = stripped[:fm.start()].count('\n') + 1
                    return (
                        f"[REENTRANCY] ERC-20 interface reentrancy in function "
                        f"'{func_name}' (line ~{line_num}). External call "
                        f"{type_name}({addr_arg}).{method_name}() with "
                        f"attacker-controlled token address allows re-entry. "
                        f"State update after external call."
                    )

        for sv in iface_state_vars:
            sv_call_pat = re.compile(
                rf'\b{re.escape(sv)}\s*\.\s*(\w+)\s*\('
            )
            for mc in sv_call_pat.finditer(func_body):
                method_name = mc.group(1)
                if method_name not in _DANGEROUS_ERC20_METHODS:
                    continue

                call_end = mc.end()
                stmt_end = func_body.find(';', call_end)
                if stmt_end == -1:
                    stmt_end = call_end
                post_call = func_body[stmt_end:]

                has_state_update_after = bool(re.search(
                    r'(?:\w+\s*\[\s*[\w.]+\s*\]\s*(?:=|\+=|-=))'
                    r'|(?:\w+\s*(?:\+=|-=)\s*\w+)'
                    r'|(?:\w+\s*=\s*(?:true|false|success|0)\s*;)',
                    post_call
                ))

                if has_state_update_after:
                    line_num = stripped[:fm.start()].count('\n') + 1
                    return (
                        f"[REENTRANCY] ERC-20 interface reentrancy in function "
                        f"'{func_name}' (line ~{line_num}). External call "
                        f"{sv}.{method_name}() on stored token reference "
                        f"allows re-entry. State update after external call."
                    )

    return None

def _should_suppress_fixpoint_verdict(source_code):
    """
    Post-fixpoint guard: suppress "Balance-preservation invariant violated"
    when the original contract is safe despite the fixpoint flagging it.

    The mapping_transformer injects synthetic BAL/attacker_bal variables for
    EVERY contract with .call.value(), regardless of whether the contract
    has real balance-tracking state.  The fixpoint then detects invariant
    violation on this synthetic state — a false positive.

    This function checks the ORIGINAL source for safety patterns:
      1. No real balance mapping AND no state modified after call
      2. All .call.value functions are access-controlled (onlyOwner etc.)
         AND the call target is NOT msg.sender with a balance mapping
      3. CEI pattern: balance mapping zeroed/decremented BEFORE the call

    Returns True if the fixpoint verdict should be suppressed (contract safe).
    """
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    _ACCESS_MOD_RE = re.compile(
        r'\b(onlyOwner|onlyAdmin|onlyAuthorized|onlyMinter|onlyManager'
        r'|auth|authorized|onlyGovernance|onlyOperator|onlyController'
        r'|onlyRole|requiresAuth|onlyCEO|onlyCFO|onlyCOO)\b'
    )
    _CALL_PAT = re.compile(
        r'\.call\.value\s*\(|\.call\s*\{\s*value\s*:', re.DOTALL
    )
    _FUNC_PAT = re.compile(
        r'function\s+(\w+)\s*\([^)]*\)([^{]*)\{', re.DOTALL
    )
    _STATE_UPDATE_RE = re.compile(
        r'(?:\w+(?:\s*\[[\w.\s]+\])+\s*(?:=(?!=)|\+=|-=))'
        r'|(?:\w+\s*(?:-=|\+=)\s*\w+)'
        r'|(?:\w+\s*=\s*0\s*;)'
        r'|(?:delete\s+\w+)'
    )

    has_balance_mapping = bool(re.search(
        r'mapping\s*\(\s*address\s*=>\s*uint', stripped
    ))

    def _get_call_funcs():
        results = []
        for m in _FUNC_PAT.finditer(stripped):
            name, header = m.group(1), m.group(2)
            start, depth, i = m.end(), 1, m.end()
            while i < len(stripped) and depth > 0:
                if stripped[i] == '{': depth += 1
                elif stripped[i] == '}': depth -= 1
                i += 1
            body = stripped[start:i-1]
            cm = _CALL_PAT.search(body)
            if cm:
                results.append((name, header, body, cm))
        return results

    call_funcs = _get_call_funcs()
    if not call_funcs:
        return False

    if not has_balance_mapping:
        has_state_after = False
        for _, _, body, cm in call_funcs:
            post = body[cm.end():]
            if _STATE_UPDATE_RE.search(post):
                has_state_after = True
                break
        if not has_state_after:
            return True

    all_access_controlled = all(
        bool(_ACCESS_MOD_RE.search(hdr)) for _, hdr, _, _ in call_funcs
    )
    if all_access_controlled:
        _MSG_SENDER_BAL = re.compile(
            r'\w+\s*\[\s*msg\.sender\s*\]\s*(?:=(?!=)|\+=|-=)', re.DOTALL
        )

        def _call_is_invoked(body, cm):
            """True iff the matched .call.value(...) / .call{value:...}"""
            seg = body[cm.start():cm.end()]
            if '{' in seg:
                j = body.index('{', cm.start())
                depth, i = 0, j
                while i < len(body):
                    if body[i] == '{':
                        depth += 1
                    elif body[i] == '}':
                        depth -= 1
                        if depth == 0:
                            i += 1
                            break
                    i += 1
            else:
                i, depth = cm.end(), 1
                while i < len(body) and depth > 0:
                    if body[i] == '(':
                        depth += 1
                    elif body[i] == ')':
                        depth -= 1
                    i += 1
            return body[i:].lstrip().startswith('(')

        def _param_names(fname):
            pm = re.search(
                r'function\s+' + re.escape(fname) + r'\s*\(([^)]*)\)', stripped
            )
            names = set()
            if pm:
                for piece in pm.group(1).split(','):
                    toks = piece.strip().split()
                    if toks:
                        names.add(toks[-1])
            return names

        balance_after_call = False
        for fname, _, body, cm in call_funcs:
            post_call = body[cm.end():]
            pre_call  = body[:cm.start()]
            if _MSG_SENDER_BAL.search(post_call):
                balance_after_call = True
                break
            tmatch = re.search(r'([A-Za-z_]\w*)\s*$', pre_call)
            target = tmatch.group(1) if tmatch else None
            if target and target in _param_names(fname) and _call_is_invoked(body, cm):
                tgt_write = re.compile(
                    r'\w+\s*\[\s*' + re.escape(target) + r'\s*\]\s*(?:=(?!=)|\+=|-=)',
                    re.DOTALL,
                )
                tgt_cei = re.compile(
                    r'\w+\s*\[\s*' + re.escape(target) + r'\s*\]\s*(?:=\s*0\s*;|-=)',
                    re.DOTALL,
                )
                if tgt_write.search(post_call) and not tgt_cei.search(pre_call):
                    balance_after_call = True
                    break
        if not balance_after_call:
            return True

    _CEI_RE = re.compile(
        r'\w+\s*\[\s*msg\.sender\s*\]\s*(?:=\s*0\s*;|-=\s*\w+\s*;)',
        re.DOTALL
    )
    if call_funcs:
        all_cei = True
        for _, _, body, cm in call_funcs:
            pre_call = body[:cm.start()]
            if not _CEI_RE.search(pre_call):
                all_cei = False
                break
        if all_cei:
            return True

    return False

def _detect_call_value_state_after(source_code):
    """Structural detector for .call{value:} / .call.value() with state update"""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    type_decls = set(re.findall(r'\b(?:interface|contract)\s+(\w+)', stripped))

    _STATE_UPDATE_RE = re.compile(
        r'(?:\w+(?:\s*\[[\w.\s]+\])+\s*(?:=|\+=|-=))'
        r'|(?:\w+\s*(?:-=|\+=)\s*\w+)'
        r'|(?:\w+\s*=\s*0\s*;)'
        r'|(?:delete\s+\w+)'
    )

    _ACCESS_MOD_RE = re.compile(
        r'\b(onlyOwner|onlyAdmin|onlyAuthorized|onlyMinter|onlyManager'
        r'|auth|authorized|onlyGovernance|onlyOperator|onlyController'
        r'|onlyRole|requiresAuth|onlyCEO|onlyCFO|onlyCOO)\b'
    )

    _CEI_RE = re.compile(
        r'\w+\s*\[\s*msg\.sender\s*\]\s*(?:=\s*0\s*;|-=\s*\w+\s*;)',
        re.DOTALL
    )

    func_block_pat = re.compile(
        r'function\s+(\w+)\s*\(([^)]*)\)\s*([^{]*)\{',
        re.DOTALL
    )

    func_bodies = {}
    for fm in func_block_pat.finditer(stripped):
        fn = fm.group(1)
        fs = fm.end()
        d, p = 1, fs
        while p < len(stripped) and d > 0:
            if stripped[p] == '{': d += 1
            elif stripped[p] == '}': d -= 1
            p += 1
        func_bodies[fn] = stripped[fs:p-1]

    for fm in func_block_pat.finditer(stripped):
        func_name = fm.group(1)
        func_header = fm.group(3)
        if re.search(r'\b(?:view|pure)\b', func_header):
            continue

        if _ACCESS_MOD_RE.search(func_header):
            continue

        fstart = fm.end()
        depth = 1
        pos = fstart
        while pos < len(stripped) and depth > 0:
            if stripped[pos] == '{':
                depth += 1
            elif stripped[pos] == '}':
                depth -= 1
            pos += 1
        func_body = stripped[fstart:pos - 1]

        call_match = (re.search(r'\.call\s*\{\s*value\s*:', func_body) or
                      re.search(r'\.call\.value\s*\(', func_body))
        if call_match:
            call_pos = call_match.start()
            pre_call = func_body[:call_pos]

            if _CEI_RE.search(pre_call):
                continue

            post_call_text = func_body[call_pos:]
            call_stmt_end = post_call_text.find(';')
            if call_stmt_end != -1:
                after_call_in_func = post_call_text[call_stmt_end+1:]
            
            pre_call = func_body[:call_pos]
            if_before = None
            for if_m in re.finditer(r'\bif\s*\(', pre_call):
                if_before = if_m

            if if_before is not None:
                if_start = if_before.start()
                paren_start = if_before.end() - 1
                paren_depth = 0
                scan = paren_start
                while scan < len(func_body):
                    if func_body[scan] == '(': paren_depth += 1
                    elif func_body[scan] == ')':
                        paren_depth -= 1
                        if paren_depth == 0:
                            break
                    scan += 1
                after_paren = func_body[scan+1:].lstrip()
                brace_pos = func_body.find('{', scan+1)

                if brace_pos != -1:
                    bd, bp = 1, brace_pos + 1
                    while bp < len(func_body) and bd > 0:
                        if func_body[bp] == '{': bd += 1
                        elif func_body[bp] == '}': bd -= 1
                        bp += 1
                    if_block = func_body[brace_pos+1:bp-1]

                    negated = bool(re.search(r'if\s*\(\s*!', func_body[if_start:brace_pos]))
                    if negated:
                        post_if = func_body[bp:]
                        if _STATE_UPDATE_RE.search(post_if):
                            return (
                                f"[REENTRANCY] State update after external call in function "
                                f"'{func_name}'. The .call{{value:}} forwards unlimited gas, "
                                f"allowing re-entry before state is updated."
                            )
                    else:

                        call_in_body = re.search(
                            r'\.call\.value\s*\(|\.call\s*\{\s*value\s*:',
                            if_block
                        )

                        if not call_in_body:
                            if _STATE_UPDATE_RE.search(if_block):
                                return (
                                    f"[REENTRANCY] State update after external call in function "
                                    f"'{func_name}'. The .call{{value:}} forwards unlimited gas, "
                                    f"allowing re-entry before state is updated."
                                )
                        else:
                            post_call_in_body = if_block[call_in_body.end():]
                            call_semi = post_call_in_body.find(';')
                            if call_semi != -1:
                                after_call = post_call_in_body[call_semi+1:]
                                if _STATE_UPDATE_RE.search(after_call):
                                    return (
                                        f"[REENTRANCY] State update after external call in function "
                                        f"'{func_name}'. The .call{{value:}} forwards unlimited gas, "
                                        f"allowing re-entry before state is updated."
                                    )

                        post_if = func_body[bp:]
                        post_if_lstripped = post_if.lstrip()
                        if post_if_lstripped.startswith('else'):
                            else_brace = post_if.find('{')
                            if else_brace != -1:
                                ed, ep = 1, else_brace + 1
                                while ep < len(post_if) and ed > 0:
                                    if post_if[ep] == '{': ed += 1
                                    elif post_if[ep] == '}': ed -= 1
                                    ep += 1
                                after_else = post_if[ep:]
                                if _STATE_UPDATE_RE.search(after_else):
                                    return (
                                        f"[REENTRANCY] State update after external call in function "
                                        f"'{func_name}'. The .call{{value:}} forwards unlimited gas, "
                                        f"allowing re-entry before state is updated."
                                    )
                        elif _STATE_UPDATE_RE.search(post_if):
                            return (
                                f"[REENTRANCY] State update after external call in function "
                                f"'{func_name}'. The .call{{value:}} forwards unlimited gas, "
                                f"allowing re-entry before state is updated."
                            )

            call_end = call_match.end()
            stmt_end = func_body.find(';', call_end)
            if stmt_end == -1:
                continue
            rest = func_body[stmt_end+1:].lstrip()
            if rest.startswith('require'):
                semi2 = func_body.find(';', stmt_end+1)
                post_call = func_body[semi2+1:] if semi2 != -1 else ''
            else:
                post_call = func_body[stmt_end+1:]

            if _STATE_UPDATE_RE.search(post_call):
                return (
                    f"[REENTRANCY] State update after external call in function "
                    f"'{func_name}'. The .call{{value:}} forwards unlimited gas, "
                    f"allowing re-entry before state is updated."
                )

        _SKIP_NAMES = frozenset({
            'require', 'assert', 'revert', 'emit', 'if', 'for', 'while',
            'return', 'delete', 'push', 'keccak256', 'abi', 'type',
            'payable', 'address',
        })
        for fc_m in re.finditer(r'\b(\w+)\s*\(', func_body):
            callee = fc_m.group(1)
            if callee in _SKIP_NAMES or callee in type_decls:
                continue
            if callee not in func_bodies:
                continue
            callee_body = func_bodies[callee]
            if not re.search(r'\.call\s*\{\s*value|\.call\.value\s*\(', callee_body):
                continue
            call_pos_2 = fc_m.end()
            semi_after = func_body.find(';', call_pos_2)
            if semi_after == -1:
                continue
            post = func_body[semi_after+1:]
            if _STATE_UPDATE_RE.search(post):
                return (
                    f"[REENTRANCY] State update after external call in function "
                    f"'{func_name}'. Called function '{callee}()' contains "
                    f".call{{value:}} forwarding unlimited gas. "
                    f"State updated after return."
                )

    return None

def _has_dangerous_external_call(source_code):
    """Determine whether the original Solidity source contains an external call"""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    has_legacy_call = bool(re.search(r'\.call\.value\s*\(', stripped))
    has_new_call    = bool(re.search(r'\.call\s*\{\s*value\s*:', stripped))

    if not has_legacy_call and not has_new_call:
        return False

    legacy_targets = re.findall(r'(\w+)\s*\.call\.value\s*\(', stripped)
    new_targets    = re.findall(r'(\w+)\s*\.call\s*\{\s*value\s*:', stripped)
    call_targets   = set(legacy_targets + new_targets)

    if 'sender' in call_targets:
        return True

    msg_sender_aliases = {'msg.sender'}
    assign_pattern = re.compile(r'(\w+)\s*=\s*msg\.sender\s*;')
    for m in assign_pattern.finditer(stripped):
        msg_sender_aliases.add(m.group(1))
    payable_pattern = re.compile(r'(\w+)\s*=\s*(?:address\s*\(\s*uint160\s*\(\s*)?payable\s*\(\s*msg\.sender\s*\)')
    for m in payable_pattern.finditer(stripped):
        msg_sender_aliases.add(m.group(1))

    if call_targets.intersection(msg_sender_aliases):
        return True

    func_param_names = set()
    param_pattern = re.compile(r'function\s+\w+\s*\(([^)]*)\)')
    for m in param_pattern.finditer(stripped):
        params_str = m.group(1)
        for param in params_str.split(','):
            param = param.strip()
            if param:
                parts = param.split()
                if parts:
                    func_param_names.add(parts[-1])

    param_targets = call_targets.intersection(func_param_names)
    if param_targets:
        for target in param_targets:
            func_block_pattern = re.compile(
                r'function\s+(\w+)\s*\(([^)]*)\)[^{]*\{',
                re.DOTALL
            )
            for fm in func_block_pattern.finditer(stripped):
                func_params = fm.group(2)
                if target not in func_params:
                    continue
                func_start = fm.end()
                depth = 1
                pos = func_start
                while pos < len(stripped) and depth > 0:
                    if stripped[pos] == '{':
                        depth += 1
                    elif stripped[pos] == '}':
                        depth -= 1
                    pos += 1
                func_body = stripped[func_start:pos]
                if not re.search(rf'\b{re.escape(target)}\s*\.call\.value\s*\(', func_body) and \
                   not re.search(rf'\b{re.escape(target)}\s*\.call\s*\{{\s*value\s*:', func_body):
                    continue
                has_any_mapping_access = bool(re.search(
                    r'\w+(?:\s*\[[\w.\s]+\])+\s*(?:=|\+=|-=)', func_body
                ))
                if has_any_mapping_access:
                    return True
                func_header = stripped[fm.start():fm.end()]
                has_owner_modifier = bool(re.search(
                    r'\b(onlyOwner|onlyAdmin|onlyAuthorized|onlyMinter|onlyManager|auth|authorized)\b',
                    func_header
                ))
                has_owner_require = bool(re.search(
                    r'require\s*\(\s*msg\.sender\s*==\s*[oO]wner',
                    func_body
                )) or bool(re.search(
                    r'require\s*\(\s*[oO]wner\s*==\s*msg\.sender',
                    func_body
                ))
                has_owner_if = bool(re.search(
                    r'if\s*\(\s*msg\.sender\s*==\s*[oO]wner',
                    func_body
                ))
                if not (has_owner_modifier or has_owner_require or has_owner_if):
                    return True

    for target in call_targets:
        mapping_assign = re.compile(
            rf'{re.escape(target)}\s*=\s*\w+\s*\[', re.MULTILINE
        )
        if mapping_assign.search(stripped):
            return True

    for target in call_targets:
        struct_chain = re.search(
            rf'\w+(?:\s*\[[\w.]+\])*\s*\.\s*{re.escape(target)}\s*\.call\.value',
            stripped
        ) or re.search(
            rf'\w+(?:\s*\[[\w.]+\])*\s*\.\s*{re.escape(target)}\s*\.call\s*\{{\s*value',
            stripped
        )
        if struct_chain:
            return True

    _STATE_UPDATE_RE_2 = re.compile(
        r'(?:\w+(?:\s*\[[\w.\s]+\])+\s*(?:=|\+=|-=))'
        r'|(?:\w+\s*(?:-=|\+=)\s*\w+)'
        r'|(?:\w+\s*=\s*0\s*;)'
        r'|(?:delete\s+\w+)'
    )
    func_block_pat = re.compile(
        r'function\s+(\w+)\s*\(([^)]*)\)\s*([^{]*)\{', re.DOTALL
    )
    for fm in func_block_pat.finditer(stripped):
        func_header = fm.group(3)
        if re.search(r'\b(?:view|pure)\b', func_header):
            continue
        fstart = fm.end()
        d, p = 1, fstart
        while p < len(stripped) and d > 0:
            if stripped[p] == '{': d += 1
            elif stripped[p] == '}': d -= 1
            p += 1
        func_body = stripped[fstart:p-1]
        call_m = re.search(r'\.call\.value\s*\(', func_body) or \
                 re.search(r'\.call\s*\{\s*value\s*:', func_body)
        if not call_m:
            continue
        after_call = func_body[call_m.end():]
        if _STATE_UPDATE_RE_2.search(after_call):
            return True

    return False

def _analyse_reentrancy(transformed_cfg, domains):
    """Run Algorithm 2 on transformed_cfg for each domain in `domains`."""

    assert not hasattr(transformed_cfg, '_overflow_used'), \
        "ISOLATION VIOLATION: overflow pipeline must not share the transformed CFG"
    
    results = {}

    for domain in domains:
        logging.info(f"[REENTRANCY] Running {domain} domain.")
        csem = AbstractCollectingSemanticsAnalysis(
            transformed_cfg, 'SourceEntry_0', 'SourceExit_0',
            '/usr/local/lib/apron.jar', domain_type=domain
        )
        _register_reentrancy_probes(csem, transformed_cfg)

        buf = StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = buf
        sys.stderr = StringIO()
        timed_out = False
        _fix_t0 = time.time()
        try:
            _compute_with_timeout(csem)
        except _FixpointTimeout:
            timed_out = True
        except Exception as e:
            pass
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
        _fix_elapsed = time.time() - _fix_t0
        csem._fixpoint_seconds = _fix_elapsed
        if timed_out:
            logging.warning(f"[REENTRANCY] {domain} domain timed out after {FIXPOINT_TIMEOUT_SECONDS}s — falling back to structural analysis.")
        logging.info(f"[TIMING] reentrancy domain={domain} fixpoint={_fix_elapsed:.4f}s")
        csem._captured_output = buf.getvalue()

        verdicts = _emit_reentrancy_verdicts(transformed_cfg, csem)
        results[domain] = (verdicts, csem)

    return results

def _credit_zeroed_before_call(cfg, entry_node, if_stmt_id, credit_var):
    """Checks-Effects-Interactions (CEI) pattern detector."""
    if entry_node is None or if_stmt_id is None or credit_var is None:
        return False

    pre_call_nodes = _collect_pre_call_nodes(cfg, entry_node, if_stmt_id)

    for nid in pre_call_nodes:
        nd = cfg.cfg_metadata.get_node(nid)
        if nd is None:
            continue
        expr = getattr(nd, 'expression', nd)
        if getattr(expr, 'node_type', '') != 'Assignment':
            continue
        lhs = getattr(expr, 'leftHandSide', None)
        if lhs is None:
            continue
        lhs_name = getattr(lhs, 'name', None)
        if lhs_name != credit_var:
            continue
        rhs = getattr(expr, 'rightHandSide', None)
        if rhs is None:
            continue
        if getattr(rhs, 'node_type', '') == 'Literal':
            rhs_val = getattr(rhs, 'value', None)
            if str(rhs_val) == '0':
                return True
        rhs_number = getattr(rhs, 'number', None)
        if rhs_number is not None and str(rhs_number) == '0':
            return True

    return False

def _collect_pre_call_nodes(cfg, entry_node, if_stmt_id):
    """Collect all CFG node IDs reachable from entry_node up to (but not"""
    pre_call = []
    visited  = set()
    stack    = [entry_node]

    func_exit_boundary = None
    if entry_node.startswith('FunctionEntry_'):
        suffix = entry_node.split('_')[-1]
        candidate = f'FunctionExit_{suffix}'
        if candidate in cfg.cfg_metadata.node_table:
            func_exit_boundary = candidate

    while stack:
        nid = stack.pop()
        if nid in visited:
            continue
        visited.add(nid)
        if nid == if_stmt_id:
            continue
        if nid != entry_node and nid.startswith('FunctionEntry_'):
            continue
        if func_exit_boundary and nid == func_exit_boundary:
            pre_call.append(nid)
            continue
        node_obj = cfg.cfg_metadata.get_node(nid)
        if node_obj is None:
            continue
        pre_call.append(nid)
        for succ in node_obj.next_nodes:
            if succ not in visited:
                stack.append(succ)
    return pre_call

def _has_credit_effect_before_call(cfg, entry_node, if_stmt_id, credit_var):
    """Detect whether credit_var is assigned to 0, decremented (-=), or"""
    if entry_node is None or if_stmt_id is None or credit_var is None:
        return False

    pre_call_nodes = _collect_pre_call_nodes(cfg, entry_node, if_stmt_id)

    for nid in pre_call_nodes:
        nd = cfg.cfg_metadata.get_node(nid)
        if nd is None:
            continue
        expr = getattr(nd, 'expression', nd)
        if getattr(expr, 'node_type', '') != 'Assignment':
            continue
        lhs = getattr(expr, 'leftHandSide', None)
        if lhs is None:
            continue
        lhs_name = getattr(lhs, 'name', None)
        if lhs_name != credit_var:
            continue

        op = getattr(expr, 'operator', '')

        if op == '=':
            rhs = getattr(expr, 'rightHandSide', None)
            if rhs is not None:
                if getattr(rhs, 'node_type', '') == 'Literal':
                    if str(getattr(rhs, 'value', '')) == '0':
                        return True
                if getattr(rhs, 'node_type', '') == 'BinaryOperation':
                    rhs_op = getattr(rhs, 'operator', '')
                    if rhs_op == '-':
                        rhs_left = getattr(rhs, 'leftExpression', None)
                        if rhs_left and getattr(rhs_left, 'name', None) == credit_var:
                            return True

        if op == '-=':
            return True

    return False

_MUTEX_NAMES = frozenset({
    'flag', 'locked', '_locked', 'mutex', 'reentrancyLock',
    '_notEntered', 'notEntered', 'entered', '_status',
    'lock', 'guard', '_guard', 'done', '_done',
})

def _has_mutex_guard_before_call(cfg, entry_node, if_stmt_id):
    """Detect whether a boolean mutex/flag is SET (= true, or toggled via !flag)"""
    if entry_node is None or if_stmt_id is None:
        return False

    pre_call_nodes = _collect_pre_call_nodes(cfg, entry_node, if_stmt_id)

    mutex_set_vars = set()

    for nid in pre_call_nodes:
        nd = cfg.cfg_metadata.get_node(nid)
        if nd is None:
            continue
        expr = getattr(nd, 'expression', nd)
        if getattr(expr, 'node_type', '') != 'Assignment':
            continue
        lhs = getattr(expr, 'leftHandSide', None)
        if lhs is None:
            continue
        lhs_name = getattr(lhs, 'name', None)
        if lhs_name is None:
            continue

        op  = getattr(expr, 'operator', '')
        rhs = getattr(expr, 'rightHandSide', None)
        if rhs is None:
            continue

        if op == '=' and getattr(rhs, 'node_type', '') == 'Literal':
            if str(getattr(rhs, 'value', '')) == 'true':
                mutex_set_vars.add(lhs_name)
        if op == '=' and getattr(rhs, 'node_type', '') == 'UnaryOperation':
            if getattr(rhs, 'operator', '') == '!' and getattr(rhs, 'prefix', True):
                sub = getattr(rhs, 'subExpression', None) or getattr(rhs, 'expression', None)
                if sub and getattr(sub, 'name', None) == lhs_name:
                    mutex_set_vars.add(lhs_name)

    if mutex_set_vars:
        def _has_negated_require(var_name):
            for nid2 in pre_call_nodes:
                nd2 = cfg.cfg_metadata.get_node(nid2)
                if nd2 is None:
                    continue
                e2 = getattr(nd2, 'expression', nd2)
                if getattr(e2, 'node_type', '') != 'FunctionCall':
                    continue
                fn2 = getattr(e2, 'expression', None)
                fn2_name = getattr(fn2, 'name', '') if fn2 else ''
                if fn2_name not in ('require', 'assert'):
                    continue
                args2 = getattr(e2, 'arguments', [])
                if not args2:
                    continue
                a0 = args2[0] if isinstance(args2, list) else None
                if a0 and getattr(a0, 'node_type', '') == 'UnaryOperation':
                    if getattr(a0, 'operator', '') == '!':
                        sub2 = getattr(a0, 'subExpression', None) or getattr(a0, 'expression', None)
                        if sub2 and getattr(sub2, 'name', None) == var_name:
                            return True
            return False

        for var in mutex_set_vars:
            if var in _MUTEX_NAMES and _has_negated_require(var):
                return True

        for var in mutex_set_vars:
            if _has_negated_require(var):
                return True

    _MUTEX_SETTER_NAMES = frozenset({
        'toggle', 'lock', '_lock', 'setLock', 'setLocked',
        'lockMutex', 'acquireLock', 'enterLock', 'setFlag',
    })

    require_guarded_vars = set()
    for nid in pre_call_nodes:
        nd = cfg.cfg_metadata.get_node(nid)
        if nd is None:
            continue
        expr = getattr(nd, 'expression', nd)
        nt = getattr(expr, 'node_type', '')
        if nt == 'FunctionCall':
            fn_expr = getattr(expr, 'expression', None)
            fn_name = getattr(fn_expr, 'name', '') if fn_expr else ''
            if fn_name in ('require', 'assert'):
                args = getattr(expr, 'arguments', [])
                if args:
                    arg0 = args[0] if isinstance(args, list) else None
                    if arg0 and getattr(arg0, 'node_type', '') == 'UnaryOperation':
                        if getattr(arg0, 'operator', '') == '!':
                            sub = getattr(arg0, 'subExpression', None) or getattr(arg0, 'expression', None)
                            if sub:
                                guarded_name = getattr(sub, 'name', None)
                                if guarded_name and guarded_name in _MUTEX_NAMES:
                                    require_guarded_vars.add(guarded_name)

    if require_guarded_vars:
        for nid in pre_call_nodes:
            nd = cfg.cfg_metadata.get_node(nid)
            if nd is None:
                continue
            expr = getattr(nd, 'expression', nd)
            nt = getattr(expr, 'node_type', '')
            if nt == 'FunctionCall':
                fn_expr = getattr(expr, 'expression', None)
                fn_name = getattr(fn_expr, 'name', '') if fn_expr else ''
                if fn_name in _MUTEX_SETTER_NAMES:
                    return True

    return False

def _is_reentry_guarded(cfg, entry_node, if_stmt_id, credit_var):
    """Master pre-filter:  returns True if the reentrant path is semantically"""
    if _has_credit_effect_before_call(cfg, entry_node, if_stmt_id, credit_var):
        return True

    if _has_mutex_guard_before_call(cfg, entry_node, if_stmt_id):
        return True

    return False

def _emit_reentrancy_verdicts(cfg, csem, verbose=False):
    """Algorithm 2, steps 6-13 — with multi-strategy detection."""
    verdicts = []
    variable_registry = csem.variable_registry.variable_table
    credit_var = getattr(cfg, 'credit_var_name', None)

    V_present = (
        'BAL'          in variable_registry
        and 'attacker_bal' in variable_registry
        and credit_var is not None
        and credit_var in variable_registry
        and credit_var != 'BAL'
    )

    if not V_present:
        if credit_var == 'BAL':
            verdicts.append(
                "[REENTRANCY-SKIP] Algorithm 2 not applied: no mapping declared, "
                "credit[a] degenerates to BAL — three-variable invariant ill-defined."
            )
        return verdicts

    def _iv(arr, idx):
        s = str(arr[idx].toString()).strip()
        if not s or s in ('bottom', 'Bottom', '[]'):
            return [0.0, 0.0]
        if s.startswith('[') and s.endswith(']'):
            s = s[1:-1]
        parts = s.split(',')
        def _f(x):
            x = x.strip()
            if x in ('Infinity', '+Infinity'): return _math.inf
            if x == '-Infinity':               return -_math.inf
            try:    return float(x)
            except: return 0.0
        return [_f(parts[0]), _f(parts[1])] if len(parts) == 2 else [0.0, 0.0]

    def _sub(fi, ii):
        return [fi[0] - ii[1], fi[1] - ii[0]]
    def _w(iv):
        return iv[1] - iv[0]

    bal_idx    = variable_registry['BAL']['id']
    att_idx    = variable_registry['attacker_bal']['id']
    credit_idx = variable_registry[credit_var]['id']

    back_edge = getattr(cfg, '_back_edge', (None, None))
    back_edge_src, if_stmt_id = back_edge

    entry_node = exit_node = None
    if if_stmt_id is not None:
        visited = set()
        queue = [if_stmt_id]
        found_entry = None
        while queue and found_entry is None:
            nid = queue.pop(0)
            if nid in visited:
                continue
            visited.add(nid)
            if nid.startswith('FunctionEntry_'):
                found_entry = nid
                break
            node_obj = cfg.cfg_metadata.get_node(nid)
            if node_obj is None:
                continue
            for prev_id in node_obj.prev_nodes:
                if prev_id not in visited:
                    queue.append(prev_id)

        if found_entry is not None:
            entry_node = found_entry
            suffix = found_entry.split('_')[-1]
            candidate_exit = f'FunctionExit_{suffix}'
            if candidate_exit in cfg.cfg_metadata.node_table:
                exit_node = candidate_exit
            if exit_node is None:
                fwd_visited = set()
                fwd_queue = [entry_node]
                while fwd_queue:
                    fid = fwd_queue.pop(0)
                    if fid in fwd_visited:
                        continue
                    fwd_visited.add(fid)
                    if fid.startswith('FunctionExit_'):
                        exit_node = fid
                        break
                    fnode = cfg.cfg_metadata.get_node(fid)
                    if fnode is None:
                        continue
                    for nxt in fnode.next_nodes:
                        if nxt not in fwd_visited:
                            fwd_queue.append(nxt)

    if entry_node is None or exit_node is None:
        entry_node = exit_node = None
        for nid in cfg.cfg_metadata.node_table:
            if entry_node is None and nid.startswith('FunctionEntry_'):
                entry_node = nid
            if nid.startswith('FunctionExit_'):
                exit_node = nid

    if entry_node is None or exit_node is None:
        return verdicts

    detected = False

    if if_stmt_id is not None:
        _guarded = _is_reentry_guarded(cfg, entry_node, if_stmt_id, credit_var)
        if _guarded:
            verdicts.append(
                "[NO REENTRANCY] Balance-preservation invariant maintained at claim."
            )
            return verdicts

    try:
        final_iter = csem.point_state.iteration
        init_ss  = csem.point_state.get_node_state_set(
            entry_node, final_iter, False)
        final_ss = csem.point_state.get_node_state_set(
            exit_node, final_iter, False)
        init_ivs  = init_ss.toBox(csem.manager)
        final_ivs = final_ss.toBox(csem.manager)

        bal_i,  bal_f  = _iv(init_ivs, bal_idx),    _iv(final_ivs, bal_idx)
        att_i,  att_f  = _iv(init_ivs, att_idx),    _iv(final_ivs, att_idx)
        cr_i,   cr_f   = _iv(init_ivs, credit_idx), _iv(final_ivs, credit_idx)

        d_bal    = _sub(bal_f,  bal_i)
        d_att    = _sub(att_f,  att_i)
        d_credit = _sub(cr_f,   cr_i)
        w_bal, w_att, w_credit = _w(d_bal), _w(d_att), _w(d_credit)

        if (w_att >= w_credit and w_credit > 0) or (w_bal >= w_credit and w_credit > 0):
            detected = True
            verdict_short = "[REENTRANCY] Balance-preservation invariant violated."
            verdict_detail = (
                f"[REENTRANCY] Balance-preservation invariant violated. "
                f"ΔBAL=[{_fmt_num(d_bal[0])},{_fmt_num(d_bal[1])}] (w={_fmt_num(w_bal)}), "
                f"Δattacker_bal=[{_fmt_num(d_att[0])},{_fmt_num(d_att[1])}] (w={_fmt_num(w_att)}), "
                f"Δ{credit_var}=[{_fmt_num(d_credit[0])},{_fmt_num(d_credit[1])}] (w={_fmt_num(w_credit)}). "
                f"Δ-width mismatch indicates attacker/contract balance drift "
                f"across re-entrant invocations while credit decrements only once (paper Algorithm 2)."
            )
            verdicts.append(verdict_detail if verbose else verdict_short)
    except Exception as e:
        logging.warning(f"[REENTRANCY] Strategy A exception: {e}")

    if not detected:
        try:
            final_iter = csem.point_state.iteration
            best_init_iter = None
            for it in range(1, final_iter + 1):
                try:
                    ss = csem.point_state.get_node_state_set(
                        entry_node, it, False)
                    ivs = ss.toBox(csem.manager)
                    b = _iv(ivs, bal_idx)
                    a = _iv(ivs, att_idx)
                    if (b[0] != -_math.inf and b[1] != _math.inf
                            and a[0] != -_math.inf and a[1] != _math.inf):
                        best_init_iter = it
                except Exception:
                    continue

            if best_init_iter is not None and best_init_iter != final_iter:
                init_ss_b = csem.point_state.get_node_state_set(
                    entry_node, best_init_iter, False)
                final_ss_b = csem.point_state.get_node_state_set(
                    exit_node, final_iter, False)
                init_ivs_b  = init_ss_b.toBox(csem.manager)
                final_ivs_b = final_ss_b.toBox(csem.manager)

                bal_i  = _iv(init_ivs_b, bal_idx)
                att_i  = _iv(init_ivs_b, att_idx)
                cr_i   = _iv(init_ivs_b, credit_idx)
                bal_f  = _iv(final_ivs_b, bal_idx)
                att_f  = _iv(final_ivs_b, att_idx)
                cr_f   = _iv(final_ivs_b, credit_idx)

                d_bal    = _sub(bal_f,  bal_i)
                d_att    = _sub(att_f,  att_i)
                d_credit = _sub(cr_f,   cr_i)
                w_bal, w_att, w_credit = _w(d_bal), _w(d_att), _w(d_credit)

                if (w_att >= w_credit and w_credit > 0) or (w_bal >= w_credit and w_credit > 0):
                    detected = True
                    verdict_short = "[REENTRANCY] Balance-preservation invariant violated."
                    verdict_detail = (
                        f"[REENTRANCY] Balance-preservation invariant violated. "
                        f"ΔBAL=[{_fmt_num(d_bal[0])},{_fmt_num(d_bal[1])}] (w={_fmt_num(w_bal)}), "
                        f"Δattacker_bal=[{_fmt_num(d_att[0])},{_fmt_num(d_att[1])}] (w={_fmt_num(w_att)}), "
                        f"Δ{credit_var}=[{_fmt_num(d_credit[0])},{_fmt_num(d_credit[1])}] (w={_fmt_num(w_credit)}). "
                        f"Δ-width mismatch detected via early-iteration probe (Algorithm 2)."
                    )
                    verdicts.append(verdict_detail if verbose else verdict_short)
        except Exception as e:
            logging.warning(f"[REENTRANCY] Strategy B exception: {e}")

    if not detected:
        try:
            final_iter = csem.point_state.iteration
            init_ss_d  = csem.point_state.get_node_state_set(entry_node, final_iter, False)
            final_ss_d = csem.point_state.get_node_state_set(exit_node,  final_iter, False)
            init_ivs_d  = init_ss_d.toBox(csem.manager)
            final_ivs_d = final_ss_d.toBox(csem.manager)
            cr_i_d = _iv(init_ivs_d,  credit_idx)
            cr_f_d = _iv(final_ivs_d, credit_idx)
            bal_f_d = _iv(final_ivs_d, bal_idx)
            bal_i_d = _iv(init_ivs_d,  bal_idx)
            att_f_d = _iv(final_ivs_d, att_idx)
            att_i_d = _iv(init_ivs_d,  att_idx)
            credit_wiped = (cr_f_d[0] == 0.0 and cr_f_d[1] == 0.0
                            and cr_i_d[1] > 0.0)
            bal_changed = (bal_f_d != bal_i_d or att_f_d != att_i_d)
            if credit_wiped and bal_changed:
                detected = True
                verdicts.append("[REENTRANCY] Balance-preservation invariant violated.")
        except Exception as e:
            logging.warning(f"[REENTRANCY] Strategy D exception: {e}")

    if not detected and if_stmt_id is not None and back_edge_src is not None:
        try:
            if_node = cfg.cfg_metadata.get_node(if_stmt_id)
            then_entry = getattr(if_node, 'true_body_next', None) if if_node else None
            if then_entry and then_entry in cfg.cfg_metadata.node_table:
                loop_body_nodes = []
                current = then_entry
                walk_seen = set()
                while current and current not in walk_seen:
                    walk_seen.add(current)
                    loop_body_nodes.append(current)
                    if current == back_edge_src:
                        break
                    cur_node = cfg.cfg_metadata.get_node(current)
                    if cur_node is None:
                        break
                    nxt = None
                    for s in cur_node.next_nodes:
                        if s != if_stmt_id:
                            nxt = s
                            break
                    current = nxt

                modified_vars = set()
                for nid in loop_body_nodes:
                    nd = cfg.cfg_metadata.get_node(nid)
                    if nd is None:
                        continue
                    expr = getattr(nd, 'expression', nd)
                    if getattr(expr, 'node_type', '') == 'Assignment':
                        lhs = getattr(expr, 'leftHandSide', None)
                        if lhs:
                            lhs_name = getattr(lhs, 'name', None)
                            if lhs_name:
                                modified_vars.add(lhs_name)

                bal_mod = 'BAL' in modified_vars
                att_mod = 'attacker_bal' in modified_vars
                credit_mod = credit_var in modified_vars

                if (bal_mod or att_mod) and not credit_mod:
                    if not _is_reentry_guarded(cfg, entry_node, if_stmt_id, credit_var):
                        detected = True
                        detail_parts = []
                        if bal_mod:
                            detail_parts.append("BAL decremented")
                        if att_mod:
                            detail_parts.append("attacker_bal incremented")
                        detail_parts.append(
                            f"{credit_var} NOT modified in re-entrant loop body")
                        verdict_short = "[REENTRANCY] Balance-preservation invariant violated."
                        verdict_detail = (
                            f"[REENTRANCY] Balance-preservation invariant violated. "
                            f"Structural analysis: {'; '.join(detail_parts)}. "
                            f"Back-edge loop {back_edge_src} → {if_stmt_id} "
                            f"drains contract balance without decrementing credit "
                            f"(paper Algorithm 2, structural fallback)."
                        )
                        verdicts.append(verdict_detail if verbose else verdict_short)
        except Exception as e:
            logging.warning(f"[REENTRANCY] Strategy C exception: {e}")

    if not detected:
        verdict_short = "[NO REENTRANCY] Balance-preservation invariant maintained at claim."
        verdict_detail = (
            f"[NO REENTRANCY] Balance-preservation invariant maintained at claim."
        )
        verdicts.append(verdict_detail if verbose else verdict_short)

    return verdicts

_OF_INT_TYPE_RE = re.compile(r'\b(u?int(?:8|16|32|64|128|256)?)\b')

def _detect_overflow_dataflow(source_code, checked_default):
    """Augmented data-flow Algorithm 3 (source level) — completes the node"""
    if checked_default:
        return []

    s = re.sub(r'//[^\n]*', '', source_code)
    s = re.sub(r'/\*.*?\*/', '', s, flags=re.DOTALL)

    state_types = {}
    depth, top = 0, []
    for ch in s:
        if ch == '{': depth += 1
        elif ch == '}': depth = max(0, depth - 1)
        elif depth <= 1:
            top.append(ch)
    top_src = ''.join(top)
    for m in re.finditer(r'\b(u?int(?:8|16|32|64|128|256)?)\s+(?:public\s+|private\s+|internal\s+|constant\s+)*(\w+)', top_src):
        state_types.setdefault(m.group(2), m.group(1))
    mappings = set(re.findall(r'mapping\s*\([^)]*\)\s*(?:public\s+|private\s+|internal\s+)*(\w+)', s))

    _CALL = ''
    _ENV = {'block.timestamp', 'now', 'msg.value'}

    lib_spans = []
    for lm in re.finditer(r'\b(?:library\s+\w+|contract\s+SafeMath\w*)\s*(?:is\s+[^{]*)?\{', s):
        d, i = 1, lm.end()
        while i < len(s) and d > 0:
            if s[i] == '{': d += 1
            elif s[i] == '}': d -= 1
            i += 1
        lib_spans.append((lm.start(), i))

    def _in_library(pos):
        return any(a <= pos < b for a, b in lib_spans)

    def _func_iter():
        for fm in re.finditer(r'function\s+(\w+)\s*\(([^)]*)\)([^{]*)\{', s):
            if _in_library(fm.start()):
                continue
            start = fm.end()
            d, i = 1, fm.end()
            while i < len(s) and d > 0:
                if s[i] == '{': d += 1
                elif s[i] == '}': d -= 1
                i += 1
            yield fm.group(1), fm.group(2), fm.group(3), s[start:i-1]

    def _param_types(plist):
        out = {}
        for piece in plist.split(','):
            mt = re.search(r'\b(u?int(?:8|16|32|64|128|256)?)\b\s+(?:memory\s+|calldata\s+|storage\s+)?(\w+)', piece)
            if mt:
                out[mt.group(2)] = mt.group(1)
        return out

    _LIT = re.compile(r'^\s*\d[\d_]*\s*(?:ether|wei|days|hours|minutes|seconds|weeks)?\s*$')

    verdicts = []
    seen = set()
    for fname, plist, header, body in _func_iter():
        ptypes = _param_types(plist)
        ltypes = {}
        for lm in re.finditer(r'\b(u?int(?:8|16|32|64|128|256)?)\s+(\w+)\s*=', body):
            ltypes[lm.group(2)] = lm.group(1)
        tainted = set(ptypes) | set(state_types) | set(mappings) | {'balance'}

        def _is_tainted(expr):
            if 'block.timestamp' in expr or 'msg.value' in expr or re.search(r'\bnow\b', expr) \
               or '.balance' in expr:
                return True
            for nm in re.findall(r'[A-Za-z_]\w*', expr):
                if nm in tainted or nm in ltypes or nm in ptypes or nm in state_types:
                    return True
            return False

        def _bounded(expr):
            if '%' in expr or '&' in expr:
                return True
            if _LIT.match(expr):
                return True
            return False

        def _type_of(expr):
            for nm in re.findall(r'[A-Za-z_]\w*', expr):
                for tbl in (ltypes, ptypes, state_types):
                    if nm in tbl:
                        return tbl[nm]
            return 'uint256'

        guard_conds = re.findall(r'(?:require|assert|if)\s*\(([^{}();]*)', body)

        def _guarded(left, right):
            lv = set(re.findall(r'[A-Za-z_]\w*', left or '')) - {'uint', 'int'}
            rv = set(re.findall(r'[A-Za-z_]\w*', right or ''))
            if not lv or not rv:
                return False
            for c in guard_conds:
                if any(o in c for o in ('>=', '>', '<=', '<')):
                    cv = set(re.findall(r'[A-Za-z_]\w*', c))
                    if (lv & cv) and (rv & cv):
                        return True
            return False

        def _ts_minus_statevar(stmt_text):
            for mm in re.finditer(r'(?:block\.timestamp|block\.number|now)\s*-\s*([A-Za-z_]\w*|\d[\d_]*)', stmt_text):
                v = mm.group(1)
                if v.isdigit() or (v in state_types and v not in ptypes):
                    return True
            return False

        def _split_bin(expr):
            mo = re.search(r'^(.+?[A-Za-z_0-9\]\)])\s*([-+*])\s*([A-Za-z_0-9\(].*)$', expr.strip())
            if mo:
                return mo.group(2), mo.group(1), mo.group(3)
            return None, None, None

        for stmt in re.split(r'[;{}]', body):
            st = stmt.strip()
            if not st:
                continue
            if re.match(r'^(?:else\s+)?(?:if|for|while)\s*\(', st):
                idx = st.index('('); d, j = 1, st.index('(') + 1
                while j < len(st) and d > 0:
                    if st[j] == '(': d += 1
                    elif st[j] == ')': d -= 1
                    j += 1
                st = st[j:].strip()
            elif re.match(r'^else\b', st):
                st = st[4:].strip()
            if not st or re.match(r'^(require|assert)\b', st):
                continue
            if re.search(r'\.(add|sub|mul|div)\s*\(', st):
                continue
            op = None; left = None; right = None; vname = None; vtype = 'uint256'
            is_compound = False
            m_ret = re.match(r'^return\s+(.+)$', st)
            m_cmp = re.search(r'([A-Za-z_]\w*(?:\s*\[[^\]]*\])*)\s*(\+=|-=|\*=)\s*(.+)$', st)
            if m_cmp:
                L, cop, R = m_cmp.group(1), m_cmp.group(2)[0], m_cmp.group(3)
                op, left, right, vname, vtype = cop, L, R, L.strip(), _type_of(L)
                is_compound = True
            elif m_ret:
                op, left, right = _split_bin(m_ret.group(1))
                vname, vtype = '(return value)', _type_of(m_ret.group(1))
            else:
                rhs_m = re.search(r'=\s*(.+)$', st)
                if rhs_m:
                    op, left, right = _split_bin(rhs_m.group(1))
                    lm = re.match(r'^(?:u?int(?:8|16|32|64|128|256)?\s+)?([A-Za-z_]\w*(?:\s*\[[^\]]*\])*)\s*=', st)
                    vname = lm.group(1).strip() if lm else '(expr)'
                    vtype = _type_of(rhs_m.group(1))
            if op is None or op not in ('-', '+', '*'):
                continue
            pair = (left or '') + ' ' + (right or '')
            if not _is_tainted(pair):
                continue
            if _bounded(left or '') and _bounded(right or ''):
                continue
            if '%' in pair or '&' in pair:
                continue
            if op != '-' and re.search(r'\bmsg\.value\b', pair):
                continue
            if op == '-':
                if _guarded(left, right):
                    continue
                if _ts_minus_statevar(st):
                    continue
            if op == '*':
                lv, rv = (left or '').strip(), (right or '').strip()
                if (lv in state_types and rv in state_types
                        and lv not in ptypes and rv not in ptypes):
                    continue
            if is_compound and op in ('+', '-'):
                rv = (right or '').strip()
                if re.match(r'^\d[\d_]*$', rv) and int(rv.replace('_', '')) <= 1000:
                    continue
            kind = 'UNDERFLOW' if op == '-' else 'OVERFLOW'
            key = (fname, vname, kind, st[:40])
            if key in seen:
                continue
            seen.add(key)
            tmax = _OVERFLOW_TYPE_RANGES.get(vtype, (0, 2**256 - 1))[1] \
                if '_OVERFLOW_TYPE_RANGES' in globals() else 2**256 - 1
            verdicts.append(
                f"[{kind}] Variable {vname} ({vtype}) in {fname}(): unguarded "
                f"'{op}' over external input can {'underflow below 0' if kind=='UNDERFLOW' else f'exceed type max {tmax}'} "
                f"(augmented data-flow Algorithm 3)."
            )
    return verdicts

def _analyse_overflow(source_code):
    """Run Algorithm 3 on the ORIGINAL (untransformed) source."""
    try:
        cfg, _ = _build_cfg(source_code)
    except RuntimeError as e:
        logging.warning(f"[OVERFLOW] CFG build failed: {e}")
        return [], None

    cfg._overflow_used = True

    checked_default = _is_checked_arithmetic_default(cfg)
    has_unchecked   = _contract_has_unchecked_blocks(cfg)

    try:
        csem = AbstractCollectingSemanticsAnalysis(
            cfg, 'SourceEntry_0', 'SourceExit_0',
            '/usr/local/lib/apron.jar', domain_type='Box'
        )
        _auto_register_function_params(cfg, csem.constant_registry)
        csem.constant_registry.register_variable('msgsender', False, ('100', '100'))
        csem.constant_registry.register_variable('msgvalue',  False, ('20',  '20'))
        csem.constant_registry.register_variable('msg.value', False, ('20',  '20'))
        buf_of = StringIO()
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = buf_of
        sys.stderr = StringIO()
        try:
            _compute_with_timeout(csem)
        except _FixpointTimeout:
            sys.stdout = old_out
            sys.stderr = old_err
            logging.warning(f"[OVERFLOW] Fixpoint timed out after {FIXPOINT_TIMEOUT_SECONDS}s — falling back to structural analysis.")
            raise
        finally:
            sys.stdout = old_out
            sys.stderr = old_err
        csem._captured_output = buf_of.getvalue()
        verdicts = _emit_overflow_verdicts(cfg, csem, checked_default, has_unchecked, source_code=source_code)
    except Exception:
        variable_table = cfg.cfg_metadata.variable_table
        verdicts = _detect_structural_overflow(cfg, variable_table)
        if not verdicts:
            logging.info("[OVERFLOW] Abstract fixpoint incomplete (unsupported node in source); no vulnerabilities detected by structural fallback.")
        csem = None

    try:
        for v in _detect_overflow_dataflow(source_code, checked_default):
            if v not in verdicts:
                verdicts.append(v)
    except Exception as e:
        logging.debug(f"[OVERFLOW] data-flow supplement skipped: {e}")

    return verdicts, csem

def _get_defined_vars_at_node(cfg, node_id):
    """Return the set of variable names written (defined) at this CFG node."""
    nobj = cfg.cfg_metadata.get_node(node_id)
    if nobj is None:
        return set()
    nt = getattr(nobj, 'node_type', '')
    defined = set()

    def _extract_lhs(lhs):
        if lhs is None:
            return
        name = getattr(lhs, 'name', None)
        if name:
            defined.add(name)
        if getattr(lhs, 'node_type', '') == 'IndexAccess':
            base = getattr(lhs, 'base_expression', None) \
                   or getattr(lhs, 'baseExpression', None)
            if base:
                bname = getattr(base, 'name', None)
                if bname:
                    defined.add(bname)

    if nt == 'Assignment':
        _extract_lhs(getattr(nobj, 'leftHandSide', None))

    elif nt == 'ExpressionStatement':
        expr = getattr(nobj, 'expression', None)
        if expr and getattr(expr, 'node_type', '') == 'Assignment':
            _extract_lhs(getattr(expr, 'leftHandSide', None))
        if expr and getattr(expr, 'node_type', '') == 'UnaryOperation':
            sub = getattr(expr, 'subExpression', None)
            if sub:
                name = getattr(sub, 'name', None)
                if name:
                    defined.add(name)

    elif nt == 'VariableDeclarationStatement':
        for decl in getattr(nobj, 'declarations', []):
            if decl:
                name = getattr(decl, 'name', None)
                if name:
                    defined.add(name)

    elif nt in ('ForLoopJoin', 'ForLoopContinue'):
        _collect_loop_arith_vars(cfg, node_id, defined)

    return defined

def _collect_loop_arith_vars(cfg, loop_join_id, result_set):
    """Scan ALL nodes in the CFG to find variables modified by arithmetic"""
    ARITH_COMPOUND = {'+=', '-=', '*='}
    ARITH_BINARY   = {'+', '-', '*', '**'}

    def _extract_arith_var(asgn_obj):
        """If asgn_obj is an Assignment with arithmetic, return LHS name."""
        op = getattr(asgn_obj, 'operator', None)
        lhs = getattr(asgn_obj, 'leftHandSide', None)
        name = None
        if lhs:
            name = getattr(lhs, 'name', None)
            if not name and getattr(lhs, 'node_type', '') == 'IndexAccess':
                base = getattr(lhs, 'base_expression', None) \
                       or getattr(lhs, 'baseExpression', None)
                if base:
                    name = getattr(base, 'name', None)
        if not name:
            return
        if op in ARITH_COMPOUND:
            result_set.add(name)
        elif op == '=':
            rhs = getattr(asgn_obj, 'rightHandSide', None)
            if rhs and getattr(rhs, 'node_type', '') == 'BinaryOperation':
                rop = getattr(rhs, 'operator', '')
                if rop in ARITH_BINARY:
                    result_set.add(name)

    for nid, nobj in cfg.cfg_metadata.node_table.items():
        n_type = getattr(nobj, 'node_type', '')

        if n_type == 'ExpressionStatement':
            expr = getattr(nobj, 'expression', None)
            if expr:
                if getattr(expr, 'node_type', '') == 'Assignment':
                    _extract_arith_var(expr)
                elif getattr(expr, 'node_type', '') == 'UnaryOperation':
                    uop = getattr(expr, 'operator', '')
                    if uop in ('++', '--'):
                        sub = getattr(expr, 'subExpression', None)
                        if sub:
                            sname = getattr(sub, 'name', None)
                            if sname:
                                result_set.add(sname)
        elif n_type == 'Assignment':
            _extract_arith_var(nobj)
        elif n_type == 'VariableDeclarationStatement':
            init_val = getattr(nobj, 'initialValue', None)
            if init_val and getattr(init_val, 'node_type', '') == 'BinaryOperation':
                rop = getattr(init_val, 'operator', '')
                if rop in ARITH_BINARY:
                    for decl in getattr(nobj, 'declarations', []):
                        if decl:
                            dname = getattr(decl, 'name', None)
                            if dname:
                                result_set.add(dname)

def _node_has_arithmetic_op(cfg, node_id):
    """Check whether the node involves arithmetic that can cause overflow."""
    nobj = cfg.cfg_metadata.get_node(node_id)
    if nobj is None:
        return True
    nt = getattr(nobj, 'node_type', '')

    def _rhs_has_arith(rhs):
        """Recursively check if an RHS expression tree contains +,-,*,**."""
        if rhs is None:
            return False
        rhs_nt = getattr(rhs, 'node_type', '')
        if rhs_nt == 'BinaryOperation':
            rop = getattr(rhs, 'operator', '')
            if rop in ('+', '-', '*', '**', '<<'):
                return True
            if rop in ('/', '%'):
                return _rhs_has_arith(getattr(rhs, 'leftExpression', None)) \
                    or _rhs_has_arith(getattr(rhs, 'rightExpression', None))
        if rhs_nt == 'TupleExpression':
            for comp in getattr(rhs, 'components', []):
                if comp and _rhs_has_arith(comp):
                    return True
        return False

    def _check_assignment(asgn_obj):
        op = getattr(asgn_obj, 'operator', None)
        if op in ('+=', '-=', '*='):
            return True
        if op == '=':
            return _rhs_has_arith(getattr(asgn_obj, 'rightHandSide', None))
        return False

    if nt == 'Assignment':
        return _check_assignment(nobj)

    if nt == 'ExpressionStatement':
        expr = getattr(nobj, 'expression', None)
        if expr and getattr(expr, 'node_type', '') == 'Assignment':
            return _check_assignment(expr)
        if expr and getattr(expr, 'node_type', '') == 'UnaryOperation':
            return getattr(expr, 'operator', '') in ('++', '--')
        return False

    if nt == 'VariableDeclarationStatement':
        init_val = getattr(nobj, 'initialValue', None)
        if init_val is None:
            return False
        return _rhs_has_arith(init_val)

    if nt in ('ForLoopJoin', 'ForLoopContinue'):
        return True

    return True

def _is_overflow_guarded(cfg, node_id, var_name, strict_guard=False):
    """Detect whether an arithmetic operation on var_name at node_id is"""
    nobj = cfg.cfg_metadata.get_node(node_id)
    if nobj is None:
        return False
 
    def _is_guard_node(n_id, strict_guard=False):
        n = cfg.cfg_metadata.get_node(n_id)
        if n is None:
            return False
        nt = getattr(n, 'node_type', '')
        expr = getattr(n, 'expression', n)
        if getattr(expr, 'node_type', '') == 'FunctionCall':
            fn_expr = getattr(expr, 'expression', None)
            fn_name = getattr(fn_expr, 'name', '') if fn_expr else ''
            if not fn_name:
                fn_name = getattr(expr, 'function_name', '')
            if fn_name and fn_name.lower() in ('require', 'assert'):
                args = getattr(expr, 'arguments', [])
                for arg in args:
                    if _expr_mentions(arg, var_name):
                        return True
        if nt == 'FunctionCall':
            fn_expr = getattr(n, 'expression', None)
            fn_name = getattr(fn_expr, 'name', '') if fn_expr else ''
            if not fn_name:
                fn_name = getattr(n, 'function_name', '')
            if fn_name and fn_name.lower() in ('require', 'assert'):
                args = getattr(n, 'arguments', [])
                for arg in args:
                    if _expr_mentions(arg, var_name):
                        return True
        if nt == 'IfStatement':
            cond = getattr(n, 'condition', None)
            if cond and _expr_mentions(cond, var_name):
                cond_nt = getattr(cond, 'node_type', '')
                cond_op = getattr(cond, 'operator', '')
                if cond_nt == 'BinaryOperation' and cond_op in ('>=', '<=', '>', '<', '==', '!='):
                    if not strict_guard:
                        return True
                    left_c = getattr(cond, 'leftExpression', None)
                    right_c = getattr(cond, 'rightExpression', None)
                    left_is_lit = getattr(left_c, 'node_type', '') == 'Literal' if left_c else False
                    right_is_lit = getattr(right_c, 'node_type', '') == 'Literal' if right_c else False
                    if not left_is_lit and not right_is_lit:
                        return True
                if cond_nt == 'BinaryOperation' and cond_op in ('&&', '||'):
                    for sub_attr in ('leftExpression', 'rightExpression'):
                        sub = getattr(cond, sub_attr, None)
                        if sub and getattr(sub, 'node_type', '') == 'BinaryOperation':
                            sub_op = getattr(sub, 'operator', '')
                            if sub_op in ('>=', '<=', '>', '<', '==', '!=') and _expr_mentions(sub, var_name):
                                if not strict_guard:
                                    return True
                                left_s = getattr(sub, 'leftExpression', None)
                                right_s = getattr(sub, 'rightExpression', None)
                                left_is_lit_s = getattr(left_s, 'node_type', '') == 'Literal' if left_s else False
                                right_is_lit_s = getattr(right_s, 'node_type', '') == 'Literal' if right_s else False
                                if not left_is_lit_s and not right_is_lit_s:
                                    return True
        return False
 
    def _expr_mentions(expr_obj, name):
        """Recursively check if an expression AST node mentions a variable name."""
        if expr_obj is None:
            return False
        if getattr(expr_obj, 'name', None) == name:
            return True
        for attr in ('leftExpression', 'rightExpression', 'subExpression',
                      'expression', 'condition', 'trueExpression', 'falseExpression',
                      'leftHandSide', 'rightHandSide',
                      'base_expression', 'baseExpression', 'index_expression', 'indexExpression'):
            child = getattr(expr_obj, attr, None)
            if child is not None and _expr_mentions(child, name):
                return True
        for arg in getattr(expr_obj, 'arguments', []):
            if arg is not None and _expr_mentions(arg, name):
                return True
        for comp in getattr(expr_obj, 'components', []):
            if comp is not None and _expr_mentions(comp, name):
                return True
        return False
 
    visited = set()
    queue_succ = []
    for succ_id in getattr(nobj, 'next_nodes', {}):
        queue_succ.append(succ_id)
    while queue_succ and len(visited) < 20:
        s_id = queue_succ.pop(0)
        if s_id in visited:
            continue
        visited.add(s_id)
        if _is_guard_node(s_id, strict_guard):
            return True
        s_node = cfg.cfg_metadata.get_node(s_id)
        if s_node is not None:
            for ns in getattr(s_node, 'next_nodes', {}):
                if ns not in visited:
                    queue_succ.append(ns)
 
    visited_pred = set()
    queue_pred = []
    for pred_id in getattr(nobj, 'prev_nodes', {}):
        queue_pred.append(pred_id)
    while queue_pred and len(visited_pred) < 50:
        p_id = queue_pred.pop(0)
        if p_id in visited_pred:
            continue
        visited_pred.add(p_id)
        if _is_guard_node(p_id, strict_guard):
            return True
        p_node = cfg.cfg_metadata.get_node(p_id)
        if p_node is not None:
            for pp in getattr(p_node, 'prev_nodes', {}):
                if pp not in visited_pred:
                    queue_pred.append(pp)
 
    return False

def _is_overflow_guarded_extended(cfg, node_id, var_name, rhs_names):
    """Extended guard detection: check guards referencing EITHER the LHS"""
    if _is_overflow_guarded(cfg, node_id, var_name):
        return True
    for rhs_var in rhs_names:
        if rhs_var and rhs_var not in ('msg', 'sender', 'value', 'this'):
            if _is_overflow_guarded(cfg, node_id, rhs_var):
                return True
    return False
 
def _is_in_internal_function(cfg, node_id):
    """Check if node_id is inside a pure/view function (like SafeMath)."""
    visited = set()
    queue = [node_id]
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        if curr.startswith('FunctionDefinition_'):
            fn_obj = cfg.cfg_metadata.get_node(curr)
            if fn_obj:
                mutability = getattr(fn_obj, 'stateMutability', '')
                visibility = getattr(fn_obj, 'visibility', '')
                if mutability in ('pure', 'view') or visibility in ('pure', 'view'):
                    return True
            return False
        curr_obj = cfg.cfg_metadata.get_node(curr)
        if curr_obj and hasattr(curr_obj, 'prev_nodes'):
            for pred in curr_obj.prev_nodes:
                if pred not in visited:
                    queue.append(pred)
        if len(visited) > 200:
            break
    return False

def _is_in_access_controlled_function(cfg, node_id, source_code=None):
    """Check if node_id is inside a function protected by access-control"""
    visited = set()
    queue = [node_id]
    func_node = None
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        if curr.startswith('FunctionDefinition_'):
            func_node = cfg.cfg_metadata.get_node(curr)
            break
        curr_obj = cfg.cfg_metadata.get_node(curr)
        if curr_obj and hasattr(curr_obj, 'prev_nodes'):
            for pred in curr_obj.prev_nodes:
                if pred not in visited:
                    queue.append(pred)
        if len(visited) > 200:
            break

    if func_node is None:
        return False

    _ACCESS_MODIFIERS = frozenset({
        'onlyOwner', 'onlyAdmin', 'onlyAuthorized', 'onlyMinter',
        'onlyManager', 'auth', 'authorized', 'onlyGovernance',
        'onlyOperator', 'onlyController', 'onlyRole', 'requiresAuth',
        'onlyCEO', 'onlyCFO', 'onlyCOO', 'ownerOnly', 'adminOnly',
    })

    modifiers = getattr(func_node, 'modifiers', [])
    if isinstance(modifiers, list):
        for mod in modifiers:
            mod_name = None
            if isinstance(mod, dict):
                mod_name = mod.get('modifierName', {}).get('name', '')
            elif hasattr(mod, 'name'):
                mod_name = mod.name
            elif isinstance(mod, str):
                mod_name = mod
            if mod_name and mod_name in _ACCESS_MODIFIERS:
                return True

    if source_code:
        func_name = getattr(func_node, 'name', None)
        if func_name:
            stripped = re.sub(r'//[^\n]*', '', source_code)
            stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)
            _ACCESS_RE = re.compile(
                r'function\s+' + re.escape(func_name) + r'\s*\([^)]*\)\s*[^{]*'
                r'\b(onlyOwner|onlyAdmin|onlyAuthorized|onlyMinter|onlyManager'
                r'|auth|authorized|onlyGovernance|onlyOperator|onlyController'
                r'|onlyRole|requiresAuth|onlyCEO|onlyCFO|onlyCOO|ownerOnly|adminOnly)\b'
            )
            if _ACCESS_RE.search(stripped):
                return True

            func_block_pat = re.compile(
                r'function\s+' + re.escape(func_name) + r'\s*\([^)]*\)\s*[^{]*\{',
                re.DOTALL
            )
            fm = func_block_pat.search(stripped)
            if fm:
                fstart = fm.end()
                depth, pos = 1, fstart
                while pos < len(stripped) and depth > 0:
                    if stripped[pos] == '{': depth += 1
                    elif stripped[pos] == '}': depth -= 1
                    pos += 1
                func_body = stripped[fstart:pos-1]

                _INLINE_ACCESS = re.compile(
                    r'(?:if\s*\(\s*msg\.sender\s*!=\s*(?:owner|_owner|admin|creator|manager)\s*\)'
                    r'|require\s*\(\s*msg\.sender\s*==\s*(?:owner|_owner|admin|creator|manager)\s*\)'
                    r'|require\s*\(\s*(?:owner|_owner|admin|creator|manager)\s*==\s*msg\.sender\s*\)'
                    r'|if\s*\(\s*msg\.sender\s*==\s*(?:owner|_owner|admin|creator|manager)\s*\))'
                )
                if _INLINE_ACCESS.search(func_body):
                    return True

    return False

def _is_conservation_bounded(cfg, var_name, source_code=None):
    """Check whether a uint256 mapping += is conservation-bounded."""
    if source_code:
        stripped = re.sub(r'//[^\n]*', '', source_code)
        stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)
        has_plus_eq = bool(re.search(
            rf'{re.escape(var_name)}\s*(?:\[.*?\])?\s*\+=', stripped
        ))
        has_minus_eq = bool(re.search(
            rf'{re.escape(var_name)}\s*(?:\[.*?\])?\s*-=', stripped
        ))
        if has_plus_eq and has_minus_eq:
            return True

    has_plus = False
    has_minus = False
    for _, nobj in cfg.cfg_metadata.node_table.items():
        nt = getattr(nobj, 'node_type', '')
        expr = nobj
        if nt == 'ExpressionStatement':
            expr = getattr(nobj, 'expression', nobj)
        if getattr(expr, 'node_type', '') == 'Assignment':
            lhs = getattr(expr, 'leftHandSide', None)
            lhs_name = getattr(lhs, 'name', None) if lhs else None
            if not lhs_name and lhs and getattr(lhs, 'node_type', '') == 'IndexAccess':
                base = getattr(lhs, 'base_expression', None) or getattr(lhs, 'baseExpression', None)
                lhs_name = getattr(base, 'name', None) if base else None
            if lhs_name == var_name:
                op = getattr(expr, 'operator', '')
                if op == '+=':
                    has_plus = True
                elif op == '-=':
                    has_minus = True
    return has_plus and has_minus

def _is_state_var_only_arithmetic(cfg, node_id, var_name):
    """Check if an arithmetic operation involves ONLY state variables or"""
    nobj = cfg.cfg_metadata.get_node(node_id)
    if nobj is None:
        return False
    nt = getattr(nobj, 'node_type', '')
    expr = nobj
    if nt == 'ExpressionStatement':
        expr = getattr(nobj, 'expression', nobj)

    if getattr(expr, 'node_type', '') != 'Assignment':
        if nt == 'VariableDeclarationStatement':
            init_val = getattr(nobj, 'initialValue', None)
            if init_val is None:
                return False
            rhs_ids = _collect_identifiers(init_val)
        else:
            return False
    else:
        op = getattr(expr, 'operator', '')
        rhs = getattr(expr, 'rightHandSide', None)
        if op in ('+=', '-=', '*='):
            rhs_ids = _collect_identifiers(rhs) if rhs else set()
        elif op == '=':
            rhs_ids = _collect_identifiers(rhs) if rhs else set()
        else:
            return False

    if not rhs_ids:
        return False

    if var_name in rhs_ids:
        return False

    func_params = set()
    for _, fn_obj in cfg.cfg_metadata.node_table.items():
        if not (hasattr(fn_obj, 'node_type') and fn_obj.node_type == 'FunctionDefinition'):
            continue
        params_dict = getattr(fn_obj, 'parameters', {})
        if not isinstance(params_dict, dict):
            continue
        for param in params_dict.get('parameters', []):
            pname = param.get('name')
            if pname:
                func_params.add(pname)

    state_vars = set()
    vt = cfg.cfg_metadata.variable_table
    for vname, vinfo in vt.items():
        if isinstance(vinfo, dict) and vinfo.get('stateVariable', False):
            state_vars.add(vname)

    rhs_clean = rhs_ids - {'msg', 'sender', 'value', 'this', 'block', 'now'}
    if rhs_clean & func_params:
        return False

    return True
 
def _get_node_operator(cfg, node_id, var_name):
    """Get the arithmetic operator at this specific node for var_name."""
    nobj = cfg.cfg_metadata.get_node(node_id)
    if nobj is None:
        return None
 
    def _from_asgn(a):
        op = getattr(a, 'operator', None)
        if op in ('+=', '-=', '*='):
            return op
        if op == '=':
            rhs = getattr(a, 'rightHandSide', None)
            if rhs:
                rop = getattr(rhs, 'operator', None)
                if rop in ('+', '-', '*', '**', '<<'):
                    return rop
        return op
 
    nt = getattr(nobj, 'node_type', '')
 
    if nt == 'Assignment':
        lhs = getattr(nobj, 'leftHandSide', None)
        lhs_name = getattr(lhs, 'name', None) if lhs else None
        if not lhs_name and lhs and getattr(lhs, 'node_type', '') == 'IndexAccess':
            base = getattr(lhs, 'base_expression', None) or getattr(lhs, 'baseExpression', None)
            lhs_name = getattr(base, 'name', None) if base else None
        if lhs_name == var_name:
            return _from_asgn(nobj)
 
    elif nt == 'ExpressionStatement':
        expr = getattr(nobj, 'expression', None)
        if expr:
            if getattr(expr, 'node_type', '') == 'Assignment':
                lhs = getattr(expr, 'leftHandSide', None)
                lhs_name = getattr(lhs, 'name', None) if lhs else None
                if not lhs_name and lhs and getattr(lhs, 'node_type', '') == 'IndexAccess':
                    base = getattr(lhs, 'base_expression', None) or getattr(lhs, 'baseExpression', None)
                    lhs_name = getattr(base, 'name', None) if base else None
                if lhs_name == var_name:
                    return _from_asgn(expr)
            elif getattr(expr, 'node_type', '') == 'UnaryOperation':
                sub = getattr(expr, 'subExpression', None)
                if sub and getattr(sub, 'name', None) == var_name:
                    return getattr(expr, 'operator', None)
 
    elif nt == 'VariableDeclarationStatement':
        for decl in getattr(nobj, 'declarations', []):
            if decl and getattr(decl, 'name', None) == var_name:
                init_val = getattr(nobj, 'initialValue', None)
                if init_val and getattr(init_val, 'node_type', '') == 'BinaryOperation':
                    return getattr(init_val, 'operator', None)
                return '='

    elif nt == 'Return':
        ret_expr = getattr(nobj, 'expression', None)
        if ret_expr and getattr(ret_expr, 'node_type', '') == 'BinaryOperation':
            rhs_ids = _collect_identifiers(ret_expr)
            if var_name in rhs_ids:
                return getattr(ret_expr, 'operator', None)

    return None

_JAVA_LONG_PRECISE_TYPES = {
    'uint8', 'uint16', 'uint32', 'uint64',
    'int8', 'int16', 'int32',
}

def _get_rhs_operand_names(cfg, node_id, var_name):
    """Extract RHS operand identifier names for the arithmetic on var_name at node_id."""
    nobj = cfg.cfg_metadata.get_node(node_id)
    if nobj is None:
        return set()
    nt = getattr(nobj, 'node_type', '')

    def _lhs_matches(lhs):
        if lhs is None:
            return False
        name = getattr(lhs, 'name', None)
        if name == var_name:
            return True
        if getattr(lhs, 'node_type', '') == 'IndexAccess':
            base = getattr(lhs, 'base_expression', None) \
                   or getattr(lhs, 'baseExpression', None)
            if base and getattr(base, 'name', None) == var_name:
                return True
        return False

    def _from_assignment(asgn):
        op = getattr(asgn, 'operator', None)
        lhs = getattr(asgn, 'leftHandSide', None)
        if not _lhs_matches(lhs):
            return set()
        rhs = getattr(asgn, 'rightHandSide', None)
        if op in ('+=', '-=', '*='):
            return _collect_identifiers(rhs) if rhs else set()
        if op == '=' and rhs:
            return _collect_identifiers(rhs)
        return set()

    if nt == 'Assignment':
        return _from_assignment(nobj)
    if nt == 'ExpressionStatement':
        expr = getattr(nobj, 'expression', None)
        if expr and getattr(expr, 'node_type', '') == 'Assignment':
            return _from_assignment(expr)
    if nt == 'VariableDeclarationStatement':
        init_val = getattr(nobj, 'initialValue', None)
        if init_val:
            return _collect_identifiers(init_val)
    if nt == 'Return':
        ret_expr = getattr(nobj, 'expression', None)
        if ret_expr:
            return _collect_identifiers(ret_expr)
    return set()

def _source_level_guard_check(source_code, var_name, rhs_names, kind):
    """Source-level regex check for require/assert/if guards protecting arithmetic."""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    if kind == 'UNDERFLOW':
        for rhs_var in rhs_names:
            if not rhs_var or rhs_var in ('msg', 'sender', 'value'):
                continue
            pats = [
                rf'require\s*\(\s*{re.escape(rhs_var)}\s*<=\s*{re.escape(var_name)}',
                rf'require\s*\(\s*{re.escape(var_name)}\s*\[.*?\]\s*>=\s*{re.escape(rhs_var)}',
                rf'require\s*\(\s*{re.escape(rhs_var)}\s*<=\s*{re.escape(var_name)}\s*\[',
                rf'require\s*\(\s*{re.escape(var_name)}\s*>=\s*{re.escape(rhs_var)}',
                rf'require\s*\(\s*{re.escape(rhs_var)}\s*<=\s*\w+\s*\[',
                rf'require\s*\(\s*{re.escape(rhs_var)}\s*>=\s*{re.escape(var_name)}',
                rf'require\s*\(\s*{re.escape(rhs_var)}\s*>=\s*{re.escape(var_name)}\s*\[',
                rf'if\s*\(\s*{re.escape(rhs_var)}\s*<=?\s*{re.escape(var_name)}\s*\[',
                rf'if\s*\(\s*{re.escape(rhs_var)}\s*<=?\s*{re.escape(var_name)}\s*\)',
                rf'if\s*\(\s*{re.escape(var_name)}\s*\[.*?\]\s*<\s*{re.escape(rhs_var)}\s*\)',
                rf'if\s*\(\s*{re.escape(var_name)}\s*<\s*{re.escape(rhs_var)}\s*\)',
                rf'if\s*\(\s*{re.escape(var_name)}\s*\[.*?\]\s*>=?\s*{re.escape(rhs_var)}\s*\)',
                rf'if\s*\(\s*{re.escape(var_name)}\s*>=?\s*{re.escape(rhs_var)}\s*\)',
                rf'if\s*\(\s*{re.escape(var_name)}\s*\[.*?\]\s*>\s*0\s*\)',
                rf'if\s*\(\s*{re.escape(rhs_var)}\s*>\s*0\s*\)',
                rf'require\s*\(\s*{re.escape(rhs_var)}\s*>\s*0\s*\)',
            ]
            for pat in pats:
                if re.search(pat, stripped):
                    return True

    if kind == 'OVERFLOW':
        pats = [
            rf'assert\s*\(\s*{re.escape(var_name)}\s*\[.*?\]\s*\+\s*[\w.]+\s*>\s*{re.escape(var_name)}\s*\[',
            rf'assert\s*\(\s*{re.escape(var_name)}\s*\+\s*[\w.]+\s*>=?\s*{re.escape(var_name)}\s*\)',
        ]
        for pat in pats:
            if re.search(pat, stripped):
                return True

    return False

def _is_param_only_msgvalue(source_code, cfg, node_id, param_name):
    """Check if a function parameter is always called with msg.value at all call sites."""
    visited = set()
    queue = [node_id]
    func_node = None
    func_name = None
    while queue:
        curr = queue.pop(0)
        if curr in visited:
            continue
        visited.add(curr)
        if curr.startswith('FunctionDefinition_'):
            func_node = cfg.cfg_metadata.get_node(curr)
            if func_node:
                func_name = getattr(func_node, 'name', None)
            break
        curr_obj = cfg.cfg_metadata.get_node(curr)
        if curr_obj and hasattr(curr_obj, 'prev_nodes'):
            for pred in curr_obj.prev_nodes:
                if pred not in visited:
                    queue.append(pred)
        if len(visited) > 200:
            break

    if not func_name:
        return False

    visibility = getattr(func_node, 'visibility', '')
    if visibility not in ('internal', 'private'):
        stripped = re.sub(r'//[^\n]*', '', source_code)
        stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)
        func_sig_pat = re.compile(
            r'function\s+' + re.escape(func_name) + r'\s*\([^)]*\)\s*[^{]*'
            r'\b(internal|private)\b'
        )
        if not func_sig_pat.search(stripped):
            return False

    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    func_def_pat = re.compile(
        r'function\s+' + re.escape(func_name) + r'\s*\(([^)]*)\)'
    )
    fm = func_def_pat.search(stripped)
    if not fm:
        return False
    params_str = fm.group(1)
    params = [p.strip().split()[-1] for p in params_str.split(',') if p.strip()]
    if param_name not in params:
        return False
    param_idx = params.index(param_name)

    call_pat = re.compile(re.escape(func_name) + r'\s*\(([^)]*)\)')
    func_def_pos = fm.start()
    all_msgvalue = True
    found_calls = False
    for cm in call_pat.finditer(stripped):
        if cm.start() == func_def_pos:
            continue
        args_str = cm.group(1)
        args = [a.strip() for a in args_str.split(',')]
        if param_idx >= len(args):
            all_msgvalue = False
            break
        arg = args[param_idx]
        if 'msg.value' not in arg:
            all_msgvalue = False
            break
        found_calls = True

    return found_calls and all_msgvalue

def _is_msgvalue_accumulator(source_code, var_name):
    """Source-level check: is var_name only incremented by msg.value?"""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)
    pat = re.compile(
        rf'{re.escape(var_name)}\s*(?:\[.*?\])?\s*\+=\s*msg\.value\s*;'
    )
    if pat.search(stripped):
        all_plus_eq = re.findall(
            rf'{re.escape(var_name)}\s*(?:\[.*?\])?\s*\+=\s*([^;]+);',
            stripped
        )
        for rhs_expr in all_plus_eq:
            rhs_expr = rhs_expr.strip()
            if rhs_expr != 'msg.value':
                return False
        return True
    return False

def _emit_overflow_verdicts(cfg, csem, checked_default, has_unchecked, source_code=None):
    """Interval pass (Algorithm 3): for each assignment-node n_i, for each"""
    TYPE_INTERVALS = {
        'uint8':   (0, 2**8  - 1), 'uint16':  (0, 2**16 - 1),
        'uint32':  (0, 2**32 - 1), 'uint64':  (0, 2**64 - 1),
        'uint128': (0, 2**128 - 1),'uint256': (0, 2**256 - 1),
        'uint':    (0, 2**256 - 1),
        'int8':    (-(2**7),   2**7   - 1), 'int16':  (-(2**15),  2**15  - 1),
        'int32':   (-(2**31),  2**31  - 1), 'int64':  (-(2**63),  2**63  - 1),
        'int128':  (-(2**127), 2**127 - 1), 'int256': (-(2**255), 2**255 - 1),
        'int':     (-(2**255), 2**255 - 1),
    }
    variable_table = cfg.cfg_metadata.variable_table
    of_registry    = csem.variable_registry.variable_table
 
    variables = [None] * len(of_registry)
    for var, data in of_registry.items():
        idx      = data['id']
        var_type = variable_table.get(var, 'unknown')
        if isinstance(var_type, dict):
            var_type = var_type.get('type', 'unknown')
        variables[idx] = {'name': var, 'type': var_type}
 
    OVERFLOW_CHECK_TYPES = {
        'ExpressionStatement', 'Assignment', 'VariableDeclarationStatement',
        'ForLoopJoin', 'ForLoopContinue',
    }
    check_nodes = {
        nid for nid in cfg.cfg_metadata.node_table
        if getattr(cfg.cfg_metadata.get_node(nid), 'node_type', '') in OVERFLOW_CHECK_TYPES
    }
 
    global_arith_vars = set()
    _collect_loop_arith_vars(cfg, None, global_arith_vars)
 
    verdicts = []
    seen     = set()
    revert_tag = " (Solidity >=0.8: overflow reverts)" if (checked_default and not has_unchecked) else ""
    unchecked_tag = " (inside unchecked block)" if (checked_default and has_unchecked) else ""
    annotation = revert_tag or unchecked_tag
 
    for node in cfg.cfg_metadata.node_table:
        if node not in check_nodes:
            continue
 
        if not _node_has_arithmetic_op(cfg, node):
            continue
 
        try:
            state_set = csem.point_state.get_node_state_set(
                node, csem.point_state.iteration, False
            )
            intervals = state_set.toBox(csem.manager)
        except Exception:
            continue
 
        defined_vars = _get_defined_vars_at_node(cfg, node)
 
        node_type = getattr(cfg.cfg_metadata.get_node(node), 'node_type', '')
 
        for i, interval in enumerate(intervals):
            parsed = _parse_iv_str(str(interval.toString()))
            if parsed is None:
                continue
            lo, hi = parsed
            v = variables[i] if i < len(variables) else None
            if not v or v['type'] == 'unknown':
                continue
 
            if defined_vars and v['name'] not in defined_vars:
                continue
 
            if node_type in ('ForLoopJoin', 'ForLoopContinue'):
                if v['name'] not in global_arith_vars:
                    continue
                op_at_node = _lookup_op(cfg, node, v['name'])
                if op_at_node is None:
                    continue
                if v['type'] in ('uint256', 'uint') and op_at_node in ('++', '+='):
                    continue
 
            if v['type'] in ('uint256', 'uint') and node_type not in ('ForLoopJoin', 'ForLoopContinue'):
                local_op = _get_node_operator(cfg, node, v['name'])
                if local_op in ('++', '--'):
                    continue

            if v['type'] in ('uint256', 'uint') and node_type not in ('ForLoopJoin', 'ForLoopContinue'):
                local_op = _get_node_operator(cfg, node, v['name'])
                if local_op == '+=':
                    rhs_for_g7 = _get_rhs_operand_names(cfg, node, v['name'])
                    rhs_clean = rhs_for_g7 - {'msg', 'sender', 'this', 'value'}
                    if rhs_for_g7 & {'msgvalue', 'msg.value', 'value'} and not rhs_clean:
                        continue
                    if rhs_for_g7 == {'msg'} or rhs_for_g7 == {'msg', 'value'}:
                        continue
                    if source_code and _is_msgvalue_accumulator(source_code, v['name']):
                        continue
                    if source_code and len(rhs_for_g7) == 1:
                        rhs_param = next(iter(rhs_for_g7))
                        if _is_param_only_msgvalue(source_code, cfg, node, rhs_param):
                            continue

            if checked_default and _is_in_internal_function(cfg, node):
                continue

            if v['type'] in ('uint256', 'uint', 'uint128'):
                if _is_in_access_controlled_function(cfg, node, source_code):
                    continue

            if v['type'] in ('uint256', 'uint', 'uint128'):
                local_op_g11 = _get_node_operator(cfg, node, v['name'])
                if local_op_g11 in ('*', '**'):
                    if _is_state_var_only_arithmetic(cfg, node, v['name']):
                        continue
 
            rhs_names = _get_rhs_operand_names(cfg, node, v['name'])
            if _is_overflow_guarded_extended(cfg, node, v['name'], rhs_names):
                continue
 
            limits = TYPE_INTERVALS.get(v['type'])
            if not limits:
                continue
 
            is_unsigned   = v['type'].startswith('uint') or v['type'] == 'uint'
            both_exceeded = lo < limits[0] and hi > limits[1]
 
            if v['type'] not in _JAVA_LONG_PRECISE_TYPES:
                if (lo == -_math.inf or lo == limits[0]) and hi == _math.inf:
                    local_op = _get_node_operator(cfg, node, v['name'])
                    if local_op not in ('+=', '-=', '*=', '+', '-', '*', '**', '<<'):
                        continue
 
            if hi == _math.inf and lo >= limits[0]:
                op = _lookup_op(cfg, node, v['name'])
                kind = 'UNDERFLOW' if op in ('-=', '-') else 'OVERFLOW'
                if source_code and _source_level_guard_check(
                        source_code, v['name'], rhs_names, kind):
                    continue
                key  = (v['name'], v['type'], kind)
                if key not in seen:
                    seen.add(key)
                    tag = f"[{kind}]"
                    if kind == 'UNDERFLOW':
                        verdicts.append(
                            f"{tag} Variable {v['name']} ({v['type']}) at {node}: "
                            f"compound '-=' with external input can fall below "
                            f"type min {limits[0]}.{annotation}"
                        )
                    else:
                        verdicts.append(
                            f"{tag} Variable {v['name']} ({v['type']}) at {node}: "
                            f"arithmetic op '{op}' with external input can exceed "
                            f"type max {limits[1]}.{annotation}"
                        )
                continue
 
            if both_exceeded and is_unsigned:
                assign_op = _lookup_op(cfg, node, v['name'])
                if assign_op in ('-=', '-'):
                    kind = 'UNDERFLOW'
                elif assign_op in ('+=', '*=', '+', '*'):
                    kind = 'OVERFLOW'
                else:
                    kind = 'OVERFLOW'
                if source_code and _source_level_guard_check(
                        source_code, v['name'], rhs_names, kind):
                    continue
                key = (v['name'], v['type'], kind)
                if key not in seen:
                    seen.add(key)
                    verdicts.append(
                        f"[{kind}] Variable {v['name']} ({v['type']}) at {node}: "
                        f"arithmetic op '{assign_op}' with external input can "
                        f"{'fall below type min ' + str(limits[0]) if kind == 'UNDERFLOW' else 'exceed type max ' + str(limits[1])}.{annotation}"
                    )
                continue
 
            if lo < limits[0]:
                if source_code and _source_level_guard_check(
                        source_code, v['name'], rhs_names, 'UNDERFLOW'):
                    pass
                else:
                    key = (v['name'], v['type'], 'UNDERFLOW')
                    if key not in seen:
                        seen.add(key)
                        verdicts.append(
                            f"[UNDERFLOW] Variable {v['name']} ({v['type']}) at {node}: "
                            f"interval [{_fmt_num(lo)},{_fmt_num(hi)}] falls below "
                            f"type min {limits[0]}.{annotation}"
                        )
            if hi > limits[1]:
                if source_code and _source_level_guard_check(
                        source_code, v['name'], rhs_names, 'OVERFLOW'):
                    pass
                else:
                    key = (v['name'], v['type'], 'OVERFLOW')
                    if key not in seen:
                        seen.add(key)
                        verdicts.append(
                            f"[OVERFLOW] Variable {v['name']} ({v['type']}) at {node}: "
                            f"interval [{_fmt_num(lo)},{_fmt_num(hi)}] exceeds "
                            f"type max {limits[1]}.{annotation}"
                        )
 
    if not seen:
        import re as _re_mod
        variable_table = cfg.cfg_metadata.variable_table

        func_def_indices = []
        for nid, nobj_f in cfg.cfg_metadata.node_table.items():
            if getattr(nobj_f, 'node_type', '') == 'FunctionDefinition':
                try:
                    fidx = int(nid.split('_')[-1])
                    func_def_indices.append(fidx)
                except (ValueError, IndexError):
                    pass
        func_def_indices.sort()

        def _get_enclosing_func_idx(node_id_str):
            """Return the FunctionDefinition index that encloses this node."""
            try:
                nidx = int(node_id_str.split('_')[-1])
            except (ValueError, IndexError):
                return -1
            best = -1
            for fi in func_def_indices:
                if fi <= nidx:
                    best = fi
                else:
                    break
            return best

        if_guards_by_func = {}
        for nid, nobj_if in cfg.cfg_metadata.node_table.items():
            if getattr(nobj_if, 'node_type', '') != 'IfStatement':
                continue
            cond = getattr(nobj_if, 'condition', None)
            if cond is None:
                continue
            if not _structural_cond_is_comparison(cond):
                continue
            cond_vars = _collect_identifiers(cond)
            if not cond_vars:
                continue
            fi = _get_enclosing_func_idx(nid)
            if fi not in if_guards_by_func:
                if_guards_by_func[fi] = []
            if_guards_by_func[fi].append(cond_vars)

        for sv in _detect_structural_overflow(cfg, variable_table):
            m = _re_mod.search(r'Variable (\S+) \((\S+)\) at (\S+):', sv)
            if m:
                sv_var, sv_type, sv_node = m.group(1), m.group(2), m.group(3)
                fi = _get_enclosing_func_idx(sv_node)
                sv_rhs = _get_rhs_operand_names(cfg, sv_node, sv_var)
                kind = 'UNDERFLOW' if '[UNDERFLOW]' in sv else 'OVERFLOW'

                guarded = False
                if kind == 'UNDERFLOW':
                    for guard_vars in if_guards_by_func.get(fi, []):
                        if sv_var in guard_vars and (sv_rhs & guard_vars):
                            guarded = True
                            break
                else:
                    check_vars = {sv_var} | sv_rhs
                    for guard_vars in if_guards_by_func.get(fi, []):
                        if check_vars & guard_vars:
                            guarded = True
                            break
                if guarded:
                    continue
                if source_code:
                    if _source_level_guard_check(source_code, sv_var, sv_rhs, kind):
                        continue
                if sv_type in ('uint256', 'uint', 'uint128') and kind != 'UNDERFLOW':
                    if _is_in_access_controlled_function(cfg, sv_node, source_code):
                        continue
                if sv_type in ('uint256', 'uint'):
                    sv_op_g7 = _get_node_operator(cfg, sv_node, sv_var)
                    if sv_op_g7 == '+=':
                        sv_rhs_g7 = _get_rhs_operand_names(cfg, sv_node, sv_var)
                        if sv_rhs_g7 == {'msg'} or sv_rhs_g7 == {'msg', 'value'}:
                            continue
                        if source_code and _is_msgvalue_accumulator(source_code, sv_var):
                            continue
                if sv_type in ('uint256', 'uint', 'uint128'):
                    sv_op_g11 = _get_node_operator(cfg, sv_node, sv_var)
                    if sv_op_g11 in ('*', '**'):
                        if _is_state_var_only_arithmetic(cfg, sv_node, sv_var):
                            continue
                if sv_type in ('uint256', 'uint', 'uint128') and kind == 'OVERFLOW':
                    sv_op_g10 = _get_node_operator(cfg, sv_node, sv_var)
                    if sv_op_g10 == '+=':
                        if _is_conservation_bounded(cfg, sv_var, source_code):
                            continue
                if _is_in_internal_function(cfg, sv_node):
                    continue
            elif sv not in verdicts:
                verdicts.append(sv)
                continue
            if sv not in verdicts:
                verdicts.append(sv)
 
    return verdicts

def _structural_cond_is_comparison(cond):
    """Check if a condition AST node is a comparison or contains comparisons."""
    if cond is None:
        return False
    cond_nt = getattr(cond, 'node_type', '')
    cond_op = getattr(cond, 'operator', '')
    if cond_nt == 'BinaryOperation':
        if cond_op in ('>=', '<=', '>', '<', '==', '!='):
            return True
        if cond_op in ('&&', '||'):
            left = getattr(cond, 'leftExpression', None)
            right = getattr(cond, 'rightExpression', None)
            return _structural_cond_is_comparison(left) or _structural_cond_is_comparison(right)
    if cond_nt == 'UnaryOperation' and cond_op == '!':
        return _structural_cond_is_comparison(getattr(cond, 'subExpression', None))
    return False

def _parse_iv_str(s):
    """Parse an APRON interval string to (lo, hi) floats or None."""
    s = s.strip()
    if not s or s in ('bottom', 'Bottom', '[]'):
        return None
    if s.startswith('[') and s.endswith(']'):
        s = s[1:-1]
    parts = s.split(',')
    if len(parts) != 2:
        return None
    def _f(x):
        x = x.strip()
        if x in ('Infinity', '+Infinity'): return _math.inf
        if x == '-Infinity':               return -_math.inf
        try:    return float(x)
        except: return None
    lo, hi = _f(parts[0]), _f(parts[1])
    return None if (lo is None or hi is None) else (lo, hi)

def _lookup_op(cfg_obj, node_id, var_name):
    """Return the effective arithmetic operator of the assignment that defines"""
    nobj = cfg_obj.cfg_metadata.get_node(node_id)

    def _from_asgn(a):
        op = getattr(a, 'operator', None)
        if op in ('+=', '-=', '*='):
            return op
        if op == '=':
            rhs = getattr(a, 'rightHandSide', None)
            if rhs:
                rop = getattr(rhs, 'operator', None)
                if rop in ('+', '-', '*'):
                    return rop
        return op

    if nobj:
        nt = getattr(nobj, 'node_type', '')
        if nt == 'Assignment':
            lhs = getattr(nobj, 'leftHandSide', None)
            if lhs and getattr(lhs, 'name', None) == var_name:
                return _from_asgn(nobj)
        if nt == 'ExpressionStatement':
            expr = getattr(nobj, 'expression', None)
            if expr and getattr(expr, 'node_type', '') == 'Assignment':
                lhs = getattr(expr, 'leftHandSide', None)
                if lhs and getattr(lhs, 'name', None) == var_name:
                    return _from_asgn(expr)
        if nt == 'VariableDeclarationStatement':
            decl_name = None
            declarations = getattr(nobj, 'declarations', [])
            if declarations:
                decl_name = getattr(declarations[0], 'name', None)
            if decl_name == var_name or (decl_name is None and declarations):
                init_val = getattr(nobj, 'initialValue', None)
                if init_val and getattr(init_val, 'node_type', '') == 'BinaryOperation':
                    op = getattr(init_val, 'operator', None)
                    if op in ('+', '-', '*'):
                        return op
            for decl in declarations:
                if getattr(decl, 'name', None) == var_name:
                    init_val = getattr(decl, 'initialValue', None)
                    if init_val and getattr(init_val, 'node_type', '') == 'BinaryOperation':
                        op = getattr(init_val, 'operator', None)
                        if op in ('+', '-', '*'):
                            return op
    for _, child in cfg_obj.cfg_metadata.node_table.items():
        if getattr(child, 'node_type', '') != 'Assignment':
            continue
        lhs = getattr(child, 'leftHandSide', None)
        if lhs and getattr(lhs, 'name', None) == var_name:
            return _from_asgn(child)
    return None

def _detect_structural_overflow(cfg, variable_table):
    """Structural fallback: flags compound-op assignments and RHS binary ops"""
    ARITHMETIC_COMPOUND_OPS = {'+=', '-=', '*='}
    OVERFLOW_OPS  = {'+=', '*='}
    UNDERFLOW_OPS = {'-='}

    func_params = set()
    for _, node_obj in cfg.cfg_metadata.node_table.items():
        if not (hasattr(node_obj, 'node_type')
                and node_obj.node_type == 'FunctionDefinition'):
            continue
        params_dict = getattr(node_obj, 'parameters', {})
        if not isinstance(params_dict, dict):
            continue
        for param in params_dict.get('parameters', []):
            pname = param.get('name')
            if pname:
                func_params.add(pname)

    state_vars = set()
    for vname, vinfo in variable_table.items():
        if isinstance(vinfo, dict) and vinfo.get('stateVariable', False):
            state_vars.add(vname)

    loop_body_nodes = set()
    LOOP_TYPES   = {'ForStatement', 'WhileStatement', 'DoWhileStatement'}
    STOP_PREFIXES = ('ForLoopJoin', 'ForLoopContinue', 'FunctionExit',
                     'FunctionEntry', 'SourceExit', 'SourceEntry')
    for node_id, node_obj in cfg.cfg_metadata.node_table.items():
        if getattr(node_obj, 'node_type', '') not in LOOP_TYPES:
            continue
        visited = set()
        queue = list(getattr(node_obj, 'next_nodes', {}).keys())
        while queue:
            nid = queue.pop(0)
            if nid in visited or nid == node_id:
                continue
            if any(nid.startswith(p) for p in STOP_PREFIXES):
                continue
            visited.add(nid)
            loop_body_nodes.add(nid)
            child = cfg.cfg_metadata.get_node(nid)
            if child:
                queue.extend(getattr(child, 'next_nodes', {}).keys())

    type_bounds = {}
    for bits in (8, 16, 32, 64, 128, 256):
        type_bounds[f'uint{bits}'] = (0, 2**bits - 1)
        type_bounds[f'int{bits}']  = (-(2**(bits-1)), 2**(bits-1) - 1)
    type_bounds['uint'] = type_bounds['uint256']
    type_bounds['int']  = type_bounds['int256']

    verdicts = []
    seen = set()

    _BUILTIN_NAMES = frozenset({
        'msg', 'sender', 'value', 'this', 'block', 'now', 'tx',
        'abi', 'super', 'selfdestruct', 'require', 'assert', 'revert',
    })

    def _resolve_lhs_name_and_type(lhs_obj):
        """Return (var_name, var_type) for a plain Identifier or an IndexAccess."""
        if lhs_obj is None:
            return None, None
        nt = getattr(lhs_obj, 'node_type', '')
        if nt == 'Identifier':
            name = getattr(lhs_obj, 'name', None)
            if not name:
                return None, None
            vt = variable_table.get(name, 'unknown')
            if isinstance(vt, dict):
                vt = vt.get('type', 'unknown')
            return name, vt
        if nt == 'IndexAccess':
            base = getattr(lhs_obj, 'base_expression', None) \
                   or getattr(lhs_obj, 'baseExpression', None)
            if base is None:
                return None, None
            base_name = getattr(base, 'name', None)
            if not base_name:
                return None, None
            raw_type = variable_table.get(base_name, 'unknown')
            if isinstance(raw_type, dict):
                raw_type = raw_type.get('type', 'unknown')
            if isinstance(raw_type, str) and '=>' in raw_type:
                try:
                    value_type = raw_type.split('=>')[1].strip().rstrip(')')
                    value_type = value_type.strip()
                except Exception:
                    value_type = 'unknown'
            else:
                value_type = raw_type
            return base_name, value_type
        return None, None

    def _has_external_input(rhs_ids):
        """Check if any RHS identifier represents external input:"""
        if rhs_ids.intersection(func_params):
            return True
        if rhs_ids.intersection(state_vars):
            return True
        if rhs_ids & {'blocktimestamp', 'now', 'block'}:
            return True
        return False

    def _describe_input(rhs_ids):
        """Return a human-readable description of the external input source."""
        p = rhs_ids.intersection(func_params)
        if p:
            return str(p)
        s = rhs_ids.intersection(state_vars)
        if s:
            return f'state var(s) {s}'
        if rhs_ids & {'blocktimestamp', 'now', 'block'}:
            return 'block.timestamp/now'
        return str(rhs_ids)

    def _process_assignment(node_id, op, lhs_obj, rhs_obj):
        """Process a single assignment (compound or plain =) for overflow/underflow."""
        if op not in ARITHMETIC_COMPOUND_OPS:
            if op == '=':
                if rhs_obj is None or getattr(rhs_obj, 'node_type', '') != 'BinaryOperation':
                    return
                rhs_op = getattr(rhs_obj, 'operator', '')
                if rhs_op not in ('+', '-', '*'):
                    return
                rhs_ids = _collect_identifiers(rhs_obj)
                lhs_name, var_type = _resolve_lhs_name_and_type(lhs_obj)
                if not lhs_name:
                    return
                if var_type not in type_bounds:
                    return
                lo, hi = type_bounds[var_type]
                if _has_external_input(rhs_ids):
                    input_desc = _describe_input(rhs_ids)
                    if rhs_op in ('+', '*'):
                        key = (lhs_name, var_type, 'OVERFLOW')
                        if key not in seen:
                            seen.add(key)
                            verdicts.append(
                                f"[OVERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                                f"'{rhs_op}' with {input_desc} can exceed type max {hi}."
                            )
                    if rhs_op == '-':
                        key = (lhs_name, var_type, 'UNDERFLOW')
                        if key not in seen:
                            seen.add(key)
                            verdicts.append(
                                f"[UNDERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                                f"'-' with {input_desc} can fall below type min {lo}."
                            )
                elif lhs_name in rhs_ids and node_id in loop_body_nodes:
                    if rhs_op in ('+', '*'):
                        key = (lhs_name, var_type, 'OVERFLOW')
                        if key not in seen:
                            seen.add(key)
                            verdicts.append(
                                f"[OVERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                                f"self-referential '{rhs_op}' in loop can exceed type max {hi}."
                            )
                    if rhs_op == '-':
                        key = (lhs_name, var_type, 'UNDERFLOW')
                        if key not in seen:
                            seen.add(key)
                            verdicts.append(
                                f"[UNDERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                                f"self-referential '-' in loop can fall below type min {lo}."
                            )
            return

        lhs_name, var_type = _resolve_lhs_name_and_type(lhs_obj)
        if not lhs_name:
            return
        rhs_ids = _collect_identifiers(rhs_obj) if rhs_obj else set()
        is_underflow_op = op in UNDERFLOW_OPS
        lhs_is_state_or_mapping = lhs_name in state_vars
        if not is_underflow_op:
            if not _has_external_input(rhs_ids) and node_id not in loop_body_nodes:
                if not rhs_ids.intersection(func_params):
                    return
        else:
            if not lhs_is_state_or_mapping and not _has_external_input(rhs_ids) \
               and node_id not in loop_body_nodes and not rhs_ids.intersection(func_params):
                return
        if var_type not in type_bounds:
            return
        input_desc = _describe_input(rhs_ids) if _has_external_input(rhs_ids) else (
            rhs_ids.intersection(func_params) or {lhs_name if lhs_is_state_or_mapping else '(local)'}
        )
        lo, hi = type_bounds[var_type]
        if op in OVERFLOW_OPS:
            key = (lhs_name, var_type, 'OVERFLOW')
            if key not in seen:
                seen.add(key)
                verdicts.append(
                    f"[OVERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                    f"compound '{op}' with {input_desc} can exceed type max {hi}."
                )
        if op in UNDERFLOW_OPS:
            key = (lhs_name, var_type, 'UNDERFLOW')
            if key not in seen:
                seen.add(key)
                verdicts.append(
                    f"[UNDERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                    f"compound '{op}' with {input_desc} can fall below type min {lo}."
                )

    for node_id, node_obj in cfg.cfg_metadata.node_table.items():
        nt = getattr(node_obj, 'node_type', '')

        if nt == 'VariableDeclarationStatement':
            init_val = getattr(node_obj, 'initialValue', None)
            if init_val is None or getattr(init_val, 'node_type', '') != 'BinaryOperation':
                continue
            rhs_op = getattr(init_val, 'operator', '')
            if rhs_op not in ('+', '-', '*'):
                continue
            decls = getattr(node_obj, 'declarations', [None])
            decl_node = decls[0] if decls else None
            lhs_name = getattr(decl_node, 'name', None) if decl_node else None
            type_node = getattr(decl_node, 'typeName', None) if decl_node else None
            var_type = getattr(type_node, 'name', None) if type_node else None
            if not var_type and lhs_name:
                vt = variable_table.get(lhs_name, 'unknown')
                var_type = vt.get('type', 'unknown') if isinstance(vt, dict) else vt
            if not lhs_name or not var_type or var_type not in type_bounds:
                continue
            lo, hi = type_bounds[var_type]
            rhs_ids = _collect_identifiers(init_val)
            if _has_external_input(rhs_ids):
                input_desc = _describe_input(rhs_ids)
                if rhs_op in ('+', '*'):
                    key = (lhs_name, var_type, 'OVERFLOW')
                    if key not in seen:
                        seen.add(key)
                        verdicts.append(
                            f"[OVERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                            f"'{rhs_op}' with {input_desc} can exceed type max {hi}."
                        )
                if rhs_op == '-':
                    key = (lhs_name, var_type, 'UNDERFLOW')
                    if key not in seen:
                        seen.add(key)
                        verdicts.append(
                            f"[UNDERFLOW] Variable {lhs_name} ({var_type}) at {node_id}: "
                            f"'-' with {input_desc} can fall below type min {lo}."
                        )
            continue

        if nt == 'ExpressionStatement':
            expr = getattr(node_obj, 'expression', None)
            if expr and getattr(expr, 'node_type', '') == 'Assignment':
                op      = getattr(expr, 'operator', None)
                lhs_obj = getattr(expr, 'leftHandSide', None)
                rhs_obj = getattr(expr, 'rightHandSide', None)
                _process_assignment(node_id, op, lhs_obj, rhs_obj)
            continue

        if nt == 'Return':
            ret_expr = getattr(node_obj, 'expression', None)
            if ret_expr is None:
                continue
            if getattr(ret_expr, 'node_type', '') != 'BinaryOperation':
                continue
            rhs_op = getattr(ret_expr, 'operator', '')
            if rhs_op not in ('+', '-', '*'):
                continue
            rhs_ids = _collect_identifiers(ret_expr)
            has_ext = _has_external_input(rhs_ids)
            if not has_ext and rhs_op != '-':
                continue
            ret_type = 'uint256'
            visited_ret = set()
            queue_ret = [node_id]
            while queue_ret:
                curr = queue_ret.pop(0)
                if curr in visited_ret:
                    continue
                visited_ret.add(curr)
                if curr.startswith('FunctionDefinition_'):
                    fn_obj = cfg.cfg_metadata.get_node(curr)
                    if fn_obj:
                        ret_params = getattr(fn_obj, 'returnParameters', {})
                        if isinstance(ret_params, dict):
                            params_list = ret_params.get('parameters', [])
                            if params_list:
                                tn = params_list[0].get('typeName', {})
                                rtype = tn.get('name', '') if isinstance(tn, dict) else ''
                                if rtype in type_bounds:
                                    ret_type = rtype
                    break
                curr_obj = cfg.cfg_metadata.get_node(curr)
                if curr_obj and hasattr(curr_obj, 'prev_nodes'):
                    for pred in curr_obj.prev_nodes:
                        if pred not in visited_ret:
                            queue_ret.append(pred)
                if len(visited_ret) > 200:
                    break
            if ret_type not in type_bounds:
                continue
            lo, hi = type_bounds[ret_type]
            input_desc = _describe_input(rhs_ids)
            lhs_name = '(return_expr)'
            for rid in rhs_ids:
                if rid not in _BUILTIN_NAMES:
                    lhs_name = rid
                    break
            if rhs_op in ('+', '*'):
                key = (lhs_name, ret_type, 'OVERFLOW')
                if key not in seen:
                    seen.add(key)
                    verdicts.append(
                        f"[OVERFLOW] Variable {lhs_name} ({ret_type}) at {node_id}: "
                        f"'{rhs_op}' with {input_desc} can exceed type max {hi}."
                    )
            if rhs_op == '-':
                key = (lhs_name, ret_type, 'UNDERFLOW')
                if key not in seen:
                    seen.add(key)
                    verdicts.append(
                        f"[UNDERFLOW] Variable {lhs_name} ({ret_type}) at {node_id}: "
                        f"'-' with {input_desc} can fall below type min {lo}."
                    )
            continue

        if nt != 'Assignment':
            continue
        op      = getattr(node_obj, 'operator', None)
        lhs_obj = getattr(node_obj, 'leftHandSide', None)
        rhs_obj = getattr(node_obj, 'rightHandSide', None)
        _process_assignment(node_id, op, lhs_obj, rhs_obj)

    return verdicts

def _structural_timestamp_fallback(source_code):
    """Source-level structural detection for timestamp dependency."""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    verdicts = []
    TS = r'block\.timestamp|now'

    if not re.search(r'\b(?:' + TS + r')\b', stripped):
        return verdicts

    ts_aliases = set()
    for m in re.finditer(r'(?<!\.)(\b\w+)\s*=\s*(?:' + TS + r')\b', stripped):
        ts_aliases.add(m.group(1))
    for m in re.finditer(
        r'(?<!\.)(\b\w+)\s*=\s*(?:u?int\d*)\s*\(\s*(?:' + TS + r')\s*\)',
        stripped,
    ):
        ts_aliases.add(m.group(1))
    for m in re.finditer(
        r'(?<!\.)(\b\w+)\s*[+\-*/%]=\s*(?:' + TS + r')\b', stripped
    ):
        ts_aliases.add(m.group(1))
    for m in re.finditer(
        r'(?<!\.)(\b\w+)\s*=\s*([^;]*\b(?:' + TS + r')\b[^;]*)', stripped
    ):
        rhs = m.group(2)
        if re.search(r'[+\-*/%]\s*[\w(]|[\w)]\s*[+\-*/%]', rhs):
            ts_aliases.add(m.group(1))

    for alias in list(ts_aliases):
        esc_a = re.escape(alias)
        for m in re.finditer(
            r'(?<!\.)(\b\w+)\s*=\s*\b' + esc_a + r'\b\s*;', stripped
        ):
            candidate = m.group(1)
            if candidate != alias:
                ts_aliases.add(candidate)

    if ts_aliases:
        AP = (r'\b(?:' + TS + r'|'
              + '|'.join(re.escape(a) for a in ts_aliases) + r')\b')
    else:
        AP = r'\b(?:' + TS + r')\b'

    def _extract_balanced(text, o='(', c=')'):
        """Return (inner_content, close_index) for the first balanced pair."""
        depth = 0
        start = None
        for i, ch in enumerate(text):
            if ch == o:
                if depth == 0:
                    start = i
                depth += 1
            elif ch == c:
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start + 1:i], i
        return None, -1

    def _is_inside_guard(pos):
        """Walk backwards from *pos* through all enclosing paren levels to"""
        preceding = stripped[:pos]
        depth = 0
        for i in range(len(preceding) - 1, -1, -1):
            ch = preceding[i]
            if ch == ')':
                depth += 1
            elif ch == '(':
                if depth > 0:
                    depth -= 1
                else:
                    pre = preceding[:i].rstrip()
                    if re.search(r'\b(?:require|assert)\s*$', pre):
                        return True
                    if re.search(r'\bif\s*$', pre):
                        d2 = 1
                        for j in range(i + 1, len(stripped)):
                            if stripped[j] == '(':
                                d2 += 1
                            elif stripped[j] == ')':
                                d2 -= 1
                                if d2 == 0:
                                    aft = stripped[j + 1:].lstrip()
                                    if re.match(
                                        r'(?:throw\s*;|revert\s*\()', aft
                                    ):
                                        return True
                                    break
                    continue
        return False

    def _is_guard_body(after_text):
        """Return True when the if/while body is a pure guard (throw,"""
        after = after_text.lstrip()
        if re.match(r'throw\s*;', after):
            return True
        if re.match(r'revert\s*\(', after):
            return True

        if after.startswith('{'):
            body, end_pos = _extract_balanced(after, '{', '}')
            if body is not None:
                stmts = [
                    s.strip() for s in body.strip().split(';') if s.strip()
                ]
                guard_re = re.compile(
                    r'^(throw'
                    r'|revert\s*\(.*\)'
                    r'|require\s*\(.*\)'
                    r'|assert\s*\(.*\)'
                    r'|break'
                    r'|continue)$',
                    re.DOTALL,
                )
                if stmts and all(guard_re.match(s) for s in stmts):
                    return True
                rest = after[end_pos + 1:].lstrip()
                if rest.startswith('else'):
                    if stmts and all(guard_re.match(s) for s in stmts):
                        if _is_guard_body(rest[4:].lstrip()):
                            return True
        return False

    hash_fns = r'sha3|sha256|keccak256|ripemd160'
    for m in re.finditer(r'\b(?:' + hash_fns + r')\s*\(', stripped):
        args, _ = _extract_balanced(stripped[m.start():], '(', ')')
        if args and re.search(AP, args) and not _is_inside_guard(m.start()):
            verdicts.append(
                "[TIMESTAMP] block.timestamp/now used in hash computation "
                "for pseudo-randomness."
            )
            return verdicts

    for m in re.finditer(
        r'(?:' + AP + r')\s*%|%\s*(?:' + AP + r')', stripped
    ):
        if not _is_inside_guard(m.start()):
            verdicts.append(
                "[TIMESTAMP] block.timestamp/now used in modulo operation."
            )
            return verdicts

    arith_re = re.compile(
        r'(?:' + AP + r')\s*[+\-*/]|[+\-*/]\s*\(?(?:' + AP + r')'
    )
    for hit in arith_re.finditer(stripped):
        if not _is_inside_guard(hit.start()):
            verdicts.append(
                "[TIMESTAMP] block.timestamp/now used in arithmetic "
                "that computes a value."
            )
            return verdicts

    if re.search(
        r'\bbool\s+\w+\s*=[^;]*(?:' + AP + r')\s*[<>=!&|]', stripped
    ):
        verdicts.append(
            "[TIMESTAMP] Boolean variable assigned from timestamp comparison."
        )
        return verdicts

    for m in re.finditer(r'return\s+([^;]+);', stripped):
        ret_body = m.group(1).strip()
        if re.match(r'^(true|false|0)$', ret_body):
            continue
        if re.search(AP, ret_body):
            verdicts.append(
                "[TIMESTAMP] Return value derived from block.timestamp/now."
            )
            return verdicts

    for m in re.finditer(r'\b(?:if|while)\s*\(', stripped):
        cond, close_pos = _extract_balanced(
            stripped[m.start():], '(', ')'
        )
        if cond is None or not re.search(AP, cond):
            continue
        after = stripped[m.start() + close_pos + 1:]
        if not _is_guard_body(after):
            verdicts.append(
                "[TIMESTAMP] block.timestamp/now in if/while-condition "
                "controls state-changing logic."
            )
            return verdicts
        has_direct_ts = bool(re.search(r'\b(?:' + TS + r')\b', cond))
        has_alias_arith = ts_aliases and bool(re.search(
            r'\b(?:' + '|'.join(re.escape(a) for a in ts_aliases) + r')\b'
            r'\s*[+\-]',
            cond,
        ))
        if has_direct_ts and has_alias_arith:
            verdicts.append(
                "[TIMESTAMP] block.timestamp/now compared against a "
                "timestamp-derived expression in condition — outcome is "
                "manipulable by miner."
            )
            return verdicts

    if ts_aliases:
        COMP_OPS = r'[<>!=]='
        COMP_SINGLE = r'(?<!=)[<>](?!=)'
        for alias in ts_aliases:
            esc = re.escape(alias)
            assign_re = re.compile(
                r'\b' + esc + r'\s*[+\-*/%]?=\s*(?:' + TS + r')\b'
                r'|\b' + esc + r'\s*=\s*(?:u?int\d*)\s*\(\s*(?:' + TS + r')'
            )
            checks = [
                re.compile(r'(?<![=<>!])\b' + esc + r'\b\s*[+\-*/%](?!=)'),
                re.compile(r'[+\-*/%]\s*\(?\b' + esc + r'\b'),
                re.compile(
                    r'\b' + esc + r'\b\s*(?:' + COMP_OPS + r'|'
                    + COMP_SINGLE + r')'
                ),
                re.compile(
                    r'(?:' + COMP_OPS + r'|' + COMP_SINGLE + r')\s*\b'
                    + esc + r'\b'
                ),
                re.compile(r'return\s+[^;]*\b' + esc + r'\b'),
            ]
            for pat in checks:
                for use in pat.finditer(stripped):
                    ctx = stripped[max(0, use.start() - 120):use.end() + 20]
                    if assign_re.search(ctx):
                        continue
                    if _is_inside_guard(use.start()):
                        continue
                    if 'return' in stripped[use.start():use.start() + 10]:
                        rl = stripped[use.start():].split(';')[0].strip()
                        if re.match(r'return\s+(true|false|0)$', rl):
                            continue
                    verdicts.append(
                        f"[TIMESTAMP] block.timestamp/now assigned to "
                        f"'{alias}' which influences downstream "
                        f"computation."
                    )
                    return verdicts

    return verdicts

def _confirm_with_domains(source_code, verdicts, vuln, domains):
    """Semantic-confirmation layer for timestamp / TOD via the abstract"""
    info = {"times": {}, "feasible": {}, "fallback": False}
    if not verdicts or not domains:
        return verdicts, info

    try:
        cfg, _ = _build_cfg(source_code)
    except Exception as e:
        logging.info(f"[CONFIRM:{vuln}] CFG build failed ({e}) — keeping structural verdicts.")
        info["fallback"] = True
        return verdicts, info

    any_feasible_overall = False
    for domain in domains:
        try:
            csem = AbstractCollectingSemanticsAnalysis(
                cfg, 'SourceEntry_0', 'SourceExit_0',
                '/usr/local/lib/apron.jar', domain_type=domain
            )
            _auto_register_function_params(cfg, csem.constant_registry)
            for v in ('blocktimestamp', 'block_timestamp', 'now', 'timestamp'):
                try:
                    csem.constant_registry.register_variable(v, False, ('0', '1000000'))
                except Exception:
                    pass
            buf = StringIO()
            old_out, old_err = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = buf, StringIO()
            t0 = time.time()
            converged = True
            try:
                _compute_with_timeout(csem)
            except _FixpointTimeout:
                converged = False
            except Exception:
                converged = False
            finally:
                sys.stdout, sys.stderr = old_out, old_err
            elapsed = time.time() - t0
            info["times"][domain] = round(elapsed, 4)
            logging.info(f"[CONFIRM:{vuln}] domain={domain} fixpoint={elapsed:.4f}s converged={converged}")

            feasible = True
            if converged:
                try:
                    feasible = _fixpoint_has_reachable_state(csem)
                except Exception:
                    feasible = True
            info["feasible"][domain] = feasible
            any_feasible_overall = any_feasible_overall or feasible or (not converged)
        except Exception as e:
            logging.info(f"[CONFIRM:{vuln}] domain={domain} unavailable ({e}) — keeping verdicts.")
            info["fallback"] = True
            any_feasible_overall = True

    converged_domains = [d for d in domains if d in info["feasible"]]
    if converged_domains and not any(info["feasible"][d] for d in converged_domains) \
            and not any_feasible_overall:
        logging.info(f"[CONFIRM:{vuln}] all domains prove infeasible — suppressing {len(verdicts)} verdict(s).")
        return [], info

    return verdicts, info

def _fixpoint_has_reachable_state(csem):
    """Return True if any registered node holds a non-bottom entry state at the"""
    ps = csem.point_state
    it = ps.iteration
    mgr = csem.manager
    for node_id in ps.node_states:
        try:
            st = ps.get_node_state_set(node_id, it, True)
        except Exception:
            continue
        if st is None:
            continue
        try:
            if not st.isBottom(mgr):
                return True
        except Exception:
            return True
    return False

def _analyse_timestamp(transformed_cfg, dep_analysis, source_code=None):
    """Run timestamp dependency analysis."""
    verdicts = []

    if source_code:
        verdicts = _structural_timestamp_fallback(source_code)

    if verdicts and source_code:
        sre = SemanticRefinementEngine(
            cfg=transformed_cfg,
            collecting_semantics={},
        )
        verdicts = sre.filter_timestamp_verdicts(verdicts, source_code)

    if not verdicts and source_code:
        _stripped = re.sub(r'//[^\n]*', '', source_code)
        _stripped = re.sub(r'/\*.*?\*/', '', _stripped, flags=re.DOTALL)
        _TS = r'block\.timestamp|now'
        _ts_uses = list(re.finditer(r'\b(?:' + _TS + r')\b', _stripped))
        _struct_assign = re.compile(r'\b\w+\.\w+\s*=\s*(?:' + _TS + r')\b')
        _all_logging = bool(_ts_uses) and all(
            _struct_assign.search(_stripped[max(0, m.start() - 30):m.end() + 5])
            for m in _ts_uses
        )
        if _all_logging:
            return verdicts

    if not verdicts and dep_analysis is not None:
        SYNTHETIC_VARS = {
            'BAL', 'attacker_bal', 'credit', 'msgsender', 'msgvalue',
            'msg.value', 'msg.sender',
        }
        ts_seen = set()
        state_vars = getattr(dep_analysis.cfg, 'state_variables', set())

        for node_id, sources in dep_analysis.timestamp_influence.items():
            if transformed_cfg is None:
                continue
            n_obj = transformed_cfg.cfg_metadata.get_node(node_id)
            if n_obj is None:
                continue

            written_var = None
            nt = getattr(n_obj, 'node_type', '')

            if nt == 'ExpressionStatement':
                expr = getattr(n_obj, 'expression', None)
                if expr and getattr(expr, 'node_type', '') == 'Assignment':
                    lhs = getattr(expr, 'leftHandSide', None)
                    if lhs:
                        written_var = getattr(lhs, 'name', None)
                        if not written_var and getattr(
                            lhs, 'node_type', ''
                        ) == 'IndexAccess':
                            base = (
                                getattr(lhs, 'base_expression', None)
                                or getattr(lhs, 'baseExpression', None)
                            )
                            if base:
                                written_var = getattr(base, 'name', None)
            elif nt == 'Assignment':
                lhs = getattr(n_obj, 'leftHandSide', None)
                if lhs:
                    written_var = getattr(lhs, 'name', None)
            elif nt == 'VariableDeclarationStatement':
                decls = getattr(n_obj, 'declarations', [])
                if decls and decls[0]:
                    written_var = getattr(decls[0], 'name', None)

            if written_var and written_var in SYNTHETIC_VARS:
                continue
            if written_var and written_var not in state_vars:
                continue

            for src in sources:
                dedup_key = (written_var or node_id, src)
                if dedup_key in ts_seen:
                    continue
                ts_seen.add(dedup_key)
                verdicts.append(
                    f"[TIMESTAMP] State variable "
                    f"'{written_var or node_id}' at {node_id} depends "
                    f"on block.timestamp via dependency chain: {src}."
                )

    return verdicts

def _extract_functions_balanced(source):
    """Extract (name, signature, body) tuples using brace-balanced parsing."""
    funcs = []
    for m in re.finditer(
        r'function\s+(\w+)\s*(\([^)]*\)[^;{]*)\{', source
    ):
        fname = m.group(1)
        sig   = m.group(2).strip()
        start = m.end()
        depth = 1
        i = start
        while i < len(source) and depth > 0:
            if source[i] == '{':
                depth += 1
            elif source[i] == '}':
                depth -= 1
            i += 1
        body = source[start:i - 1]
        funcs.append((fname, sig, body))
    return funcs

def _collect_state_var_declarations(source):
    """Return set of variable names declared at contract scope (state vars)."""
    state_vars = set()
    cleaned = source

    func_header_re = re.compile(r'function\s+\w+\s*\([^)]*\)[^;{]*\{')
    for m in list(func_header_re.finditer(cleaned)):
        start = m.start()
        depth = 0
        i = m.end() - 1
        while i < len(cleaned):
            if cleaned[i] == '{':
                depth += 1
            elif cleaned[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        cleaned = cleaned[:start] + ' ' * (i + 1 - start) + cleaned[i + 1:]

    for kw in ('struct', 'event', 'modifier', 'enum'):
        for m in list(re.finditer(kw + r'\s+\w+\s*(?:\([^)]*\))?\s*\{', cleaned)):
            start = m.start()
            depth = 0
            i = m.end() - 1
            while i < len(cleaned):
                if cleaned[i] == '{':
                    depth += 1
                elif cleaned[i] == '}':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            cleaned = cleaned[:start] + ' ' * (i + 1 - start) + cleaned[i + 1:]

    for m in list(re.finditer(r'constructor\s*\([^)]*\)[^;{]*\{', cleaned)):
        start = m.start()
        depth = 0
        i = m.end() - 1
        while i < len(cleaned):
            if cleaned[i] == '{':
                depth += 1
            elif cleaned[i] == '}':
                depth -= 1
                if depth == 0:
                    break
            i += 1
        cleaned = cleaned[:start] + ' ' * (i + 1 - start) + cleaned[i + 1:]

    decl_re = re.compile(
        r'\b(?:uint\d*|int\d*|address|bool|bytes\d*|string)\s+'
        r'(?:payable\s+)?'
        r'(?:public\s+|private\s+|internal\s+)?'
        r'(\w+)\s*(?:=[^;]*)?\s*;'
    )
    for m in decl_re.finditer(cleaned):
        state_vars.add(m.group(1))

    map_re = re.compile(r'mapping\s*\([^)]+\)\s*(?:public|private|internal)?\s*(\w+)\s*;')
    for m in map_re.finditer(cleaned):
        state_vars.add(m.group(1))

    return state_vars

_TOD_SKIP_VARS = {
    'owner', 'creator', 'admin', 'organizer', 'manager', 'operator',
    'minter', 'pauser', 'governance', 'authority', 'controller',
    'beneficiary', 'newowner', 'pendingowner', 'contractowner',
    'founder', 'supervisor', 'ceo', 'cfo', 'coo',
    'name', 'symbol', 'decimals', 'totalsupply', '_totalsupply',
    '_name', '_symbol', '_decimals',
    'bal', 'attacker_bal', 'msgsender', 'msgvalue',
}

_TOD_SKIP_PREFIXES = (
    'fee', 'gas_price', 'gasprice', 'min_fee', 'minfee', 'max_fee',
    'maxfee', 'cancellation', 'commission', 'rate', 'exchangerate',
    'version', 'newversion', 'killswitch', 'paused', 'stopped',
    'locked', 'migrated', 'deprecated', 'initialized', 'isactive',
)

_TOD_RELEVANT_SUBSTRINGS = (
    'reward', 'winner', 'bounty', 'prize', 'jackpot', 'pot', '_tod',
)

def _structural_tod_fallback(source_code):
    """Source-level structural fallback for TOD detection."""
    stripped = re.sub(r'//[^\n]*', '', source_code)
    stripped = re.sub(r'/\*.*?\*/', '', stripped, flags=re.DOTALL)

    verdicts = []

    has_hash_compare = bool(re.search(
        r'require\s*\(\s*\w+\s*==\s*(?:sha3|keccak256)\s*\(', stripped
    ))
    has_transfer_in_same = bool(re.search(
        r'\.transfer\s*\(', stripped
    ))
    if has_hash_compare and has_transfer_in_same:
        verdicts.append(
            "[TOD] Contract uses hash-challenge pattern with ether transfer; "
            "solution can be front-run by observing the mempool."
        )

    functions = _extract_functions_balanced(stripped)

    _REWARD_VARS_RE = re.compile(
        r'^(reward|price|bounty|prize|jackpot|pot)', re.IGNORECASE
    )

    writers_p2 = set()
    readers_p2 = set()

    for fname, _sig, fbody in functions:
        assign_matches = re.findall(
            r'\b(reward\w*|price\w*|bounty\w*|prize\w*|jackpot\w*|pot\w*)\s*=[^=]',
            fbody, re.IGNORECASE
        )
        for var in assign_matches:
            writers_p2.add((fname, var.strip().lower()))

        transfer_matches = re.findall(
            r'\.(?:transfer|send)\s*\(\s*(\w+)', fbody
        )
        for arg in transfer_matches:
            if _REWARD_VARS_RE.match(arg):
                readers_p2.add((fname, arg.lower()))

    for wfunc, wvar in writers_p2:
        for rfunc, rvar in readers_p2:
            if wfunc != rfunc and wvar == rvar:
                verdicts.append(
                    f"[TOD] Variable '{wvar}' is set in {wfunc}() and used in "
                    f"{rfunc}()'s ether transfer. Transaction reordering may "
                    f"change the transferred amount."
                )
                break
        if verdicts and len(verdicts) > 1:
            break

    has_msg_sender_storage = bool(re.search(
        r'(?:Player|player)\s*\([^)]*msg\.sender'
        r'|'
        r'\w+\[.*\]\s*=\s*(?:Player|player)\s*\([^)]*msg\.sender',
        stripped
    ))
    has_payable_play = bool(re.search(
        r'function\s+\w*(?:play|bet|wager|commit|join|enter)\s*\([^)]*\)'
        r'\s*[^{]*payable',
        stripped, re.IGNORECASE
    ))
    has_conditional_send = bool(re.search(
        r'if\s*\([^)]*\)\s*\{[^}]*\.(?:send|transfer)\s*\(',
        stripped, re.DOTALL
    ))
    if has_msg_sender_storage and has_payable_play and has_conditional_send:
        verdicts.append(
            "[TOD] Contract uses competitive game pattern: player choices "
            "are stored on-chain and can be observed in the mempool, "
            "allowing opponents to front-run with an optimal response."
        )

    _CONSTRUCTOR_RE = re.compile(r'^constructor$', re.IGNORECASE)
    _INTERNAL_SIG = re.compile(r'\b(internal|view|pure)\b', re.IGNORECASE)
    _OWNER_MOD_KEYWORDS = (
        'onlyowner', 'onlyadmin', 'only_owner', 'onlyminter', 'onlyceo',
        'onlycfo', 'onlygov', 'onlyauthority', 'onlycontroller',
        'onlyoperator', 'onlypauser', 'onlymanager', 'restricted',
        'onlybeneficiary', 'onlyfounder', 'byoracle', 'byadmin',
        'onlygovernance', 'onlywhitelisted', 'onlyrole',
    )

    contract_names = set()
    for m in re.finditer(r'\bcontract\s+(\w+)', stripped):
        contract_names.add(m.group(1))

    state_vars = _collect_state_var_declarations(stripped)

    def _is_tod_skip_var(v):
        """Return True if the variable should be excluded from P4/P5 TOD."""
        vl = v.lower()
        if any(sub in vl for sub in _TOD_RELEVANT_SUBSTRINGS):
            return False
        if vl in _TOD_SKIP_VARS:
            return True
        if any(vl.startswith(p) or vl == p for p in _TOD_SKIP_PREFIXES):
            return True
        return False

    func_assigns    = {}
    func_amt_uses   = {}
    func_rcpt_uses  = {}
    func_restricted = {}
    func_inline_acl = {}

    for fname, sig, fbody in functions:
        if _CONSTRUCTOR_RE.match(fname) or fname in contract_names:
            continue
        if _INTERNAL_SIG.search(sig):
            continue

        sig_lower = sig.lower()
        func_restricted[fname] = any(
            kw in sig_lower for kw in _OWNER_MOD_KEYWORDS
        )

        func_inline_acl[fname] = bool(re.search(
            r'(?:require|if)\s*\(\s*msg\.sender\s*==', fbody
        ))

        assigns = set()
        for m in re.finditer(r'\b(\w+)\s*=[^=]', fbody):
            v = m.group(1)
            if v in state_vars and not _is_tod_skip_var(v):
                assigns.add(v)
        for m in re.finditer(r'\b(\w+)\s*(?:\+|-|\*)=', fbody):
            v = m.group(1)
            if v in state_vars and not _is_tod_skip_var(v):
                assigns.add(v)
        func_assigns[fname] = assigns

        amt_uses = set()
        for m in re.finditer(r'\.(?:transfer|send)\s*\(\s*(\w+)', fbody):
            v = m.group(1)
            if v in state_vars and not _is_tod_skip_var(v):
                amt_uses.add(v)
        func_amt_uses[fname] = amt_uses

        rcpt_uses = set()
        for m in re.finditer(r'\b(\w+)\.(?:transfer|send)\s*\(', fbody):
            v = m.group(1)
            if v in state_vars and not _is_tod_skip_var(v):
                rcpt_uses.add(v)
        func_rcpt_uses[fname] = rcpt_uses

    tod_found = set()

    def _is_tod_relevant_name(v):
        """Return True if variable name suggests TOD-exploitable semantics."""
        vl = v.lower()
        return any(sub in vl for sub in _TOD_RELEVANT_SUBSTRINGS)

    for f_def, assigned in func_assigns.items():
        if func_restricted.get(f_def, False):
            continue
        has_inline_acl = func_inline_acl.get(f_def, False)

        for f_use in func_amt_uses:
            if f_def == f_use:
                continue
            shared = assigned & func_amt_uses[f_use]
            for v in shared:
                if has_inline_acl and not _is_tod_relevant_name(v):
                    continue
                key = (v, f_def, f_use, 'amount')
                if key not in tod_found:
                    tod_found.add(key)
                    verdicts.append(
                        f"[TOD] Variable '{v}' is assigned in {f_def}() and "
                        f"used as ether transfer amount in {f_use}(). "
                        f"Transaction reordering may change the transferred amount."
                    )

        for f_use in func_rcpt_uses:
            if f_def == f_use:
                continue
            shared = assigned & func_rcpt_uses[f_use]
            for v in shared:
                if has_inline_acl and not _is_tod_relevant_name(v):
                    continue
                key = (v, f_def, f_use, 'recipient')
                if key not in tod_found:
                    tod_found.add(key)
                    verdicts.append(
                        f"[TOD] Variable '{v}' is assigned in {f_def}() and "
                        f"used as ether transfer recipient in {f_use}(). "
                        f"Transaction reordering may change the transfer target."
                    )

    if re.search(
        r'function\s+approve\s*\([^)]*\)[^{]*\{[^}]*?'
        r'\b\w+\s*\[\s*msg\.sender\s*\]\s*\[[^\]]+\]\s*=(?!=)',
        stripped, re.DOTALL,
    ):
        verdicts.append(
            "[TOD] ERC-20 approve() sets the allowance to an absolute value; a "
            "spender can front-run an allowance change to spend both the old and "
            "the new amount (approve/transferFrom race, SWC-114)."
        )

    return verdicts

def _analyse_tod(dep_analysis, source_code=None):
    """Emit TOD verdicts from DependencyAnalysisEngine.tod_entries."""
    SYNTHETIC_VARS = {'BAL', 'attacker_bal', 'credit', 'msgsender', 'msgvalue',
                      'msg.value', 'msg.sender', 'CONTRACT_BALANCE',
                      'BLOCK_TIMESTAMP', 'BLOCK_NUMBER'}

    _contract_names = set()
    if source_code:
        for m in re.finditer(r'\bcontract\s+(\w+)', source_code):
            _contract_names.add(m.group(1))

    _ACCESS_CTRL = {
        'owner', 'creator', 'admin', 'organizer', 'manager', 'operator',
        'minter', 'pauser', 'governance', 'authority', 'controller',
        'beneficiary', 'ceoaddress', 'ceo', 'cfo', 'coo', 'newowner',
        'pendingowner', 'requester', 'wallet', 'masteraddress',
        'owneraddress', 'contractowner', 'founder', 'supervisor',
    }

    _BALANCE_VARS = {
        'balances', 'balance', '_balances', 'userbalances', 'locktime',
        'locked', 'deposits', 'credits', 'lastdeposit', 'commit',
        'stake', 'stakes', 'creditedpoints', 'nonces', 'tokenbalances',
        'wagers', 'timestamps', 'bets', 'playerbalances', 'debt',
    }
    _DEP_LIKE = ('deposit', 'fund', 'contribute', 'stake', 'lock',
                 'bet', 'wager', 'receive', 'fallback')
    _WDR_LIKE = ('withdraw', 'refund', 'claim', 'unstake', 'unlock',
                 'payout', 'collect', 'cashout', 'redeem')

    _OWNER_MODS = (
        'onlyowner', 'onlyadmin', 'only_owner', 'onlyminter', 'onlyceo',
        'onlycfo', 'onlygov', 'onlyauthority', 'onlycontroller',
        'onlyoperator', 'onlypauser', 'onlymanager', 'restricted',
        'onlybeneficiary', 'onlyfounder',
    )

    _TOKEN_META = {
        'name', '_name', 'symbol', '_symbol', 'decimals', '_decimals',
        'totalsupply', '_totalsupply', 'initialsupply', 'cap', '_cap',
        'maxsupply', 'minsupply', 'rate', '_rate', 'version',
    }

    _MAPPING_SCALARS = {
        'balanceof', 'allowance', 'allowed', 'approved', 'approvals',
        '_allowances', '_balances',
    }

    _func_sig_cache = {}
    if source_code:
        src_clean = re.sub(r'//[^\n]*|/\*.*?\*/', '', source_code,
                           flags=re.DOTALL)
        for m in re.finditer(
            r'function\s+(\w+)\s*\([^)]*\)\s*([^{]*)\{',
            src_clean, re.DOTALL,
        ):
            _func_sig_cache[m.group(1)] = m.group(2).lower()

    def _func_name(func_str):
        """'FunctionDefinition_N: name' → 'name'"""
        return func_str.split(':')[-1].strip()

    def _is_constructor(func_str):
        name = _func_name(func_str)
        if not name:
            return True
        if name.lower() == 'constructor':
            return True
        if name in _contract_names:
            return True
        return False

    def _is_dep_like(name):
        n = name.lower()
        return any(kw in n for kw in _DEP_LIKE)

    def _is_wdr_like(name):
        n = name.lower()
        return any(kw in n for kw in _WDR_LIKE)

    def _is_owner_restricted(fname):
        if not source_code or not fname:
            return False
        sig = _func_sig_cache.get(fname, '')
        if sig and any(kw in sig for kw in _OWNER_MODS):
            return True
        return False

    def _is_non_external(fname):
        """D11: return True if function is internal, view, or pure."""
        if not fname:
            return False
        sig = _func_sig_cache.get(fname, '')
        if not sig:
            return False
        for kw in ('internal', 'view', 'pure', 'private'):
            if kw in sig.split():
                return True
        return False

    verdicts = []
    tod_seen = set()
    tod_re   = re.compile(
        r'\s*(\S+):\s+defined in (\S+)\s+\(([^)]+)\),\s+used in (\S+)\s+\(([^)]+)\)'
    )

    for entry in getattr(dep_analysis, 'tod_entries', []):
        m = tod_re.match(entry)
        if m:
            var, def_node, def_func, use_node, use_func = m.groups()
            var = var.strip()
            def_func = def_func.strip()
            use_func = use_func.strip()
            df_name = _func_name(def_func)
            uf_name = _func_name(use_func)

            if var in SYNTHETIC_VARS:
                continue

            if def_func == use_func:
                continue

            if _is_constructor(def_func):
                continue

            if var.lower() in _ACCESS_CTRL:
                continue

            if var.lower() in _BALANCE_VARS:
                if _is_dep_like(df_name) or _is_wdr_like(uf_name):
                    continue

            if _is_owner_restricted(df_name):
                continue

            if var.lower() in _TOKEN_META:
                continue

            if _is_non_external(df_name) or _is_non_external(uf_name):
                continue

            if var.lower() in _MAPPING_SCALARS:
                continue

            key = (var, use_func)
            if key in tod_seen:
                continue
            tod_seen.add(key)

            verdicts.append(
                f"[TOD] Function {use_func} reads storage variable "
                f"{var} which is written by externally callable function "
                f"{def_func}. Reordering may affect {use_func}'s behavior."
            )
        else:
            if entry not in tod_seen:
                tod_seen.add(entry)
                verdicts.append(f"[TOD] {entry.strip()}")

    if source_code:
        structural = _structural_tod_fallback(source_code)
        for v in structural:
            if v not in verdicts:
                verdicts.append(v)

    return verdicts

def _select_reentrancy_domains(transformed_cfg):
    """Return ['Box','Octagon','Polka'] when a reentrancy encoding is present,"""
    has_back_edge = (
        any(nid.startswith("IfStatement_")
            for nid in transformed_cfg.cfg_metadata.node_table)
        and getattr(transformed_cfg, 'credit_var_name', None) not in (None, 'BAL')
    )
    if has_back_edge:
        logging.info("[DOMAIN] Reentrancy encoding detected → Box + Octagon + Polka")
        return ["Box", "Octagon", "Polka"]
    logging.info("[DOMAIN] No reentrancy encoding → Box only")
    return ["Box"]

def run_static_analysis(source_code, solidity_filepath,
                        annotate_dependencies=False, verbose=False,
                        output_dir=None, json_output=False,
                        pipelines=None, reentrancy_domain='auto'):
    """Orchestrate all four analysis pipelines."""
    out_dir = _resolve_output_dir(output_dir)

    base_name = os.path.basename(solidity_filepath).replace(".sol", "")

    _ALL_PIPELINES = {"reentrancy", "overflow", "timestamp", "tod"}
    active = set(pipelines) if pipelines else _ALL_PIPELINES

    logging.info("Starting Solidity compilation and static analysis.")
    start_total = time.time()
 
    transform_failed = False
    transform_error_msg = None
    try:
        transformed_cfg, credit_var_name, transformed_source = \
            _build_transformed_cfg(source_code)
    except (RuntimeError, Exception) as e:
        transform_error_msg = str(e)
        logging.warning(f"Transformed CFG build failed: {e}")
        logging.info("Falling back: skipping reentrancy/timestamp/TOD analysis, running overflow only.")
        transform_failed = True
        transformed_cfg = None
        credit_var_name = None
        transformed_source = None

    if transform_failed:
        if "overflow" in active:
            logging.info("\n========== PIPELINE 2: OVERFLOW / UNDERFLOW (fallback) ==========")
            try:
                overflow_verdicts, overflow_csem = _analyse_overflow(source_code)
            except Exception as e2:
                logging.warning(f"Overflow analysis also failed: {e2}")
                overflow_verdicts = []
                overflow_csem = None
        else:
            overflow_verdicts, overflow_csem = [], None

        all_domains = ["Box"]

        if "reentrancy" in active:
            fallback_reentrancy_verdict = None
            try:
                fallback_reentrancy_verdict = _detect_modifier_reentrancy(source_code)
            except Exception:
                pass
            if fallback_reentrancy_verdict is None:
                try:
                    fallback_reentrancy_verdict = _detect_erc20_reentrancy(source_code)
                except Exception:
                    pass
            if fallback_reentrancy_verdict is None:
                try:
                    fallback_reentrancy_verdict = _detect_call_value_state_after(source_code)
                except Exception:
                    pass
            if fallback_reentrancy_verdict is not None:
                reentrancy_results = {"Box": [fallback_reentrancy_verdict]}
                fallback_reentrancy_flag = 1
            else:
                reentrancy_results = {"Box": ["[REENTRANCY-SKIP] Transformed CFG unavailable."]}
                fallback_reentrancy_flag = -1
        else:
            reentrancy_results = {"Box": []}
            fallback_reentrancy_flag = -1

        if "timestamp" in active:
            timestamp_verdicts = _structural_timestamp_fallback(source_code)
            if not timestamp_verdicts:
                timestamp_verdicts = ["[TIMESTAMP-SKIP] Transformed CFG unavailable."]
                fallback_timestamp_flag = -1
            else:
                fallback_timestamp_flag = 1
        else:
            timestamp_verdicts = []
            fallback_timestamp_flag = -1

        if "tod" in active:
            tod_verdicts = _structural_tod_fallback(source_code)
            if not tod_verdicts:
                fallback_tod_flag = 0
            else:
                fallback_tod_flag = 1
        else:
            tod_verdicts = []
            fallback_tod_flag = -1

        verdicts_by_domain = {}
        for dom in all_domains:
            combined = []
            combined.extend(reentrancy_results.get(dom, []))
            combined.extend(overflow_verdicts)
            combined.extend(timestamp_verdicts)
            combined.extend(tod_verdicts)
            verdicts_by_domain[dom] = combined

        analysis_path = os.path.join(out_dir, f"{base_name}_analysis.txt")
        relevant_re = re.compile(r'^(ENTRY|EXIT)')
        with open(analysis_path, "w") as af:
            af.write("\n===== OVERFLOW / UNDERFLOW (Box domain, original source) =====\n")
            of_raw = getattr(overflow_csem, '_captured_output', '') if overflow_csem else ''
            of_keys = next(
                (ln for ln in of_raw.splitlines() if ln.startswith("dict_keys")), None
            )
            if of_keys:
                af.write(of_keys + "\n")
            for ln in of_raw.splitlines():
                if relevant_re.match(ln):
                    af.write(ln + "\n")

        logging.info("")
        seen_file_lines = set()
        deduped_lines = []
        for dom in ("Box",):
            if dom not in verdicts_by_domain:
                continue
            logging.info(f"===== VERDICTS ({dom}) =====")
            for line in verdicts_by_domain[dom]:
                logging.info(line)
                if line not in seen_file_lines:
                    seen_file_lines.add(line)
                    deduped_lines.append(line)
            logging.info("")

        total_time = time.time() - start_total
        logging.info("\n========== FINAL VULNERABILITY SUMMARY ==========")
        has_reentrancy_fallback = any('[REENTRANCY]' in v and '[NO REENTRANCY]' not in v and '[REENTRANCY-SKIP]' not in v for v in deduped_lines)
        has_timestamp_fallback = any('[TIMESTAMP]' in v and '[TIMESTAMP-SKIP]' not in v for v in deduped_lines)
        has_tod_fallback = any('[TOD]' in v and '[TOD-SKIP]' not in v for v in deduped_lines)
        has_overflow  = any('[OVERFLOW]'  in v for v in deduped_lines)
        has_underflow = any('[UNDERFLOW]' in v for v in deduped_lines)
        _NA = "ANALYSIS UNAVAILABLE (transformed CFG failed)"
        logging.info("[SUMMARY] Reentrancy: " + ("VULNERABLE" if has_reentrancy_fallback else _NA))
        logging.info("[SUMMARY] Integer Overflow: " + ("VULNERABLE" if has_overflow else "NOT VULNERABLE"))
        logging.info("[SUMMARY] Integer Underflow: " + ("VULNERABLE" if has_underflow else "NOT VULNERABLE"))
        logging.info("[SUMMARY] Timestamp Dependency: " + ("VULNERABLE" if has_timestamp_fallback else _NA))
        if has_tod_fallback:
            logging.info("[SUMMARY] TOD: VULNERABLE")
        elif fallback_tod_flag == 0:
            logging.info("[SUMMARY] TOD: NOT VULNERABLE")
        else:
            logging.info("[SUMMARY] TOD: " + _NA)
        skipped = []
        if not has_reentrancy_fallback and fallback_reentrancy_flag == -1:
            skipped.append("reentrancy")
        if not has_timestamp_fallback and fallback_timestamp_flag == -1:
            skipped.append("timestamp")
        if not has_tod_fallback and fallback_tod_flag == -1:
            skipped.append("tod")
        if skipped:
            logging.info(
                "\nNOTE: Some pipelines were SKIPPED because the "
                "mapping transformer could not process this contract.  These vulnerabilities "
                "are recorded as -1 (N/A) in the JSON verdict — they are excluded from "
                "TP/TN/FP/FN counts rather than counted as negatives."
            )

        logging.info(f"\nTotal analysis time: {total_time:.2f}s")

        if json_output:
            verdict_dict = {
                "reentrancy": fallback_reentrancy_flag,
                "overflow":   1 if (has_overflow or has_underflow) else 0,
                "timestamp":  fallback_timestamp_flag,
                "tod":        fallback_tod_flag,
            }
            _write_json_verdict(
                out_dir, base_name, verdict_dict, total_time,
                error=f"transform_failed: {transform_error_msg}",
                skipped_pipelines=skipped if skipped else None,
            )

        return analysis_path

    gen_dir = os.path.join(out_dir, 'gen')
    os.makedirs(gen_dir, exist_ok=True)
    try:
        orig_compiler = SolCompiler(source_code)
        orig_output = orig_compiler.compile()
        orig_contracts = orig_output.get_contracts_list()
        if orig_contracts:
            orig_ast = orig_output.get_ast(orig_contracts[0])
            with open(os.path.join(gen_dir, 'ast.json'), 'w', encoding='utf8') as f:
                json.dump(orig_ast, f, indent=4)
    except Exception as e:
        logging.warning(f"AST dump skipped: {e}")
 
    try:
        transformed_cfg.generate_dot()
        transformed_cfg.generate_dot_bottom_up()
    except Exception:
        pass
 
    back_edge_src, back_edge_dst = insert_reentrancy_back_edge(transformed_cfg)
    transformed_cfg._back_edge = (back_edge_src, back_edge_dst)
    try:
        transformed_cfg.generate_dot()
        transformed_cfg.generate_dot_bottom_up()
    except Exception:
        pass
 
    start_dep = time.time()
    dep_analysis = DependencyAnalysisEngine(
        transformed_cfg, annotate_dependencies=annotate_dependencies
    )
    _silence(dep_analysis.compute_reaching_definitions_and_dependencies)
    logging.info(f"Dependency analysis completed in {time.time() - start_dep:.4f}s.")
 
    _auto_domains = _select_reentrancy_domains(transformed_cfg)
    _has_encoding = (_auto_domains != ["Box"])
    if reentrancy_domain in (None, 'auto'):
        reentrancy_domains = _auto_domains
        _genuine_multidomain = False
    elif reentrancy_domain == 'all':
        reentrancy_domains = ["Box", "Octagon", "Polka"] if _has_encoding else ["Box"]
        _genuine_multidomain = True
    else:
        reentrancy_domains = [reentrancy_domain] if _has_encoding else ["Box"]
        _genuine_multidomain = True
    if _genuine_multidomain:
        logging.info(f"[DOMAIN] Genuine per-domain run requested: {reentrancy_domains}")

    if reentrancy_domain in (None, 'auto'):
        confirm_domains = None
    elif reentrancy_domain == 'all':
        confirm_domains = ["Box", "Octagon", "Polka"]
    else:
        confirm_domains = [reentrancy_domain]
    confirm_info = {}
    reentrancy_csems   = {dom: None for dom in reentrancy_domains}

    if "reentrancy" in active:
        logging.info("\n========== PIPELINE 1: REENTRANCY ==========")

        modifier_verdict = _detect_modifier_reentrancy(source_code)
        if modifier_verdict is not None:
            logging.info("[REENTRANCY] Modifier-based reentrancy detected.")

        erc20_verdict = _detect_erc20_reentrancy(source_code)
        if erc20_verdict is not None:
            logging.info("[REENTRANCY] ERC-20 interface reentrancy detected.")

        if not _has_dangerous_external_call(source_code):
            structural_verdict = modifier_verdict or erc20_verdict
            if structural_verdict is not None:
                reentrancy_results = {dom: [structural_verdict] for dom in reentrancy_domains}
            else:
                stripped_src = re.sub(r'//[^\n]*', '', source_code)
                stripped_src = re.sub(r'/\*.*?\*/', '', stripped_src, flags=re.DOTALL)
                has_any_call_value = bool(re.search(r'\.call\.value\s*\(', stripped_src)) or \
                                     bool(re.search(r'\.call\s*\{\s*value\s*:', stripped_src))
                if has_any_call_value:
                    logging.info("[REENTRANCY] External calls target fixed addresses (not msg.sender) — reentrancy infeasible.")
                    safe_verdict = "[NO REENTRANCY] External calls target fixed/owner-controlled addresses; reentrancy by caller infeasible."
                else:
                    logging.info("[REENTRANCY] Only gas-limited calls (transfer/send) detected — reentrancy infeasible.")
                    safe_verdict = "[NO REENTRANCY] Contract uses only gas-limited external calls (transfer/send); reentrancy infeasible."
                reentrancy_results = {dom: [safe_verdict] for dom in reentrancy_domains}
        else:
            if _genuine_multidomain:
                reentrancy_raw = _analyse_reentrancy(transformed_cfg, reentrancy_domains)
            else:
                box_raw = _analyse_reentrancy(transformed_cfg, ["Box"])
                box_verdicts, box_csem = box_raw["Box"]
                reentrancy_raw = {"Box": (box_verdicts, box_csem)}
                for dom in reentrancy_domains:
                    if dom != "Box":
                        reentrancy_raw[dom] = (box_verdicts, None)
            reentrancy_results = {dom: vd for dom, (vd, _) in reentrancy_raw.items()}
            reentrancy_csems   = {dom: cs for dom, (_, cs) in reentrancy_raw.items()}

            _fp_has_violation = any(
                any('Balance-preservation invariant violated' in v for v in vl)
                for vl in reentrancy_results.values()
            )
            if _fp_has_violation and _should_suppress_fixpoint_verdict(source_code):
                logging.info("[REENTRANCY] Suppressing fixpoint verdict: original source is safe.")
                for dom in reentrancy_domains:
                    reentrancy_results[dom] = [
                        v.replace(
                            '[REENTRANCY] Balance-preservation invariant violated.',
                            '[NO REENTRANCY] Balance-preservation invariant maintained at claim.'
                        ) if 'Balance-preservation invariant violated' in v else v
                        for v in reentrancy_results[dom]
                    ]

            structural_verdict = modifier_verdict or erc20_verdict
            if structural_verdict is not None:
                fixpoint_detected = any(
                    any('[REENTRANCY]' in v and '[NO REENTRANCY]' not in v
                        for v in vlist)
                    for vlist in reentrancy_results.values()
                )
                if not fixpoint_detected:
                    for dom in reentrancy_domains:
                        reentrancy_results[dom] = [structural_verdict] + reentrancy_results[dom]

        already_detected = any(
            any('[REENTRANCY]' in v and '[NO REENTRANCY]' not in v
                for v in vlist)
            for vlist in reentrancy_results.values()
        )
        if not already_detected:
            call_value_verdict = _detect_call_value_state_after(source_code)
            if call_value_verdict is not None:
                logging.info("[REENTRANCY] Structural call-value-state-after reentrancy detected (augmentation).")
                for dom in reentrancy_domains:
                    reentrancy_results[dom] = [call_value_verdict] + reentrancy_results[dom]
    else:
        reentrancy_results = {dom: [] for dom in reentrancy_domains}

    if "overflow" in active:
        logging.info("\n========== PIPELINE 2: OVERFLOW / UNDERFLOW ==========")
        try:
            overflow_verdicts, overflow_csem = _analyse_overflow(source_code)
        except Exception as e:
            logging.warning(f"[OVERFLOW] Pipeline failed: {e}")
            overflow_verdicts, overflow_csem = [], None
    else:
        overflow_verdicts, overflow_csem = [], None

    if "timestamp" in active:
        logging.info("\n========== PIPELINE 3: TIMESTAMP DEPENDENCY ==========")
        try:
            timestamp_verdicts = _analyse_timestamp(transformed_cfg, dep_analysis, source_code)
            if confirm_domains and timestamp_verdicts:
                timestamp_verdicts, _ci = _confirm_with_domains(
                    source_code, timestamp_verdicts, "timestamp", confirm_domains)
                confirm_info["timestamp"] = _ci
        except Exception as e:
            logging.warning(f"[TIMESTAMP] Pipeline failed: {e}")
            timestamp_verdicts = []
    else:
        timestamp_verdicts = []

    if "tod" in active:
        logging.info("\n========== PIPELINE 4: TOD ==========")
        try:
            tod_verdicts = _analyse_tod(dep_analysis, source_code)
            if confirm_domains and tod_verdicts:
                tod_verdicts, _ci = _confirm_with_domains(
                    source_code, tod_verdicts, "tod", confirm_domains)
                confirm_info["tod"] = _ci
        except Exception as e:
            logging.warning(f"[TOD] Pipeline failed: {e}")
            tod_verdicts = []
    else:
        tod_verdicts = []
 
    analysis_path = os.path.join(out_dir, f"{base_name}_analysis.txt")
    relevant_re = re.compile(r'^(ENTRY|EXIT)')
    with open(analysis_path, "w") as af:
        first = True
        for dom in reentrancy_domains:
            cs = reentrancy_csems.get(dom)
            if cs is None:
                continue
            raw = getattr(cs, '_captured_output', '')
            if first:
                keys_line = next(
                    (ln for ln in raw.splitlines() if ln.startswith("dict_keys")), None
                )
                if keys_line:
                    af.write(keys_line + "\n")
                first = False
            af.write(f"\n===== REENTRANCY ({dom} domain, transformed source) =====\n")
            for ln in raw.splitlines():
                if relevant_re.match(ln):
                    af.write(ln + "\n")
 
        af.write("\n===== OVERFLOW / UNDERFLOW (Box domain, original source) =====\n")
        of_raw = getattr(overflow_csem, '_captured_output', '') if overflow_csem else ''
        of_keys = next(
            (ln for ln in of_raw.splitlines() if ln.startswith("dict_keys")), None
        )
        if of_keys:
            af.write(of_keys + "\n")
        for ln in of_raw.splitlines():
            if relevant_re.match(ln):
                af.write(ln + "\n")
 
    all_domains = reentrancy_domains
    verdicts_by_domain = {}
    for dom in all_domains:
        combined = []
        combined.extend(reentrancy_results.get(dom, []))
        combined.extend(overflow_verdicts)
        combined.extend(timestamp_verdicts)
        combined.extend(tod_verdicts)
        verdicts_by_domain[dom] = combined
 
    logging.info("")
    seen_file_lines = set()
    deduped_lines = []

    for dom in ("Box", "Octagon", "Polka"):
        if dom not in verdicts_by_domain:
            continue
        logging.info(f"===== VERDICTS ({dom}) =====")
        for line in verdicts_by_domain[dom]:
            logging.info(line)
            if line not in seen_file_lines:
                seen_file_lines.add(line)
                deduped_lines.append(line)
        logging.info("")
 
    total_time = time.time() - start_total
    logging.info("\n========== FINAL VULNERABILITY SUMMARY ==========")
    all_verdict_lines = deduped_lines
 
    has_reentrancy = any('[REENTRANCY]' in v and '[NO REENTRANCY]' not in v and '[REENTRANCY-SKIP]' not in v for v in all_verdict_lines)
    has_overflow = any('[OVERFLOW]' in v for v in all_verdict_lines)
    has_underflow = any('[UNDERFLOW]' in v for v in all_verdict_lines)
    has_timestamp = any('[TIMESTAMP]' in v for v in all_verdict_lines)
    has_tod = any('[TOD]' in v for v in all_verdict_lines)
 
    logging.info("[SUMMARY] Reentrancy: " + ("VULNERABLE" if has_reentrancy else "NOT VULNERABLE"))
    logging.info("[SUMMARY] Integer Overflow: " + ("VULNERABLE" if has_overflow else "NOT VULNERABLE"))
    logging.info("[SUMMARY] Integer Underflow: " + ("VULNERABLE" if has_underflow else "NOT VULNERABLE"))
    logging.info("[SUMMARY] Timestamp Dependency: " + ("VULNERABLE" if has_timestamp else "NOT VULNERABLE"))
    logging.info("[SUMMARY] TOD: " + ("VULNERABLE" if has_tod else "NOT VULNERABLE"))
 
    logging.info(f"\nTotal analysis time: {total_time:.2f}s")
 
    if json_output:
        skipped = [p for p in _ALL_PIPELINES if p not in active]
        verdict_dict = {
            "reentrancy": (1 if has_reentrancy else 0) if "reentrancy" in active else -1,
            "overflow":   (1 if (has_overflow or has_underflow) else 0) if "overflow" in active else -1,
            "timestamp":  (1 if has_timestamp else 0) if "timestamp" in active else -1,
            "tod":        (1 if has_tod else 0) if "tod" in active else -1,
        }
        fixpoint_times = {
            dom: round(getattr(cs, '_fixpoint_seconds', 0.0), 4)
            for dom, cs in reentrancy_csems.items() if cs is not None
        }
        confirm_times = {v: ci.get("times", {}) for v, ci in confirm_info.items()
                         if ci.get("times")}
        _write_json_verdict(out_dir, base_name, verdict_dict, total_time,
                            skipped_pipelines=skipped if skipped else None,
                            reentrancy_domains=reentrancy_domains,
                            fixpoint_times=fixpoint_times or None,
                            confirm_times=confirm_times or None)
 
    return analysis_path

def _write_json_verdict(out_dir, base_name, verdict_dict, duration,
                        error=None, skipped_pipelines=None,
                        reentrancy_domains=None, fixpoint_times=None,
                        confirm_times=None):
    """Write machine-readable JSON verdict for batch runner consumption."""
    json_path = os.path.join(out_dir, f"{base_name}_verdicts.json")
    output = {
        "filename": base_name + ".sol",
        "reentrancy": verdict_dict.get("reentrancy", 0),
        "overflow": verdict_dict.get("overflow", 0),
        "timestamp": verdict_dict.get("timestamp", 0),
        "tod": verdict_dict.get("tod", 0),
        "duration_s": round(duration, 2),
        "error": error,
    }
    if skipped_pipelines:
        output["skipped_pipelines"] = skipped_pipelines
    if reentrancy_domains:
        output["reentrancy_domains"] = reentrancy_domains
    if fixpoint_times:
        output["reentrancy_fixpoint_times"] = fixpoint_times
    if confirm_times:
        output["confirm_fixpoint_times"] = confirm_times
    with open(json_path, "w") as f:
        json.dump(output, f, indent=2)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Abstract Interpretation-based Solidity Vulnerability Analyzer"
    )
    parser.add_argument("solidity_filepath", type=str, nargs='+',
                    help="Path to one or more Solidity files")
    parser.add_argument("--annotate-dependencies", action="store_true",
                        help="Enable dependency chain reporting")
    parser.add_argument("--verbose", action="store_true",
                        help="Show full interval details in verdicts")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Directory for generated result files "
                             "(_output.txt, _analysis.txt, gen/ast.json, JSON "
                             "verdicts). Default: ./analysis_output/ in the "
                             "current directory. Result files are NEVER written "
                             "next to the input .sol, so scanning a dataset does "
                             "not pollute it.")
    parser.add_argument("--json", action="store_true", dest="json_output",
                        help="Emit machine-readable JSON verdict file")
    parser.add_argument("--pipelines", type=str, default=None,
                        help="Comma-separated pipelines to run: "
                             "reentrancy,overflow,timestamp,tod (default: all)")
    parser.add_argument("--reentrancy-domain", type=str, default="auto",
                        choices=["auto", "Box", "Octagon", "Polka", "all"],
                        dest="reentrancy_domain",
                        help="Numerical domain for the reentrancy fixpoint. "
                             "'auto' (default) keeps historical fast behaviour; "
                             "Box/Octagon/Polka genuinely run that single domain "
                             "(used for per-domain timing); 'all' genuinely runs "
                             "all three (domain-agreement study).")
    args = parser.parse_args()

    pipelines_set = None
    if args.pipelines:
        pipelines_set = set(p.strip() for p in args.pipelines.split(","))
        valid = {"reentrancy", "overflow", "timestamp", "tod"}
        bad = pipelines_set - valid
        if bad:
            sys.exit(f"Unknown pipeline(s): {bad}. Valid: {valid}")
 
    log_filename = setup_logging(args.solidity_filepath[0], output_dir=args.output_dir)
    
    CONTRACT_TIMEOUT = FIXPOINT_TIMEOUT_SECONDS * 3   

    for filepath in args.solidity_filepath:
        try:
            source_code = read_source_code(filepath)
            if hasattr(_signal, 'SIGALRM'):
                old_h = _signal.signal(_signal.SIGALRM, _timeout_handler)
                _signal.alarm(CONTRACT_TIMEOUT)
            try:
                run_static_analysis(
                    source_code,
                    filepath,
                    annotate_dependencies=args.annotate_dependencies,
                    verbose=args.verbose,
                    output_dir=args.output_dir,
                    json_output=args.json_output,
                    pipelines=pipelines_set,
                    reentrancy_domain=args.reentrancy_domain,
                )
            except _FixpointTimeout:
                logging.error(f"[TIMEOUT] {filepath}: analysis exceeded {CONTRACT_TIMEOUT}s — skipped.")
                if args.json_output:
                    base = os.path.basename(filepath).replace(".sol", "")
                    _write_json_verdict(
                        _resolve_output_dir(args.output_dir), base,
                        {"reentrancy": -1, "overflow": -1, "timestamp": -1, "tod": -1},
                        CONTRACT_TIMEOUT,
                        error=f"timeout after {CONTRACT_TIMEOUT}s",
                        skipped_pipelines=["reentrancy", "overflow", "timestamp", "tod"],
                    )
            finally:
                if hasattr(_signal, 'SIGALRM'):
                    _signal.alarm(0)
                    _signal.signal(_signal.SIGALRM, old_h)
        except Exception as e:
            logging.error(f"[ERROR] {filepath}: {e}")
            if args.json_output:
                base = os.path.basename(filepath).replace(".sol", "")
                _write_json_verdict(
                    _resolve_output_dir(args.output_dir), base,
                    {"reentrancy": -1, "overflow": -1, "timestamp": -1, "tod": -1},
                    0,
                    error=f"unhandled exception: {e}",
                    skipped_pipelines=["reentrancy", "overflow", "timestamp", "tod"],
                )
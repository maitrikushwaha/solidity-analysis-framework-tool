from typing import Set, Dict, Tuple, List
from collections import defaultdict
from itertools import combinations
from collections import deque
from control_flow_graph import ControlFlowGraph
from control_flow_graph.node_processor import nodes

from static_analysis.dataflow_analysis.avl_expr.expr_builder import expr_builder
from control_flow_graph.node_processor.nodes import (
    VariableDeclaration,
    VariableDeclarationStatement,
    IfStatement,
    ExpressionStatement,
    BinaryOperation,
    Identifier,
    Assignment,
    FunctionCall,
    Return,
    WhileStatement,
    UnaryOperation,
    FunctionDefinition,
)

output_file_path = "dependency_analysis_output.txt"

class DependencyAnalysisEngine:
    """Dependency Analysis Engine: Computes dataflow (reaching definitions), control dependencies,"""

    def __init__(self, cfg: ControlFlowGraph, annotate_dependencies=False):
        """Initialize the analysis with the control flow graph (CFG)."""
        self.cfg = cfg
        self.variable_dependencies: Dict[str, Set[Tuple[str, str]]] = {}
        self.statement_dependencies: Dict[str, Set[Tuple[str, str]]] = {}
        self.latest_definitions: Dict[str, str] = {}
        self.control_dependencies: Dict[str, str] = {}
        self.annotate_dependencies = annotate_dependencies
        self.timestamp_vars = {"blocktimestamp", "block.timestamp", "now"}
        self.timestamp_influence = defaultdict(set)
        self.tod_entries = []
        self.cfg.state_variables = set(
            node.name for node_id, node in self.cfg.cfg_metadata.node_table.items()
            if isinstance(node, VariableDeclaration) and getattr(node, "storage_location", "default") != "memory"
        )
        self.node_used_defined = {}
        self.variable_func_usage = defaultdict(lambda: {'used': set(), 'defined': set()})
        self.node_to_function: Dict[str, str] = {}
        self.function_nodes: Dict[str, str] = {}
        
        for node_id in self.cfg.cfg_metadata.node_table:
            node = self.cfg.cfg_metadata.get_node(node_id)
            if isinstance(node, FunctionCall) or isinstance(node, ExpressionStatement):
                expr = getattr(node, "expression", node)
                if hasattr(expr, "memberName") and expr.memberName in {"balance", "timestamp", "number"}:
                    if hasattr(expr, "expression") and hasattr(expr.expression, "name"):
                        base = expr.expression.name
                        if base == "address" and expr.memberName == "balance":
                            self.cfg.state_variables.add("CONTRACT_BALANCE")
                        elif base == "block" and expr.memberName in {"timestamp", "number"}:
                            self.cfg.state_variables.add(f"BLOCK_{expr.memberName.upper()}")
                elif hasattr(expr, "name") and expr.name in {"msg.value", "tx.origin", "tx.gasprice"}:
                    self.cfg.state_variables.add(expr.name)

    def compute_reaching_definitions_and_dependencies(self):
        """Perform the reaching definitions analysis with variable dependency tracking."""
        with open(output_file_path, "w") as output_file:

            entry = {node_id: set() for node_id in self.cfg.cfg_metadata.node_table.keys()}
            exit_ = {node_id: set() for node_id in self.cfg.cfg_metadata.node_table.keys()}
            
            global_definitions = {
                (node.name, node_id)
                for node_id, node in self.cfg.cfg_metadata.node_table.items()
                if isinstance(node, VariableDeclaration)
            }

            include_reaching_nodes = {
                VariableDeclaration,
                VariableDeclarationStatement,
                IfStatement,
                ExpressionStatement,
                Assignment,
                BinaryOperation,
                Return,
                WhileStatement,
                UnaryOperation,
                FunctionDefinition,
            }
            
            iteration = 1
            while True:
                output_file.write(f"\nIteration {iteration}\n")
                output_file.write(f"{'Node ID':<25} {'Used Variables':<30} {'Defined Variables':<25}\n")
                output_file.write("-" * 80 + "\n")

                changes = False

                for node_id in list(self.cfg.cfg_metadata.node_table.keys()):
                    node = self.cfg.cfg_metadata.get_node(node_id)

                    if node_id not in entry:
                        entry[node_id] = set()
                    if node_id not in exit_:
                        exit_[node_id] = set()

                    if hasattr(node, 'prev_nodes') and node.prev_nodes:
                        for pred_id in node.prev_nodes:
                            entry[node_id].update(exit_.get(pred_id, set()))

                    entry[node_id].update(global_definitions)

                    gen_set = set()
                    kill_set = set()
                    used_vars = set()
                    defined_vars = set()
                    reaching_from = {}
                    
                    if isinstance(node, VariableDeclaration):
                        try:
                            defined_vars.add(node.name)
                            gen_set = {(node.name, node_id)}
                            self.latest_definitions[node.name] = node_id

                            value = getattr(node, "value", None)
                            if value and isinstance(value, dict) and value.get("nodeType") == "Identifier":
                                used_vars.add(value["name"])

                            for var in used_vars:
                                latest_def = self.latest_definitions.get(var, None)
                                if latest_def:
                                    reaching_from[var] = latest_def
                                    if var not in self.variable_dependencies:
                                        self.variable_dependencies[var] = set()
                                    self.variable_dependencies[var].add((node_id, latest_def))

                                    output_file.write(f"DATA DEPENDENCY: {node.name} is data dependent on {var}\n")
                        
                            for var in defined_vars:
                                latest_def = reaching_from.get(var)
                                if latest_def and latest_def != node_id:
                                    if var not in self.variable_dependencies:
                                        self.variable_dependencies[var] = set()
                                    self.variable_dependencies[var].add((node_id, latest_def))

                        except Exception as e:
                            output_file.write(f"[WARN] Failed to process VariableDeclaration {node_id}: {e}\n")
                    
                    elif isinstance(node, FunctionDefinition):
                        func_name = node.name
                        self.function_nodes[node_id] = func_name
                        output_file.write(f"DEBUG: FunctionDefinition - names: {func_name}, visibility: {node.visibility}, modifiers: {node.modifiers}\n")
                    
                    elif isinstance(node, VariableDeclarationStatement):
                        try:
                            expr = expr_builder(node)
                            used_vars |= expr.right_symbols if expr else set()
                            defined_vars |= expr.left_symbols if expr else set()
                            gen_set = {(var, node_id) for var in defined_vars}

                            for var in defined_vars:
                                self.latest_definitions[var] = node_id
                            
                            for var in used_vars:
                                latest_def = self.latest_definitions.get(var, None)
                                if latest_def:
                                    reaching_from[var] = latest_def
                                    if var not in self.variable_dependencies:
                                        self.variable_dependencies[var] = set()
                                    self.variable_dependencies[var].add((node_id, latest_def))

                                    for lhs_var in defined_vars:
                                        output_file.write(f"DATA DEPENDENCY: {lhs_var} is data dependent on {var}\n")
                        
                                        if node_id not in self.statement_dependencies:
                                            self.statement_dependencies[node_id] = set()
                                        self.statement_dependencies[node_id].add((latest_def, var))
                        
                        except Exception as e:
                            output_file.write(f"Error processing node {node_id}: {e}\n")
                            continue

                    elif isinstance(node, (IfStatement, ExpressionStatement, BinaryOperation, Assignment, FunctionCall, Assignment, Return, WhileStatement)):
                        try:
                            if isinstance(node, IfStatement):
                                condition_vars = self.extract_variables_from_expression(node.condition)
                                used_vars |= condition_vars
                                
                                for var in condition_vars:
                                    latest_def = self.latest_definitions.get(var, None)
                                    if latest_def:
                                        if node_id not in self.statement_dependencies:
                                            self.statement_dependencies[node_id] = set()
                                        self.statement_dependencies[node_id].add((latest_def, var))
                                        output_file.write(f"STATEMENT DEPENDENCY: Node '{node_id}' is data dependent on Node '{latest_def}' for variable '{var}'\n")
                                true_next = getattr(node, "true_body_next", None)
                                false_next = getattr(node, "false_body_next", None)
                                join_node = getattr(node, "join_node", None)

                                for branch in [true_next, false_next]:
                                    if branch:
                                        to_visit = [branch]
                                        visited = set()
                                        while to_visit:
                                            current = to_visit.pop()
                                            if current in visited or current == join_node:
                                                continue
                                            visited.add(current)

                                            output_file.write(
                                                f"CONTROL DEPENDENCY: Node '{current}' is control dependent on '{node_id}'\n"
                                            )
                                            self.control_dependencies[current] = node_id
                                            if current == join_node:
                                                continue

                                            next_nodes = self.cfg.cfg_metadata.get_node(current).next_nodes
                                            to_visit.extend(next_nodes.keys())
                               
                            else:
                                expr = expr_builder(node)
                                used_vars |= expr.right_symbols if expr else set()
                                defined_vars |= expr.left_symbols if expr else set()

                                for sym in list(used_vars):
                                    if "address(this).balance" in sym or "this.balance" in sym:
                                        used_vars.add("CONTRACT_BALANCE")

                                if not used_vars and hasattr(node, "next_nodes"):
                                    for next_id in node.next_nodes:
                                        child_node = self.cfg.cfg_metadata.get_node(next_id)
                                        used_vars |= self.extract_variables_from_expression(child_node)

                                function_arguments = self.extract_function_arguments(node)
                                used_vars |= function_arguments

                                for var in used_vars:
                                    latest_def = self.latest_definitions.get(var, None)
                                    if latest_def:
                                        reaching_from[var] = latest_def
                                        if var not in self.variable_dependencies:
                                            self.variable_dependencies[var] = set()
                                        self.variable_dependencies[var].add((node_id, latest_def))

                                for var in defined_vars:
                                    prev_def = self.latest_definitions.get(var)
                                    if prev_def and prev_def != node_id:
                                        if var not in self.variable_dependencies:
                                            self.variable_dependencies[var] = set()
                                        self.variable_dependencies[var].add((node_id, prev_def))

                                for var in defined_vars:
                                    self.latest_definitions[var] = node_id

                                gen_set = {(var, node_id) for var in defined_vars}

                                for var in used_vars:
                                    latest_def = self.latest_definitions.get(var)
                                    if latest_def:
                                        for lhs_var in defined_vars:
                                            output_file.write(f"DATA DEPENDENCY: {lhs_var} is data dependent on {var}\n")
                                            if node_id not in self.statement_dependencies:
                                                self.statement_dependencies[node_id] = set()
                                            self.statement_dependencies[node_id].add((latest_def, var))

                            if isinstance(node, FunctionCall):
                                function_args = self.extract_function_arguments(node)
                                for arg in function_args:
                                    latest_def = self.latest_definitions.get(arg, None)
                                    if latest_def:
                                        if node_id not in self.statement_dependencies:
                                            self.statement_dependencies[node_id] = set()
                                        self.statement_dependencies[node_id].add((latest_def, arg))
                                        output_file.write(
                                            f"STATEMENT DEPENDENCY: Node '{node_id}' is data dependent on Node '{latest_def}' for variable '{arg}'\n"
                                        )
                            if isinstance(node, Return):
                                return_expr = getattr(node, "return_expression", None)

                                if return_expr:
                                    try:
                                        node_type = return_expr.get("nodeType")
                                        constructor = getattr(nodes, node_type)

                                        expr_node = self.cfg.cfg_metadata.get_node_by_ast_id(return_expr['id']) \
                                            if 'id' in return_expr else None

                                        if expr_node is None:
                                            expr_node = constructor(return_expr, None, None, None, self.cfg.cfg_metadata)

                                        used_vars |= self.extract_variables_from_expression(expr_node)
                                        for var in used_vars:
                                            latest_def = self.latest_definitions.get(var, None)
                                            if latest_def:
                                                if node_id not in self.statement_dependencies:
                                                    self.statement_dependencies[node_id] = set()
                                                self.statement_dependencies[node_id].add((latest_def, var))
                                                output_file.write(
                                                    f"STATEMENT DEPENDENCY: Node '{node_id}' is data dependent on Node '{latest_def}' for variable '{var}'\n"
                                                )

                                    except Exception as e:
                                        output_file.write(f"Error processing node {node_id}: {e}\n")

                            if isinstance(node, WhileStatement):
                                condition_vars = self.extract_variables_from_expression(node.condition)
                                used_vars |= condition_vars

                                for var in condition_vars:
                                    latest_def = self.latest_definitions.get(var, None)
                                    if latest_def:
                                        if node_id not in self.statement_dependencies:
                                            self.statement_dependencies[node_id] = set()
                                        self.statement_dependencies[node_id].add((latest_def, var))
                                        output_file.write(
                                            f"STATEMENT DEPENDENCY: Node '{node_id}' is data dependent on Node '{latest_def}' for variable '{var}'\n"
                                        )
                                
                                body_next = getattr(node, "body_next", None)
                                join_node = getattr(node, "join_node", None)

                                if body_next:
                                    to_visit = [body_next]
                                    visited = set()
                                    while to_visit:
                                        current = to_visit.pop()
                                        if current in visited or current == join_node:
                                            continue
                                        visited.add(current)

                                        output_file.write(
                                            f"CONTROL DEPENDENCY: Node '{current}' is control dependent on '{node_id}'\n"
                                        )
                                        self.control_dependencies[current] = node_id

                                        next_nodes = self.cfg.cfg_metadata.get_node(current).next_nodes
                                        to_visit.extend(next_nodes.keys())
                        
                        except Exception as e:
                            output_file.write(f"Error processing node {node_id}: {e}\n")
                            continue

                    for var in used_vars:
                        if var in self.timestamp_vars:
                            self.timestamp_influence[node_id].add(var)
                    
                    kill_set = {
                        (var, other_node_id)
                        for var, _ in gen_set
                        for other_node_id in self.cfg.cfg_metadata.node_table.keys()
                        if other_node_id != node_id
                    }

                    new_exit = (entry[node_id] - kill_set) | gen_set
                    if new_exit != exit_[node_id]:
                        changes = True
                        exit_[node_id] = new_exit

                    filtered_exit_set = exit_[node_id] if type(node) in include_reaching_nodes else set()

                    used_vars_with_reaching = ", ".join(
                        f"{var} (from {reaching_from[var]})" if var in reaching_from else var
                        for var in used_vars
                    )
                    used_vars_str = used_vars_with_reaching if used_vars else "None"
                    defined_vars_str = ', '.join(defined_vars) if defined_vars else "None"
                    def get_enclosing_function(nid):
                        if nid in self.function_nodes:
                            return self.function_nodes[nid]
                        visited = set()
                        queue = [nid]
                        while queue:
                            current = queue.pop(0)
                            if current in self.function_nodes:
                                return self.function_nodes[current]
                            visited.add(current)
                            for pred in self.cfg.cfg_metadata.get_node(current).prev_nodes:
                                if pred not in visited:
                                    queue.append(pred)
                        return "Unknown"
                    
                    func_ctx = get_enclosing_function(node_id)
                    self.node_to_function[node_id] = func_ctx
                    for var in used_vars:
                        self.variable_func_usage[var]['used'].add(node_id)
                    for var in defined_vars:
                        self.variable_func_usage[var]['defined'].add(node_id)
                    output_file.write(f"{node_id:<25} {used_vars_str:<50} {defined_vars_str:<35} \n")
                    self.node_used_defined[node_id] = (used_vars.copy(), defined_vars.copy())

                output_file.write("-" * 150 + "\n")

                if not changes:
                    output_file.write("\nFixed point reached. Reaching definitions have converged.\n")
                    break

                iteration += 1

                if iteration == 2:
                    influenced_by_state = set(self.cfg.state_variables)
                    queue = deque(influenced_by_state)

                    while queue:
                        state_var = queue.popleft()
                        for var, deps in self.variable_dependencies.items():
                            for use_node, def_node in deps:
                                if state_var in self.node_used_defined.get(def_node, ([], []))[0]:
                                    if var not in self.cfg.state_variables:
                                        self.cfg.state_variables.add(var)
                                        queue.append(var)

            self.print_statement_dependencies(output_file)
            self.print_reaching_definition(output_file)

            output_file.write("\nDependency Chains (computed inline):\n")

            var_use_map = defaultdict(lambda: defaultdict(set))
            all_defs = defaultdict(set)

            def sort_key(node_id):
                try:
                    return int(node_id.split('_')[-1])
                except:
                    return float('inf')

            def is_state_var(varname):
                return 'state' if varname in getattr(self.cfg, 'state_variables', set()) else 'local'

            for var, links in self.variable_dependencies.items():
                for use_node, def_node in links:
                    var_use_map[var][def_node].add(use_node)
                    all_defs[var].add(def_node)

            visited = set()

            def dfs(var, def_node, depth=0):
                indent = "  " * (depth + 1)
                uses = sorted(var_use_map[var].get(def_node, []), key=sort_key)

                for use in uses:
                    if (def_node, use) in visited:
                        continue
                    visited.add((def_node, use))

                    used_vars, defined_vars = self.node_used_defined.get(use, (set(), set()))
                    is_def = var in defined_vars

                    if is_def:
                        output_file.write(f"{indent}→ defined in {use} ({self.get_function_context(use)})\n")
                        dfs(var, use, depth + 1)
                    else:
                        output_file.write(f"{indent}→ used in {use} ({self.get_function_context(use)}) [redef=False]\n")

            for var in sorted(var_use_map.keys()):
                defs = sorted(all_defs[var], key=sort_key)
                redefs = {use for d in defs for use in var_use_map[var][d] if use in defs}
                root_defs = [d for d in defs if d not in redefs]
                if not root_defs:
                    root_defs = [defs[0]]

                header_root = next((d for d in root_defs if d.startswith("VariableDeclaration_")), root_defs[0])

                if is_state_var(var):
                    output_file.write(f"{var} [state] (defined in {header_root})\n")
                else:
                    output_file.write(f"{var} [local] (defined in {header_root} - {self.get_function_context(header_root)})\n")

                for root in sorted(root_defs, key=sort_key):
                    dfs(var, root)                          

            output_file.write("\n[ TOD Summary - Compact CLI Format]\n")

            tod_entries = []

            def is_likely_mapping(varname):
                return varname in { "commit", "balanceOf", "lockTime", "userBalances"}

            def looks_like_arithmetic_only(var, node_id):
                node = self.cfg.cfg_metadata.get_node(node_id)

                if isinstance(node, (VariableDeclarationStatement, Assignment)):
                    return True

                if isinstance(node, FunctionCall):
                    fname = getattr(node, "function_name", "")
                    if fname and fname.lower() in {"require", "assert"}:
                        return not is_control_or_transfer_sensitive(node, var=var)

                if isinstance(node, ExpressionStatement):
                    expr = getattr(node, "expression", None)

                    if isinstance(expr, BinaryOperation) or isinstance(expr, Assignment):
                        return True
                    
                    if isinstance(expr, FunctionCall):
                        fname = getattr(expr, "function_name", "")
                        if fname and fname.lower() in {"require", "assert"}:
                            return not is_control_or_transfer_sensitive(node, var=var)
                return False
  
            def is_control_or_transfer_sensitive(node, var=None):
                """Returns True only if a variable appears in a require/assert that guards a sensitive transfer."""
                sensitive_keywords = {"transfer", "call", "send", "delegatecall"}

                output_file.write(f"[DEBUG is_control_or_transfer_sensitive] Checking node: {getattr(node, 'cfg_id', node)}\n")

                def contains_call_value(expr):
                    """Recursively detect .call.value(...) or similar sensitive member calls in nested expressions."""
                    if not expr:
                        return False

                    visited = set()
                    stack = [expr]

                    while stack:
                        current = stack.pop()
                        if id(current) in visited:
                            continue
                        visited.add(id(current))

                        output_file.write(f"[DEBUG DUMP] Node={type(current).__name__} | content={str(current)}\n")

                        member = getattr(current, "memberName", None) or current.__dict__.get("memberName", "")
                        if member:
                            output_file.write(f"[DEBUG MEMBER] memberName={member}\n")
                        if member == "value":
                            output_file.write("[MATCH] Detected .call.value(...) inside MemberAccess chain\n")
                            return True

                        for attr in dir(current):
                            if attr.startswith("_") or attr in {"cfg_metadata", "prev_nodes", "next_nodes", "basic_block_type", "node_type", "cfg_id"}:
                                continue
                            child = getattr(current, attr)
                            if isinstance(child, list):
                                stack.extend(c for c in child if hasattr(c, "__dict__"))
                            elif hasattr(child, "__dict__"):
                                stack.append(child)

                    return False

                def check_expr(expr):
                    if not expr:
                        return False
                    output_file.write(f"[DEBUG] Expression: {type(expr).__name__}, content: {expr}\n")

                    if isinstance(expr, FunctionCall):
                        fname = getattr(expr, "function_name", "")
                        if fname and fname.lower() in {"require", "assert"}:
                            to_visit = list(node.next_nodes.keys())
                            visited = set()

                            if not to_visit:
                                output_file.write(f"[DEBUG] require/assert has no successors — skipping TOD\n")
                                return False
                            
                            while to_visit:
                                nid = to_visit.pop()
                                if nid in visited:
                                    continue
                                visited.add(nid)
                                next_node = node.cfg_metadata.get_node(nid)
                                output_file.write(f"[DEBUG] Checking successor node: {nid} → {next_node}\n")

                                if isinstance(next_node, ExpressionStatement):
                                    inner = getattr(next_node, "expression", None)
                                    if inner and isinstance(inner, FunctionCall):
                                        inner_fname = getattr(inner, "function_name", "")
                                        if any(kw in inner_fname.lower() for kw in sensitive_keywords):
                                            output_file.write(f"[MATCH] Sensitive transfer found after require/assert\n")
                                            return True
                                
                                to_visit.extend(next_node.next_nodes.keys())
                            output_file.write(f"[DEBUG] No sensitive transfer found in successors of require/assert → benign\n")
                            return False

                        if fname and any(key in fname.lower() for key in sensitive_keywords):
                            output_file.write(f"[MATCH] Direct sensitive call: {fname}\n")
                            return True
                        
                        if contains_call_value(expr):
                            return True

                    return False

                if isinstance(node, ExpressionStatement):
                    expr = getattr(node, "expression", None)
                    return check_expr(expr)
                if isinstance(node, FunctionCall):
                    return check_expr(node)
                expr = getattr(node, "expression", None)
                return check_expr(expr) if expr else False

            def is_safe_variable(var):
                safe_keywords = {"if", "require", "assert", "transfer", "call"}
                for node_id, (used, _) in self.node_used_defined.items():
                    if var in used:
                        node = self.cfg.cfg_metadata.get_node(node_id)
                        if isinstance(node, FunctionCall) or isinstance(node, IfStatement):
                            return False
                return True

            def is_misaligned_arithmetic_tod(var, def_node, use_node):
                return looks_like_arithmetic_only(var, use_node) and looks_like_arithmetic_only(var, def_node)

            output_file.write("[DEBUG] Starting NEW intra-function TOD detection loop\n")
            for var in self.cfg.state_variables:
                output_file.write(f"[DEBUG] Analyzing state variable '{var}' for intra-function TOD\n")
                for use_node in self.node_used_defined:
                    used_vars, _ = self.node_used_defined[use_node]

                    if not used_vars and isinstance(self.cfg.cfg_metadata.get_node(use_node), FunctionCall):
                        for nid, (uv, _) in self.node_used_defined.items():
                            if use_node in self.cfg.cfg_metadata.get_node(nid).next_nodes:
                                used_vars = uv
                                use_node = nid
                                break

                    if var not in used_vars:
                        continue

                    use_func = self.get_function_context(use_node)
                    for def_node in self.node_used_defined:
                        _, def_vars = self.node_used_defined[def_node]
                        if var not in def_vars:
                            continue

                        def_node_obj = self.cfg.cfg_metadata.get_node(def_node)
                        if isinstance(def_node_obj, VariableDeclaration):
                            redef_found = any(
                                def_node != other_def and var in def_vars
                                for other_def, (_, def_vars) in self.node_used_defined.items()
                            )
                            if redef_found:
                                continue

                        def_func = self.get_function_context(def_node)
                        if use_func != def_func or use_func == "Unknown":
                            continue

                        try:
                            output_file.write(f"[DEBUG-TOD-CHECK] use_node={use_node}, def_node={def_node}, func={use_func}\n")
                            use_node_obj = self.cfg.cfg_metadata.get_node(use_node)
                            if is_control_or_transfer_sensitive(use_node_obj, var=var):
                                output_file.write(f"[DEBUG-TOD-CHECK] use_node={use_node}, def_node={def_node}, func={use_func}\n")
                                entry = f"{var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func}) [INTRA-TOD]"
                                if entry not in tod_entries:
                                    tod_entries.append(entry)
        
                        except ValueError:
                            continue

            for var, links in self.variable_dependencies.items():
                if var not in self.cfg.state_variables or is_likely_mapping(var) :
                    continue

                for use_node, def_node in links:
                    use_func = self.get_function_context(use_node)
                    def_func = self.get_function_context(def_node)

                    used_vars, defined_vars = self.node_used_defined.get(use_node, (set(), set()))
                    is_use = var in used_vars and var not in defined_vars

                    _, def_vars = self.node_used_defined.get(def_node, (set(), set()))
                    is_def = var in def_vars and not def_node.startswith("VariableDeclaration_")

                    if is_use and is_def and use_func != def_func and "Unknown" not in (use_func, def_func):
                        use_node_obj = self.cfg.cfg_metadata.get_node(use_node)
                        def_node_obj = self.cfg.cfg_metadata.get_node(def_node)

                        if use_node in self.timestamp_influence:
                            output_file.write(f"[SKIP TOD] {var} usage in {use_node} skipped due to timestamp-influenced logic\n")
                            continue            
                        
                        output_file.write(f"[DEBUG TOD PATH] var={var}, def_node={def_node} ({def_func}), use_node={use_node} ({use_func})\n")

                        if use_node_obj and isinstance(use_node_obj, (ExpressionStatement, FunctionCall)):
                            node_str = str(use_node_obj).lower()
                            if (hasattr(use_node_obj, "memberName") and use_node_obj.memberName == "value") or ("call.value" in node_str):
                                if var in used_vars:
                                    output_file.write(f"[MATCH] Direct .call.value transfer based on state var '{var}' in node {use_node}\n")
                                    entry = f" {var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func})"
                                    if entry not in tod_entries:
                                        tod_entries.append(entry)
                                    continue
                        
                        if is_misaligned_arithmetic_tod(var, def_node, use_node):
                            output_file.write(f"[DEBUG] → is_misaligned_arithmetic_tod = True\n")
                            output_file.write(f"[DEBUG] → use_node_obj = {use_node_obj}\n")
                            
                            if not (is_control_or_transfer_sensitive(use_node_obj, var=var) or 
                                    is_control_or_transfer_sensitive(def_node_obj, var=var)):
                                output_file.write(f"[SKIP TOD] {var} flow skipped due to arithmetic-only and benign use/def\n")
                                continue

                        entry = f" {var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func})"
                        if entry not in tod_entries:
                            tod_entries.append(entry)

            output_file.write("\n[DEBUG] Starting cross-function TOD detection via node_used_defined\n")

            _SYNTHETIC = {'BAL', 'attacker_bal', 'credit', 'msgsender',
                          'msgvalue', 'msg.value', 'msg.sender',
                          'CONTRACT_BALANCE', 'BLOCK_TIMESTAMP', 'BLOCK_NUMBER'}

            for var in self.cfg.state_variables:
                if var in _SYNTHETIC or is_likely_mapping(var):
                    continue

                def_nodes = []
                use_nodes = []
                for nid, (uvars, dvars) in self.node_used_defined.items():
                    if var in dvars and not nid.startswith("VariableDeclaration_"):
                        def_nodes.append(nid)
                    if var in uvars and var not in dvars:
                        use_nodes.append(nid)

                if not def_nodes or not use_nodes:
                    continue

                for def_node in def_nodes:
                    def_func = self.get_function_context(def_node)
                    if def_func == "Unknown":
                        continue
                    for use_node in use_nodes:
                        use_func = self.get_function_context(use_node)
                        if use_func == "Unknown":
                            continue
                        if def_func == use_func:
                            continue

                        entry_candidate = f" {var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func})"
                        if entry_candidate in tod_entries:
                            continue

                        if use_node in self.timestamp_influence:
                            continue

                        use_node_obj = self.cfg.cfg_metadata.get_node(use_node)
                        def_node_obj = self.cfg.cfg_metadata.get_node(def_node)

                        use_sensitive = False
                        try:
                            use_sensitive = is_control_or_transfer_sensitive(
                                use_node_obj, var=var
                            )
                        except Exception:
                            pass

                        if not use_sensitive:
                            u_used, _ = self.node_used_defined.get(use_node, (set(), set()))
                            _, u_def  = self.node_used_defined.get(use_node, (set(), set()))
                            if 'BAL' in u_def and var in u_used:
                                use_sensitive = True
                                output_file.write(
                                    f"[CROSS-FUNC] {var} feeds BAL update in "
                                    f"{use_node} ({use_func})\n"
                                )

                        if use_sensitive:
                            output_file.write(
                                f"[CROSS-FUNC TOD] {var}: def={def_node} "
                                f"({def_func}), use={use_node} ({use_func})\n"
                            )
                            if entry_candidate not in tod_entries:
                                tod_entries.append(entry_candidate)

            self.tod_entries = list(tod_entries)
            if tod_entries:
                output_file.write("--------------------------------------\n")
                output_file.write("  TOD Detected\n")
                output_file.write("--------------------------------------\n")
                for entry in tod_entries:
                    output_file.write(f" -{entry}\n")
            else:
                output_file.write("--------------------------------------\n")
                output_file.write(" No transaction-ordering dependencies detected.\n")
                output_file.write("--------------------------------------\n")

    def extract_function_arguments(self, node):
            """Extracts function call arguments as used variables from both ExpressionStatements and FunctionCall nodes."""
            variables = set()

            if isinstance(node, FunctionCall):
                for arg in node.arguments:
                    if isinstance(arg, Identifier):
                        variables.add(arg.name)
                    elif isinstance(arg, BinaryOperation):
                        variables |= self.extract_variables_from_expression(arg)
                    elif hasattr(arg, "sub_expression"):
                        variables |= self.extract_variables_from_expression(arg.sub_expression)
                    else:
                        variables |= self.extract_variables_from_expression(arg)
            
            elif hasattr(node, 'expression') and hasattr(node.expression, 'is_function_call') and node.expression.is_function_call():
                for arg in node.expression.arguments:
                    if isinstance(arg, Identifier):
                        variables.add(arg.name)
                    elif isinstance(arg, BinaryOperation):
                        variables |= self.extract_variables_from_expression(arg)
                    elif hasattr(arg, "sub_expression"):
                        variables |= self.extract_variables_from_expression(arg.sub_expression)
                    else:
                        variables |= self.extract_variables_from_expression(arg)
            return variables
    
    def extract_variables_from_expression(self, expr):
        """Recursively extracts variable names from an expression, handling nested BinaryOperations."""
        variables = set()
        if expr is None:
            return variables

        if isinstance(expr, Identifier):
            variables.add(expr.name)
        
        elif isinstance(expr, BinaryOperation):
            variables |= self.extract_variables_from_expression(expr.leftExpression)
            variables |= self.extract_variables_from_expression(expr.rightExpression)
        
        elif isinstance(expr, UnaryOperation,):
            variables |= self.extract_variables_from_expression(expr.subExpression)

        elif isinstance(expr, FunctionCall):
            for arg in getattr(expr, "arguments", []):
                variables |= self.extract_variables_from_expression(arg)

        elif hasattr(expr, "leftExpression") and hasattr(expr, "rightExpression"):
            variables |= self.extract_variables_from_expression(expr.leftExpression)
            variables |= self.extract_variables_from_expression(expr.rightExpression)

        elif hasattr(expr, "subExpression"):
            variables |= self.extract_variables_from_expression(expr.subExpression)

        return variables
     
    def get_node_id_by_ast_id(self, ast_id: int) -> str:
        """Maps an AST node ID to a CFG node ID using cfg metadata."""
        for node_id, node in self.cfg.cfg_metadata.node_table.items():
            if getattr(node, 'ast_id', None) == ast_id:
                return node_id
        return None

    def print_reaching_definition(self, output_file):
        """Correctly print reaching definitions grouped by node, classifying defs vs. uses."""
        output_file.write("\nDataflow Analysis (Reaching Definitions):\n")

        node_dependencies = defaultdict(list)

        for var, dependencies in self.variable_dependencies.items():
            for use_node, def_node in dependencies:
                if self.latest_definitions.get(var) == use_node:
                    continue
                node_dependencies[use_node].append((var, def_node))

        sorted_nodes = sorted(node_dependencies.keys(), key=lambda node: int(node.split('_')[-1]) if node.split('_')[-1].isdigit() else float('inf'))

        for node_id in sorted_nodes:
            output_file.write(f"\nNode '{node_id}' uses:\n")
            for var, def_node in node_dependencies[node_id]:
                output_file.write(f"  - Variable '{var}' reached from Node '{def_node}'\n")

    def print_statement_dependencies(self, output_file):
        """Print both statement-level data dependencies and control structure dependencies."""
        output_file.write("\nStatement-Level Dependencies:\n")

        for dependent_stmt, dependencies in self.statement_dependencies.items():
            for dependency in dependencies:
                if isinstance(dependency, tuple) and len(dependency) == 2:
                    defining_stmt, variable = dependency
                    output_file.write(
                        f"STATEMENT DEPENDENCY: Node '{dependent_stmt}' is data dependent on Node '{defining_stmt}' for variable '{variable}'\n"
                    )

        output_file.write("\nControl Structure Dependencies Only:\n")

        for child_node, controlling_if in self.control_dependencies.items():
            label = child_node

            node_obj = self.cfg.cfg_metadata.get_node(child_node)
            if isinstance(node_obj, ExpressionStatement):
                for candidate_id, candidate_node in self.cfg.cfg_metadata.node_table.items():
                    if isinstance(candidate_node, FunctionCall):
                        if child_node in candidate_node.prev_nodes or candidate_node.cfg_id in self.cfg.cfg_metadata.get_node(child_node).next_nodes:
                            label = f"{child_node}({candidate_id})"
                            break

            output_file.write(
                f"{label} control depend on {controlling_if}\n"
            )

        if self.annotate_dependencies:

            output_file.write("\nTimestamp Influence Zones:\n")
            for node_id, sources in self.timestamp_influence.items():
                for src in sources:
                    output_file.write(f"→ Node {node_id} influenced by timestamp source: {src}\n")

            for node_id, deps in self.statement_dependencies.items():
                for def_node, var in deps:
                    if var in {"blocktimestamp", "block.timestamp", "now"}:
                        output_file.write(f"→ Node {node_id} influenced by timestamp source: {var}\n")

    def get_function_context(self, node_id):
        """Returns function context (FunctionDefinition_#: name) for a node ID using cached map."""
        if not hasattr(self, "_function_map"):
            self._function_map = {}
            current_func_id = None
            current_func_name = None
            try:
                with open("dependency_analysis_output.txt", "r") as f:
                    for line in f:
                        if "DEBUG: FunctionDefinition" in line:
                            parts = line.split("names:")
                            if len(parts) > 1:
                                current_func_name = parts[1].split(",")[0].strip()
                        elif line.strip().startswith("FunctionDefinition_"):
                            current_func_id = line.strip().split()[0]
                        elif line.strip() and current_func_id:
                            nid = line.strip().split()[0]
                            self._function_map[nid] = f"{current_func_id}: {current_func_name}"
            except Exception as e:
                return f"[unknown: {e}]"
        return self._function_map.get(node_id, "Unknown")

class SemanticRefinementEngine:
    """Implements expression-level and statement-level abstract semantic"""

    _TS_LOW  = 1_700_000_000
    _TS_HIGH = 1_700_000_015

    _INF = float('inf')

    def __init__(self, cfg=None, collecting_semantics=None):
        """Parameters"""
        self.cfg = cfg
        self.collecting_semantics = collecting_semantics or {}

    def is_timestamp_independent(self, source_fragment: str) -> bool:
        """Return True if ``source_fragment`` is expression-level semantically"""
        lo, hi = self._eval_interval(source_fragment)
        if lo is None:
            return False
        return lo == hi

    def filter_timestamp_verdicts(self, verdicts: list, source_code: str) -> list:
        """Post-filter a list of [TIMESTAMP] verdict strings by applying"""
        if not verdicts:
            return verdicts

        stripped = self._strip_comments(source_code)
        spurious_expressions = self._collect_spurious_expressions(stripped)

        if not spurious_expressions:
            return verdicts

        filtered = []
        for v in verdicts:
            if '[TIMESTAMP]' not in v:
                filtered.append(v)
                continue
            suppressed = False
            for expr_str in spurious_expressions:
                if self.is_timestamp_independent(expr_str):
                    suppressed = True
                    break
            if not suppressed:
                filtered.append(v)
        return filtered

    def check_relevancy(self, var: str, def_node_id: str,
                        collecting_semantics=None) -> bool:
        """CHECKRELEVANCY predicate from Algorithm 4 (TOD detection)."""
        cs = collecting_semantics or self.collecting_semantics
        if not cs or def_node_id not in cs:
            return True
        state = cs[def_node_id]
        interval = self._get_interval_from_state(state, var)
        if interval is None:
            return True
        lo, hi = interval
        if lo == hi:
            return False
        return True

    def check_dependency(self, var: str, use_node_id: str,
                         collecting_semantics=None) -> bool:
        """CHECKDEPENDENCY predicate from Algorithm 4 (TOD detection)."""
        cs = collecting_semantics or self.collecting_semantics
        if not cs or use_node_id not in cs:
            return True
        state = cs[use_node_id]
        interval = self._get_interval_from_state(state, var)
        if interval is None:
            return True
        lo, hi = interval
        if lo == hi:
            return False
        return True

    def check_condition_dependency(self, var: str, def_func: str,
                                   use_func: str, cfg=None) -> bool:
        """CHECKCONDITIONDEPENDENCY predicate from Algorithm 4 (TOD detection)."""
        g = cfg or self.cfg
        if g is None:
            return True

        transfer_keywords = {'transfer', 'send', 'call', 'delegatecall'}
        var_in_condition = False

        for node_id, node in g.cfg_metadata.node_table.items():
            func_ctx = getattr(node, 'function_context', None) or ''
            if use_func not in func_ctx and use_func not in node_id:
                continue
            if isinstance(node, IfStatement):
                ids_in_cond = self._names_in_condition(node)
                if var in ids_in_cond:
                    var_in_condition = True
                    break
            if isinstance(node, FunctionCall):
                fname = getattr(node, 'function_name', '') or ''
                if fname.lower() in {'require', 'assert'}:
                    ids_in_args = self._names_in_call_args(node)
                    if var in ids_in_args:
                        var_in_condition = True
                        break

        if not var_in_condition:
            return False

        for node_id, node in g.cfg_metadata.node_table.items():
            func_ctx = getattr(node, 'function_context', None) or ''
            if use_func not in func_ctx and use_func not in node_id:
                continue
            if isinstance(node, FunctionCall):
                fname = getattr(node, 'function_name', '') or ''
                if any(kw in fname.lower() for kw in transfer_keywords):
                    return True
            if isinstance(node, ExpressionStatement):
                expr = getattr(node, 'expression', None)
                if expr and isinstance(expr, FunctionCall):
                    fname = getattr(expr, 'function_name', '') or ''
                    if any(kw in fname.lower() for kw in transfer_keywords):
                        return True
        return False

    def _eval_interval(self, expr_str: str):
        """Evaluate ``expr_str`` under interval arithmetic with timestamp"""
        ts_interval = (self._TS_LOW, self._TS_HIGH)
        try:
            result = self._parse_and_eval(expr_str.strip(), ts_interval)
            return result
        except Exception:
            return (None, None)

    @staticmethod
    def _algebraic_simplify(expr: str) -> str:
        """Pre-simplification pass: apply algebraic identities that the pure"""
        import re as _re
        _TERM = r'block\.timestamp|now|blocktimestamp|\w+'
        changed = True
        while changed:
            changed = False
            for m in _re.finditer(
                r'(?<![+\-*/])\b(\d+)\s*\*\s*(' + _TERM + r')\s*%\s*(\d+)\b',
                expr,
            ):
                c, d = int(m.group(1)), int(m.group(3))
                if c % d == 0:
                    expr = expr[:m.start()] + '0' + expr[m.end():]
                    changed = True
                    break
            if changed:
                continue
            for m in _re.finditer(r'\b(' + _TERM + r')\s*%\s*1\b', expr):
                expr = expr[:m.start()] + '0' + expr[m.end():]
                changed = True
                break
            if changed:
                continue
            for m in _re.finditer(r'\b(\d+)\s*%\s*(\d+)\b', expr):
                expr = (expr[:m.start()]
                        + str(int(m.group(1)) % int(m.group(2)))
                        + expr[m.end():])
                changed = True
                break
            if changed:
                continue
            for m in _re.finditer(
                r'\b(\d+)\s*\+\s*0\b|(?<!\d)\b0\s*\+\s*(\d+)\b', expr
            ):
                val = m.group(1) or m.group(2)
                expr = expr[:m.start()] + val + expr[m.end():]
                changed = True
                break
        return expr.strip()

    def _parse_and_eval(self, expr: str, ts_iv):
        """Recursive descent interval evaluator for a subset of Solidity"""
        expr = self._algebraic_simplify(expr.strip())
        expr = expr.strip()

        if expr.startswith('(') and self._matching_close(expr, 0) == len(expr) - 1:
            return self._parse_and_eval(expr[1:-1], ts_iv)

        for op in ('+', '-', '*', '/', '%'):
            idx = self._find_binary_op(expr, op)
            if idx is not None:
                left  = self._parse_and_eval(expr[:idx], ts_iv)
                right = self._parse_and_eval(expr[idx + 1:], ts_iv)
                return self._apply_op(op, left, right)

        try:
            v = int(expr)
            return (v, v)
        except ValueError:
            pass
        try:
            v = float(expr)
            return (v, v)
        except ValueError:
            pass

        token = expr.strip()
        ts_names = {'block.timestamp', 'now', 'blocktimestamp',
                    'block_timestamp', '_timestamp', 'timestamp'}
        if token.lower() in ts_names:
            return ts_iv

        cast_m = __import__('re').match(
            r'^u?int\d*\s*\(\s*(.*)\s*\)$', token, __import__('re').DOTALL
        )
        if cast_m:
            return self._parse_and_eval(cast_m.group(1), ts_iv)

        return (-self._INF, self._INF)

    def _apply_op(self, op: str, left, right):
        lo1, hi1 = left
        lo2, hi2 = right
        INF = self._INF

        def safe(a, b, fn):
            try:
                r = fn(a, b)
                return r if r == r else (0 if fn == _safe_div else 0)
            except (ZeroDivisionError, OverflowError):
                return INF

        def _safe_div(a, b):
            if b == 0:
                raise ZeroDivisionError
            return a / b

        if op == '+':
            new_lo = (-INF if lo1 == -INF or lo2 == -INF
                      else lo1 + lo2)
            new_hi = (INF if hi1 == INF or hi2 == INF
                      else hi1 + hi2)
        elif op == '-':
            new_lo = (-INF if lo1 == -INF or hi2 == INF
                      else lo1 - hi2)
            new_hi = (INF if hi1 == INF or lo2 == -INF
                      else hi1 - lo2)
        elif op == '*':
            corners = []
            for a in (lo1, hi1):
                for b in (lo2, hi2):
                    if a == INF or a == -INF or b == INF or b == -INF:
                        corners.append(INF if (a == INF or b == INF) else -INF)
                    else:
                        corners.append(a * b)
            new_lo = min(corners)
            new_hi = max(corners)
        elif op == '/':
            if lo2 <= 0 <= hi2:
                new_lo, new_hi = -INF, INF
            else:
                corners = [lo1 / lo2, lo1 / hi2, hi1 / lo2, hi1 / hi2]
                new_lo = min(corners)
                new_hi = max(corners)
        elif op == '%':
            if lo2 > 0 and lo2 == hi2:
                n = int(lo2)
                if lo1 != -INF and hi1 != INF:
                    lo_int = int(_math.floor(lo1))
                    hi_int = int(_math.ceil(hi1))
                    if hi_int - lo_int <= 10_000:
                        vals = {v % n for v in range(lo_int, hi_int + 1)}
                        new_lo = min(vals)
                        new_hi = max(vals)
                    else:
                        new_lo, new_hi = 0, n - 1
                else:
                    new_lo, new_hi = 0, n - 1
            else:
                new_lo, new_hi = -INF, INF
        else:
            new_lo, new_hi = -INF, INF

        return (new_lo, new_hi)

    @staticmethod
    def _strip_comments(source: str) -> str:
        s = __import__('re').sub(r'//[^\n]*', '', source)
        s = __import__('re').sub(r'/\*.*?\*/', '', s, flags=__import__('re').DOTALL)
        return s

    def _collect_spurious_expressions(self, stripped: str) -> list:
        """Extract candidate arithmetic expressions that contain a timestamp"""
        import re
        TS = r'block\.timestamp|now|blocktimestamp'
        expressions = []

        for m in re.finditer(
            r'\b\w+\s*=\s*([^;]+(?:' + TS + r')[^;]*);', stripped
        ):
            rhs = m.group(1).strip()
            expressions.append(rhs)

        for m in re.finditer(
            r'([0-9+\-*/%\s(]*(?:' + TS + r')[0-9+\-*/%\s)]*)', stripped
        ):
            fragment = m.group(1).strip()
            if fragment:
                expressions.append(fragment)

        return expressions

    def _find_binary_op(self, expr: str, op: str):
        """Find the index of the rightmost top-level binary operator ``op``"""
        depth = 0
        for i in range(len(expr) - 1, -1, -1):
            ch = expr[i]
            if ch in ')':
                depth += 1
            elif ch in '(':
                depth -= 1
            elif depth == 0 and ch == op:
                if op == '-' and i > 0 and expr[i - 1] in '+-*/%(':
                    continue
                return i
        return None

    def _matching_close(self, s: str, open_idx: int) -> int:
        """Return index of the matching closing parenthesis."""
        depth = 0
        for i in range(open_idx, len(s)):
            if s[i] == '(':
                depth += 1
            elif s[i] == ')':
                depth -= 1
                if depth == 0:
                    return i
        return -1

    @staticmethod
    def _get_interval_from_state(state, var: str):
        """Extract a (lo, hi) interval for ``var`` from an abstract state"""
        if isinstance(state, dict):
            iv = state.get(var)
            if isinstance(iv, (list, tuple)) and len(iv) == 2:
                return tuple(iv)
            return None
        try:
            bounds = state.bound_variable(var)
            return (bounds.inf, bounds.sup)
        except Exception:
            return None

    @staticmethod
    def _names_in_condition(if_node) -> set:
        names = set()
        cond = getattr(if_node, 'condition', None)
        if cond is None:
            return names
        stack = [cond]
        visited = set()
        while stack:
            obj = stack.pop()
            oid = id(obj)
            if oid in visited:
                continue
            visited.add(oid)
            name = getattr(obj, 'name', None)
            if isinstance(name, str):
                names.add(name)
            for attr in ('leftExpression', 'rightExpression', 'subExpression',
                         'expression', 'condition'):
                child = getattr(obj, attr, None)
                if child is not None and hasattr(child, '__dict__'):
                    stack.append(child)
        return names

    @staticmethod
    def _names_in_call_args(call_node) -> set:
        names = set()
        for arg in getattr(call_node, 'arguments', []):
            if arg is None:
                continue
            stack = [arg]
            visited = set()
            while stack:
                obj = stack.pop()
                oid = id(obj)
                if oid in visited:
                    continue
                visited.add(oid)
                name = getattr(obj, 'name', None)
                if isinstance(name, str):
                    names.add(name)
                for attr in ('leftExpression', 'rightExpression',
                             'subExpression', 'expression'):
                    child = getattr(obj, attr, None)
                    if child is not None and hasattr(child, '__dict__'):
                        stack.append(child)
        return names

import math as _math
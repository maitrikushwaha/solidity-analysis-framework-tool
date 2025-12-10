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

# Save output to a file
output_file_path = "reaching_definitions_output.txt"

class ReachingDefinitionsWithUsage:
    """
    Class to compute reaching definitions and track variable dependencies in a given CFG.
    """

    def __init__(self, cfg: ControlFlowGraph, annotate_dependencies=False):
        """
        Initialize the analysis with the control flow graph (CFG).
        """
        self.cfg = cfg
        self.variable_dependencies: Dict[str, Set[Tuple[str, str]]] = {}  # Variable -> {(use_node_id, def_node_id)}
        self.statement_dependencies: Dict[str, Set[Tuple[str, str]]] = {}  # Statement-Level dependencies
        self.latest_definitions: Dict[str, str] = {}  # Variable -> Latest defining node ID
        self.control_dependencies: Dict[str, str] = {}  # child_node -> controlling_if_node
        self.annotate_dependencies = annotate_dependencies
        self.timestamp_vars = {"blocktimestamp", "block.timestamp", "now"}
        self.timestamp_influence = defaultdict(set)
        self.cfg.state_variables = set(
            node.name for node_id, node in self.cfg.cfg_metadata.node_table.items()
            if isinstance(node, VariableDeclaration) and getattr(node, "storage_location", "default") != "memory"
        )
        self.node_used_defined = {}
        # variable → {'used': set(func_names), 'defined': set(func_names)}
        self.variable_func_usage = defaultdict(lambda: {'used': set(), 'defined': set()})
        self.node_to_function: Dict[str, str] = {}  # node_id → function name
        self.function_nodes: Dict[str, str] = {}  # func_id → name
        
        # ✅ PATCH: Add symbolic state-like inputs used in TOD
        for node_id in self.cfg.cfg_metadata.node_table:
            node = self.cfg.cfg_metadata.get_node(node_id)
            if isinstance(node, FunctionCall) or isinstance(node, ExpressionStatement):
                expr = getattr(node, "expression", node)
                # Detect order-sensitive runtime inputs and alias them as pseudo-state
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
        """
        Perform the reaching definitions analysis with variable dependency tracking.
        """
        with open(output_file_path, "w") as output_file:

             # Initialize entry and exit sets for each node
            entry = {node_id: set() for node_id in self.cfg.cfg_metadata.node_table.keys()}
            exit_ = {node_id: set() for node_id in self.cfg.cfg_metadata.node_table.keys()}
            
            # Collect all global variable declarations
            global_definitions = {
                (node.name, node_id)
                for node_id, node in self.cfg.cfg_metadata.node_table.items()
                if isinstance(node, VariableDeclaration)
            }

            # Specify node types to include reaching variables
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

                     # SAFETY CHECK FOR DYNAMICALLY REGISTERED NODES
                    if node_id not in entry:
                        entry[node_id] = set()
                    if node_id not in exit_:
                        exit_[node_id] = set()

                    if hasattr(node, 'prev_nodes') and node.prev_nodes:
                        for pred_id in node.prev_nodes:
                            entry[node_id].update(exit_.get(pred_id, set()))

                    # Add global variables to the entry set
                    entry[node_id].update(global_definitions)

                    # Compute GEN and KILL sets
                    gen_set = set()
                    kill_set = set()
                    used_vars = set()
                    defined_vars = set()
                    reaching_from = {}  # Store reaching sources for each used variable
                    
                    if isinstance(node, VariableDeclaration):
                        try:
                            defined_vars.add(node.name)  # Always define the declared variable
                            gen_set = {(node.name, node_id)}
                            self.latest_definitions[node.name] = node_id  # Track latest definition

                            # Ensure the node has a value assigned
                            value = getattr(node, "value", None)  # Extract value correctly
                            if value and isinstance(value, dict) and value.get("nodeType") == "Identifier":
                                used_vars.add(value["name"])  # Capture the dependency 

                                # Track dependencies for used variables
                            for var in used_vars:
                                latest_def = self.latest_definitions.get(var, None)
                                if latest_def:
                                    reaching_from[var] = latest_def  # Track dependency source
                                    if var not in self.variable_dependencies:
                                        self.variable_dependencies[var] = set()
                                    self.variable_dependencies[var].add((node_id, latest_def))

                                    # Print data dependency within a statement
                                    output_file.write(f"DATA DEPENDENCY: {node.name} is data dependent on {var}\n")
                        
                            for var in defined_vars:
                                latest_def = reaching_from.get(var)
                                if latest_def and latest_def != node_id:
                                    if var not in self.variable_dependencies:
                                        self.variable_dependencies[var] = set()
                                    self.variable_dependencies[var].add((node_id, latest_def))  # redef path

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
                                self.latest_definitions[var] = node_id  # Update latest definition
                            
                            # Track dependencies for used variables
                            for var in used_vars:
                                latest_def = self.latest_definitions.get(var, None)
                                if latest_def:
                                    reaching_from[var] = latest_def  # Use latest definition instead of initial declaration
                                    # Store variable dependency explicitly
                                    if var not in self.variable_dependencies:
                                        self.variable_dependencies[var] = set()
                                    self.variable_dependencies[var].add((node_id, latest_def))

                                    # Print data dependency within a statement
                                    for lhs_var in defined_vars:
                                        output_file.write(f"DATA DEPENDENCY: {lhs_var} is data dependent on {var}\n")
                        
                                        # Link the statement that uses a variable to the statement that defines it
                                        if node_id not in self.statement_dependencies:
                                            self.statement_dependencies[node_id] = set()
                                        self.statement_dependencies[node_id].add((latest_def, var))
                        
                        except Exception as e:
                            output_file.write(f"Error processing node {node_id}: {e}\n")
                            continue

                    elif isinstance(node, (IfStatement, ExpressionStatement, BinaryOperation, Assignment, FunctionCall, Assignment, Return, WhileStatement)):
                        try:
                            if isinstance(node, IfStatement):
                                # Extract all condition variables (left, right, and any nested operations)
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
                                            # Stop at the join node, don't go beyond
                                            if current == join_node:
                                                continue

                                            # Explore the next nodes in CFG to catch synthetic nodes too
                                            next_nodes = self.cfg.cfg_metadata.get_node(current).next_nodes
                                            to_visit.extend(next_nodes.keys())
                               
                            else:
                                expr = expr_builder(node)
                                used_vars |= expr.right_symbols if expr else set()
                                defined_vars |= expr.left_symbols if expr else set()

                                # [PATCH] Track symbolic pseudo-variables
                                for sym in list(used_vars):
                                    if "address(this).balance" in sym or "this.balance" in sym:
                                        used_vars.add("CONTRACT_BALANCE")


                                # Fallback extraction (for missing expr_builder coverage)
                                if not used_vars and hasattr(node, "next_nodes"):
                                    for next_id in node.next_nodes:
                                        child_node = self.cfg.cfg_metadata.get_node(next_id)
                                        used_vars |= self.extract_variables_from_expression(child_node)

                                # Handle function arguments (e.g., f(x, y + z))
                                function_arguments = self.extract_function_arguments(node)
                                used_vars |= function_arguments

                                # Track dependencies for used vars FIRST (important!)
                                for var in used_vars:
                                    latest_def = self.latest_definitions.get(var, None)
                                    if latest_def:
                                        reaching_from[var] = latest_def
                                        if var not in self.variable_dependencies:
                                            self.variable_dependencies[var] = set()
                                        self.variable_dependencies[var].add((node_id, latest_def))

                                # Track redef links (this is where ExpressionStatement_3 → VariableDeclaration_3 is built)
                                for var in defined_vars:
                                    prev_def = self.latest_definitions.get(var)
                                    if prev_def and prev_def != node_id:
                                        if var not in self.variable_dependencies:
                                            self.variable_dependencies[var] = set()
                                        self.variable_dependencies[var].add((node_id, prev_def))  # redef edge

                                # Now finally update latest definition
                                for var in defined_vars:
                                    self.latest_definitions[var] = node_id

                                # Mark GEN set
                                gen_set = {(var, node_id) for var in defined_vars}

                                # Print dependency debug info
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
                                        # Dynamically get the correct class from the nodeType
                                        node_type = return_expr.get("nodeType")
                                        constructor = getattr(nodes, node_type)

                                        # Check if node already exists in CFG
                                        expr_node = self.cfg.cfg_metadata.get_node_by_ast_id(return_expr['id']) \
                                            if 'id' in return_expr else None

                                        # Build it if not already presentexpr_node)
                                        if expr_node is None:
                                            expr_node = constructor(return_expr, None, None, None, self.cfg.cfg_metadata)

                                        # Extract variables from the built node
                                        used_vars |= self.extract_variables_from_expression(expr_node)
                                        # Track statement-level data dependencies for Return node
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
                                # Extract variables used in the loop condition
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
                                
                                # Control Dependency: Everything in while body is control dependent on WhileStatement
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

                                        # Visit children inside the while body
                                        next_nodes = self.cfg.cfg_metadata.get_node(current).next_nodes
                                        to_visit.extend(next_nodes.keys())
                        
                        except Exception as e:
                            output_file.write(f"Error processing node {node_id}: {e}\n")
                            continue

                    # ✅ Timestamp tracking patch
                    for var in used_vars:
                        if var in self.timestamp_vars:
                            self.timestamp_influence[node_id].add(var)
                    
                    # KILL set: Remove earlier definitions of variables in GEN
                    kill_set = {
                        (var, other_node_id)
                        for var, _ in gen_set
                        for other_node_id in self.cfg.cfg_metadata.node_table.keys()
                        if other_node_id != node_id
                    }

                    # Compute Exit set
                    new_exit = (entry[node_id] - kill_set) | gen_set
                    if new_exit != exit_[node_id]:
                        changes = True
                        exit_[node_id] = new_exit

                    # Filter the Exit set to only include reaching variables for specific node types
                    filtered_exit_set = exit_[node_id] if type(node) in include_reaching_nodes else set()

                    # Format used variables with their reaching source
                    used_vars_with_reaching = ", ".join(
                        f"{var} (from {reaching_from[var]})" if var in reaching_from else var
                        for var in used_vars
                    )
                    used_vars_str = used_vars_with_reaching if used_vars else "None"
                    defined_vars_str = ', '.join(defined_vars) if defined_vars else "None"
                    # exit_set_str = ', '.join(f"{var}:{point}" for var, point in filtered_exit_set)
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
                    
                    # ✅ Track which function uses/defines each state variable (for TOD detection)
                    func_ctx = get_enclosing_function(node_id)
                    self.node_to_function[node_id] = func_ctx
                    for var in used_vars:
                        self.variable_func_usage[var]['used'].add(node_id)
                    for var in defined_vars:
                        self.variable_func_usage[var]['defined'].add(node_id)
                    # Write the current node information to the file
                    output_file.write(f"{node_id:<25} {used_vars_str:<50} {defined_vars_str:<35} \n")
                    self.node_used_defined[node_id] = (used_vars.copy(), defined_vars.copy())  # 🆕
                    # output_file.write(f"[TRACKED] {node_id}: used={used_vars}, defined={defined_vars}\n")

                output_file.write("-" * 150 + "\n")

                if not changes:
                    output_file.write("\nFixed point reached. Reaching definitions have converged.\n")
                    break

                iteration += 1

                # PATCH: Promote transitive state-influenced variables after first pass
                if iteration == 2:
                    influenced_by_state = set(self.cfg.state_variables)
                    queue = deque(influenced_by_state)

                    while queue:
                        state_var = queue.popleft()
                        for var, deps in self.variable_dependencies.items():
                            for use_node, def_node in deps:
                                if state_var in self.node_used_defined.get(def_node, ([], []))[0]:  # use set
                                    if var not in self.cfg.state_variables:
                                        self.cfg.state_variables.add(var)
                                        queue.append(var)

            # Print variable dependencies in order
            self.print_statement_dependencies(output_file)
            self.print_reaching_definition(output_file)

            # self.detect_tod_vulnerabilities(output_file)

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

            output_file.write("\n[📋 TOD Summary - Compact CLI Format]\n")

            tod_entries = []

            def is_likely_mapping(varname):
                # Add mapping-originated variable names you transform
                return varname in { "commit", "balanceOf", "lockTime", "userBalances"}

            def looks_like_arithmetic_only(var, node_id):
                node = self.cfg.cfg_metadata.get_node(node_id)

                # Only allow arithmetic expressions, not control or call-related
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
                """
                Returns True only if a variable appears in a require/assert that guards a sensitive transfer.
                If it's a pure arithmetic gating (like require(numElements > 1500)), return False.
                """
                sensitive_keywords = {"transfer", "call", "send", "delegatecall"}

                output_file.write(f"[DEBUG is_control_or_transfer_sensitive] Checking node: {getattr(node, 'cfg_id', node)}\n")

                def contains_call_value(expr):
                    """
                    Recursively detect .call.value(...) or similar sensitive member calls in nested expressions.
                    """
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

                        # Traverse all nested attributes
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

                    # If this is a require/assert, scan its successors for sensitive action
                    if isinstance(expr, FunctionCall):
                        fname = getattr(expr, "function_name", "")
                        if fname and fname.lower() in {"require", "assert"}:
                            # Look ahead to see if there's any sensitive action after this
                            to_visit = list(node.next_nodes.keys())
                            visited = set()

                            # PATCH: require/assert with no successor is benign
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
                            return False  # No sensitive call found after require/assert

                        # Direct sensitive call? Immediate risk
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
                # Never appears in control-flow statements or transfer
                safe_keywords = {"if", "require", "assert", "transfer", "call"}
                for node_id, (used, _) in self.node_used_defined.items():
                    if var in used:
                        node = self.cfg.cfg_metadata.get_node(node_id)
                        if isinstance(node, FunctionCall) or isinstance(node, IfStatement):
                            return False
                return True

            def is_misaligned_arithmetic_tod(var, def_node, use_node):
                return looks_like_arithmetic_only(var, use_node) and looks_like_arithmetic_only(var, def_node)

            # --- NEW INTRA-FUNCTION DETECTION FROM self.node_used_defined ---
            output_file.write("[DEBUG] Starting NEW intra-function TOD detection loop\n")
            for var in self.cfg.state_variables:
                output_file.write(f"[DEBUG] Analyzing state variable '{var}' for intra-function TOD\n")
                for use_node in self.node_used_defined:
                    used_vars, _ = self.node_used_defined[use_node]

                    # If the node is a FunctionCall with no used_vars, try its parent ExpressionStatement
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

                        # ⚠️ Skip VariableDeclaration unless it's a defining statement
                        def_node_obj = self.cfg.cfg_metadata.get_node(def_node)
                        if isinstance(def_node_obj, VariableDeclaration):
                            # Skip raw declarations unless this variable is NOT redefined elsewhere
                            # (to preserve legit declaration-based definitions)
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
                            # Intra-function TOD detected if there's a sensitive use and a definition in the same function
                            use_node_obj = self.cfg.cfg_metadata.get_node(use_node)
                            if is_control_or_transfer_sensitive(use_node_obj, var=var):
                                output_file.write(f"[DEBUG-TOD-CHECK] use_node={use_node}, def_node={def_node}, func={use_func}\n")
                                entry = f"{var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func}) [INTRA-TOD]"
                                if entry not in tod_entries:
                                    tod_entries.append(entry)
        
                        except ValueError:
                            continue  # skip unlisted nodes safely

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

                        #  Skip TOD if timestamp influence guards the use_node
                        if use_node in self.timestamp_influence:
                            output_file.write(f"[SKIP TOD] {var} usage in {use_node} skipped due to timestamp-influenced logic\n")
                            continue            
                        
                        output_file.write(f"[DEBUG TOD PATH] var={var}, def_node={def_node} ({def_func}), use_node={use_node} ({use_func})\n")

                        #  PATCH: Detect direct use of the state variable in .call.value(...) transfer
                        if use_node_obj and isinstance(use_node_obj, (ExpressionStatement, FunctionCall)):
                            node_str = str(use_node_obj).lower()
                            if (hasattr(use_node_obj, "memberName") and use_node_obj.memberName == "value") or ("call.value" in node_str):
                                if var in used_vars:
                                    output_file.write(f"[MATCH] Direct .call.value transfer based on state var '{var}' in node {use_node}\n")
                                    entry = f" {var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func})"
                                    if entry not in tod_entries:
                                        tod_entries.append(entry)
                                    continue  #  Skip the rest — already confirmed as TOD
                        
                        # Skip if it's arithmetic-only and not involved in control or transfer
                        if is_misaligned_arithmetic_tod(var, def_node, use_node):
                            output_file.write(f"[DEBUG] → is_misaligned_arithmetic_tod = True\n")
                            output_file.write(f"[DEBUG] → use_node_obj = {use_node_obj}\n")
                            
                            if not (is_control_or_transfer_sensitive(use_node_obj, var=var) or 
                                    is_control_or_transfer_sensitive(def_node_obj, var=var)):
                                output_file.write(f"[SKIP TOD] {var} flow skipped due to arithmetic-only and benign use/def\n")
                                continue

                        #  Flag TOD
                        
                        entry = f" {var}: defined in {def_node} ({def_func}), used in {use_node} ({use_func})"
                        if entry not in tod_entries:
                            tod_entries.append(entry)

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
            """
            Extracts function call arguments as used variables from both ExpressionStatements and FunctionCall nodes.
            """
            variables = set()

            # If the node itself is a FunctionCall, extract arguments
            if isinstance(node, FunctionCall):
                for arg in node.arguments:
                    if isinstance(arg, Identifier):  # Direct variable usage
                        variables.add(arg.name)
                    elif isinstance(arg, BinaryOperation):  # Handle expressions like (pot - FEE_AMOUNT)
                        variables |= self.extract_variables_from_expression(arg)
                    elif hasattr(arg, "sub_expression"):  # Handle unary expressions like !claimed
                        variables |= self.extract_variables_from_expression(arg.sub_expression)
                    else:
                        # Fallback for other expression types (e.g., MemberAccess, nested FunctionCall, etc.)
                        variables |= self.extract_variables_from_expression(arg)
            
            # If the function call is embedded inside an expression, extract arguments
            elif hasattr(node, 'expression') and hasattr(node.expression, 'is_function_call') and node.expression.is_function_call():
                for arg in node.expression.arguments:
                    if isinstance(arg, Identifier):  # Direct variable usage
                        variables.add(arg.name)
                    elif isinstance(arg, BinaryOperation):  # Handle expressions like (pot - FEE_AMOUNT)
                        variables |= self.extract_variables_from_expression(arg)
                    elif hasattr(arg, "sub_expression"):  # Handle unary operations in arguments
                        variables |= self.extract_variables_from_expression(arg.sub_expression)
                    else:
                        variables |= self.extract_variables_from_expression(arg)
            return variables
    
    def extract_variables_from_expression(self, expr):
        """
        Recursively extracts variable names from an expression, handling nested BinaryOperations.
        """
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

        # Optional fallback for dynamic/untyped nodes
        elif hasattr(expr, "leftExpression") and hasattr(expr, "rightExpression"):
            variables |= self.extract_variables_from_expression(expr.leftExpression)
            variables |= self.extract_variables_from_expression(expr.rightExpression)

        elif hasattr(expr, "subExpression"):
            variables |= self.extract_variables_from_expression(expr.subExpression)

        return variables
     
    def get_node_id_by_ast_id(self, ast_id: int) -> str:
        """
        Maps an AST node ID to a CFG node ID using cfg metadata.
        """
        for node_id, node in self.cfg.cfg_metadata.node_table.items():
            if getattr(node, 'ast_id', None) == ast_id:
                return node_id
        return None

    def print_reaching_definition(self, output_file):
        """
        Correctly print reaching definitions grouped by node, classifying defs vs. uses.
        """
        output_file.write("\nReaching Definition:\n")

        node_dependencies = defaultdict(list)

        for var, dependencies in self.variable_dependencies.items():
            for use_node, def_node in dependencies:
                # Avoid logging a definition node as a use
                if self.latest_definitions.get(var) == use_node:
                    continue
                node_dependencies[use_node].append((var, def_node))

        sorted_nodes = sorted(node_dependencies.keys(), key=lambda node: int(node.split('_')[-1]) if node.split('_')[-1].isdigit() else float('inf'))

        for node_id in sorted_nodes:
            output_file.write(f"\nNode '{node_id}' uses:\n")
            for var, def_node in node_dependencies[node_id]:
                output_file.write(f"  - Variable '{var}' reached from Node '{def_node}'\n")

    def print_statement_dependencies(self, output_file):
        """
        Print both statement-level data dependencies and control structure dependencies.
        """
        output_file.write("\nStatement-Level Dependencies:\n")

        for dependent_stmt, dependencies in self.statement_dependencies.items():
            for dependency in dependencies:
                # Ensure correct unpacking of tuple
                if isinstance(dependency, tuple) and len(dependency) == 2:
                    defining_stmt, variable = dependency
                    output_file.write(
                        f"STATEMENT DEPENDENCY: Node '{dependent_stmt}' is data dependent on Node '{defining_stmt}' for variable '{variable}'\n"
                    )

        output_file.write("\nControl Structure Dependencies Only:\n")

        for child_node, controlling_if in self.control_dependencies.items():
            label = child_node

            # Check if this node is an ExpressionStatement and has a FunctionCall child
            node_obj = self.cfg.cfg_metadata.get_node(child_node)
            if isinstance(node_obj, ExpressionStatement):
                # Search CFG to find any FunctionCall node that lists this as its previous node
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
            # 1. From direct timestamp influence tracking (reliable)
            for node_id, sources in self.timestamp_influence.items():
                for src in sources:
                    output_file.write(f"→ Node {node_id} influenced by timestamp source: {src}\n")

            # 2. (Optional) From statement dependencies (legacy support)
            for node_id, deps in self.statement_dependencies.items():
                for def_node, var in deps:
                    if var in {"blocktimestamp", "block.timestamp", "now"}:
                        output_file.write(f"→ Node {node_id} influenced by timestamp source: {var}\n")

            
    def get_function_context(self, node_id):
        """
        Returns function context (FunctionDefinition_#: name) for a node ID using cached map.
        """
        if not hasattr(self, "_function_map"):
            self._function_map = {}
            current_func_id = None
            current_func_name = None
            try:
                with open("reaching_definitions_output.txt", "r") as f:
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


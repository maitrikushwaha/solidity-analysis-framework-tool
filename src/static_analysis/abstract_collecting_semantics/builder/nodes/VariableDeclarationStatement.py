'''
VariableDeclarationStatement Expression Handlers

FIX: Null-safe get_variables — skip None declarations.
FIX: generate_exit_sets — handle missing initialValue gracefully
     (forward entry_set unchanged instead of crashing).
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from java_wrapper import java, apron
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import VariableDeclarationStatement
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object


def get_variables(node: VariableDeclarationStatement) -> Set[str]:
    '''
    Obtain variable names from LHS declarations.
    Skips None entries (tuple destructuring placeholders).
    '''
    left_symbols = set()
    for decl in node.declarations:
        if decl is None:
            continue
        name = getattr(decl, 'name', None)
        if name is not None:
            left_symbols.add(name)
    return left_symbols


def generate_exit_sets(node: VariableDeclarationStatement, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry, manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics.
    '''
    left_symbols = get_variables(node)

    # No variables extracted (all declarations were None) — pass through
    if not left_symbols:
        return {'*': entry_set}

    left_symbol = left_symbols.pop()

    # No initial value — forward entry set unchanged
    if node.initialValue is None:
        return {'*': entry_set}

    print(f"Processing variable '{left_symbol}' with initial value {node.initialValue}")

    # Compute the expression based on the initial value
    expr = compute_expression_object(
        node.initialValue, var_registry, const_registry, entry_set, manager
    )

    expr = apron.Texpr0Intern(expr)

    variable_index = var_registry.get_id(left_symbol)

    if variable_index == -1:
        # Variable not in registry — forward entry set without crash
        print(f"Variable '{left_symbol}' not in registry, forwarding entry set.")
        return {'*': entry_set}

    new_state = entry_set.assignCopy(manager, variable_index, expr, None)

    var_registry.register_variable(left_symbol, stateVariable=False, value=node.initialValue)

    print(f"New state created for variable '{left_symbol}': {new_state}")

    return {'*': new_state}
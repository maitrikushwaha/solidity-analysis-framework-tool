import logging
from typing import Set, Dict, Tuple, Any
from java_wrapper import apron
from control_flow_graph.node_processor.nodes import VariableDeclaration
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from java_wrapper.apron import _Interval, _Texpr0CstNode, _Texpr0Intern


def get_variables(node: VariableDeclaration) -> Set[str]:
    '''
    Handles individual Variable Declarations, but only adds state variables (global) to the registry.
    '''
    left_symbols = set()
    if node.stateVariable:
        left = node.name
        left_symbols.add(left)
    else:
        logging.debug(f"Local variable {node.name} detected but not added to the registry.")
    return left_symbols


def generate_exit_sets(node: VariableDeclaration, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry, manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics.
    This function handles the state of both global and local variables but only adds global variables to the registry.
    '''
    left_symbols = get_variables(node)

    if not left_symbols:
        logging.debug(f"No global variables to process for node {node.name}.")
        return {'*': entry_set}

    left_symbol = left_symbols.pop()
    logging.debug(f"Processing global variable {left_symbol}")

    if node.value is None:
        logging.debug(f"Global variable {left_symbol} has no initial value, setting to 0.")
        initial_value = apron.Interval(apron.MpqScalar(0), apron.MpqScalar(0))
    else:
        expr = compute_expression_object(
            node.value, var_registry, const_registry, entry_set, manager
        )
        initial_value = expr
        logging.debug(f"Computed expression for global variable {left_symbol}: {expr}")

    if left_symbol not in var_registry.variable_table:
        logging.debug(f"Registering variable {left_symbol} in registry with value: {initial_value} and stateVariable: {node.stateVariable}")
        var_registry.register_variable(left_symbol, stateVariable=node.stateVariable, value=initial_value)
    else:
        existing_var = var_registry.variable_table[left_symbol]
        if existing_var['value'] != initial_value or existing_var['stateVariable'] != node.stateVariable:
            existing_var['value'] = initial_value
            existing_var['stateVariable'] = node.stateVariable
            logging.debug(f"Updated variable {left_symbol} in registry with value: {initial_value} and stateVariable: {node.stateVariable}")

    variable_index = var_registry.get_id(left_symbol)
    logging.debug(f"Global variable {left_symbol} has index {variable_index} in the variable registry.")

    if isinstance(initial_value, _Interval):
        if initial_value.inf().equals(initial_value.sup()):
            scalar = initial_value.inf()
            const_node = _Texpr0CstNode(scalar)
            expr = _Texpr0Intern(const_node)
            new_state = entry_set.assignCopy(manager, variable_index, expr, None)
        else:
            raise NotImplementedError("Only constant intervals are supported.")
    else:
        new_state = entry_set.assignCopy(manager, variable_index, initial_value, None)

    logging.debug(f"Adding new state to exit set for global variable {left_symbol}.")
    return {'*': new_state}
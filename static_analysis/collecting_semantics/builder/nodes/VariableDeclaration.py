'''
VariableDeclaration Expression Handlers for Global Variables
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from static_analysis.collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import VariableDeclaration
from static_analysis.collecting_semantics.builder.common import update_state_tuple, compute_expression_object, set_var_registry_state


def get_variables(node: VariableDeclaration) -> Set[str]:
    '''
    Handles individual Variable Declarations, but only adds state variables (global) to the registry.
    '''

    left_symbols = set()

    # Check if the variable is a state variable (global)
    if node.stateVariable:
        # It's a state variable (global)
        left = node.name
        print(f"Global variable detected: {left}")  # Debugging print for global variable

        # Add the variable name to the set if it's global
        left_symbols.add(left)
        print(f"Global variable {left} added to the symbol set")  # Debugging print for added global variable
    else:
        # It's a local variable, skip it
        print(f"Local variable {node.name} detected but not added to the registry.")  # Debugging print for skipped local variable

    return left_symbols


def generate_exit_sets(node: VariableDeclaration, entry_set: Set[Tuple[Any]],
                       var_registry: VariableRegistry, const_registry: VariableRegistry) -> Dict[str, Set[Tuple[Any]]]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics.
    This function handles the state of both global and local variables but only adds global variables to the registry.
    '''

    # Get the variable symbol, but only if it's global
    left_symbols = get_variables(node)

    # If there are no global variables, return the existing entry set without modifications
    if not left_symbols:
        print(f"No global variables to process for node {node.name}.")
        return {'*': entry_set}

    # Pop the global variable (since there's only one variable in the set)
    left_symbol = left_symbols.pop()
    print(f"Processing global variable {left_symbol}")  # Debugging print to track variables in exit sets

    # Init exit_set ('*') as empty set
    exit_set = set()

    # For each state in the entry state
    for state_tuple in entry_set:
        # EDGE CASE: if the global variable is not declared with any values
        if node.value is None:
            print(f"Global variable {left_symbol} has no initial value, using entry set.")
            continue

        # 1. Based on the state values, compute the expression for the variable
        set_var_registry_state(state_tuple, var_registry)

        # Compute the expression
        expr_value = compute_expression_object(
            node.value, var_registry, const_registry
        )

        # 2. Replace the computed global variable's value in this particular state
        # Create a copy of the entry set state tuple
        new_state_tuple = deepcopy(state_tuple)

        # Replace the global variable's value in the tuple
        new_state_tuple = update_state_tuple(
            new_state_tuple, left_symbol, expr_value, var_registry
        )

        # 3. Add this new state to the set of exit states
        exit_set.add(new_state_tuple)
        print(f"New state created for global variable {left_symbol}: {new_state_tuple}")  # Debugging print for new state

    return {'*': exit_set}

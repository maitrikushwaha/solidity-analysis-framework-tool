from typing import Set, Dict, Tuple, Any
from java_wrapper import apron
from control_flow_graph.node_processor.nodes import VariableDeclaration
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from java_wrapper.apron import _Interval,_Texpr0CstNode, _Texpr0Intern


def get_variables(node: VariableDeclaration) -> Set[str]:
    '''
    Handles individual Variable Declarations, but only adds state variables (global) to the registry.
    '''
    # print("kk, this function 2 is running")

    left_symbols = set()

    # Check if the variable is a state variable (global)
    if node.stateVariable:
        # It's a state variable (global)
        left = node.name
        # print(f"Global variable detected: {left}")  # Debugging print for global variable

        # Add the variable name to the set if it's global
        left_symbols.add(left)
        # print(f"Global variable {left} added to the symbol set")  # Debugging print for added global variable
    else:
        # It's a local variable, skip it
        print(f"Local variable {node.name} detected but not added to the registry.")  # Debugging print for skipped local variable

    return left_symbols


def generate_exit_sets(node: VariableDeclaration, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry, manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics.
    This function handles the state of both global and local variables but only adds global variables to the registry.
    '''
    print("kk, this function 1 is running")

    # Get the variable symbol, but only if it's global
    left_symbols = get_variables(node)

    # If there are no global variables, return the existing entry set without modifications
    if not left_symbols:
        print(f"No global variables to process for node {node.name}.")
        return {'*': entry_set}

    # Pop the global variable (since there's only one variable in the set)
    left_symbol = left_symbols.pop()
    print(f"Processing global variable {left_symbol}")  # Debugging print to track variables in exit sets

    # Check if the variable has an initial value
    if node.value is None:
        print(f"Global variable {left_symbol} has no initial value, setting to 0.")  # Debugging for no initial value
        initial_value = apron.Interval(apron.MpqScalar(0), apron.MpqScalar(0))  # Default to 0 if uninitialized
    else:
        # Compute the expression (right-hand side) based on the initial value of the global variable
        expr = compute_expression_object(
            node.value, var_registry, const_registry, entry_set, manager
        )
        initial_value = expr
        print(f"Computed expression for global variable {left_symbol}: {expr}")  # Debugging print for computed expression

    # Register the variable with stateVariable=True and its initial value
    if left_symbol not in var_registry.variable_table:
        print(f"Registering variable {left_symbol} in registry with value: {initial_value} and stateVariable: {node.stateVariable}")
        var_registry.register_variable(left_symbol, stateVariable=node.stateVariable, value=initial_value)
    else:
        # If the variable is already registered, update its value and stateVariable if needed
        existing_var = var_registry.variable_table[left_symbol]
        if existing_var['value'] != initial_value or existing_var['stateVariable'] != node.stateVariable:
            existing_var['value'] = initial_value
            existing_var['stateVariable'] = node.stateVariable
            print(f"Updated variable {left_symbol} in registry with value: {initial_value} and stateVariable: {node.stateVariable}")

    # Update the state with the computed expression
    variable_index = var_registry.get_id(left_symbol)
    print(f"Global variable {left_symbol} has index {variable_index} in the variable registry.")  # Debugging print for variable index

    # Create the new state for the variable in the entry set
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

    # Add this new state to the set of exit states
    print(f"Adding new state to exit set for global variable {left_symbol}.")  # Debugging print for exit set update
    return {'*': new_state}

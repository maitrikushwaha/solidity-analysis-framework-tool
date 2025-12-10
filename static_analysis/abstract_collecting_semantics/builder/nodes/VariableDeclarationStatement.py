'''
VariableDeclarationStatement Expression Handlers
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from java_wrapper import java, apron
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import VariableDeclarationStatement
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object




def get_variables(node: VariableDeclarationStatement) -> Set[str]:
   '''
   Recursively obtain variables from LHS of the variable declaration
   '''
#    print("kk, get variables function of variable declaration stmt is getting called here")
#    print("kartik checking 2")
   left_symbols = set()


   # obtain the left hand assignment symbol
   left = node.declarations[0].name
   # add the assignment to the set of symbols
   left_symbols.add(left)


   return left_symbols




def generate_exit_sets(node: VariableDeclarationStatement, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry, manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics.
    '''
    # print("kk generate exit sets of variable declarationn statement is getting control here")
    # Get the left-hand symbol (variable name)
    left_symbol = get_variables(node).pop()

    # Check if the variable has an initial value
    if node.initialValue is None:
        raise ValueError(f"Variable '{left_symbol}' has no initial value.")

    # Log for debugging
    print(f"Processing variable '{left_symbol}' with initial value {node.initialValue}")

    # Compute the expression based on the initial value of the variable
    expr = compute_expression_object(
        node.initialValue, var_registry, const_registry, entry_set, manager
    )

    # Assuming parsed_expression returns a Texpr0Node or similar
    expr = apron.Texpr0Intern(expr)

    # Replace the computed variable (lhs) value in this particular state
    variable_index = var_registry.get_id(left_symbol)

    if variable_index == -1:
        raise ValueError(f"Variable '{left_symbol}' is not registered in the variable registry.")

    new_state = entry_set.assignCopy(manager, variable_index, expr, None)

    # Register the variable with its initial value (also handle stateVariable flag if necessary)
    var_registry.register_variable(left_symbol, stateVariable=False, value=node.initialValue)

    # Add this new state to the set of exit states
    print(f"New state created for variable '{left_symbol}': {new_state}")

    return {'*': new_state}






'''
WhileStatement Expression Handlers
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from static_analysis.collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import IfStatement
from static_analysis.collecting_semantics.builder.common import compute_expression_object, set_var_registry_state


def get_variables(node: IfStatement) -> Set[str]:
    '''
    Recursively obtain variables from LHS of the while statement
    '''

    # as of now, we return empty set
    left_symbols = set()

    return left_symbols


def generate_exit_sets(node: IfStatement, entry_set: Set[Tuple[Any]],
                       var_registry: VariableRegistry, const_registry: VariableRegistry) -> Dict[str, Set[Tuple[Any]]]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics
    '''

    # obtain the condition property
    condition = node.condition

    # obtain the true and false branches
    true_branch = node.true_body_next
    false_branch = node.false_body_next

    # init exit_set ('*') as empty set
    exit_dict = {true_branch: set(), false_branch: set()}

    # for each state in the entry state,
    for state_tuple in entry_set:
        #   1. based on the state values, compute the expression
        set_var_registry_state(state_tuple, var_registry)

        # compute the expression,
        expr_value = compute_expression_object(
            condition, var_registry, const_registry)

        print(node.cfg_id, expr_value, state_tuple)

        #   2. based on the computed expression,
        # if expr_value is True, add state to true branch
        # else add state to false branch
        if expr_value == True:
            exit_dict[true_branch].add(deepcopy(state_tuple))
        elif expr_value == False:
            exit_dict[false_branch].add(deepcopy(state_tuple))
        else:
            raise Exception(
                f'Invalid expression value {expr_value} for If Statement!')

    print("EXIT DICT", exit_dict)

    return exit_dict

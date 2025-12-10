'''
WhileStatement Expression Handlers
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from java_wrapper import java, apron
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import ForStatement
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object


def get_variables(node: ForStatement) -> Set[str]:
    '''
    Recursively obtain variables from LHS of the while statement
    '''

    # as of now, we return empty set
    left_symbols = set()

    return left_symbols


def generate_exit_sets(node: ForStatement, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry,
                       manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics
    '''

    # obtain the condition property
    condition = node.condition

    # obtain the true and false branches
    true_branch = node.body_next
    false_branch = node.join_node

    # init exit_set ('*') as empty set
    exit_dict = {true_branch: apron.Abstract0(manager, entry_set),
                 false_branch: apron.Abstract0(manager, entry_set)}
    if '*' not in exit_sets:
        exit_dict = {true_branch: exit_sets[true_branch],
                     false_branch: exit_sets[false_branch]}

    #   1. based on the state values, compute the expression
    expr_value = compute_expression_object(
        condition, var_registry, const_registry,
        entry_set, manager)

    #   2. based on the computed expression,
    # if expr_value is True, add state to true branch
    # else add state to false branch
    if expr_value == True:
        exit_dict[true_branch] = entry_set
    elif expr_value == False:
        exit_dict[false_branch] = entry_set
    else:
        raise Exception(
            f'Invalid expression value {expr_value} for ForLoop Statement!')

    return exit_dict

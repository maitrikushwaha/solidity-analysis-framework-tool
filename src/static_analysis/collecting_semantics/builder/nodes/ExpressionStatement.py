'''
ExpressionStatement Expression Handlers
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from static_analysis.collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import ExpressionStatement
from static_analysis.collecting_semantics.builder.common import traverse_expression_object, update_state_tuple, compute_expression_object, set_var_registry_state


def get_variables(node: ExpressionStatement) -> Set[str]:
    '''
    Recursively obtain variables from LHS of the expression
    '''

    # obtain the expression property
    expression = node.expression

    # init symbol sets
    left_symbols = set()

    # handle assignment nodes
    if expression.node_type == 'Assignment':
        # traverse and generate the left hand side
        traverse_expression_object(
            expression.leftHandSide, left_symbols)

        return left_symbols

    # handle UnaryOperation nodes
    if expression.node_type == 'UnaryOperation':
        # traverse and generate the left hand side
        traverse_expression_object(
            expression.subExpression, left_symbols)

        return left_symbols
    # can we moe this if else thingy to a class / module based calling method?
    # this will really get complicated with more functionality being added


def generate_exit_sets(node: ExpressionStatement, entry_set: Set[Tuple[Any]],
                       var_registry: VariableRegistry, const_registry: VariableRegistry) -> Dict[str, Set[Tuple[Any]]]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics
    '''

    # obtain the expression property
    expression = node.expression

    # init symbol sets
    left_symbol = get_variables(node).pop()

    # init exit_set ('*') as empty set
    exit_set = set()

    # for each state in the entry state,
    for state_tuple in entry_set:
        #   1. based on the state values, compute the expression
        set_var_registry_state(state_tuple, var_registry)

        # compute the expression,
        expr_value = compute_expression_object(
            expression.rightHandSide, var_registry, const_registry)

        #   2. replace the computed variable (lhs) value in this particular state
        # create a copy of the entry set state tuple
        new_state_tuple = deepcopy(state_tuple)

        # replace the lhs variable's value in the tuple
        new_state_tuple = update_state_tuple(
            new_state_tuple, left_symbol, expr_value, var_registry)

        #   3. add this new state to the set of exit states
        exit_set.add(new_state_tuple)

    return {'*': exit_set}

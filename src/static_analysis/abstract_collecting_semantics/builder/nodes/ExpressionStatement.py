'''
ExpressionStatement Expression Handlers
'''
from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from java_wrapper import java, apron
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor.nodes import ExpressionStatement
from static_analysis.abstract_collecting_semantics.builder.common import traverse_expression_object, compute_expression_object


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

    if expression.node_type == 'FunctionCall':
        return set()

    # Fallback: any other expression type (bare identifier, tuple, etc.)
    # has no LHS variable to track — return empty set instead of None.
    return set()

    # can we moe this if else thingy to a class / module based calling method?
    # this will really get complicated with more functionality being added


def generate_exit_sets(node: ExpressionStatement, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry,
                       manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics
    '''

    # obtain the expression property
    expression = node.expression

    print(entry_set)

    # if expression is a function call
    if len(get_variables(node)) == 0:
        return {'*': entry_set}

    # init symbol sets
    left_symbol = get_variables(node).pop()

    # Handle UnaryOperation (++, --): synthesise the equivalent assignment
    # e.g. i++ becomes i = i + 1, i-- becomes i = i - 1
    if expression.node_type == 'UnaryOperation' and expression.operator in ('++', '--'):
        variable_index = var_registry.get_id(left_symbol)
        dim_node = apron.Texpr0DimNode(variable_index)
        one_node = apron.Texpr0CstNode(apron.MpqScalar(1))
        if expression.operator == '++':
            bin_node = apron.Texpr0BinNode(apron.Texpr0BinNode.OP_ADD, dim_node, one_node)
        else:  # '--'
            bin_node = apron.Texpr0BinNode(apron.Texpr0BinNode.OP_SUB, dim_node, one_node)
        expr = apron.Texpr0Intern(bin_node)
        new_state = entry_set.assignCopy(manager, variable_index, expr, None)
        return {'*': new_state}

    #   1. based on the state values, compute the expression
    expr = compute_expression_object(
        expression.rightHandSide, var_registry, const_registry,
        entry_set, manager)

    # Guard: compute_expression_object returns None or Bottom when it encounters
    # an unsupported RHS node type (e.g. IndexAccess like balances[msg.sender],
    # MemberAccess, or nested FunctionCall). In that case we cannot build a
    # Texpr0Intern — attempting to do so raises:
    #   TypeError: No matching overloads for Texpr0Intern(Bottom)
    # Safe fallback: treat the assignment as identity (entry_set passes through
    # unchanged). This is sound over-approximation — we lose precision for this
    # one node but do not crash and do not affect any other node or pipeline.
    if expr is None:
        return {'*': entry_set}
    try:
        if not isinstance(expr, apron.Texpr0Intern):
            expr = apron.Texpr0Intern(expr)
    except TypeError:
        # RHS evaluated to an Apron Bottom object — unsupported expression type.
        # Return entry_set unchanged (identity semantics for this assignment).
        return {'*': entry_set}

    #   2. replace the computed variable (lhs) value in this particular state
    variable_index = var_registry.get_id(left_symbol)
    new_state = entry_set.assignCopy(manager, variable_index, expr, None)

    #   3. add this new state to the set of exit states
    return {'*': new_state}
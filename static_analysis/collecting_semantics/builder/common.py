from typing import Tuple, Any, Union
from static_analysis.collecting_semantics.objects import VariableRegistry, NumericalDomain
from control_flow_graph.node_processor import Node


def traverse_expression_object(node: Node, identifiers: set) -> str:
    '''
    Recursively traverse the expression node and generate the expression
    '''

    # base case: if node type is a Literal, return the value
    if node.node_type == 'Literal':
        return str(node.value)

    # base case: if node type is a Identifier, return the name
    if node.node_type == 'Identifier':
        identifiers.add(node.name)
        return node.name

    # handle if node type is Assignment
    if node.node_type == 'Assignment':
        return f'{traverse_expression_object(node.leftHandSide, identifiers)} {node.operator} {traverse_expression_object(node.rightHandSide, identifiers)}'

    # handle if node type is BinaryOperation
    if node.node_type == 'BinaryOperation':
        return f'{traverse_expression_object(node.leftExpression, identifiers)} {node.operator} {traverse_expression_object(node.rightExpression, identifiers)}'


def update_state_tuple(state_tuple: Tuple[Any], variable: str, value: Any, var_registry: VariableRegistry) -> Tuple[Any]:
    '''
    Update the State Tuple with the given value of the variable
    '''

    # convert the tuple to a list
    state_tuple = list(state_tuple)

    # get the index of the variable in state tuple
    variable_index = var_registry.get_id(variable)

    # update the state tuple with the given value of the variable
    state_tuple[variable_index] = value

    # return the updated state tuple
    return tuple(state_tuple)


def compute_expression_object(node: Node, var_registry: VariableRegistry, const_registry: VariableRegistry) -> int:
    '''
    Recursively Compute the Expression Object and return the value
    '''

    # base case: if node type is a Literal, return the value
    if node.node_type == 'Literal':
        return int(node.value)

    # base case: if node type is a Identifier,
    # retrieve the value from var_registry or const_registry
    if node.node_type == 'Identifier':
        if node.name in var_registry.variable_table.keys():
            return var_registry.get_value(node.name)
        elif node.name in const_registry.variable_table.keys():
            return const_registry.get_value(node.name)
        else:
            raise Exception(
                f'Variable {node.name} not found in var or const registry!')

    # handle if node type is BinaryOperation
    if node.node_type == 'BinaryOperation':
        left = compute_expression_object(
            node.leftExpression, var_registry, const_registry)
        right = compute_expression_object(
            node.rightExpression, var_registry, const_registry)

        return compute_binary_operation(left,
                                        right,
                                        node.operator)

    raise Exception(
        f'Handlers for node type {node.node_type} not implemented yet!')


def compute_binary_operation(left: int, right: int, operator: str) -> int:
    '''
    Compute a binary operation equation based on the lhs, rhs and operator
    '''

    if operator == '+':
        return left + right
    elif operator == '-':
        return left - right
    elif operator == '*':
        return left * right
    elif operator == '/':
        return left / right
    elif operator == '%':
        return left % right
    elif operator == '==':
        return left == right
    elif operator == '!=':
        return left == right
    elif operator == '<':
        return left < right
    elif operator == '<=':
        return left <= right
    elif operator == '>':
        return left > right
    elif operator == '>=':
        return left >= right
    else:
        raise Exception(f'Operator {operator} not implemented yet!')


def set_var_registry_state(state: Tuple[Any], variable_reg: VariableRegistry) -> VariableRegistry:
    '''
    Generate a new variable registry containing the state of variables as supplied in the state tuple
    '''

    for variable in variable_reg.variable_table.keys():
        value = state[variable_reg.get_id(variable)]
        variable_reg.set_value(variable, value)

    return variable_reg

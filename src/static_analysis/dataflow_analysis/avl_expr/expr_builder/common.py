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

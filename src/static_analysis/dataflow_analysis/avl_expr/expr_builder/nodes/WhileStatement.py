'''
WhileStatement Expression Handlers
'''
from control_flow_graph.node_processor.nodes import WhileStatement
from static_analysis.dataflow_analysis.avl_expr.expr_builder.objects import ExpressionStatement as ExpStmt
from static_analysis.dataflow_analysis.avl_expr.expr_builder.common import traverse_expression_object


def build(node: WhileStatement) -> ExpStmt:
    '''
    Recursively build the expression object
    '''

    # obtain the expression property
    condition = node.condition

    # init symbol sets
    left_symbols, right_symbols = set(), set()

    # handle assignment nodes
    if condition.node_type == 'Assignment':
        # traverse and generate the left hand side
        left = traverse_expression_object(
            condition.leftHandSide, left_symbols)

        # traverse and generate the right hand side
        right = traverse_expression_object(
            condition.rightHandSide, right_symbols)

        # render the expression
        expr_str = f'{left} {condition.operator} {right}'

        # create the expression object
        expr = ExpStmt(expr_str, left, right,
                       left_symbols, right_symbols)

        return expr
    elif condition.node_type == 'BinaryOperation':
        # # traverse and generate the left hand side
        # left = traverse_expression_object(
        #     condition.leftExpression, left_symbols)

        # # traverse and generate the right hand side
        # right = traverse_expression_object(
        #     condition.rightExpression, right_symbols)

        # # render the expression
        # expr_str = f'{left} {condition.operator} {right}'

        # create the expression object
        expr = ExpStmt('', '', '',
                       left_symbols, right_symbols)

        return expr

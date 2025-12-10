'''
ExpressionStatement Expression Handlers
'''
from control_flow_graph.node_processor.nodes import ExpressionStatement
from static_analysis.dataflow_analysis.avl_expr.expr_builder.objects import ExpressionStatement as ExpStmt
from static_analysis.dataflow_analysis.avl_expr.expr_builder.common import traverse_expression_object


def build(node: ExpressionStatement) -> ExpStmt:
    '''
    Recursively build the expression object
    '''

    # obtain the expression property
    expression = node.expression

    # init symbol sets
    left_symbols, right_symbols = set(), set()

    # handle assignment nodes
    if expression.node_type == 'Assignment':
        # traverse and generate the left hand side
        left = traverse_expression_object(
            expression.leftHandSide, left_symbols)

        # traverse and generate the right hand side
        right = traverse_expression_object(
            expression.rightHandSide, right_symbols)

        # render the expression
        expr_str = f'{left} {expression.operator} {right}'

        # create the expression object
        expr = ExpStmt(expr_str, left, right,
                       left_symbols, right_symbols)

        return expr

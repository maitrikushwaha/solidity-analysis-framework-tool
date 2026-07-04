'''
VariableDeclarationStatement Expression Handlers
'''
from control_flow_graph.node_processor.nodes import VariableDeclarationStatement
from static_analysis.dataflow_analysis.avl_expr.expr_builder.objects import ExpressionStatement as ExpStmt
from static_analysis.dataflow_analysis.avl_expr.expr_builder.common import traverse_expression_object


def build(node: VariableDeclarationStatement) -> ExpStmt:
    '''
    Recursively build the variable declaration object
    '''

    left_symbols, right_symbols = set(), set()

    # obtain the left hand assignment symbol
    left = node.declarations[0].name
    # add the assignment to the set of symbols
    left_symbols.add(left)

    # if there is an initial value, traverse the right hand assignment
    if node.initialValue is not None:
        # traverse and generate the right hand assignment
        right = traverse_expression_object(
            node.initialValue, right_symbols)

        # generate the overall expression stmt
        expr_str = f'{left} = {right}'

        # create the expression object
        expr = ExpStmt(expr_str, left, right,
                       left_symbols, right_symbols)

        return expr
    else:
        # in this case, the expression stmt, and the right will be null
        expr = ExpStmt('', left, '',
                       left_symbols, right_symbols)

        return expr

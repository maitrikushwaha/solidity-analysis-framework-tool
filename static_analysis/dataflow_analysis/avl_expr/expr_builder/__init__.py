'''
Expression Builder Module
'''

from control_flow_graph.node_processor import Node
from static_analysis.dataflow_analysis.avl_expr.expr_builder.objects import ExpressionStatement
import static_analysis.dataflow_analysis.avl_expr.expr_builder.nodes as nodes


def expr_builder(node: Node) -> ExpressionStatement:
    '''
    Expression Builder Function to handle them node-wise
    '''

    node_module = getattr(nodes, node.node_type, None)

    if node_module is None:
        return None

    return node_module.build(node)

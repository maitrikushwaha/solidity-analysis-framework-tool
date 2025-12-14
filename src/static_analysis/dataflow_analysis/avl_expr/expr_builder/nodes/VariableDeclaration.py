'''
VariableDeclaration Expression Handlers for Global Variables
'''
from control_flow_graph.node_processor.nodes import VariableDeclaration
from static_analysis.dataflow_analysis.avl_expr.expr_builder.objects import ExpressionStatement as ExpStmt
from static_analysis.dataflow_analysis.avl_expr.expr_builder.common import traverse_expression_object


def build(node: VariableDeclaration) -> ExpStmt:
    '''
    Recursively build the variable declaration object for global variables.
    Only processes global variables (state variables).
    '''

    left_symbols, right_symbols = set(), set()

    # Check if the variable is a state variable (global)
    if node.stateVariable:
        # It's a state variable (global), so process it
        left = node.name
        left_symbols.add(left)

        # If there is an initial value, traverse the right hand assignment
        if node.value is not None:
            # Traverse and generate the right hand assignment (initial value)
            right = traverse_expression_object(
                node.value, right_symbols
            )

            # Generate the overall expression statement
            expr_str = f'{left} = {right}'

            # Create the expression object
            expr = ExpStmt(expr_str, left, right,
                           left_symbols, right_symbols)

            print(f"Global variable assignment: {expr_str}")  # Debugging print for global assignment
            return expr
        else:
            # If there's no initial value, just process the variable name
            expr = ExpStmt('', left, '',
                           left_symbols, right_symbols)

            print(f"Global variable declared without assignment: {left}")  # Debugging print for no initial value
            return expr
    else:
        # It's a local variable, skip processing
        print(f"Local variable {node.name} detected but skipped.")  # Debugging print for skipped local variable
        return None
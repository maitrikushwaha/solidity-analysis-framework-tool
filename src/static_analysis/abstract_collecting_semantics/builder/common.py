from typing import Tuple, Any, Union
from java_wrapper import java, apron
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor import Node

# Class to represent Bottom (⊥) in abstract interpretation
class Bottom:
    def __init__(self):
        self.node_type = 'Bottom'

    def __repr__(self):
        return '⊥'


def traverse_expression_object(node: Node, identifiers: set) -> str:
    '''
    Recursively traverse the expression node and generate the expression
    '''
    if node.node_type == 'Literal':
        return str(node.value)

    if node.node_type == 'Identifier':
        identifiers.add(node.name)
        return node.name

    if node.node_type == 'Assignment':
        return f'{traverse_expression_object(node.leftHandSide, identifiers)} {node.operator} {traverse_expression_object(node.rightHandSide, identifiers)}'

    if node.node_type == 'BinaryOperation':
        return f'{traverse_expression_object(node.leftExpression, identifiers)} {node.operator} {traverse_expression_object(node.rightExpression, identifiers)}'

    if node.node_type == 'UnaryOperation':
        return f"{node.operator}({traverse_expression_object(node.expression, identifiers)})"
    
    if node.node_type == 'Conditional':
        condition_str = traverse_expression_object(node.condition, identifiers)
        true_str = traverse_expression_object(node.trueExpression, identifiers)
        false_str = traverse_expression_object(node.falseExpression, identifiers)
        return f"({condition_str}) ? ({true_str}) : ({false_str})"

    if node.node_type == 'Bottom':
        return '⊥'

    raise Exception(f'Handlers for node type {node.node_type} not implemented yet!')


def compute_expression_object(node: Union[Node, dict], var_registry: VariableRegistry, const_registry: VariableRegistry,
                              abstract_state: apron.Abstract0, manager: apron.Manager) -> Union[apron.Texpr0Intern, Bottom]:
    '''
    Recursively Compute the Expression Object and return the value as Texpr0Intern.
    Propagates Bottom if necessary.
    '''

    # If node is Bottom, propagate Bottom
    if isinstance(node, Bottom) or (isinstance(node, dict) and node.get('nodeType') == 'Bottom'):
        return Bottom()

    # Handle dict-type nodes
    if isinstance(node, dict):
        if node.get('nodeType') == 'Literal':
            const_expr = apron.Texpr0CstNode(apron.MpqScalar(int(node['value'])))
            return apron.Texpr0Intern(const_expr)

        if node.get('nodeType') == 'Identifier':
            node_name = node.get('name')
            if node_name in var_registry.variable_table.keys():
                dim_node = apron.Texpr0DimNode(var_registry.get_id(node_name))
                return apron.Texpr0Intern(dim_node)
            elif node_name in const_registry.variable_table.keys():
                const_value = const_registry.get_value(node_name)

                # Handle constant as interval if it's a tuple
                if isinstance(const_value, tuple) and len(const_value) == 2:
                    interval = apron.Texpr0CstNode(apron.Interval(int(const_value[0]), int(const_value[1])))
                    return apron.Texpr0Intern(interval)
                elif isinstance(const_value, str):
                    if const_value == 'top':
                        interval = apron.Interval()
                        interval.setTop()
                        return apron.Texpr0CstNode(interval)
                    else:
                        const_expr = apron.Texpr0CstNode(apron.MpqScalar(int(const_value)))
                        return apron.Texpr0Intern(const_expr)
                else:
                    raise Exception(f'Illegal value for Constant {node_name}! Value: {const_value}')
            else:
                return Bottom()  # Return Bottom if variable not found

        if node.get('nodeType') == 'BinaryOperation':
            left = compute_expression_object(
                node['leftExpression'], var_registry, const_registry, abstract_state, manager)
            right = compute_expression_object(
                node['rightExpression'], var_registry, const_registry, abstract_state, manager)

            # If either left or right is Bottom, propagate Bottom
            if isinstance(left, Bottom) or isinstance(right, Bottom):
                return Bottom()

            return compute_binary_operation(left, right, node['operator'], abstract_state, manager)

        if node.get('nodeType') == 'UnaryOperation':
            operand = compute_expression_object(node['expression'], var_registry, const_registry, abstract_state, manager)
            
            # If operand is Bottom, propagate Bottom
            if isinstance(operand, Bottom):
                return Bottom()
            
            return compute_unary_operation(operand, node['operator'], abstract_state, manager)
        
        if node.get('nodeType') == 'Conditional':
                condition = compute_expression_object(node['condition'], var_registry, const_registry, abstract_state, manager)
                true_expr = compute_expression_object(node['trueExpression'], var_registry, const_registry, abstract_state, manager)
                false_expr = compute_expression_object(node['falseExpression'], var_registry, const_registry, abstract_state, manager)

                if isinstance(condition, Bottom) or isinstance(true_expr, Bottom) or isinstance(false_expr, Bottom):
                    return Bottom()

                condition_result = evaluate_boolean(condition, abstract_state, manager)
                return true_expr if condition_result else false_expr
    
    # Handle Node objects similarly
    if hasattr(node, 'node_type') and node.node_type == 'Literal':
        const_expr = apron.Texpr0CstNode(apron.MpqScalar(int(node.value)))
        return apron.Texpr0Intern(const_expr)

    if hasattr(node, 'node_type') and node.node_type == 'Identifier':
        if node.name in var_registry.variable_table.keys():
            dim_node = apron.Texpr0DimNode(var_registry.get_id(node.name))
            return apron.Texpr0Intern(dim_node)
        elif node.name in const_registry.variable_table.keys():
            const_value = const_registry.get_value(node.name)

            # Handle constant as interval if it's a tuple
            if isinstance(const_value, tuple) and len(const_value) == 2:
                interval = apron.Texpr0CstNode(apron.Interval(int(const_value[0]), int(const_value[1])))
                return apron.Texpr0Intern(interval)
            elif isinstance(const_value, str):
                if const_value == 'top':
                    interval = apron.Interval()
                    interval.setTop()
                    return apron.Texpr0CstNode(interval)
                else:
                    const_expr = apron.Texpr0CstNode(apron.MpqScalar(int(const_value)))
                    return apron.Texpr0Intern(const_expr)
            else:
                raise Exception(f'Illegal value for Constant {node.name}! Value: {const_value}')
        else:
            return Bottom()  # Return Bottom if variable not found

    # Handle BinaryOperation node for Node objects
    if hasattr(node, 'node_type') and node.node_type == 'BinaryOperation':
        left = compute_expression_object(
            node.leftExpression, var_registry, const_registry, abstract_state, manager)
        right = compute_expression_object(
            node.rightExpression, var_registry, const_registry, abstract_state, manager)

        # If either left or right is Bottom, propagate Bottom
        if isinstance(left, Bottom) or isinstance(right, Bottom):
            return Bottom()

        return compute_binary_operation(left, right, node.operator, abstract_state, manager)
    
    # Handle UnaryOperation node for Node objects
    if hasattr(node, 'node_type') and node.node_type == 'UnaryOperation':
        print(vars(node))
        operand_node = node.subExpression if hasattr(node, 'subExpression') else node.get('subExpression')
        operand = compute_expression_object(operand_node, var_registry, const_registry, abstract_state, manager)

        # If operand is Bottom, propagate Bottom
        if isinstance(operand, Bottom):
            return Bottom()

        return compute_unary_operation(operand, node.operator, abstract_state, manager)
    
    if hasattr(node, 'node_type') and node.node_type == 'Conditional':
        condition = compute_expression_object(node.condition, var_registry, const_registry, abstract_state, manager)
        true_expr = compute_expression_object(node.trueExpression, var_registry, const_registry, abstract_state, manager)
        false_expr = compute_expression_object(node.falseExpression, var_registry, const_registry, abstract_state, manager)

        if isinstance(condition, Bottom) or isinstance(true_expr, Bottom) or isinstance(false_expr, Bottom):
            return Bottom()

        condition_result = evaluate_boolean(condition, abstract_state, manager)
        return true_expr if condition_result else false_expr
    
    node_type = getattr(node, 'node_type', getattr(node, 'nodeType', getattr(node, 'type', 'Unknown')))
    print("[DEBUG] Unhandled node:", node)
    print("[DEBUG] node_type:", node_type)
    raise Exception(f'Handlers for node type {node_type} not implemented yet!')

def compute_unary_operation(operand, operator: str, abstract_state: apron.Abstract0, manager: apron.Manager):
    '''
    Compute a unary operation based on the operand and operator.
    Propagates Bottom if the operand is Bottom.
    '''

    # If operand is Bottom, propagate Bottom
    if isinstance(operand, Bottom):
        return Bottom()

    # Handle unary operations
    if operator == '-':
        if isinstance(operand, apron.Texpr0Intern):
            operand_node = operand.toTexpr0Node()
            return apron.Texpr0UnNode(apron.Texpr0UnNode.OP_NEG, operand_node)
        else:
            raise TypeError(f"Unexpected type for operand: {type(operand)}")

    # Handle logical NOT (!)
    if operator == '!':
        return not evaluate_boolean(operand, abstract_state, manager)  # Convert operand to a boolean

    raise ValueError(f"Unsupported unary operator: {operator}")

def compute_binary_operation(left, right, operator: str, abstract_state: apron.Abstract0, manager: apron.Manager):
    '''
    Compute a binary operation based on the lhs, rhs, and operator.
    Propagates Bottom if one of the operands is Bottom.
    '''

    # If either operand is Bottom, propagate Bottom
    if isinstance(left, Bottom) or isinstance(right, Bottom):
        return Bottom()

    # Arithmetic operations mapping
    arithmetic_op_mapping = {
        '+': apron.Texpr0BinNode.OP_ADD,
        '-': apron.Texpr0BinNode.OP_SUB,
        '*': apron.Texpr0BinNode.OP_MUL,
        '/': apron.Texpr0BinNode.OP_DIV,
        '%': apron.Texpr0BinNode.OP_MOD
    }

    # Comparison operations mapping
    comparison_op_mapping = {
        '<': 'lt',
        '<=': 'le',
        '>': 'gt',
        '>=': 'ge',
        '==': 'eq',
        '!=': 'ne'
    }

    # Logical operations for boolean evaluation
    if operator == '&&':
        return evaluate_boolean(left, abstract_state, manager) and evaluate_boolean(right, abstract_state, manager)
    elif operator == '||':
        return evaluate_boolean(left, abstract_state, manager) or evaluate_boolean(right, abstract_state, manager)

    # Ensure both operands are converted to Texpr0Node
    if isinstance(left, apron.Texpr0Intern):
        left_node = left.toTexpr0Node()  # Convert Texpr0Intern to Texpr0Node
    elif isinstance(left, apron.Texpr0Node):
        left_node = left  # Use Texpr0Node directly
    else:
        raise TypeError(f"Unexpected type for left operand: {type(left)}")

    if isinstance(right, apron.Texpr0Intern):
        right_node = right.toTexpr0Node()  # Convert Texpr0Intern to Texpr0Node
    elif isinstance(right, apron.Texpr0Node):
        right_node = right  # Use Texpr0Node directly
    else:
        raise TypeError(f"Unexpected type for right operand: {type(right)}")

    # Handle arithmetic operations
    if operator in arithmetic_op_mapping:
        return apron.Texpr0BinNode(arithmetic_op_mapping[operator], left_node, right_node)

    # Handle comparison operations
    if operator in comparison_op_mapping:
        interval_left = abstract_state.getBound(manager, apron.Texpr0Intern(left_node))
        interval_right = abstract_state.getBound(manager, apron.Texpr0Intern(right_node))
        return compare_intervals(interval_left, interval_right, operator)

    raise ValueError(f"Unsupported operator: {operator}")


# def evaluate_boolean(value, abstract_state, manager):
#     '''
#     Evaluate a value (Texpr0Intern or interval) as a boolean.
#     '''
#     if isinstance(value, apron.Texpr0Intern):
#         interval = abstract_state.getBound(manager, value)
#         # If the interval includes 0, it's false; otherwise, it's true
#         return not interval.contains(0)
#     elif isinstance(value, apron.Interval):
#         return not value.contains(0)
#     elif isinstance(value, bool):
#         return value
#     else:
#         raise TypeError(f"Unexpected type for boolean evaluation: {type(value)}")

def evaluate_boolean(value, abstract_state, manager):
    '''
    Evaluate a value (Texpr0Intern or interval) as a boolean.
    '''
    if isinstance(value, apron.Texpr0Intern):
        interval = abstract_state.getBound(manager, value)  # Get the interval bounds
        return is_nonzero_interval(interval)  # Check if interval contains zero

    elif isinstance(value, apron.Interval):
        return is_nonzero_interval(value)  # Check if interval contains zero

    elif isinstance(value, bool):
        return value  # Already a boolean

    else:
        raise TypeError(f"Unexpected type for boolean evaluation: {type(value)}")


def is_nonzero_interval(interval: apron.Interval) -> bool:
    '''
    Check if an interval definitely does NOT include zero.
    '''
    if interval.isBottom():
        return False  # A bottom interval is equivalent to false

    # Get the lower and upper bounds of the interval
    lower = float(interval.inf().val)  # Convert to float for safe comparisons
    upper = float(interval.sup().val)

    # Check if zero lies within the interval
    return not (lower <= 0 <= upper)


def compare_intervals(interval_left: apron.Interval, interval_right: apron.Interval, operator: str) -> bool:
    '''
    Compare two intervals based on the given operator.
    '''
    if operator == '==':
        return interval_left.isEqual(interval_right)
    elif operator == '!=':
        return not interval_left.isEqual(interval_right)
    elif operator == '<':
        return interval_left.sup().cmp(interval_right.inf()) < 0
    elif operator == '<=':
        return interval_left.sup().cmp(interval_right.inf()) <= 0
    elif operator == '>':
        return interval_left.inf().cmp(interval_right.sup()) > 0
    elif operator == '>=':
        return interval_left.inf().cmp(interval_right.sup()) >= 0
    else:
        raise ValueError(f"Unsupported comparison operator: {operator}")


def generate_undef_state(variable_reg: VariableRegistry, manager: apron.Manager) -> apron.Abstract0:
    '''
    Generate the initial abstract state tuple based on the variables present in the variable registry.
    '''
    variables = variable_reg.variable_table.keys()
    int_variables_count = len(variables)
    box_state = [apron.Interval() for _ in variables]
    return apron.Abstract0(manager, int_variables_count, 0, box_state)


def generate_bottom_state(variable_reg: VariableRegistry, manager: apron.Manager) -> apron.Abstract0:
    '''
    Generate the initial bottom state based on the variables in the variable registry.
    '''
    variables = variable_reg.variable_table.keys()
    int_variables_count = len(variables)
    box_state = [apron.Interval() for _ in variables]
    for interval in box_state:
        interval.setBottom()
    return apron.Abstract0(manager, int_variables_count, 0, box_state)

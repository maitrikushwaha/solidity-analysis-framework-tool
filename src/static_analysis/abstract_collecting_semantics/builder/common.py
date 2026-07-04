from platform import node
from typing import Tuple, Any, Union
from java_wrapper import java, apron
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from control_flow_graph.node_processor import Node

# Java long limits — values outside this range cannot be represented as MpqScalar
_JAVA_LONG_MAX = 2**63 - 1

def _safe_parse_literal(raw):
    """Parse a Solidity literal value to a Python int for Apron, or return None.

    Handles: decimal ints, hex ints (0x...), boolean literals (true/false),
    and guards against values exceeding Java's long range.
    Returns None for string literals, addresses too large for long, and
    any other non-numeric value — the caller should use ⊤ (top) instead.
    """
    if raw is None:
        return 0
    s = str(raw).strip()
    # Boolean literals
    if s == 'true':
        return 1
    if s == 'false':
        return 0
    # Numeric (decimal or hex)
    try:
        val = int(s, 0)  # auto-detects 0x prefix
        if abs(val) > _JAVA_LONG_MAX:
            return None   # too large for MpqScalar → caller uses top
        return val
    except (ValueError, TypeError):
        return None       # string literal, etc. → caller uses top

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
        sub = getattr(node, 'subExpression', None) or getattr(node, 'expression', None)
        return f"{node.operator}({traverse_expression_object(sub, identifiers)})"
    
    if node.node_type == 'Conditional':
        condition_str = traverse_expression_object(node.condition, identifiers)
        true_str = traverse_expression_object(node.trueExpression, identifiers)
        false_str = traverse_expression_object(node.falseExpression, identifiers)
        return f"({condition_str}) ? ({true_str}) : ({false_str})"

    if node.node_type == 'MemberAccess':
        expr_part = getattr(node, 'expression', None)
        member = getattr(node, 'memberName', getattr(node, 'member_name', ''))
        if expr_part is not None:
            base = traverse_expression_object(expr_part, identifiers)
            flat_name = f"{base}_{member}" if member else base
        else:
            flat_name = member or 'unknown'
        identifiers.add(flat_name)
        return flat_name

    if node.node_type == 'FunctionCall':
        # Function calls don't contribute LHS variables
        return 'fn_call'

    if node.node_type == 'IndexAccess':
        base_expr = getattr(node, 'baseExpression', getattr(node, 'base_expression', None))
        index_expr = getattr(node, 'indexExpression', getattr(node, 'index_expression', None))
        if base_expr is not None:
            base = traverse_expression_object(base_expr, identifiers)
        else:
            base = 'arr'
        if index_expr is not None:
            idx = traverse_expression_object(index_expr, identifiers)
        else:
            idx = 'i'
        flat_name = f"{base}_{idx}"
        identifiers.add(flat_name)
        return flat_name

    if node.node_type == 'TupleExpression':
        components = getattr(node, 'components', [])
        parts = []
        for comp in components:
            if comp is not None:
                parts.append(traverse_expression_object(comp, identifiers))
        return ', '.join(parts) if parts else 'tuple'

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
            raw = node.get('value', '0')
            parsed_int = _safe_parse_literal(raw)
            if parsed_int is not None:
                # Value fits in Java long — use exact scalar
                const_expr = apron.Texpr0CstNode(apron.MpqScalar(parsed_int))
                return apron.Texpr0Intern(const_expr)
            else:
                # Non-numeric or out-of-range → sound top
                interval = apron.Interval()
                interval.setTop()
                return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

        if node.get('nodeType') == 'Identifier':
            node_name = node.get('name')
            if node_name in var_registry.variable_table.keys():
                dim_node = apron.Texpr0DimNode(var_registry.get_id(node_name))
                return apron.Texpr0Intern(dim_node)
            elif node_name in const_registry.variable_table.keys():
                const_value = const_registry.get_value(node_name)

                # Handle constant as interval if it's a tuple
                if isinstance(const_value, tuple) and len(const_value) == 2:
                    # Guard against values too large for Java's long
                    if abs(int(const_value[0])) > 2**63-1 or abs(int(const_value[1])) > 2**63-1:
                        interval = apron.Interval()
                        interval.setTop()
                        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))
                    interval = apron.Texpr0CstNode(apron.Interval(int(const_value[0]), int(const_value[1])))
                    return apron.Texpr0Intern(interval)
                elif isinstance(const_value, str):
                    if const_value == 'top':
                        interval = apron.Interval()
                        interval.setTop()
                        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))
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
            sub_expr = node.get('subExpression') or node.get('expression')
            operand = compute_expression_object(sub_expr, var_registry, const_registry, abstract_state, manager)

            
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
        raw = getattr(node, 'value', '0')
        parsed_int = _safe_parse_literal(raw)
        if parsed_int is not None:
            const_expr = apron.Texpr0CstNode(apron.MpqScalar(parsed_int))
            return apron.Texpr0Intern(const_expr)
        else:
            interval = apron.Interval()
            interval.setTop()
            return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

    if hasattr(node, 'node_type') and node.node_type == 'Identifier':
        if node.name in var_registry.variable_table.keys():
            dim_node = apron.Texpr0DimNode(var_registry.get_id(node.name))
            return apron.Texpr0Intern(dim_node)
        elif node.name in const_registry.variable_table.keys():
            const_value = const_registry.get_value(node.name)

            # Handle constant as interval if it's a tuple
            if isinstance(const_value, tuple) and len(const_value) == 2:
                # Guard against values too large for Java's long
                if abs(int(const_value[0])) > 2**63-1 or abs(int(const_value[1])) > 2**63-1:
                    interval = apron.Interval()
                    interval.setTop()
                    return apron.Texpr0Intern(apron.Texpr0CstNode(interval))
                interval = apron.Texpr0CstNode(apron.Interval(int(const_value[0]), int(const_value[1])))
                return apron.Texpr0Intern(interval)
            elif isinstance(const_value, str):
                if const_value == 'top':
                    interval = apron.Interval()
                    interval.setTop()
                    return apron.Texpr0Intern(apron.Texpr0CstNode(interval))
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
        # FIX: use getattr (node is a Node object, not a dict — .get() would AttributeError)
        operand_node = getattr(node, 'subExpression', None) or getattr(node, 'expression', None)
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
    
    # Handle FunctionCall (e.g. require(...), assert(...)) — treat as top
    if (isinstance(node, dict) and node.get('nodeType') == 'FunctionCall') or \
       (hasattr(node, 'node_type') and node.node_type == 'FunctionCall'):
        interval = apron.Interval()
        interval.setTop()
        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

    # Handle MemberAccess (e.g. msg.sender, msg.value) — treat as top
    if (isinstance(node, dict) and node.get('nodeType') == 'MemberAccess') or \
       (hasattr(node, 'node_type') and node.node_type == 'MemberAccess'):
        interval = apron.Interval()
        interval.setTop()
        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

    # Handle chained Assignment (e.g. a = b = expr) — evaluate the RHS
    if (isinstance(node, dict) and node.get('nodeType') == 'Assignment'):
        rhs = node.get('rightHandSide')
        if rhs:
            return compute_expression_object(rhs, var_registry, const_registry, abstract_state, manager)
        return Bottom()
    if hasattr(node, 'node_type') and node.node_type == 'Assignment':
        rhs = getattr(node, 'rightHandSide', None)
        if rhs:
            return compute_expression_object(rhs, var_registry, const_registry, abstract_state, manager)
        return Bottom()

    # Handle IndexAccess (e.g. balances[addr]) — treat as top
    if (isinstance(node, dict) and node.get('nodeType') == 'IndexAccess') or \
       (hasattr(node, 'node_type') and node.node_type == 'IndexAccess'):
        interval = apron.Interval()
        interval.setTop()
        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

    # Handle TupleExpression (e.g. (a, b)) — treat as top
    if (isinstance(node, dict) and node.get('nodeType') == 'TupleExpression') or \
       (hasattr(node, 'node_type') and node.node_type == 'TupleExpression'):
        interval = apron.Interval()
        interval.setTop()
        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

    # Fallback: any unhandled node type returns top (sound over-approximation)
    # instead of crashing the analysis.
    node_type = getattr(node, 'node_type', None)
    if node_type is None and isinstance(node, dict):
        node_type = node.get('nodeType', 'Unknown')
    interval = apron.Interval()
    interval.setTop()
    return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

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
        result = not evaluate_boolean(operand, abstract_state, manager)
        const_expr = apron.Texpr0CstNode(apron.MpqScalar(1 if result else 0))
        return apron.Texpr0Intern(const_expr)


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
        result = evaluate_boolean(left, abstract_state, manager) and evaluate_boolean(right, abstract_state, manager)
        return apron.Texpr0Intern(apron.Texpr0CstNode(apron.MpqScalar(1 if result else 0)))
    elif operator == '||':
        result = evaluate_boolean(left, abstract_state, manager) or evaluate_boolean(right, abstract_state, manager)
        return apron.Texpr0Intern(apron.Texpr0CstNode(apron.MpqScalar(1 if result else 0)))

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
        try:
            interval_left = abstract_state.getBound(manager, apron.Texpr0Intern(left_node))
            interval_right = abstract_state.getBound(manager, apron.Texpr0Intern(right_node))
            return compare_intervals(interval_left, interval_right, operator)
        except (AttributeError, Exception):
            # abstract_state not available or not Abstract0; return top
            interval = apron.Interval()
            interval.setTop()
            return apron.Texpr0Intern(apron.Texpr0CstNode(interval))

    if operator in ('**', '&', '|', '^', '~', '<<', '>>', '>>>'):
        interval = apron.Interval()
        interval.setTop()
        return apron.Texpr0Intern(apron.Texpr0CstNode(interval))
    
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
        # FIX: abstract_state may be a dict (unvisited node state) in some
        # IfStatement condition evaluation paths — guard getBound call
        try:
            interval = abstract_state.getBound(manager, value)
        except (AttributeError, Exception):
            return True  # unknown → conservatively treat as nonzero (top)
        return is_nonzero_interval(interval)

    elif isinstance(value, apron.Interval):
        return is_nonzero_interval(value)

    elif isinstance(value, bool):
        return value

    else:
        raise TypeError(f"Unexpected type for boolean evaluation: {type(value)}")


def _scalar_to_float(scalar) -> float:
    '''Convert an Apron scalar bound to a Python float, robust to the gmp.Mpq
    rationals that the relational domains (Octagon/Polyhedra) produce and to
    +/- infinity.  Box returns plain doubles; Octagon/Polka return Mpq, which
    float() cannot consume directly (TypeError).'''
    # Apron scalars expose sign-of-infinity via isInfty() (-1/0/+1).
    try:
        sgn = scalar.isInfty()
        if sgn < 0:
            return float('-inf')
        if sgn > 0:
            return float('inf')
    except Exception:
        pass
    val = getattr(scalar, 'val', scalar)
    try:
        return float(val)            # DoubleScalar / plain numeric
    except (TypeError, ValueError):
        pass
    # gmp.Mpq (MpqScalar): parse its "p/q" string representation.
    try:
        s = str(val)
        if '/' in s:
            num, den = s.split('/', 1)
            return float(num) / float(den)
        return float(s)
    except Exception:
        return float('nan')


def is_nonzero_interval(interval: apron.Interval) -> bool:
    '''
    Check if an interval definitely does NOT include zero.
    '''
    if interval.isBottom():
        return False  # A bottom interval is equivalent to false

    # Get the lower and upper bounds of the interval (robust to Mpq / infinity)
    lower = _scalar_to_float(interval.inf())
    upper = _scalar_to_float(interval.sup())

    # NaN (unconvertible bound) → conservatively treat as possibly-zero (top).
    if lower != lower or upper != upper:  # NaN check
        return False

    # Check if zero lies within the interval
    return not (lower <= 0 <= upper)


def compare_intervals(interval_left: apron.Interval, interval_right: apron.Interval, operator: str):
    '''
    Compare two intervals based on the given operator.
    Returns a Texpr0Intern wrapping 0 or 1 (not a raw Python bool),
    so the result can be safely used wherever an Apron expression is expected.
    '''
    if operator == '==':
        result = interval_left.isEqual(interval_right)
    elif operator == '!=':
        result = not interval_left.isEqual(interval_right)
    elif operator == '<':
        result = interval_left.sup().cmp(interval_right.inf()) < 0
    elif operator == '<=':
        result = interval_left.sup().cmp(interval_right.inf()) <= 0
    elif operator == '>':
        result = interval_left.inf().cmp(interval_right.sup()) > 0
    elif operator == '>=':
        result = interval_left.inf().cmp(interval_right.sup()) >= 0
    else:
        raise ValueError(f"Unsupported comparison operator: {operator}")
    const_expr = apron.Texpr0CstNode(apron.MpqScalar(1 if result else 0))
    return apron.Texpr0Intern(const_expr)


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
from java_wrapper import apron
from static_analysis.abstract_collecting_semantics.builder.common import compute_expression_object, Bottom


def evaluate_return_expression_as_interval(return_expr, var_registry, const_registry, abstract_state, manager):
    """
    Evaluates a return expression and returns its interval.
    """
    if not return_expr:
        return None

    try:
        expr = compute_expression_object(return_expr, var_registry, const_registry, abstract_state, manager)
        if isinstance(expr, Bottom):
            return None

        interval = abstract_state.getBound(manager, expr)
        return expr, interval
    except Exception as e:
        print(f"Error in evaluating return expression: {e}")
        return None

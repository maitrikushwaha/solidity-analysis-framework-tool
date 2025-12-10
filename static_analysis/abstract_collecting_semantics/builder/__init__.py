'''
The Builder Module for Collecting Semantics
'''

from typing import Set, Tuple, Any, Dict
from copy import deepcopy
from java_wrapper import apron
from control_flow_graph.node_processor import Node
import static_analysis.abstract_collecting_semantics.builder.nodes as nodes
from static_analysis.abstract_collecting_semantics.objects import VariableRegistry
from java_wrapper.apron import _Interval,_Texpr0CstNode, _Texpr0Intern

def get_variables(node: Node) -> Set[str]:
    '''
    Function to obtain the variables from expressions node-wise
    '''

    node_module = getattr(nodes, node.node_type, None)

    if node_module is None:
        return set()

    return node_module.get_variables(node)


def generate_exit_sets(node: Node, entry_set: apron.Abstract0, exit_sets: Dict[str, apron.Abstract0],
                       var_registry: VariableRegistry, const_registry: VariableRegistry,
                       manager: apron.Manager) -> Dict[str, apron.Abstract0]:
    '''
    Function to compute the exit set(s) from the given entry set and node semantics,
    while ensuring global variables (state variables) retain their values in each exit set.
    '''

    # Dynamically load the module specific to the node type
    node_module = getattr(nodes, node.node_type, None)

    # If the node type has no specific module, return a default exit set
    if node_module is None:
        default_exit_set = apron.Abstract0(manager, entry_set)
        # Retain global variables in the default exit set
        for variable, details in var_registry.variable_table.items():
            if details['stateVariable']:
                variable_id = details['id']
                last_value = var_registry.get_value(variable)
                if isinstance(last_value, _Interval):
                    if last_value.inf().equals(last_value.sup()):
                        scalar = last_value.inf()
                        const_node = _Texpr0CstNode(scalar)
                        expr = _Texpr0Intern(const_node)
                    else:
                        raise NotImplementedError("Non-constant intervals are not supported.")
                else:
                    expr = last_value

                default_exit_set = default_exit_set.assignCopy(manager, variable_id, expr, None)
        return {'*': default_exit_set}

    # Generate exit sets from the node's specific semantics
    exit_sets = node_module.generate_exit_sets(node, entry_set, exit_sets, var_registry, const_registry, manager)

    
    return exit_sets   

# kk, this is prone
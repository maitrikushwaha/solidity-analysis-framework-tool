import logging
'''
Class definition for the EmitStatement CFG (AST) node.

Solidity `emit EventName(...)` statements.  These are treated as
simple statements with no control-flow effect.
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class EmitStatement(Node):
    '''
    EmitStatement Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        super(EmitStatement, self).__init__(
            ast_node, entry_node_id, prev_node_id,
            exit_node_id, cfg_metadata)

        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'EmitStatement'
        self.add_prev_node(prev_node_id)
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        logging.debug(f'Processing CFG Node {self.cfg_id}')

        # Parse the event call expression if present
        event_call = ast_node.get('eventCall', {})
        if event_call:
            expr_type = event_call.get('nodeType')
            expr_class = getattr(nodes, expr_type, None) if expr_type else None
            if expr_class:
                self.event_call = expr_class(
                    event_call, None, None, None, self.cfg_metadata)
            else:
                self.event_call = None
        else:
            self.event_call = None

        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        child_leaves = set()
        for node_id in self.next_nodes.keys():
            node = self.cfg_metadata.get_node(node_id)
            if node is not None:
                child_leaves.update(node.get_leaf_nodes())
        if child_leaves:
            self.leaves = set(child_leaves)
        return self.leaves

    def get_whois_next_node(self) -> str:
        return self.cfg_id
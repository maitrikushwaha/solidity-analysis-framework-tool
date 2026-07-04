import logging
'''
Class definition for the RevertStatement CFG (AST) node.

Solidity `revert CustomError(...)` — terminates execution.
Treated as a terminal statement (similar to Throw / Return).
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node


class RevertStatement(Node):
    '''
    RevertStatement Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        super(RevertStatement, self).__init__(
            ast_node, entry_node_id, prev_node_id,
            exit_node_id, cfg_metadata)

        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'RevertStatement'
        self.add_prev_node(prev_node_id)
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        logging.debug(f'Processing CFG Node {self.cfg_id}')
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
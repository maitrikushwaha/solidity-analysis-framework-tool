import logging
'''
Class definition for the UncheckedBlock CFG (AST) node.

Solidity >= 0.8 introduced checked arithmetic by default.
The `unchecked { ... }` block disables overflow/underflow checks
for the statements it wraps.  In the AST the compiler emits a node
of type "UncheckedBlock" whose shape is identical to a regular
Block node (it carries a `statements` array).

This node transparently processes its child statements and wires
them into the CFG just like FunctionDefinition or ForStatement do
for their body blocks.  It also annotates every descendant CFG
node with `unchecked = True` so that the overflow/underflow
detector can honour the programmer's intent.
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class UncheckedBlock(Node):
    '''
    UncheckedBlock Node — transparent wrapper that marks its body
    as unchecked arithmetic.
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(UncheckedBlock, self).__init__(
            ast_node, entry_node_id, prev_node_id,
            exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'UncheckedBlock'

        # link the previous node
        self.add_prev_node(prev_node_id)

        # register the node
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        logging.debug(f'Processing CFG Node {self.cfg_id}')

        # Mark this node itself as unchecked
        self.unchecked = True

        # ---- Process child statements (same pattern as FunctionDefinition) ----
        body_statements = ast_node.get('statements', [])

        self._child_nodes = []
        body_prev_statement = self.cfg_id

        for i, statement in enumerate(body_statements):
            child_node_type = statement['nodeType']
            childConstructor = getattr(nodes, child_node_type, Node)

            child_node = childConstructor(
                statement, entry_node_id, body_prev_statement,
                exit_node_id, cfg_metadata)

            # Mark every child as unchecked so the overflow detector
            # can tell these operations are intentionally wrapping.
            child_node.unchecked = True

            self._child_nodes.append(child_node)

            # Link previous → current
            prev_node_obj = self.cfg_metadata.get_node(body_prev_statement)
            if prev_node_obj is not None:
                prev_leaves = prev_node_obj.get_leaf_nodes()
                to_link = (body_prev_statement
                           if len(prev_leaves) == 0
                           else next(iter(prev_leaves)))
                link_node = self.cfg_metadata.get_node(to_link)
                if link_node is not None:
                    link_node.add_next_node(child_node.cfg_id)

            body_prev_statement = (child_node.cfg_id
                                   if child_node.join_node is None
                                   else child_node.join_node)

        # Set leaf nodes
        if self._child_nodes:
            last_child = self._child_nodes[-1]
            self.leaves = last_child.get_leaf_nodes().copy()
        else:
            self.leaves.add(self.cfg_id)

    # ------------------------------------------------------------------
    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf nodes in the current branch.
        '''
        child_leaves = set()

        for node_id in self.next_nodes.keys():
            node = self.cfg_metadata.get_node(node_id)
            if node is not None:
                _leaves = node.get_leaf_nodes()
                child_leaves.update(_leaves)

        if len(child_leaves) > 0:
            self.leaves = set()
            self.leaves.update(child_leaves)

        return self.leaves

    def get_whois_next_node(self) -> str:
        '''
        The "next node" for linking purposes is this node itself
        (the first child is wired internally).
        '''
        return self.cfg_id
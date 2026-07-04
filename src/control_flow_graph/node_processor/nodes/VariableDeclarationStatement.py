import logging
'''
Class definition for the VariableDeclarationStatement CFG (AST) node

FIX: Handle null entries in declarations array.
     Solidity tuple destructuring like (bool success, ) = ... produces
     declarations: [{ nodeType: "VariableDeclaration", ... }, null]
     The null entry must be skipped to avoid TypeError.

FIX: Handle missing initialValue (set to None instead of crashing
     on dict key lookup).
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes

import logging


class VariableDeclarationStatement(Node):
    '''
    VariableDeclarationStatement Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(VariableDeclarationStatement, self).__init__(ast_node, entry_node_id, prev_node_id,
                                                           exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'VariableDeclarationStatement'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        logging.debug(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.assignments = ast_node.get('assignments', None)

        # FIX: Skip null entries in declarations array.
        self.declarations = []
        for declaration in ast_node.get('declarations', []):
            if declaration is None:
                continue
            node_type_str = declaration.get('nodeType', None)
            if node_type_str is None:
                continue
            decl_class = getattr(nodes, node_type_str, Node)
            self.declarations.append(
                decl_class(declaration, None, None, None, self.cfg_metadata)
            )

        # FIX: Handle missing or malformed initialValue gracefully.
        raw_init = ast_node.get('initialValue', None)
        if raw_init is not None and isinstance(raw_init, dict) and 'nodeType' in raw_init:
            init_class = getattr(nodes, raw_init['nodeType'], Node)
            self.initialValue = init_class(
                raw_init, None, None, None, self.cfg_metadata)
        else:
            self.initialValue = None

        # since it does not have any children, set this as the leaf node
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node

        Note that this might not have children, but this can be part of a Block statement,
        hence a chain of statements, therefore we check the next nodes for leaf nodes
        '''

        # init child leaves
        child_leaves = set()

        # recursively traverse all the nodes till we hit the leaf nodes
        for node_id in self.next_nodes.keys():
            # obtain the next node's instance
            node = self.cfg_metadata.get_node(node_id)

            # obtain their leaf nodes (recursive)
            _leaves = node.get_leaf_nodes()

            # add them to the child nodes
            child_leaves.update(_leaves)

        # now if there are leaf nodes obtained from the next node,
        # we need to drop the leaf nodes of the current node
        # and propogate the nodes of the next node as leaf nodes
        if len(child_leaves) > 0:
            # reset leaves
            self.leaves = set()

            # add the child nodes
            self.leaves.update(child_leaves)

        return self.leaves
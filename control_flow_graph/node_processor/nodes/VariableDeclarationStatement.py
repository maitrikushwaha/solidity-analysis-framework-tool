'''
Class definition for the VariableDeclarationStatement CFG (AST) node
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

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.assignments = ast_node.get('assignments', None)
        self.declarations = [getattr(nodes, declaration['nodeType'], Node)(declaration, None, None, None, self.cfg_metadata)
                             for declaration in ast_node.get('declarations', [])]
        self.initialValue = ast_node.get('initialValue', dict())
        self.initialValue = getattr(nodes, self.initialValue['nodeType'], Node)(
            self.initialValue, None, None, None, self.cfg_metadata)
        # set default value for initialValue if not provided
        # self.initialValue = ast_node.get('initialValue', None)
        # if self.initialValue is not None:
        #     self.initialValue = getattr(nodes, self.initialValue['nodeType'], Node)(
        #         self.initialValue, None, None, None, self.cfg_metadata)
        # else:
        #     # Provide a fallback or handle missing initial value as needed
        #     self.initialValue = None
        # since it does not have any children, set this as the leaf node
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node

        Note that this might not have children, but this can be part of a Block statemtent,
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





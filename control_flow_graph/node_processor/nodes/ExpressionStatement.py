'''
Class definition for the Expression Statement CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class ExpressionStatement(Node):
    '''
    Expression Statement Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(ExpressionStatement, self).__init__(ast_node, entry_node_id, prev_node_id,
                                                  exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'ExpressionStatement'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        # exported symbols from the source unit
        self.expression = ast_node.get('expression', dict())
        # self.expression = getattr(nodes, self.expression['nodeType'], Node)(
        #     self.expression, None, None, None, self.cfg_metadata)

        expression_node_type = self.expression['nodeType']
        expression_class = getattr(nodes, expression_node_type, None)

        if expression_class:
            self.expression = expression_class(
                self.expression, None, None, None, self.cfg_metadata
            )
        else:
            # Fallback: create a dummy Node with required fields to avoid crashes
            fallback = Node(self.expression, None, None, None, self.cfg_metadata)
            fallback.node_type = expression_node_type
            fallback.cfg_id = f"UnknownNode_{expression_node_type}_{self.cfg_id}"
            self.expression = fallback


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

'''
Class definition for the Contract Definition CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class ContractDefinition(Node):
    '''
    Contract Definition Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(ContractDefinition, self).__init__(ast_node, entry_node_id, prev_node_id,
                                                 exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.ClassBody
        self.node_type = 'ContractDefinition'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.baseContracts = ast_node.get('baseContracts', list())
        self.contractDependencies = ast_node.get(
            'contractDependencies', list())
        self.contractKind = ast_node.get('contractKind', None)
        self.documentation = ast_node.get('documentation', None)
        self.fullyImplemented = ast_node.get('fullyImplemented', None)
        self.linearizedBaseContracts = ast_node.get(
            'linearizedBaseContracts', list())
        self.name = ast_node.get('name', None)
        self.scope = ast_node.get('scope', None)

        # traverse the children and construct the rest of the CFG recursively
        for child in self.children:
            # obtain the child node's type
            child_node_type = child['nodeType']

            # obtain the child node's constructor
            childConstructor = getattr(nodes, child_node_type, Node)

            # initialize the child node (recursive)
            child_node = childConstructor(child, self.entry_node, self.cfg_id,
                                          self.exit_node, self.cfg_metadata)

            # add the child node's ID to the next_nodes list
            self.add_next_node(child_node.cfg_id)

            # obtain the leaf nodes from the child nodes (recursively, DFS)
            self.leaves.update(child_node.get_leaf_nodes())

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 
        '''

        # recursively traverse all the nodes till we hit the leaf nodes
        for node_id in self.next_nodes.keys():
            # obtain node instance of the child node
            node = self.cfg_metadata.get_node(node_id)

            # obtain the leaf nodes from the child node (recursively)
            _leaves = node.get_leaf_nodes()

            # update the leaf nodes for self
            self.leaves.update(_leaves)

        return self.leaves

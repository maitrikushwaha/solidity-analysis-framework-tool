'''
Class definition for the MemberAccess CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import BasicBlockTypes
from control_flow_graph.node_processor import Node
import control_flow_graph.node_processor.nodes as nodes


class MemberAccess(Node):
    '''
    MemberAccess Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(MemberAccess, self).__init__(ast_node, entry_node_id, prev_node_id,
                                           exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Statement
        self.node_type = 'MemberAccess'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and get a CFG ID
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.argumentTypes = ast_node.get('argumentTypes', None)
        self.memberName = ast_node.get('memberName', "")
        self.typeDescriptions = ast_node.get('typeDescriptions', dict())

        # build nested expression node (e.g., msg.sender.call)
        expression_ast = ast_node.get("expression", {})
        expression_class = getattr(nodes, expression_ast.get("nodeType", ""), Node)
        self.expression = expression_class(
            expression_ast, None, None, None, cfg_metadata
        )

        # add self as a leaf node
        self.leaves.add(self.cfg_id)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(s) for this MemberAccess
        '''
        return self.leaves

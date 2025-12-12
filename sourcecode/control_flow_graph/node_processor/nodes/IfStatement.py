'''
Class definition for the If Statement CFG (AST) node
'''
from control_flow_graph.node_processor import CFGMetadata
from control_flow_graph.node_processor import Node, BasicBlockTypes
import control_flow_graph.node_processor.nodes as nodes
from control_flow_graph.node_processor.nodes.extra_nodes.if_statement.join import IfConditionJoin


class IfStatement(Node):
    '''
    If Statement Node
    '''

    def __init__(self, ast_node: dict,
                 entry_node_id: str, prev_node_id: str,
                 exit_node_id: str, cfg_metadata: CFGMetadata):
        '''
        Constructor
        '''
        super(IfStatement, self).__init__(ast_node, entry_node_id, prev_node_id,
                                          exit_node_id, cfg_metadata)

        # set the basic block type and node type
        self.basic_block_type = BasicBlockTypes.Conditional
        self.node_type = 'IfStatement'

        # link the previous node to indexing
        self.add_prev_node(prev_node_id)

        # register the node to the CFG Metadata store and
        # obtain a CFG ID of the form f'{node_type}_{n}'
        self.cfg_id = cfg_metadata.register_node(self, self.node_type)

        print(f'Processing CFG Node {self.cfg_id}')

        # node specific metadata
        self.condition = ast_node.get('condition', dict())
        self.condition = getattr(nodes, self.condition['nodeType'], Node)(
            self.condition, None, None, None, self.cfg_metadata)

        # generate the join node
        join_node = IfConditionJoin(dict(), self.entry_node, None,
                                    self.exit_node, cfg_metadata)
        self.join_node = join_node.cfg_id

        ######################
        # True Body Processing
        # first generate the true body of the conditional (recursively)
        if ast_node['trueBody']['nodeType'] == 'Block':
            true_body_statements = ast_node['trueBody']['statements']
        else:
            true_body_statements = [ast_node['trueBody']]
        body_prev_statement = self.cfg_id
        for i, statement in enumerate(true_body_statements):
            # obtain the child node's type
            child_node_type = statement['nodeType']

            # obtain the child node's constructor
            childConstructor = getattr(nodes, child_node_type, Node)

            # initialize the child node (recursive)
            child_node = childConstructor(statement,
                                          self.entry_node, body_prev_statement,
                                          self.join_node, cfg_metadata)

            # for the first statement node in the block, link it to the if statement
            # and label the edge as the TrueBody
            if i == 0:
                self.add_next_node(child_node.cfg_id, label='True')
                self.true_body_next = child_node.cfg_id
            else:
                # in case of the statement is not first,
                # link the previous statement in the block with the current statement
                # 1. first obtain the prev node's leaves
                prev_leaves = self.cfg_metadata.get_node(
                    body_prev_statement).get_leaf_nodes()

                # 2. now check if a leaf node is there or we need to link the previous node itself
                to_link = body_prev_statement if len(
                    prev_leaves) == 0 else next(iter(prev_leaves))

                # 3. link the leaf node's next as the current child node
                self.cfg_metadata.get_node(
                    to_link).add_next_node(child_node.cfg_id)

            # add the child node's ID as the previous statement for next iteration
            body_prev_statement = child_node.cfg_id if child_node.join_node is None else child_node.join_node

            # for the last node in the block, set it as the leaf node of if block
            if i == len(true_body_statements) - 1:
                try:
                    self.leaves.update(child_node.get_leaf_nodes())
                except NotImplementedError:
                    print("Missing get_leaf_nodes in node type:", type(child_node))

        #######################
        # False Body Processing
        # now we generate the false body of the conditional (recursively)
        # if false body is present
        if 'falseBody' in ast_node and ast_node['falseBody'] is not None:
            false_body = ast_node['falseBody']

            if false_body.get('nodeType') == 'Block':
                false_body_statements = false_body.get('statements', [])
                body_prev_statement = self.cfg_id

                for i, statement in enumerate(false_body_statements):
                    child_node_type = statement['nodeType']
                    childConstructor = getattr(nodes, child_node_type, Node)
                    child_node = childConstructor(statement,
                                                self.entry_node, body_prev_statement,
                                                self.join_node, cfg_metadata)

                    if i == 0:
                        self.add_next_node(child_node.cfg_id, label='False')
                        self.false_body_next = child_node.cfg_id
                    else:
                        prev_leaves = self.cfg_metadata.get_node(
                            body_prev_statement).get_leaf_nodes()
                        to_link = body_prev_statement if len(
                            prev_leaves) == 0 else next(iter(prev_leaves))
                        self.cfg_metadata.get_node(
                            to_link).add_next_node(child_node.cfg_id)

                    body_prev_statement = child_node.cfg_id if child_node.join_node is None else child_node.join_node

                    if i == len(false_body_statements) - 1:
                        self.leaves.update(child_node.get_leaf_nodes())

            else:
                # New safe enhancement
                child_node_type = false_body['nodeType']
                childConstructor = getattr(nodes, child_node_type, Node)
                child_node = childConstructor(false_body,
                                            self.entry_node, self.cfg_id,
                                            self.join_node, cfg_metadata)

                self.add_next_node(child_node.cfg_id, label='False')
                self.false_body_next = child_node.cfg_id
                self.leaves.update(child_node.get_leaf_nodes())
        # If statement does not contain false block
        else:
            # add the join node's previous node as the self (direct link of false edge)
            join_node.add_prev_node(self.cfg_id, label='False')

            # also add self's next node as the join node
            self.add_next_node(self.join_node, label='False')

            # also set the false body next
            self.false_body_next = self.join_node

        # now for the leaf nodes in the set,
        # pop them one by one and link them with the join node of the if block
        while len(self.leaves) != 0:
            # pop the leaf node
            last_stmt_node = self.leaves.pop()

            # add the join node's previous node as the last child (leaf) node of the block
            join_node.add_prev_node(last_stmt_node)

            # also add the next node of last child (leaf) node as the join node
            cfg_metadata.get_node(
                last_stmt_node).add_next_node(self.join_node)

        # finally add the join node as the leaf
        # (at this point the leaf nodes set should be empty)
        self.leaves.add(self.join_node)

    def get_leaf_nodes(self) -> set:
        '''
        Returns the leaf node(a) in the current branch,
        where the current node is the root node 

        Note that this might not have children, but this can be part of a Block statemtent,
        hence a chain of statements, therefore we check the next nodes for leaf nodes.

        However unlike simple statements, this time we start with the next nodes of the join node
        '''

        # init child leaves
        child_leaves = set()

        # obtain the join_node
        join_node = self.cfg_metadata.get_node(self.join_node)

        # recursively traverse all the nodes of the join node till we hit the leaf nodes
        for node_id in join_node.next_nodes.keys():
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

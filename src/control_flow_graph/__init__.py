from graphviz import Digraph

from control_flow_graph.node_processor import CFGMetadata
import control_flow_graph.node_processor.nodes as nodes
from control_flow_graph.node_processor.nodes.extra_nodes.source.entry import SourceEntry
from control_flow_graph.node_processor.nodes.extra_nodes.source.exit import SourceExit
from control_flow_graph.node_processor.nodes.IfStatement import IfStatement

class ControlFlowGraph(object):
    '''
    The CFG Wrapper class, 
    encapsulating the complete functionality of building 
    and traversing the CFG from AST. 
    '''

    def __init__(self, source: str, ast: dict) -> None:
        self.source_code = source
        self.ast = ast

        # init graph
        self.graph = Digraph(comment='Control Flow Graph')

        # initialize the metadata handler
        self.cfg_metadata = CFGMetadata()

        # generate the entry and exit nodes
        self.entry_node = SourceEntry(dict(), None, None,
                                      None, self.cfg_metadata)

        self.exit_node = SourceExit(dict(), None, None,
                                    None, self.cfg_metadata)

        # link the entry and exit nodes
        self.entry_node.set_entry_node(self.entry_node.cfg_id)
        self.entry_node.set_exit_node(self.exit_node.cfg_id)
        self.exit_node.set_entry_node(self.entry_node.cfg_id)
        self.exit_node.set_exit_node(self.exit_node.cfg_id)

    def build_cfg(self) -> None:
        '''
        Build the CFG recursively
        '''
        # obtain the AST's first node's type
        node_type = self.ast['nodeType']

        # obtain the child node's constructor
        nodeConstructor = getattr(nodes, node_type)

        # initialize the child node (recursive)
        child_node = nodeConstructor(self.ast, self.entry_node.cfg_id, self.entry_node.cfg_id,
                                     self.exit_node.cfg_id, self.cfg_metadata)

        # add the ast's first node's ID to the next_nodes list of the entry node
        self.entry_node.add_next_node(child_node.cfg_id)

        leaves = child_node.get_leaf_nodes()

        print('ALL-LEAVES', leaves)

        for leaf in leaves:
            node = self.cfg_metadata.get_node(leaf)
            node.add_next_node(self.exit_node.cfg_id)

            self.exit_node.add_prev_node(leaf)

    def generate_dot(self) -> str:
        '''
        Traverse the CFG and generate a Graphviz Digraph DOT file
        '''
        graph = Digraph(comment='Control Flow Graph')
        visited = set()

        def traverse(node_id, graph: Digraph, visited: set, cfg_metadata: CFGMetadata):
            '''
            Traverse the Graph and Generate the Digraph
            '''

            if node_id in visited:
                return

            # add to visited set
            visited.add(node_id)

            # get node instance / object
            node = cfg_metadata.get_node(node_id)

            print(node_id)

            graph.node(node_id, label=node_id)

            print(
                getattr(node, 'next_nodes', None),
                getattr(node, 'prev_nodes', None))

            for child_id in node.next_nodes:
                child_node = cfg_metadata.get_node(child_id)

                traverse(child_node.cfg_id, graph, visited, cfg_metadata)

                graph.edge(node_id, child_id,
                           label=node.next_nodes[child_id]['label'])

        traverse(self.entry_node.cfg_id, graph, visited, self.cfg_metadata)

        graph.render(filename='./gen/cfg.png')

    def generate_dot_bottom_up(self) -> str:
        '''
        Traverse the CFG and generate a Graphviz Digraph DOT file
        '''
        graph = Digraph(comment='Control Flow Graph')
        visited = set()

        def traverse(node_id, graph: Digraph, visited: set, cfg_metadata: CFGMetadata):
            '''
            Traverse the Graph and Generate the Digraph
            '''

            if node_id in visited:
                return

            # add to visited set
            visited.add(node_id)

            # get node instance / object
            node = cfg_metadata.get_node(node_id)

            print(node_id)

            graph.node(node_id, label=node_id)

            print(
                getattr(node, 'next_nodes', None),
                getattr(node, 'prev_nodes', None))

            for child_id in node.prev_nodes:
                child_node = cfg_metadata.get_node(child_id)

                traverse(child_node.cfg_id, graph, visited, cfg_metadata)

                graph.edge(child_id, node_id,
                           label=node.prev_nodes[child_id]['label'])

        traverse(self.exit_node.cfg_id, graph, visited, self.cfg_metadata)

        graph.render(filename='./gen/cfg.rev.png')

    def get_all_nodes_in_function(self, func_node_id):
        """
        Traverse all nodes reachable from a FunctionDefinition node.
        Returns a set of node IDs in the function body.
        """
        visited = set()
        to_visit = [func_node_id]

        while to_visit:
            current = to_visit.pop()
            if current in visited:
                continue
            visited.add(current)

            node = self.cfg_metadata.get_node(current)
            if hasattr(node, "next_nodes"):
                to_visit.extend(node.next_nodes.keys())

        return visited
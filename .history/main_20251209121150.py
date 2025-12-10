import argparse
import json
import os
import sys
import time 
from io import StringIO
from compiler import SolCompiler
from control_flow_graph import ControlFlowGraph
from static_analysis.abstract_collecting_semantics import AbstractCollectingSemanticsAnalysis
from invariant_generator.generator import generate_invariants_from_file  # Import the invariant generator
from java_wrapper import apron
import re
import logging
from mapping_transformer import transform_mappings  # Import the mapping transformer
from control_flow_graph.node_processor.nodes import FunctionCall
from control_flow_graph.node_processor.nodes import VariableDeclarationStatement
from control_flow_graph.node_processor.nodes import IfStatement, ExpressionStatement  # Import the node classes
from control_flow_graph.node_processor.nodes.extra_nodes.if_statement.join import IfConditionJoin
from reachingdefinitionnew import ReachingDefinitionsWithUsage

# Set up logging to capture both terminal and file output
# log_file = "output.txt"
# logging.basicConfig(level=logging.INFO, format="%(message)s", handlers=[
#     logging.FileHandler(log_file, mode="w"),
#     logging.StreamHandler(sys.stdout)  # This ensures logs are printed to terminal as well
# ])

# Redirect output to both terminal and a file
def setup_logging(solidity_filepath):
    solidity_dir = os.path.dirname(solidity_filepath)
    log_filename = os.path.basename(solidity_filepath).replace(".sol", "_output.txt")
    log_file_path = os.path.join(solidity_dir, log_filename)  # Save in Solidity file's directory
    
    # Get the root logger
    logger = logging.getLogger()
    
    # Remove existing handlers to prevent duplicates
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Set up logging again
    logger.setLevel(logging.INFO)

    # Create a file handler to save logs in the correct directory
    file_handler = logging.FileHandler(log_file_path, mode="w")
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    
    # Create a stream handler to print logs to the terminal
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(logging.Formatter("%(message)s"))

    # Add both handlers to the logger
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return log_file_path

def read_source_code(filename):
    """Reads Solidity source code from a given file."""
    try:
        with open(filename, "r") as file:
            return file.read()
    except FileNotFoundError:
        logging.error(f"File '{filename}' not found.")
        sys.exit(1)

# Save the transformed source code to a text file named "source_1.txt"
def save_transformed_source(transformed_source, filename="source_1.txt"):
    with open(filename, "w") as file:
        file.write(transformed_source)

# Function to filter and save only relevant abstract interpretation output (e.g., lines starting with 'ENTRY')
def save_filtered_analysis_output(raw_output, solidity_filepath):
    # Get the directory where the Solidity file is located
    solidity_dir = os.path.dirname(solidity_filepath)
    
    # Define output file name (e.g., input.sol → input_analysis.txt)
    output_filename = os.path.basename(solidity_filepath).replace(".sol", "_analysis.txt")
    output_file_path = os.path.join(solidity_dir, output_filename)
    if os.path.exists(output_file_path):
        os.remove(output_file_path)

    # Regular expression to match lines starting with 'ENTRY'
    relevant_line_pattern = re.compile(r'^(ENTRY|EXIT)')
    variable_keys_line = next((line for line in raw_output.splitlines() if line.startswith("dict_keys")), None)

    # Open the file in 'w' mode to overwrite any existing content
    with open(output_file_path, "w") as output_file:
        # Write the variable keys line at the beginning of the file if found
        if variable_keys_line:
            output_file.write(variable_keys_line + '\n')
        
        # Write the filtered lines that match the relevant pattern (e.g., starting with 'ENTRY')
        for line in raw_output.splitlines():
            if relevant_line_pattern.match(line):
                output_file.write(line + '\n')  # Write only relevant lines (starting with 'ENTRY')

    return output_file_path

# Function to run the static analysis and get the output
def run_static_analysis(source_code, solidity_filepath, annotate_dependencies=False):

    logging.info("Starting Solidity compilation and static analysis.")
    transformed_source = transform_mappings(source_code)
    # save_transformed_source(transformed_source)
    compiler = SolCompiler(transformed_source)
    output = compiler.compile()
    contracts = output.get_contracts_list()

    if not contracts:
        logging.error("No contracts found in the source code.")
        sys.exit(1)
        
    logging.info(f"Contracts found: {contracts}")
    ast = output.get_ast(contracts[0])
    # print(ast)

    # Save the AST as JSON to the 'gen' directory
    if not os.path.exists('./gen'):
        os.makedirs('./gen')

    with open('./gen/ast.json', 'w', encoding='utf8') as f:
        json.dump(ast, f, indent=4)

    cfg = ControlFlowGraph(transformed_source, ast)
    cfg.build_cfg()
    cfg.generate_dot()
    cfg.generate_dot_bottom_up()
    
    # add connection for re-entrancy function call
    function_call = cfg.cfg_metadata.get_node(
    'ExpressionStatement_1')
    # reset next nodes for this statement
    function_call.next_nodes = dict()
    function_call.add_next_node('IfStatement_0')
    cfg.cfg_metadata.get_node('IfStatement_0').add_prev_node(
    'ExpressionStatement_1')

    # function_call = cfg.cfg_metadata.get_node(
    # 'ExpressionStatement_3')
    # # reset next nodes for this statement
    # function_call.next_nodes = dict()
    # function_call.add_next_node('IfStatement_0')
    # cfg.cfg_metadata.get_node('IfStatement_0').add_prev_node(
    # 'ExpressionStatement_3')
    
    # function_call = cfg.cfg_metadata.get_node(
    # 'ExpressionStatement_0')
    # # reset next nodes for this statement
    # function_call.next_nodes = dict()
    # function_call.add_next_node('IfStatement_0')
    # cfg.cfg_metadata.get_node('IfStatement_0').add_prev_node(
    # 'ExpressionStatement_0')

    # function_call = cfg.cfg_metadata.get_node(
    # 'Return_0')
    # # reset next nodes for this statement
    # function_call.next_nodes = dict()
    # function_call.add_next_node('IfStatement_0')
    # cfg.cfg_metadata.get_node('IfStatement_0').add_prev_node(
    # 'Return_0')
    
    # function_call = cfg.cfg_metadata.get_node(
    # 'ExpressionStatement_0')
    # # reset next nodes for this statement
    # function_call.next_nodes = dict()
    # function_call.add_next_node('IfStatement_1')
    # cfg.cfg_metadata.get_node('IfStatement_1').add_prev_node(
    # 'ExpressionStatement_0') 

    cfg.generate_dot()
    cfg.generate_dot_bottom_up()

    # Perform Reaching Definitions Analysis first and log output
    start_time = time.time()
    reaching_analysis = ReachingDefinitionsWithUsage(cfg, annotate_dependencies==annotate_dependencies)
    reaching_analysis.compute_reaching_definitions_and_dependencies()
    end_time = time.time()
    duration = end_time - start_time
    logging.info(f"Full timestamp dependency analysis (incl. annotations) completed in {duration:.4f} seconds.")
    print("\n========== Reaching Definitions Output ==========\n")
    with open("reaching_definitions_output.txt", "r") as output:
        print(output.read())

    # Log output from reaching definitions file
    reaching_output_file = "reaching_definitions_output.txt"
    if os.path.exists(reaching_output_file):
        logging.info("\n========== Reaching Definitions Output ==========")
        with open(reaching_output_file, "r") as f:
            reaching_output = f.read()
            logging.info(reaching_output)
    else:
        logging.warning("Reaching definitions output file not found.")
    
    # Perform Abstract Collecting Semantics Analysis
    domains = ["Box", "Polka", "Octagon"]
    domains = ["Box"]
    analysis_outputs = []
    
    for domain in domains:
        logging.info(f"\n========== Running analysis for {domain} Abstract Domain ==========")
        csem = AbstractCollectingSemanticsAnalysis(cfg, 'SourceEntry_0', 'SourceExit_0', '/usr/local/lib/apron.jar', domain_type=domain)
        
        csem.constant_registry.register_variable('totalSupply', False, (40,40))
        csem.constant_registry.register_variable('_initialSupply', False, (40,40))
        csem.constant_registry.register_variable('_value', False, (10,10))
        csem.constant_registry.register_variable('input', False, (255,255))
        csem.constant_registry.register_variable('submission', False, (40,40))
        csem.constant_registry.register_variable('solution', False, (40,40))
        csem.constant_registry.register_variable('number', False, (10,10))
        csem.constant_registry.register_variable('a', False, (10,10))
        csem.constant_registry.register_variable('b', False, (2,2))
        csem.constant_registry.register_variable('amount', False, (20,20))
        csem.constant_registry.register_variable('_amount', False, (10,10))
        csem.constant_registry.register_variable('_wei', False, (10,10))
        csem.constant_registry.register_variable('v', False, (100,100))
        csem.constant_registry.register_variable('wagerLimit', False, (10,10))
        csem.constant_registry.register_variable('num', False, (10,10))
        csem.constant_registry.register_variable('supplyLOCKER', False, (10,10))
        csem.constant_registry.register_variable('requestType', False, (10,10))
        csem.constant_registry.register_variable('timestamp', False, (10,10))
        csem.constant_registry.register_variable('vs', False, (10,10))
        csem.constant_registry.register_variable('_decimals', False, (3,3))
        csem.constant_registry.register_variable('number', False, (3,3))
        csem.constant_registry.register_variable('_decimals', False, (3,3))
        csem.constant_registry.register_variable('_owner', False, (10,10))
        csem.constant_registry.register_variable('owner', False, (10,10))
        csem.constant_registry.register_variable('_from', False, (10,10))
        csem.constant_registry.register_variable('_data', False, (3,3))
        csem.constant_registry.register_variable('_secretSigner', False, (1,1))
        csem.constant_registry.register_variable('secretSignerAddress', False, (4,4))
        csem.constant_registry.register_variable('ticketID', False, (20,20))
        csem.constant_registry.register_variable('ticketLastBlock', False, (20,20))
        csem.constant_registry.register_variable('autoPlayBotAddress', False, (10,10))
        csem.constant_registry.register_variable('whaleAddress', False, (2,2))
        csem.constant_registry.register_variable('supplyLOCKER', False, (50,50))
        csem.constant_registry.register_variable('_dst', False, (50,50))
        csem.constant_registry.register_variable('_weiToWithdraw', False, (40,40))
        csem.constant_registry.register_variable('_am', False, (40,40))
        csem.constant_registry.register_variable('_wei', False, (40,40))
        csem.constant_registry.register_variable('_required', False, (25,25))
        csem.constant_registry.register_variable('_start', False, (2,2))
        csem.constant_registry.register_variable('n', False, (10,10))
        csem.constant_registry.register_variable('_amt', False, (10,10))
        csem.constant_registry.register_variable('_mult', False, (10,10))
        csem.constant_registry.register_variable('_fee', False, (10,10))
        csem.constant_registry.register_variable('_pcent', False, (10,10))
        csem.constant_registry.register_variable('_newOwner', False, (10,10))
        csem.constant_registry.register_variable('_maxsum', False, (40,40))
        csem.constant_registry.register_variable('_when', False, (40,40))
        csem.constant_registry.register_variable('b', False, (2,2))
        csem.constant_registry.register_variable('n', False, (239,239))
        csem.constant_registry.register_variable('max', False, (10,10))
        csem.constant_registry.register_variable('cards', False, (10,10))
        csem.constant_registry.register_variable('a', False, (10,10))
        csem.constant_registry.register_variable('x', False, (10,10))
        csem.constant_registry.register_variable('_to', False, (10,10))
        csem.constant_registry.register_variable('card', False, (20,20))
        csem.constant_registry.register_variable('hash', False, (20,20))
        csem.constant_registry.register_variable('value', False, (40,40))
        csem.constant_registry.register_variable('deposit', False, (255,255))
        csem.constant_registry.register_variable('rand', False, (40,40))
        csem.constant_registry.register_variable('_secondsToIncrease', False, (255,255))
        csem.constant_registry.register_variable('numTokens', False, (255,255))
        csem.constant_registry.register_variable('_unlockTime', False, (40,40))
        csem.constant_registry.register_variable('_lockTime', False, (40,40))
        csem.constant_registry.register_variable('blocktimestamp', False, ('100', '100'))
        csem.constant_registry.register_variable('msgsender', False, ('100', '100'))
        csem.constant_registry.register_variable('msgvalue', False, ('20', '20'))
        csem.constant_registry.register_variable('_tkA', False, ('40', '40'))
        
        # Redirect stdout and stderr to capture output while still printing to the terminal
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = StringIO()
        sys.stderr = StringIO()

        try:
            logging.info("Running abstract collecting semantics analysis.")
            start_time = time.time()
            csem.compute()
            
            # Retrieve the variable table from CFG metadata and the variable registry.
            # variable_table = cfg.cfg_metadata.variable_table
            # print(variable_table)
            # print(csem.variable_registry.variable_table)

            # # Use the node_table keys as the list of node IDs.
            # all_nodes = list(cfg.cfg_metadata.node_table.keys())

            # # Build the variable metadata mapping.
            # variables = [None] * len(csem.variable_registry.variable_table)
            # for var, data in csem.variable_registry.variable_table.items():
            #     index = data['id']
            #     is_state_variable = data.get('stateVariable', False)
            #     var_type = variable_table.get(var, 'unknown')
            #     if isinstance(var_type, dict):
            #         var_type = var_type.get('type', 'unknown')

            #     variables[index] = {
            #         'name': var,
            #         'type': var_type,
            #         'is_state_variable': is_state_variable,
            #         'value': data.get('value')
            #     }

            # # Define allowed intervals for supported variable types.
            # type_intervals = {
            #     'uint8': [0, (2 ** 8) - 1],
            #     'uint256': [0, (2 ** 256) - 1],
            #     'int8': [-(2 ** 7), (2 ** 7) - 1]
            # }

            # # Iterate over every program point (node) in the CFG.
            # for node in all_nodes:
            #     # Check if the node is registered. (This is just an extra precaution.)
            #     if node not in cfg.cfg_metadata.node_table:
            #         print(f"Skipping node: {node} (not registered)")
            #         continue

            #     print(f"\n--- Checking node: {node} ---")
            #     try:
            #         state_set = csem.point_state.get_node_state_set(
            #             node, csem.point_state.iteration, False
            #         )
            #         intervals = state_set.toBox(csem.manager)
            #     except Exception as e:
            #         print(f"Skipping node {node} due to error: {e}")
            #         continue

            #     for i, interval in enumerate(intervals):
            #         # Convert the interval to a standard Python format.
            #         interval = json.loads(str(interval.toString()))
            #         var = variables[i]

            #         # Skip undefined or unknown variables.
            #         if not var or var['type'] == 'unknown':
            #             continue

            #         var_limits = type_intervals.get(var['type'])
            #         if not var_limits:
            #             continue

            #         # Debug: Print current variable info.
            #         print(f"Checking variable: {var['name']} ({'State' if var['is_state_variable'] else 'Local'})")
            #         print(f"Interval: {interval}, Allowed Limits: {var_limits}")

            #         # Detect underflow.
            #         if interval[0] < var_limits[0]:
            #             print(
            #                 f'Underflow Detected for {"state variable" if var["is_state_variable"] else "local variable"} {var["name"]} at node {node}!\n'
            #                 f'Expected range: {var_limits} but found: {interval}'
            #             )

            #         # Detect overflow.
            #         if interval[1] > var_limits[1]:
            #             print(
            #                 f'Overflow Detected for {"state variable" if var["is_state_variable"] else "local variable"} {var["name"]} at node {node}!\n'
            #                 f'Expected range: {var_limits} but found: {interval}'
            #             )
        
            end_time = time.time()
            
            # Get the abstract interpretation output from the StringIO buffer
            abstract_output = sys.stdout.getvalue()
            error_output = sys.stderr.getvalue()

            duration = end_time - start_time
            logging.info(f"Abstract collecting semantics analysis completed in {duration:.4f} seconds.")
        
        finally:
            # Reset stdout and stderr back to terminal
            sys.stdout = old_stdout
            sys.stderr = old_stderr

        # Log both outputs
        logging.info(abstract_output)
        logging.error(error_output)

        # Filter and save abstract interpretation output to a text file
        filtered_output_file = save_filtered_analysis_output(abstract_output, solidity_filepath)
        logging.info(f"Filtered abstract interpretation output saved to {filtered_output_file}")

        analysis_outputs.append(filtered_output_file)  # Store all output files

    return filtered_output_file


# Function to generate invariants based on the static analysis output
def generate_invariants(analysis_output_file):
    logging.info("Generating invariants based on the analysis output.")
    
    # Call the invariant generator to process the abstract interpretation output file
    invariants_output_file = os.path.join(os.getcwd(), "invariants_output.txt")
    invariants = generate_invariants_from_file(analysis_output_file)
    
    # Write the invariants to a text file
    with open(invariants_output_file, "w") as invariants_file:
        for invariant in invariants:
            invariants_file.write(f"{invariant}\n")

    logging.info(f"Invariants saved to {invariants_output_file}")

# Main execution flow
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("solidity_filepath", type=str, help="Solidity file path")
    parser.add_argument("--annotate-dependencies", action="store_true", help="Enable dependency chain and timestamp influence reporting")
    args = parser.parse_args()

    solidity_filepath = args.solidity_filepath
    annotate_dependencies = args.annotate_dependencies
    log_filename = setup_logging(solidity_filepath)
    source_code = read_source_code(solidity_filepath)
    analysis_output_file = run_static_analysis(source_code, solidity_filepath, annotate_dependencies=annotate_dependencies)

    # generate_invariants(analysis_output_file)


# #!/bin/bash

# for file in ICSE_DATASET/MODIFIED/TIMESTAMP/*.sol
# do
#     echo "Processing $file..."
#     python main.py "$file"
# done



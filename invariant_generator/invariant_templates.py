def check_invariants(variable_states):
    invariants = []

    # Generate equality and range invariants for each variable
    for var, (min_val, max_val) in variable_states.items():
        # Check for equality invariants (e.g., a == 5)
        if min_val == max_val:
            invariants.append(f"{var} == {min_val}")
        # Check for range invariants (e.g., 0 <= a <= 10)
        else:
            invariants.append(f"{min_val} <= {var} <= {max_val}")

    # Get all variable names
    variable_names = list(variable_states.keys())

    # Check for relational invariants between variables if there are exactly two variables
    if len(variable_names) == 2:
        var1, var2 = variable_names  # Dynamically assign variable names

        var1_min, var1_max = variable_states[var1]
        var2_min, var2_max = variable_states[var2]

        # Check if var1 == var2
        if var1_min == var2_min and var1_max == var2_max:
            invariants.append(f"{var1} == {var2}")

        # Check for relational invariants (e.g., var1 <= var2 or var1 >= var2)
        if var1_max <= var2_min:
            invariants.append(f"{var1} <= {var2}")
        elif var1_min >= var2_max:
            invariants.append(f"{var1} >= {var2}")

        # Check if var1 == var2 + constant
        diff_min = var1_min - var2_min
        diff_max = var1_max - var2_max
        if diff_min == diff_max:
            invariants.append(f"{var1} == {var2} + {diff_min}")

    return invariants

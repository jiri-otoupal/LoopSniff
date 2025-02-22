import os
import ast
import concurrent.futures
import click
import rich
from rich.console import Console
from rich.table import Table


def contains_name(node, name):
    """
    Recursively check if 'node' contains a Name node with id equal to 'name'.
    """
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == name:
            return True
    return False


class QueryAssignmentVisitor(ast.NodeVisitor):
    """
    This visitor collects variable names that are assigned from SQLAlchemy query calls.

    It handles several cases:
      1. Direct query calls:
             items = session.query(MyModel)
         Here, 'items' is recognized as a query result.

      2. Partial function assignments:
             query = session.query
         In this case, 'query' is a partial reference to the session's query method.

      3. Calls on partial functions:
             items = query(MyModel).all()
         Since 'query' was previously set to session.query, this call is also recognized as a query.

    The recognized variables (stored in self.query_vars) are later used to detect
    iterative row processing patterns.
    """

    def __init__(self):
        self.query_vars = set()  # Variables holding complete query results.
        self.partial_funcs = set()  # Variables holding partial functions (e.g., session.query).
        self._recognized_funcs = {"query", "subquery", "select"}

    def visit_Assign(self, node):
        # Process each target in the assignment.
        for target in node.targets:
            if isinstance(target, ast.Name):
                assigned_var = target.id

                # 1) Direct assignment of session.query to a variable.
                if self._is_partial_query_attribute(node.value):
                    # E.g., query = session.query
                    self.partial_funcs.add(assigned_var)

                # 2) Direct query call, e.g., items = session.query(MyModel)
                elif self._is_direct_query_call(node.value):
                    self.query_vars.add(assigned_var)

                # 3) Call on a partial function, e.g., items = query(MyModel).all()
                elif self._is_call_on_partial_func(node.value):
                    self.query_vars.add(assigned_var)

        self.generic_visit(node)

    def _is_partial_query_attribute(self, node):
        """
        Returns True if node is an attribute reference like 'session.query'
        (i.e., not called yet).
        """
        if isinstance(node, ast.Attribute):
            return (
                    isinstance(node.value, ast.Name)
                    and node.value.id == "session"
                    and node.attr in self._recognized_funcs
            )
        return False

    def _is_direct_query_call(self, node):
        """
        Returns True if node is a direct call to session.query(...),
        session.subquery(...), or session.select(...).
        """
        if not isinstance(node, ast.Call):
            return False
        func = node.func
        if isinstance(func, ast.Attribute):
            return (
                    isinstance(func.value, ast.Name)
                    and func.value.id == "session"
                    and func.attr in self._recognized_funcs
            )
        return False

    def _is_call_on_partial_func(self, node):
        """
        Returns True if node is a call on a function that was previously set to a partial
        query function (like query = session.query).
        """
        if not isinstance(node, ast.Call):
            return False

        root = node.func
        while isinstance(root, ast.Attribute):
            root = root.value
        return self._call_or_name_references_partial(root)

    def _call_or_name_references_partial(self, node):
        if isinstance(node, ast.Name):
            return node.id in self.partial_funcs
        if isinstance(node, ast.Call):
            func = node.func
            while isinstance(func, ast.Attribute):
                func = func.value
            if isinstance(func, ast.Name):
                return func.id in self.partial_funcs
        return False


class ForLoopVisitor(ast.NodeVisitor):
    """
    Find for-loops iterating over the detected query variables, then look for either:
      - .add() calls, or
      - .append() calls, or
      - Augmented assignments (e.g. "+=") where the loop variable appears in the added value.

    This flags cases where iterative row processing is occurring—if a loop iterates over
    a query result and then processes each item by adding it (directly or via an attribute)
    to another collection.

    This visitor does not flag iterative addition to a plain Python set or list if the iterable
    is not a recognized query result.
    """

    def __init__(self, query_vars):
        self.query_vars = query_vars
        # Each match is stored as (for_loop_lineno, loop_var, query_var, call_lineno)
        self.matches = []

    def visit_For(self, node):
        # Identify the iterable variable, if it's a simple name.
        iter_name = node.iter.id if isinstance(node.iter, ast.Name) else None

        if iter_name in self.query_vars:
            loop_var = node.target.id if isinstance(node.target, ast.Name) else None
            for child in ast.walk(node):
                # 1. Detect function calls to either .add() or .append()
                if isinstance(child, ast.Call):
                    if (isinstance(child.func, ast.Attribute) and
                            child.func.attr in {"add", "append"}):
                        for arg in child.args:
                            # Case 1: e.g., xd.add(item.something)
                            if (isinstance(arg, ast.Attribute) and
                                    isinstance(arg.value, ast.Name) and arg.value.id == loop_var):
                                self.matches.append(
                                    (node.lineno, loop_var, iter_name, child.lineno)
                                )
                            # Case 2: e.g., xd.add(item) or xd.append(item)
                            elif (isinstance(arg, ast.Name) and arg.id == loop_var):
                                self.matches.append(
                                    (node.lineno, loop_var, iter_name, child.lineno)
                                )
                # 2. Detect augmented assignment using += (e.g. xd += (item))
                elif isinstance(child, ast.AugAssign) and isinstance(child.op, ast.Add):
                    if contains_name(child.value, loop_var):
                        self.matches.append(
                            (node.lineno, loop_var, iter_name, child.lineno)
                        )
        self.generic_visit(node)


class ForLoopInefficiencyVisitor(ast.NodeVisitor):
    """
    Scan for other potential inefficiencies inside for-loops, such as:
      - .commit() calls
      - .filter() / .filter_by() calls
      - .delete() / .update() calls
      - Additional recognized queries (.query, .subquery, .select) used inside loops.
    """

    def __init__(self):
        self.inefficiencies = []  # list of tuples (for_loop_lineno, method_name, call_lineno)
        self._loop_stack = []
        self._recognized_funcs = {"query", "subquery", "select"}
        self._inefficient_funcs = {"commit", "filter", "filter_by", "delete", "update"}

    def visit_For(self, node):
        self._loop_stack.append(node)
        self.generic_visit(node)
        self._loop_stack.pop()

    def visit_Call(self, node):
        if self._loop_stack:
            if isinstance(node.func, ast.Attribute):
                method_name = node.func.attr
                if method_name in self._inefficient_funcs:
                    for_node = self._loop_stack[-1]
                    self.inefficiencies.append(
                        (for_node.lineno, method_name, node.lineno)
                    )
                if method_name in self._recognized_funcs:
                    for_node = self._loop_stack[-1]
                    self.inefficiencies.append(
                        (for_node.lineno, method_name + " (loop)", node.lineno)
                    )
        self.generic_visit(node)


class ListCompVisitor(ast.NodeVisitor):
    """
    Detects list comprehensions that iterate over a SQLAlchemy query result.

    For example:
         [ a for a in session.query(MyModel).all() ]

    This pattern is flagged because iterating over a query result in a comprehension
    may indicate an inefficient operation if the intent is to process rows in bulk.
    """

    def __init__(self):
        # Each match is stored as (list_comp_lineno, loop_var, "listcomp", call_lineno)
        self.matches = []

    def visit_ListComp(self, node):
        for gen in node.generators:
            # Check if generator.iter is a call with .all()
            if isinstance(gen.iter, ast.Call):
                call_node = gen.iter
                if isinstance(call_node.func, ast.Attribute) and call_node.func.attr == "all":
                    # Check if the call_node.func.value is a query call
                    sub_call = call_node.func.value
                    if isinstance(sub_call, ast.Call):
                        if (isinstance(sub_call.func, ast.Attribute)
                                and isinstance(sub_call.func.value, ast.Name)
                                and sub_call.func.value.id == "session"
                                and sub_call.func.attr in {"query", "subquery", "select"}):
                            loop_var = None
                            if isinstance(gen.target, ast.Name):
                                loop_var = gen.target.id
                            self.matches.append((node.lineno, loop_var, "listcomp", node.lineno))
        self.generic_visit(node)


def analyze_file(filepath):
    """
    Parse a Python file and return detected pattern matches in a dict:
       - "standard_matches": from ForLoopVisitor (e.g. iterative .add()/.append() or +=)
       - "inefficiency_matches": from ForLoopInefficiencyVisitor and ListCompVisitor
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        tree = ast.parse(content, filename=filepath)
    except Exception:
        return []

    # 1) Original detection for query assignments and .add()/.append() in for-loops.
    qa_visitor = QueryAssignmentVisitor()
    qa_visitor.visit(tree)
    if not qa_visitor.query_vars:
        standard_matches = []
    else:
        for_visitor = ForLoopVisitor(qa_visitor.query_vars)
        for_visitor.visit(tree)
        standard_matches = for_visitor.matches

    # 2) Additional inefficiency detection
    inefficiency_visitor = ForLoopInefficiencyVisitor()
    inefficiency_visitor.visit(tree)
    inefficiency_matches = inefficiency_visitor.inefficiencies

    # 3) Detect list comprehensions iterating over query results.
    listcomp_visitor = ListCompVisitor()
    listcomp_visitor.visit(tree)
    listcomp_matches = listcomp_visitor.matches

    # Combine inefficiency matches and list comprehension matches.
    inefficiency_matches.extend(listcomp_matches)

    return {
        "standard_matches": standard_matches,
        "inefficiency_matches": inefficiency_matches
    }


def get_scan_results(root_dir):
    """
    Recursively scan .py files in the provided directory,
    returning a dict {filepath: {"standard_matches": [...], "inefficiency_matches": [...]}}.
    """
    results = {}
    filepaths = [
        os.path.join(dirpath, fname)
        for dirpath, _, filenames in os.walk(root_dir)
        for fname in filenames if fname.endswith(".py")
    ]

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future_to_filepath = {executor.submit(analyze_file, fp): fp for fp in filepaths}
        for future in concurrent.futures.as_completed(future_to_filepath):
            filepath = future_to_filepath[future]
            try:
                file_result = future.result()
            except Exception as e:
                print(f"Error processing {filepath}: {e}")
                file_result = None

            if file_result and (file_result["standard_matches"] or file_result["inefficiency_matches"]):
                results[filepath] = file_result

    return results


def print_results(results):
    """
    Print a short, color-coded summary line for each detected pattern, including:
      - File and line number details
      - A concise explanation of the inefficiency
      - A short code snippet from the relevant source line.
    """
    console = Console()

    for filepath, file_result in results.items():
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                file_lines = f.readlines()
        except Exception:
            file_lines = []

        # Process standard matches (e.g. iterative .add(), .append() or +=)
        for match in file_result.get("standard_matches", []):
            for_loop_lineno, loop_var, query_var, call_lineno = match
            snippet = (file_lines[for_loop_lineno - 1].strip()
                       if len(file_lines) >= for_loop_lineno
                       else "Code snippet not available.")
            explanation = (
                f"Iteratively processing '{loop_var}' from query '{query_var}' is slow. "
                "Consider bulk operations for better performance."
            )
            console.print(
                f"[bold blue]{filepath}[/bold blue] | For-loop at line [bold green]{for_loop_lineno}[/bold green] "
                f"(.add()/.append() at line [bold green]{call_lineno}[/bold green]): "
                f"[italic]{explanation}[/italic] | Code: [yellow]{snippet}[/yellow]"
            )

        # Process inefficiency matches (e.g. commit, filter, update, list comprehensions, etc.)
        for ineff in file_result.get("inefficiency_matches", []):
            # Handle tuple length: either 3 elements or 4 elements (from list comprehensions)
            if len(ineff) == 3:
                for_loop_lineno, call_name, call_lineno = ineff
                loop_var_info = ""
            elif len(ineff) == 4:
                for_loop_lineno, loop_var, call_name, call_lineno = ineff
                loop_var_info = f" (loop var: {loop_var})"
            else:
                continue

            snippet = (file_lines[call_lineno - 1].strip()
                       if len(file_lines) >= call_lineno
                       else "Code snippet not available.")

            if call_name == "commit":
                explanation = "Calling commit() inside a loop is a performance killer. Use bulk commit."
            elif call_name in ("filter", "filter_by"):
                explanation = "Loop filtering detected. Pre-filter your dataset outside the loop."
            elif call_name == "delete":
                explanation = "Deleting rows one-by-one is inefficient. Opt for bulk delete."
            elif call_name == "update":
                explanation = "Updating rows within a loop is expensive. Consider a bulk update."
            elif call_name.startswith("query (loop)"):
                explanation = "Repeated querying inside a loop burdens performance. Restructure your logic."
            elif call_name == "listcomp":
                explanation = "List comprehension over query results is suboptimal. Rethink your approach."
            else:
                explanation = "Inefficient call detected in loop. Review and optimize your query usage."

            console.print(
                f"[bold blue]{filepath}[/bold blue] | At line [bold green]{call_lineno}[/bold green] "
                f"({call_name}{loop_var_info}): [italic]{explanation}[/italic] | Code: [yellow]{snippet}[/yellow]"
            )


@click.command()
@click.argument("directory", default=".",
                type=click.Path(exists=True, file_okay=False, dir_okay=True, readable=True))
def main(directory):
    """Scan Python files for iterative SQLAlchemy row processing patterns."""
    results = get_scan_results(directory)
    if results:
        print_results(results)
    else:
        console = Console()
        console.print(
            "[bold green]No iterative SQLAlchemy row processing patterns found at all.[/bold green]")


if __name__ == "__main__":
    main()

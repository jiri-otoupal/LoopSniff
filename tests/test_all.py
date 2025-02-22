import tempfile
import textwrap
import pytest

from app.main import analyze_file


# Replace 'your_module_name' with the actual import path or relative import,
# for example:
# from sqlalchemy_scan_click import analyze_file


@pytest.mark.parametrize(
    "source,expected_standard,expected_inefficiencies",
    [
        (
            # 1) .query() + .add() loop (standard pattern)
            textwrap.dedent(
                """
                from somewhere import session

                def foo():
                    items = session.query(MyModel)
                    for item in items:
                        session.add(item)
                """
            ),
            # We expect one standard match:
            #   - for_loop_lineno: 6
            #   - loop_var: 'item'
            #   - query_var: 'items'
            #   - add_call_lineno: 7
            [(6, "item", "items", 7)],
            []
        ),
        (
                # 1) .query() + .add() loop (standard pattern)
                textwrap.dedent(
                    """
                    from somewhere import session
            
                    def foo():
                        query = session.query
                        xd = set()
                        items = query(MyModel).all()
                        for item in items:
                            xd.add(item)
                    """
                ),
                # We expect one standard match:
                #   - for_loop_lineno: 6
                #   - loop_var: 'item'
                #   - query_var: 'items'
                #   - add_call_lineno: 7
                [(8, "item", "items", 9)],
                []
        ),
        (
            # 2) .commit() in a loop (inefficiency)
            textwrap.dedent(
                """
                from somewhere import session

                def bar():
                    for i in range(10):
                        session.commit()
                """
            ),
            # No standard matches
            [],
            # One inefficiency: (for_loop_lineno=5, call_name='commit', call_lineno=6)
            [(5, "commit", 6)]
        ),
        (
            # 3) .select() usage assigned, plus .query() usage inside loop
            #    and .filter() inside loop. This triggers both standard and inefficiencies.
            textwrap.dedent(
                '''
                from somewhere import session

                def baz():
                    data = session.select(MyModel)  # recognized assignment
                    stuff = [1,2,3]
                    for x in data:
                        session.add(x)
                        new_query = session.query(MyOtherModel).filter(MyOtherModel.id == x.id)
                '''
            ),
            # standard match:
            #   for_loop_lineno=7, loop_var='x', query_var='data', add_call_lineno=8
            [(7, "x", "data", 8)],
            # inefficiency:
            #   - (for_loop_lineno=7, call_name='query (loop)', call_lineno=9)
            #        because there's a .query() inside the same for-loop
            #   - (for_loop_lineno=7, call_name='filter', call_lineno=9)
            [
                (7, "filter", 9),
                (7, "query (loop)", 9)
            ]
        ),
        (
            # 4) No patterns matched at all.
            textwrap.dedent(
                """
                def no_patterns():
                    x = [1, 2, 3]
                    for n in x:
                        print(n)
                """
            ),
            [],
            []
        ),
        (
            # 5) Repeated recognized calls inside a loop: .select() + .subquery()
            #    Also .update() inside that loop to show inefficiency.
            textwrap.dedent(
                """
                from somewhere import session

                def do_something():
                    for i in range(5):
                        session.select(MyModel)
                        session.subquery(MyModel)
                        session.update(MyModel)
                """
            ),
            [],
            [
                # We'll see repeated recognized queries in the loop: 'select (loop)' and 'subquery (loop)'
                # Also .update is recognized as inefficient
                (5, "select (loop)", 6),
                (5, "subquery (loop)", 7),
                (5, "update", 8),
            ]
        ),
        (
            # 6) .query() assigned to variable, but no for-loop => no standard match
            #    Just a function call, no iteration => no standard or inefficiency matches
            textwrap.dedent(
                """
                from somewhere import session

                def do_nothing():
                    my_query = session.query(MyModel)
                    print(my_query)
                """
            ),
            [],
            []
        ),
        (
            # 7) .filter_by() used inside for-loop
            #    but the variable is not recognized as a query variable => no standard
            #    we do get an inefficiency for .filter_by() inside loop
            textwrap.dedent(
                """
                from somewhere import session

                def filter_in_loop():
                    data = [1, 2, 3]
                    for item in data:
                        session.filter_by(id=item)
                """
            ),
            [],
            [
                # for_loop_lineno=6, call_name='filter_by', call_lineno=7
                (6, "filter_by", 7)
            ]
        ),
        (
            # 8) .query() assigned, used in a nested for-loop => standard match for .add(),
            #    plus .delete() call => inefficiency
            textwrap.dedent(
                """
                from somewhere import session

                def nested_loop():
                    res = session.query(MyModel)
                    for a in range(2):
                        for r in res:
                            session.add(r)
                            session.delete(r)
                """
            ),
            # standard match: for_loop_lineno=7, loop_var='r', query_var='res', add_call_lineno=8
            [(7, "r", "res", 8)],
            [
                # inefficiency: (for_loop_lineno=7, call_name='delete', call_lineno=9)
                (7, "delete", 9)
            ]
        ),
    ]
)
def test_analyze_file(source, expected_standard, expected_inefficiencies):
    """
    Tests various snippets for standard_matches and inefficiency_matches.
    """
    with tempfile.NamedTemporaryFile(suffix=".py", delete=False) as tmp:
        tmp.write(source.encode("utf-8"))
        tmp.flush()
        result = analyze_file(tmp.name)

    # 'result' should be a dict with keys 'standard_matches' and 'inefficiency_matches'
    assert isinstance(result, dict), "Expected 'analyze_file' to return a dict."
    assert "standard_matches" in result, "Dict is missing 'standard_matches' key."
    assert "inefficiency_matches" in result, "Dict is missing 'inefficiency_matches' key."

    assert result["standard_matches"] == expected_standard, (
        f"Unexpected standard_matches.\nExpected: {expected_standard}\nGot: {result['standard_matches']}"
    )

    assert result["inefficiency_matches"] == expected_inefficiencies, (
        f"Unexpected inefficiency_matches.\nExpected: {expected_inefficiencies}\nGot: {result['inefficiency_matches']}"
    )

from somewhere import session

class MyModel:
    pass

class MyOtherModel:
    pass

def test_list_comprehension():
    # This list comprehension should be flagged as inefficient.
    # It iterates over query results and builds a list.
    results = [a for a in session.query(MyModel).all()]

def test_iterative_add_on_set():
    # This function uses a for-loop over a query result and adds each row to a set.
    query = session.query(MyModel)
    my_set = set()
    for item in query:
        my_set.add(item)

def test_iterative_append_on_list():
    # This function uses a for-loop over a query result and appends each row to a list.
    query = session.query(MyModel)
    my_list = []
    for item in query:
        my_list.append(item)

def test_iterative_plus_equals():
    # This function uses a for-loop over a query result and uses the += operator.
    query = session.query(MyModel)
    my_list = []
    for item in query:
        my_list += (item,)

def test_iterative_append_with_attribute():
    # This should also be flagged even if adding an attribute of the loop variable.
    query = session.query(MyOtherModel)
    result_list = []
    for row in query:
        result_list.append(row.id)

def test_normal_loop_no_match():
    # This loop is over a normal Python list and should not be flagged.
    normal_list = [1, 2, 3]
    my_set = set()
    for x in normal_list:
        my_set.add(x)
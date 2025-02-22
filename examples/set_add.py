from somewhere import session


def foo():
    query = session.query
    xd = set()
    items = query(MyModel).all()
    for item in items:
        xd.add(item)
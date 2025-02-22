from somewhere import session


def do_something():
    for i in range(5):
        session.select(MyModel)
        session.subquery(MyModel)
        session.update(MyModel)
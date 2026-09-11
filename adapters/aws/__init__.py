"""AWS adapter implementations.

Every module here plugs an AWS service into one of the ports defined in
``src/youth_compass/ports/``. Domain code must never import this package;
the ``test_guards_imports.py`` guard enforces that.
"""

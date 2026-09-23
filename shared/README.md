Agent<->backend contract package (`tally_contract`): record schemas, XML request builder, parser, normalization, error codes, logging.
Must not import backend or agent code, and must not depend on FastAPI or SQLAlchemy.

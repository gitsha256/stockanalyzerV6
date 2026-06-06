import logging
import sys
from typing import NoReturn

def setup_logging(verbose: bool = True) -> logging.Logger:
    """Sets up standard logging for the package."""
    level = logging.INFO if verbose else logging.WARNING
    logging.basicConfig(
        level=level,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[
            logging.FileHandler('workflow.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger("stockanalyzer")

def get_input(prompt: str) -> str:
    """CLI helper to handle quit command."""
    val = input(prompt)
    if val.strip().lower() == 'q':
        print("Operation cancelled by user.")
        sys.exit(0)
    return val
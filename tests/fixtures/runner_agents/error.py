"""Error fixture — writes to stderr and exits non-zero to test error capture."""

import sys


def main() -> None:
    sys.stderr.write("boom\n")
    sys.exit(1)


if __name__ == "__main__":
    main()

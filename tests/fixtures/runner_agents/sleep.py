"""Sleep fixture — used to exercise the runner timeout path."""

import time


def main() -> None:
    time.sleep(5)


if __name__ == "__main__":
    main()

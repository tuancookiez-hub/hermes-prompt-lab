import argparse


def total(values):
    return sum(values)


def main(argv=None):
    p = argparse.ArgumentParser(description="Sum numbers")
    p.add_argument("values", nargs="+", type=int)
    args = p.parse_args(argv)
    print(f"Total: {total(args.values)}")


if __name__ == "__main__":
    main()

def fizzbuzz_generator(n):
    """FizzBuzz using a generator approach"""
    for i in range(1, n + 1):
        if i % 15 == 0:
            yield "FizzBuzz"
        elif i % 3 == 0:
            yield "Fizz"
        elif i % 5 == 0:
            yield "Buzz"
        else:
            yield str(i)

def fizzbuzz_list_from_generator(n):
    """Helper function to convert generator to list"""
    return list(fizzbuzz_generator(n))

if __name__ == "__main__":
    print("FizzBuzz Generator (1-20):")
    result = fizzbuzz_list_from_generator(20)
    print(result)
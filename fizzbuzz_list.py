def fizzbuzz_list(n):
    """FizzBuzz that returns a list instead of printing"""
    result = []
    for i in range(1, n + 1):
        if i % 15 == 0:
            result.append("FizzBuzz")
        elif i % 3 == 0:
            result.append("Fizz")
        elif i % 5 == 0:
            result.append("Buzz")
        else:
            result.append(str(i))
    return result

if __name__ == "__main__":
    print("FizzBuzz List (1-20):")
    result = fizzbuzz_list(20)
    print(result)
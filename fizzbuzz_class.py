class FizzBuzz:
    """FizzBuzz using a class-based approach"""
    
    def __init__(self, n):
        self.n = n
        self.words = {3: "Fizz", 5: "Buzz"}
    
    def _get_fizzbuzz_value(self, num):
        """Get FizzBuzz value for a single number"""
        result = ""
        for divisor, word in self.words.items():
            if num % divisor == 0:
                result += word
        return result if result else str(num)
    
    def generate(self):
        """Generate FizzBuzz sequence"""
        return [self._get_fizzbuzz_value(i) for i in range(1, self.n + 1)]
    
    def print(self):
        """Print FizzBuzz sequence"""
        for value in self.generate():
            print(value)

if __name__ == "__main__":
    print("FizzBuzz Class (1-20):")
    fb = FizzBuzz(20)
    result = fb.generate()
    print(result)
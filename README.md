# LoopSniff

[![image](https://img.shields.io/pypi/v/loopsniff.svg)](https://pypi.org/project/loopsniff/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/loopsniff)](https://pypi.org/project/loopsniff/)

[![Build Status](https://travis-ci.com/jiri-otoupal/loopsniff.svg?branch=master)](https://travis-ci.com/github/jiri-otoupal/loopsniff)
[![Downloads](https://pepy.tech/badge/loopsniff)](https://pepy.tech/project/loopsniff)

LoopSniff is a static analysis tool that scans your Python code for inefficient iterative processing patterns—especially those involving SQLAlchemy query results. If you’ve ever manually looped over query results to add rows one-by-one or used list comprehensions on query results, LoopSniff will help you identify and optimize these patterns for better performance.

## Features

- **Detects Inefficient Iteration:**  
  Finds for-loops iterating over SQLAlchemy query results where items are added individually using `.add()`, `.append()`, or via augmented assignment (`+=`).

- **List Comprehension Analysis:**  
  Flags list comprehensions that iterate over query results (e.g., `[a for a in session.query(MyModel).all()]`) to help you rethink bulk operations.

- **Extended Pattern Matching:**  
  Recognizes both direct query calls (e.g., `session.query(MyModel)`) and calls via partial functions (e.g., `query = session.query` then `items = query(MyModel).all()`).

- **Additional Inefficiency Warnings:**  
  Detects other performance bottlenecks in loops, such as calling `.commit()`, `.filter()`, `.update()`, etc., inside loops.

- **User-Friendly Output:**  
  Uses the [Rich](https://github.com/Textualize/rich) library for colorful, engaging console output with explanations and code snippets for each issue found.

- **Easy-to-Use CLI:**  
  Built with [Click](https://click.palletsprojects.com/) for a dynamic command-line interface that lets you scan directories with ease.

- **Tested & Reliable:**  
  Comes with comprehensive tests using [pytest](https://docs.pytest.org/), ensuring robust detection across a variety of edge cases.

## Installation

Clone the repository and install the dependencies using pip:

```bash
git clone https://github.com/yourusername/loopsniff.git
cd loopsniff
pip install -r requirements.txt
```

*Note: Make sure your `requirements.txt` includes dependencies such as `click`, `rich`, and `pytest`.*

## Usage

To scan your code for inefficient SQLAlchemy patterns, run:

```bash
loopsniff /path/to/your/project
```

This command recursively scans all `.py` files in the specified directory and prints out a concise, color-coded summary of any detected patterns, along with code snippets and recommendations for improvement.

### Example Output

```
myfile.py | For-loop at line 10 (.add()/.append() at line 11): Iteratively processing 'item' from query 'items' is slow. Consider bulk operations for better performance. | Code: for item in items:
myfile.py | At line 15 (listcomp): List comprehension over query results is suboptimal. Rethink your approach. | Code: [a for a in session.query(MyModel).all()]
```

## Testing

LoopSniff is tested with pytest. To run the tests, simply execute:

```bash
pytest
```

This runs a suite of tests covering various edge cases—from standard for-loops with `.add()`/`.append()` and `+=` to inefficient list comprehensions.

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests for enhancements, bug fixes, or new features. Please follow standard GitHub contribution guidelines.

## License

This project is licensed under the [MIT License](LICENSE).

## Acknowledgments

- Thanks to the [Rich](https://github.com/Textualize/rich) and [Click](https://click.palletsprojects.com/) communities for their fantastic libraries.
- Inspired by real-world performance challenges in SQLAlchemy-based applications.

---

Happy scanning and optimizing!

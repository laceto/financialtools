import unittest
from financialtools.processor import FinancialDataProcessor

class TestFinancialDataProcessor(unittest.TestCase):
    def test_init(self):
        processor = FinancialDataProcessor()
        self.assertIsNotNone(processor)

if __name__ == '__main__':
    unittest.main()
